"""Tests de los dos pasos del usuario (#38): el preview de tags y la busqueda
con los tags confirmados.

GitHub y Gemini se mockean con respx a nivel HTTP, como en `test_app.py` y
`test_tags_api.py`: la suite no toca la red ni gasta cuota.
"""

from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from snippet_search.app import create_app

from conftest import SEARCH_BODY, SETTINGS as BASE_SETTINGS
from test_llm_tags import MODEL_TAGS, SNIPPET

SETTINGS = replace(BASE_SETTINGS, gemini_api_key="test-key")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{SETTINGS.gemini_model}:generateContent"
)
SEARCH_CODE = "https://api.github.com/search/code"


def no_model(query: str, snippets: list[str]) -> list[float]:
    raise AssertionError("these tests should not reach UniXcoder")


def _gemini_response(tags: dict = MODEL_TAGS) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(tags)}]}}]}


@pytest.fixture
def client():
    with TestClient(create_app(SETTINGS, rank=no_model)) as test_client:
        yield test_client


# --- preview -----------------------------------------------------------------


def _pool(*tags: tuple[str, str, str], selected: bool = True) -> list[dict]:
    return [{"tag": t, "kind": k, "source": src, "selected": selected} for t, k, src in tags]


@respx.mock
def test_the_preview_offers_the_pool_and_the_queries_the_search_would_run(
    client: TestClient,
) -> None:
    respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json=_gemini_response()))
    github = respx.get(SEARCH_CODE).mock(return_value=httpx.Response(200, json=SEARCH_BODY))

    response = client.post("/api/search/preview", json={"source": SNIPPET})

    assert response.status_code == 200
    assert response.json() == {
        # Por peso (#22): el dominio primero, las APIs despues. Los seeds que el
        # modelo descarto se ofrecen sin seleccionar
        "pool": [
            *_pool(
                ("sort_by_value", "conceptual", "llm"),
                ("ranking", "conceptual", "llm"),
                ("dictionary", "conceptual", "seed"),
            ),
            *_pool(
                ("rank_dictionary_by_value", "syntactic", "seed"),
                ("sort", "conceptual", "seed"),
                ("python", "conceptual", "seed"),
                selected=False,
            ),
            *_pool(
                ("sorted", "syntactic", "seed"),
                ("items", "syntactic", "seed"),
                ("lambda", "paradigm", "seed"),
                ("itemgetter", "paradigm", "llm"),
            ),
        ],
        "queries": [
            {
                "kind": "syntactic",
                "tags": ["sorted", "items"],
                "dropped": [],
                "q": "sorted items language:python",
            },
            {
                "kind": "conceptual",
                "tags": ["sort_by_value", "ranking", "dictionary"],
                "dropped": [],
                "q": "sort_by_value ranking dictionary language:python",
            },
            {
                "kind": "paradigm",
                "tags": ["lambda", "itemgetter"],
                "dropped": [],
                "q": "lambda itemgetter language:python",
            },
        ],
        "llm": {"error": None},
        "is_fallback": False,
    }
    # El preview no gasta presupuesto de code search
    assert not github.called


def test_without_the_model_the_preview_offers_the_ast_query() -> None:
    # #1: el LLM es un complemento, asi que el preview sigue con un 200
    with TestClient(create_app(BASE_SETTINGS, rank=no_model)) as client:
        response = client.post("/api/search/preview", json={"source": SNIPPET})

    assert response.status_code == 200
    body = response.json()
    assert body["llm"] == {"error": "llm_unavailable"}
    # Por peso: el nombre propio y el dominio, despues las APIs. Los seis que
    # entran en la query van seleccionados; el resto se ofrece
    assert [(tag["tag"], tag["selected"]) for tag in body["pool"]] == [
        ("rank_dictionary_by_value", True),
        ("sort", True),
        ("python", True),
        ("dictionary", True),
        ("sorted", True),
        ("items", True),
        ("lambda", False),
    ]
    assert {tag["kind"] for tag in body["pool"]} == {"tiers"}
    assert body["queries"][0]["dropped"] == []


