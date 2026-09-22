"""Tests del servicio de tags por LLM (#7).

Nada de red: cada test arma un `httpx.MockTransport` que responde lo que el
caso necesita. Asi la suite es deterministica y no gasta cuota del free tier.
"""

from __future__ import annotations

import json

import httpx
import pytest

from code_search_proxy.constants.app_constants import (
    DEFAULT_MAX_QUERY_TAGS,
    ERROR_EMPTY_SOURCE,
    ERROR_LLM_AUTH,
    ERROR_LLM_MALFORMED,
    ERROR_LLM_QUOTA,
    ERROR_LLM_UNAVAILABLE,
    MAX_ATTEMPTS,
    MAX_QUERY_LENGTH,
    MAX_SUGGESTED_TAGS,
    MAX_TAGS_PER_CATEGORY,
)
from code_search_proxy.contracts.tags_set import TagSet
from code_search_proxy.errors.llm_tag_error import LlmTagError
from code_search_proxy.llm_config import GeminiSettings
from code_search_proxy.llm_tags import GeminiTagService

# El snippet del ejemplo de #7 ("Validation against the dictionary-ranking
# example snippet"). Todo lo que se valida contra tags reales sale de aca.
SNIPPET = '''
def rank_dictionary_by_value(input_dict, reverse_order=True):
    """Sort a Python dictionary by its values and return a new dictionary."""
    sorted_pairs = sorted(input_dict.items(), key=lambda item: item[1], reverse=reverse_order)
    return dict(sorted_pairs)
'''

MODEL_TAGS = {
    "api_calls": ["sorted", "items", "dict"],
    "data_structures": ["defaultdict", "tuple"],
    "paradigm": ["lambda"],
    "algorithm": ["sort by value"],
    "domain_keywords": ["ranking"],
    "language": "Python",
    "suggested": ["defaultdict", "sorted"],
}

SETTINGS = GeminiSettings(api_key="test-key", model="gemini-2.5-flash", timeout=5.0)


@pytest.fixture(autouse=True)
def no_sleeping_between_retries(monkeypatch):
    """El backoff es real en produccion, pero la suite no lo va a esperar."""

    async def instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr("code_search_proxy.llm_tags.asyncio.sleep", instant)


def _gemini_response(tags: dict | None = None) -> dict:
    """Envuelve un payload de tags en la forma que devuelve generateContent."""
    body = json.dumps(MODEL_TAGS if tags is None else tags)
    return {"candidates": [{"content": {"parts": [{"text": body}]}}]}


def _service(handler) -> GeminiTagService:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GeminiTagService(SETTINGS, client=client)


# --- extraccion ----------------------------------------------------------


async def test_extract_maps_every_category() -> None:
    service = _service(lambda request: httpx.Response(200, json=_gemini_response()))

    tags = await service.extract(SNIPPET, language="Python")

    # 'dict' se cae por generico: matchea en cualquier archivo Python y solo
    # recorta resultados al AND-earse.
    assert tags.api_calls == ("sorted", "items")
    assert tags.data_structures == ("defaultdict", "tuple")
    assert tags.paradigm == ("lambda",)
    assert tags.algorithm == ("sort by value",)
    assert tags.domain_keywords == ("ranking",)
    assert tags.language == "Python"


async def test_the_dictionary_ranking_snippet_yields_a_usable_query() -> None:
    # AC de #7: validado contra el snippet del ejemplo. La query tiene que ser
    # corta y literal, porque GitHub AND-ea los terminos.
    service = _service(lambda request: httpx.Response(200, json=_gemini_response()))

    tags = await service.extract(SNIPPET, language="Python")

    assert tags.to_query() == "sorted items defaultdict tuple language:Python"
    assert len(tags.query_tags()) <= DEFAULT_MAX_QUERY_TAGS


async def test_request_carries_key_model_and_json_schema() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_gemini_response())

    await _service(handler).extract(SNIPPET)

    assert seen["key"] == "test-key"
    assert seen["url"].endswith("/models/gemini-2.5-flash:generateContent")
    config = seen["body"]["generationConfig"]
    # Sin responseMimeType JSON el modelo devuelve markdown con fences.
    assert config["responseMimeType"] == "application/json"
    assert config["temperature"] == 0.0
    assert "api_calls" in config["responseSchema"]["properties"]


async def test_language_and_filename_reach_the_prompt() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["text"] = json.loads(request.content)["contents"][0]["parts"][0]["text"]
        return httpx.Response(200, json=_gemini_response())

    await _service(handler).extract(SNIPPET, language="Python", filename="helpers.py")

    assert "Filename: helpers.py" in seen["text"]
    assert "Language: Python" in seen["text"]


