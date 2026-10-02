"""Tests del servicio de tags por LLM (#7).

Nada de red: cada test arma un `httpx.MockTransport` que responde lo que el
caso necesita. Asi la suite es deterministica y no gasta cuota del free tier.
"""

from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from snippet_search.config import Settings
from snippet_search.llm_tags import (
    ERROR_EMPTY_SOURCE,
    ERROR_LLM_AUTH,
    ERROR_LLM_MALFORMED,
    ERROR_LLM_QUOTA,
    ERROR_LLM_UNAVAILABLE,
    MAX_TAGS_PER_CATEGORY,
    GeminiTagService,
    LlmTagError,
)

# El snippet del ejemplo de #7 ("Validation against the dictionary-ranking
# example snippet"). Todo lo que se valida contra tags reales sale de aca.
SNIPPET = '''
def rank_dictionary_by_value(input_dict, reverse_order=True):
    """Sort a Python dictionary by its values and return a new dictionary."""
    sorted_pairs = sorted(input_dict.items(), key=lambda item: item[1], reverse=reverse_order)
    return dict(sorted_pairs)
'''

# Salida real de Gemini (gemini-2.5-flash) para SNIPPET, sin editar. Es la
# respuesta que valida el AC de #7 contra el snippet del diccionario.
MODEL_TAGS = {
    "api_calls": ["sorted", "items", "dict"],
    "data_structures": ["dictionary", "list", "tuple"],
    "paradigm": ["functional programming", "lambda", "higher-order function"],
    "algorithm": ["dictionary sorting", "key-value sorting"],
    "domain_keywords": ["ranking", "data manipulation"],
    "language": "Python",
}

SETTINGS = Settings(
    github_token="ghp_fake", gemini_api_key="test-key", gemini_model="gemini-2.5-flash"
)


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

    # AC de #7: las cinco categorias del snippet del diccionario, y el LLM suma
    # lo que el grep no ve: 'higher-order function' no esta escrito en el codigo
    assert tags.api_calls == ("sorted", "items", "dict")
    assert tags.data_structures == ("dictionary", "list", "tuple")
    assert tags.paradigm == ("functional programming", "lambda", "higher-order function")
    assert tags.algorithm == ("dictionary sorting", "key-value sorting")
    assert tags.domain_keywords == ("ranking", "data manipulation")
    assert tags.language == "Python"


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


async def test_language_reaches_the_prompt() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["text"] = json.loads(request.content)["contents"][0]["parts"][0]["text"]
        return httpx.Response(200, json=_gemini_response())

    await _service(handler).extract(SNIPPET, language="Python")

    assert "Language: Python" in seen["text"]


async def test_the_model_uses_the_configured_model_name() -> None:
    # GEMINI_MODEL solia quedar ignorado porque el default ya era truthy.
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=_gemini_response())

    other = replace(SETTINGS, gemini_model="gemini-3-pro-preview")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await GeminiTagService(other, client=client).extract(SNIPPET)

    assert seen["url"].endswith("/models/gemini-3-pro-preview:generateContent")


# --- normalizacion -------------------------------------------------------


async def test_blank_and_repeated_tags_are_dropped() -> None:
    noisy = {
        "api_calls": ["sorted", "  ", "sorted"],
        "data_structures": [],
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


async def test_generic_words_are_kept_because_the_model_describes() -> None:
    # #19 decide que entra a la query; aca no se descarta nada por generico
    generic = {**MODEL_TAGS, "data_structures": ["dict", "list"]}
    service = _service(lambda r: httpx.Response(200, json=_gemini_response(generic)))

    tags = await service.extract(SNIPPET)

    assert tags.data_structures == ("dict", "list")


async def test_language_falls_back_to_the_caller_when_the_model_omits_it() -> None:
    no_language = {**MODEL_TAGS, "language": ""}
    service = _service(lambda r: httpx.Response(200, json=_gemini_response(no_language)))

    tags = await service.extract(SNIPPET, language="Go")

    assert tags.language == "Go"


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


async def test_without_a_key_the_service_answers_llm_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no key: the LLM must not be called")

    keyless = replace(SETTINGS, gemini_api_key=None)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(LlmTagError) as exc:
        await GeminiTagService(keyless, client=client).extract(SNIPPET)

    # El LLM es un complemento: el cliente cae al grep, el resto del back anda
    assert exc.value.code == ERROR_LLM_UNAVAILABLE
    assert exc.value.fallback == "grep"


@pytest.mark.parametrize(
    ("status", "expected", "code", "reported"),
    [
        (401, "HTTP 401", ERROR_LLM_AUTH, 502),
        (429, "HTTP 429", ERROR_LLM_QUOTA, 429),
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


# --- Retry-After ----------------------------------------------------------


async def test_retry_after_is_carried_on_the_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}},
                              headers={"Retry-After": "7"})

    with pytest.raises(LlmTagError) as exc:
        await _service(handler).extract(SNIPPET)

    assert exc.value.retry_after == 7


async def test_a_malformed_retry_after_is_ignored_not_fatal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}},
                              headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})

    with pytest.raises(LlmTagError) as exc:
        await _service(handler).extract(SNIPPET)

    assert exc.value.retry_after is None