def test_the_preview_says_when_the_snippet_did_not_parse() -> None:
    broken = 'def rank(items):\n    """Cosine ranking."""\n    return sorted(items\n'
    with TestClient(create_app(BASE_SETTINGS, rank=no_model)) as client:
        response = client.post("/api/search/preview", json={"source": broken})

    # El regex rescata los tags igual, y el pool se arma como siempre (#22)
    assert response.status_code == 200
    assert response.json()["is_fallback"] is True
    assert [tag["tag"] for tag in response.json()["pool"]] == ["rank", "cosine", "ranking", "sorted"]


@respx.mock
def test_a_model_tag_with_a_double_quote_is_offered_without_it(client: TestClient) -> None:
    # #35: con la comilla, confirmarlo daria invalid_tag, y el modelo lo volveria a proponer
    tags = {"tags": [{"tag": 'say "hi"', "kind": "conceptual"}], "language": "Python"}
    respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json=_gemini_response(tags)))

    preview = client.post("/api/search/preview", json={"source": SNIPPET}).json()
    offered = next(tag for tag in preview["pool"] if tag["source"] == "llm")
    confirmed = client.post(
        "/api/search/preview",
        json={"source": SNIPPET, "tags": [{"tag": offered["tag"], "kind": offered["kind"]}]},
    )

    assert offered["tag"] == "say hi"
    assert confirmed.status_code == 200
    assert confirmed.json()["queries"][0]["q"] == '"say hi" language:python'


@respx.mock
def test_with_tags_the_preview_rebuilds_the_queries_without_the_model(client: TestClient) -> None:
    gemini = respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json=_gemini_response()))
    seven = [{"tag": f"term{n}", "kind": "syntactic"} for n in range(7)]

    response = client.post(
        "/api/search/preview",
        json={"source": SNIPPET, "tags": [*seven, {"tag": "NOT", "kind": "conceptual"}]},
    )

    assert response.status_code == 200
    assert not gemini.called
    assert response.json() == {
        # El cliente ya tiene el pool: aca solo se rearman las queries
        "pool": [],
        "queries": [
            {
                "kind": "syntactic",
                "tags": [f"term{n}" for n in range(6)],
                "dropped": ["term6"],
                "q": " ".join(f"term{n}" for n in range(6)) + " language:python",
            },
            # Un operador de GitHub viaja entre comillas: se busca como palabra
            {"kind": "conceptual", "tags": ["NOT"], "dropped": [], "q": '"NOT" language:python'},
        ],
        "llm": {"error": None},
        "is_fallback": False,
    }


@respx.mock
@pytest.mark.parametrize(
    ("source", "language", "code"),
    [("x = 1\nprint(x)\n", "python", "nothing_to_search"), (SNIPPET, "Go", "unsupported_language")],
)
def test_the_preview_explains_what_it_cannot_search(
    client: TestClient, source: str, language: str, code: str
) -> None:
    # Un modelo que tampoco encuentra nada que buscar
    nothing = {"tags": [], "language": "Python"}
    respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json=_gemini_response(nothing)))
    github = respx.get(SEARCH_CODE).mock(return_value=httpx.Response(200, json=SEARCH_BODY))

    response = client.post("/api/search/preview", json={"source": source, "language": language})

    assert response.status_code == 422
    assert response.json()["code"] == code
    assert not github.called


# --- busqueda con los tags confirmados ---------------------------------------

CONFIRMED = [
    {"tag": "sorted", "kind": "syntactic"},
    {"tag": "sort by value", "kind": "conceptual"},
    {"tag": "itemgetter", "kind": "paradigm"},
    {"tag": "operator", "kind": "paradigm"},
]
EMPTY_SEARCH = {"total_count": 0, "incomplete_results": False, "items": []}