async def test_the_model_uses_the_configured_model_name() -> None:
    # GEMINI_MODEL solia quedar ignorado porque el default ya era truthy.
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=_gemini_response())

    other = GeminiSettings(api_key="k", model="gemini-3-pro-preview", timeout=5.0)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await GeminiTagService(other, client=client).extract(SNIPPET)

    assert seen["url"].endswith("/models/gemini-3-pro-preview:generateContent")


# --- normalizacion -------------------------------------------------------


async def test_blank_categories_and_non_strings_are_dropped() -> None:
    noisy = {
        "api_calls": ["sorted", "  ", "SORTED", 42, None],
        "data_structures": "not a list",
        "paradigm": [],
        "algorithm": [],
        "domain_keywords": [],
        "language": "Python",
    }
    service = _service(lambda r: httpx.Response(200, json=_gemini_response(noisy)))

    tags = await service.extract(SNIPPET)

    assert tags.api_calls == ("sorted",)
    assert tags.data_structures == ()


async def test_a_category_is_capped_even_when_the_model_ignores_the_prompt() -> None:
    # Pasa de verdad con archivos grandes: el prompt pide 6 y el modelo manda 18.
    greedy = {**MODEL_TAGS, "api_calls": [f"call_{i}" for i in range(20)]}
    service = _service(lambda r: httpx.Response(200, json=_gemini_response(greedy)))

    tags = await service.extract(SNIPPET)

    assert len(tags.api_calls) == MAX_TAGS_PER_CATEGORY


async def test_generic_noise_never_reaches_the_tag_set() -> None:
    noise = {**MODEL_TAGS, "data_structures": ["dict", "List", "str", "ndarray"]}
    service = _service(lambda r: httpx.Response(200, json=_gemini_response(noise)))

    tags = await service.extract(SNIPPET)

    assert tags.data_structures == ("ndarray",)


async def test_tags_too_short_to_form_a_trigram_are_dropped() -> None:
    # El modelo manda '@' como paradigm cada tanto. GitHub matchea de a tres
    # caracteres: un tag de menos no puede matchear nada.
    tiny = {**MODEL_TAGS, "paradigm": ["@", "os", "lambda"]}
    service = _service(lambda r: httpx.Response(200, json=_gemini_response(tiny)))

    tags = await service.extract(SNIPPET)

    assert tags.paradigm == ("lambda",)


async def test_language_falls_back_to_the_caller_when_the_model_omits_it() -> None:
    no_language = {**MODEL_TAGS, "language": ""}
    service = _service(lambda r: httpx.Response(200, json=_gemini_response(no_language)))

    tags = await service.extract(SNIPPET, language="Go")

    assert tags.language == "Go"


# --- armado de la query --------------------------------------------------


def test_ordered_tags_dedupes_across_tiers_keeping_the_higher_one() -> None:
    # 'sorted' viene en api_calls y en data_structures: gana api_calls, que es
    # el tier mas alto, y no se repite mas abajo.
    tags = TagSet(
        api_calls=("sorted", "argsort"),
        data_structures=("Sorted", "ndarray"),
        paradigm=("lambda",),
    )

    assert tags.ordered_tags() == ["sorted", "argsort", "ndarray", "lambda"]


def test_ordered_tags_respects_max_tags() -> None:
    tags = TagSet(api_calls=("a", "b", "c"), paradigm=("lambda",))

    assert tags.ordered_tags(max_tags=2) == ["a", "b"]


def test_the_query_only_draws_from_the_literal_tiers() -> None:
    # 'comprehension' y 'machine learning' describen el codigo, no aparecen
    # escritos en el: como termino AND-eado solo sacan resultados.
    tags = TagSet(
        api_calls=("train_test_split",),
        data_structures=("DataFrame",),
        paradigm=("comprehension",),
        algorithm=("gradient descent",),
        domain_keywords=("machine learning",),
        language="Python",
    )

    assert tags.to_query() == "train_test_split DataFrame language:Python"
    # Pero siguen disponibles para #22 y para la etapa de embeddings.
    assert "machine learning" in tags.ordered_tags()


def test_the_query_ands_only_a_handful_of_terms() -> None:
    # Antes se llenaban los 256 caracteres con ~25 terminos, y GitHub AND-ea:
    # ningun archivo cumple 25 condiciones y la busqueda vuelve vacia.
    tags = TagSet(
        api_calls=tuple(f"call_{i}" for i in range(6)),
        data_structures=tuple(f"Struct{i}" for i in range(6)),
        language="Python",
    )

    assert len(tags.to_query().split()) == DEFAULT_MAX_QUERY_TAGS + 1  # + language:


