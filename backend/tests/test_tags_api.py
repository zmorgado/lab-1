"""Tests del endpoint del servicio de tags (#7).

El servicio se inyecta con un `httpx.MockTransport`, asi que la suite no toca
la red ni gasta cuota, igual que en `test_llm_tags.py`.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from code_search_proxy.constants.app_constants import (
    ERROR_EMPTY_SOURCE,
    ERROR_LLM_QUOTA,
    ERROR_LLM_UNAVAILABLE,
    ERROR_SOURCE_NOT_TEXT,
)
from code_search_proxy.llm_config import GeminiSettings
from code_search_proxy.llm_tags import GeminiTagService
from code_search_proxy.tags_api import create_tags_app

from test_llm_tags import MODEL_TAGS, SNIPPET

SETTINGS = GeminiSettings(api_key="test-key", model="gemini-2.5-flash", timeout=5.0)


def _gemini_response(tags: dict | None = None) -> dict:
    body = json.dumps(MODEL_TAGS if tags is None else tags)
    return {"candidates": [{"content": {"parts": [{"text": body}]}}]}


def _client(handler) -> TestClient:
    """Una app con el servicio ya armado sobre un transporte de mentira."""
    app = create_tags_app(SETTINGS)
    service = GeminiTagService(
        SETTINGS, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    # El lifespan arma el suyo; se pisa despues de arrancar para que el test
    # controle que contesta el proveedor.
    client = TestClient(app)
    client.__enter__()
    app.state.tags = service
    return client


@pytest.fixture
def client():
    handler = lambda request: httpx.Response(200, json=_gemini_response())  # noqa: E731
    test_client = _client(handler)
    yield test_client
    test_client.__exit__(None, None, None)


@pytest.fixture(autouse=True)
def no_sleeping_between_retries(monkeypatch):
    async def instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr("code_search_proxy.llm_tags.asyncio.sleep", instant)


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# --- snippet como JSON ---------------------------------------------------


def test_the_endpoint_returns_every_category_and_a_query(client: TestClient) -> None:
    response = client.post("/api/tags", json={"source": SNIPPET, "language": "Python"})

    assert response.status_code == 200
    body = response.json()
    # AC de #7: estructura fija y documentada, con las cinco categorias.
    assert list(body["tags"]) == [
        "api_calls",
        "data_structures",
        "paradigm",
        "algorithm",
        "domain_keywords",
    ]
    assert body["language"] == "Python"
    assert body["query"] == "sorted items defaultdict tuple language:Python"
    assert body["query_tags"] == ["sorted", "items", "defaultdict", "tuple"]
    assert body["query_length"] == len(body["query"])
    assert body["model"] == "gemini-2.5-flash"
    assert body["truncated"] is False


def test_the_response_carries_the_models_preselection(client: TestClient) -> None:
    body = client.post("/api/tags", json={"source": SNIPPET}).json()

    # Lo que el picker de #22 muestra tildado, en el orden que eligio el modelo.
    assert body["suggested"] == ["defaultdict", "sorted"]
    # Siempre elegible en la lista completa: son casillas, no tags nuevos.
    assert set(body["suggested"]) <= set(body["ordered_tags"])


def test_the_full_tag_list_is_returned_even_though_the_query_is_short(
    client: TestClient,
) -> None:
    # El cliente se queda con lo que quiera: #22 deja elegir los tags a mano.
    body = client.post("/api/tags", json={"source": SNIPPET}).json()

    assert "sort by value" in body["ordered_tags"]
    assert "sort by value" not in body["query_tags"]


def test_the_language_parameter_is_optional(client: TestClient) -> None:
    response = client.post("/api/tags", json={"source": SNIPPET})

    assert response.status_code == 200
    # El modelo lo infiere cuando no se lo pasan.
    assert response.json()["language"] == "Python"


def test_the_caller_can_widen_the_query(client: TestClient) -> None:
    body = client.post(
        "/api/tags", json={"source": SNIPPET, "max_query_tags": 2}
    ).json()

    assert body["query_tags"] == ["sorted", "items"]


def test_a_missing_source_is_a_422(client: TestClient) -> None:
    assert client.post("/api/tags", json={}).status_code == 422


# --- archivo como cuerpo crudo -------------------------------------------


def test_a_file_can_be_posted_as_a_raw_body(client: TestClient) -> None:
    response = client.post(
        "/api/tags/file",
        content=SNIPPET.encode("utf-8"),
        params={"filename": "helpers.py", "language": "Python"},
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 200
    assert response.json()["query"].endswith("language:Python")


def test_a_file_that_is_not_utf8_text_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/tags/file",
        content=b"\xff\xfe\x00binary",
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == ERROR_SOURCE_NOT_TEXT


# --- errores -------------------------------------------------------------


def test_an_empty_snippet_is_rejected_without_a_fallback_hint(
    client: TestClient,
) -> None:
    response = client.post("/api/tags", json={"source": "   \n  "})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == ERROR_EMPTY_SOURCE
    # No hay nada que extraer con ningun metodo: el grep tampoco ayuda.
    assert "fallback" not in body


def test_a_provider_outage_tells_the_client_to_fall_back_to_grep() -> None:
    # AC de #7: "Rate limit/provider errors yield clear messages, enabling
    # fallback to grep extraction".
    handler = lambda r: httpx.Response(  # noqa: E731
        503, json={"error": {"message": "This model is experiencing high demand"}}
    )
    client = _client(handler)

    response = client.post("/api/tags", json={"source": SNIPPET})

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == ERROR_LLM_UNAVAILABLE
    assert body["fallback"] == "grep"
    assert "high demand" in body["message"]
    client.__exit__(None, None, None)


def test_a_quota_error_forwards_retry_after() -> None:
    handler = lambda r: httpx.Response(  # noqa: E731
        429,
        json={"error": {"message": "quota exceeded"}},
        headers={"Retry-After": "11"},
    )
    client = _client(handler)

    response = client.post("/api/tags", json={"source": SNIPPET})

    assert response.status_code == 429
    assert response.json()["code"] == ERROR_LLM_QUOTA
    assert response.headers["retry-after"] == "11"
    client.__exit__(None, None, None)


def test_a_rejected_key_is_not_reported_as_the_users_problem() -> None:
    # Un 401 de Gemini es *nuestra* credencial; devolverlo tal cual haria pensar
    # al frontend que el usuario no esta autenticado.
    handler = lambda r: httpx.Response(401, json={"error": {"message": "bad key"}})  # noqa: E731
    client = _client(handler)

    response = client.post("/api/tags", json={"source": SNIPPET})

    assert response.status_code == 502
    assert response.json()["fallback"] == "grep"
    client.__exit__(None, None, None)


def test_the_api_key_never_reaches_the_client() -> None:
    handler = lambda r: httpx.Response(401, json={"error": {"message": "bad key"}})  # noqa: E731
    client = _client(handler)

    response = client.post("/api/tags", json={"source": SNIPPET})

    assert "test-key" not in response.text
    client.__exit__(None, None, None)