@respx.mock
def test_the_search_runs_on_the_confirmed_tags_without_the_model(client: TestClient) -> None:
    gemini = respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json=_gemini_response()))
    github = respx.get(SEARCH_CODE).mock(return_value=httpx.Response(200, json=EMPTY_SEARCH))

    response = client.post("/api/search", json={"source": SNIPPET, "tags": CONFIRMED})

    assert response.status_code == 200
    assert not gemini.called
    # Una query por tipo, en el orden de los tipos, con los tags tal cual
    assert [call.request.url.params["q"] for call in github.calls] == [
        "sorted language:python",
        '"sort by value" language:python',
        "itemgetter operator language:python",
    ]
    body = response.json()
    assert body["llm"] == {"tags": None, "error": None}
    # Las anclas: APIs y estructuras del AST, y todos los confirmados
    assert body["anchors"] == [
        "sorted",
        "items",
        "rank_dictionary_by_value",
        "lambda",
        "sort by value",
        "itemgetter",
        "operator",
    ]


@respx.mock
def test_confirmed_ast_tags_make_one_tiers_query(client: TestClient) -> None:
    github = respx.get(SEARCH_CODE).mock(return_value=httpx.Response(200, json=EMPTY_SEARCH))

    client.post(
        "/api/search",
        json={"source": SNIPPET, "tags": [{"tag": "sorted", "kind": "tiers"}, {"tag": "lambda", "kind": "tiers"}]},
    )

    assert github.calls.last.request.url.params["q"] == "sorted lambda language:python"


@respx.mock
@pytest.mark.parametrize(
    "tag",
    [
        {"tag": "  ", "kind": "syntactic"},
        {"tag": "sorted", "kind": "semantic"},
        {"tag": 'say "hi"', "kind": "conceptual"},
        {"tag": "x" * 101, "kind": "conceptual"},
    ],
    ids=["empty", "unknown kind", "double quote", "too long"],
)
def test_an_invalid_confirmed_tag_is_a_422_before_github(client: TestClient, tag: dict) -> None:
    github = respx.get(SEARCH_CODE).mock(return_value=httpx.Response(200, json=EMPTY_SEARCH))

    response = client.post(
        "/api/search", json={"source": SNIPPET, "tags": [{"tag": "sorted", "kind": "syntactic"}, tag]}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_tag"
    assert not github.called


@respx.mock
def test_ast_tags_mixed_with_the_models_are_a_422(client: TestClient) -> None:
    github = respx.get(SEARCH_CODE).mock(return_value=httpx.Response(200, json=EMPTY_SEARCH))

    response = client.post(
        "/api/search",
        json={"source": SNIPPET, "tags": [*CONFIRMED, {"tag": "lambda", "kind": "tiers"}]},
    )

    # La query de tiers reemplaza a las del modelo: juntas serian cuatro requests
    # de code search, y una busqueda gasta como mucho tres
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_tag"
    assert not github.called


@respx.mock
def test_no_confirmed_tags_is_nothing_to_search(client: TestClient) -> None:
    github = respx.get(SEARCH_CODE).mock(return_value=httpx.Response(200, json=EMPTY_SEARCH))

    response = client.post("/api/search", json={"source": SNIPPET, "tags": []})

    assert response.status_code == 422
    assert response.json()["code"] == "nothing_to_search"
    assert not github.called


def test_the_preview_and_the_confirmed_tags_are_typed_in_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    ok = schema["paths"]["/api/search/preview"]["post"]["responses"]["200"]
    assert ok["content"]["application/json"]["schema"]["$ref"].endswith("/PreviewResponse")
    query = schema["components"]["schemas"]["PreviewQueryOut"]["properties"]
    assert {"kind", "tags", "dropped", "q"} <= query.keys()
    pool = schema["components"]["schemas"]["PoolTagOut"]["properties"]
    assert {"tag", "kind", "source", "selected"} <= pool.keys()
    preview_request = schema["components"]["schemas"]["PreviewRequest"]["properties"]
    assert "tags" in preview_request
    assert "is_fallback" in schema["components"]["schemas"]["PreviewResponse"]["properties"]
    request = schema["components"]["schemas"]["SearchRequest"]["properties"]
    assert "tags" in request
    assert {"tag", "kind"} <= schema["components"]["schemas"]["TagIn"]["properties"].keys()