def test_to_query_quotes_multiword_tags_and_language() -> None:
    tags = TagSet(
        api_calls=("sorted",),
        data_structures=("ordered mapping",),
        language="Jupyter Notebook",
    )

    assert tags.to_query() == 'sorted "ordered mapping" language:"Jupyter Notebook"'


def test_to_query_never_exceeds_the_github_limit_nor_splits_a_tag() -> None:
    long_tags = tuple(f"identifier_number_{i:03d}" * 3 for i in range(40))
    tags = TagSet(api_calls=long_tags, language="Python")

    query = tags.to_query(max_tags=None)

    assert len(query) <= MAX_QUERY_LENGTH
    # Cada termino que entro quedo entero, no truncado a mitad de palabra.
    emitted = query.removesuffix(" language:Python").split()
    assert all(tag in long_tags for tag in emitted)
    assert query.endswith("language:Python")


def test_as_dict_keeps_the_five_categories_in_tier_order() -> None:
    tags = TagSet(api_calls=("sorted",), domain_keywords=("ranking",))

    assert list(tags.as_dict()) == [
        "api_calls",
        "data_structures",
        "paradigm",
        "algorithm",
        "domain_keywords",
    ]


# --- pre-seleccion del modelo -------------------------------------------


async def test_the_model_preselects_tags_for_the_picker() -> None:
    service = _service(lambda r: httpx.Response(200, json=_gemini_response()))

    tags = await service.extract(SNIPPET, language="Python")

    # El orden es el del modelo: de mas a menos distintivo, no el de los tiers.
    assert tags.suggested == ("defaultdict", "sorted")


async def test_suggested_is_always_a_subset_of_the_emitted_tags() -> None:
    # El modelo a veces devuelve algo que no puso en ninguna categoria; el
    # picker de #22 no tiene casilla que tildar para eso.
    invented = {**MODEL_TAGS, "suggested": ["sorted", "never_emitted_anywhere"]}
    service = _service(lambda r: httpx.Response(200, json=_gemini_response(invented)))

    tags = await service.extract(SNIPPET)

    assert tags.suggested == ("sorted",)
    assert set(tags.suggested) <= set(tags.ordered_tags())


async def test_suggested_keeps_the_spelling_of_the_category() -> None:
    # 'SORTED' y 'sorted' son el mismo tag; gana la grafia que ve el usuario.
    shouted = {**MODEL_TAGS, "suggested": ["SORTED"]}
    service = _service(lambda r: httpx.Response(200, json=_gemini_response(shouted)))

    tags = await service.extract(SNIPPET)

    assert tags.suggested == ("sorted",)


async def test_suggested_is_capped() -> None:
    every = {**MODEL_TAGS, "suggested": ["sorted", "items", "defaultdict", "tuple",
                                         "lambda", "sort by value", "ranking"]}
    service = _service(lambda r: httpx.Response(200, json=_gemini_response(every)))

    tags = await service.extract(SNIPPET)

    assert len(tags.suggested) == MAX_SUGGESTED_TAGS


async def test_fewer_than_five_suggestions_are_not_padded() -> None:
    # El prompt pide quedarse corto antes que rellenar con ruido.
    one = {**MODEL_TAGS, "suggested": ["defaultdict"]}
    service = _service(lambda r: httpx.Response(200, json=_gemini_response(one)))

    tags = await service.extract(SNIPPET)

    assert tags.suggested == ("defaultdict",)


async def test_the_picker_never_opens_empty_when_the_model_suggests_nothing() -> None:
    none_usable = {**MODEL_TAGS, "suggested": []}
    service = _service(lambda r: httpx.Response(200, json=_gemini_response(none_usable)))

    tags = await service.extract(SNIPPET)

    # Degrada a los tags de la query, que al menos son literales.
    assert tags.suggested == tuple(tags.query_tags(max_tags=MAX_SUGGESTED_TAGS))


async def test_a_suggested_field_that_is_not_a_list_does_not_blow_up() -> None:
    broken = {**MODEL_TAGS, "suggested": "sorted, items"}
    service = _service(lambda r: httpx.Response(200, json=_gemini_response(broken)))

    tags = await service.extract(SNIPPET)

    assert tags.suggested == tuple(tags.query_tags(max_tags=MAX_SUGGESTED_TAGS))


# --- fallas --------------------------------------------------------------


async def test_empty_source_is_rejected_before_spending_quota() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("the LLM must not be called for an empty snippet")

    with pytest.raises(LlmTagError, match="Empty source") as exc:
        await _service(handler).extract("   \n  ")

    assert exc.value.code == ERROR_EMPTY_SOURCE
    assert exc.value.status_code == 422
    # No hay fallback: si no hay snippet, el grep (#4) tampoco tiene que leer.
    assert exc.value.fallback is None


@pytest.mark.parametrize(
    ("status", "expected", "code", "reported"),
    [
        (401, "rejected the API key", ERROR_LLM_AUTH, 502),
        (429, "quota exhausted", ERROR_LLM_QUOTA, 429),
        (500, "HTTP 500", ERROR_LLM_UNAVAILABLE, 503),
    ],
)
async def test_http_errors_become_llm_tag_errors(
    status: int, expected: str, code: str, reported: int
) -> None:
    body = {"error": {"message": "upstream said so"}}
    service = _service(lambda r: httpx.Response(status, json=body))

    with pytest.raises(LlmTagError, match=expected) as exc:
        await service.extract(SNIPPET)

    assert "upstream said so" in str(exc.value)
    assert exc.value.code == code
    # Un 401 es *nuestra* key, no la sesion del usuario: sale como 502.
    assert exc.value.status_code == reported
    # AC de #7: el cliente puede caer al grep en cualquiera de los tres.
    assert exc.value.fallback == "grep"


async def test_an_error_body_that_is_not_an_object_does_not_escape_the_module() -> None:
    # Un proxy intermedio puede devolver una lista o un string; '.get' sobre eso
    # tiraba AttributeError, que no es LlmTagError.
    service = _service(lambda r: httpx.Response(500, json=["gateway exploded"]))

    with pytest.raises(LlmTagError, match="HTTP 500"):
        await service.extract(SNIPPET)


async def test_non_json_model_output_becomes_an_llm_tag_error() -> None:
    fenced = {"candidates": [{"content": {"parts": [{"text": "```json\n{"}]}}]}
    service = _service(lambda r: httpx.Response(200, json=fenced))

    with pytest.raises(LlmTagError, match="non-JSON") as exc:
        await service.extract(SNIPPET)

    assert exc.value.code == ERROR_LLM_MALFORMED


async def test_response_without_candidates_becomes_an_llm_tag_error() -> None:
    # Pasa cuando el prompt se corta por safety filter o por maxTokens.
    blocked = {"promptFeedback": {"blockReason": "SAFETY"}}
    service = _service(lambda r: httpx.Response(200, json=blocked))

    with pytest.raises(LlmTagError, match="Malformed LLM response"):
        await service.extract(SNIPPET)


async def test_network_failure_becomes_an_llm_tag_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with pytest.raises(LlmTagError, match="LLM request failed") as exc:
        await _service(handler).extract(SNIPPET)

    assert exc.value.code == ERROR_LLM_UNAVAILABLE


# --- reintentos ----------------------------------------------------------


async def test_a_transient_503_is_retried_and_succeeds() -> None:
    # El caso real del free tier: 'high demand' en un intento, respuesta en el
    # siguiente. Sin reintento esto le llega al usuario como servicio roto.
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(
                503, json={"error": {"message": "This model is experiencing high demand"}}
            )
        return httpx.Response(200, json=_gemini_response())

    tags = await _service(handler).extract(SNIPPET)

    assert attempts["n"] == 2
    assert tags.language == "Python"


async def test_retries_give_up_and_report_the_last_failure() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503, json={"error": {"message": "still busy"}})

    with pytest.raises(LlmTagError, match="still busy") as exc:
        await _service(handler).extract(SNIPPET)

    # El tope existe por la cuota diaria, no solo por latencia: cada intento
    # extra gasta una request de las 20 que da el free tier.
    assert attempts["n"] == MAX_ATTEMPTS
    assert exc.value.code == ERROR_LLM_UNAVAILABLE


async def test_a_rejected_key_is_not_retried() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(401, json={"error": {"message": "API key not valid"}})

    with pytest.raises(LlmTagError, match="rejected the API key"):
        await _service(handler).extract(SNIPPET)

    # La key no mejora sola: reintentar solo suma latencia.
    assert attempts["n"] == 1


async def test_retry_after_is_carried_on_the_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}},
                              headers={"Retry-After": "7"})

    with pytest.raises(LlmTagError) as exc:
        await _service(handler).extract(SNIPPET)

    assert exc.value.retry_after == 7
    assert exc.value.body["retry_after"] == 7


async def test_a_malformed_retry_after_is_ignored_not_fatal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}},
                              headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})

    with pytest.raises(LlmTagError) as exc:
        await _service(handler).extract(SNIPPET)

    assert exc.value.retry_after is None


# --- ciclo de vida del cliente -------------------------------------------


async def test_an_injected_client_is_not_closed_by_the_service() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_gemini_response()))
    )

    async with GeminiTagService(SETTINGS, client=client) as service:
        await service.extract(SNIPPET)

    # Es del que llama: el resto del pipeline lo sigue usando.
    assert not client.is_closed
    await client.aclose()
