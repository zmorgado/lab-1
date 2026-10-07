"""Tests del endpoint de tags (#7).

Gemini se mockea con respx a nivel HTTP, como GitHub en `test_app.py`: la suite
no toca la red ni gasta cuota.
"""

from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from snippet_search.app import create_app
from snippet_search.llm_tags import (
    ERROR_EMPTY_SOURCE,
    ERROR_LLM_QUOTA,
    ERROR_LLM_UNAVAILABLE,
)

from conftest import SETTINGS as BASE_SETTINGS
from test_llm_tags import MODEL_TAGS, SNIPPET

SETTINGS = replace(BASE_SETTINGS, gemini_api_key="test-key")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-3.8-flash:generateContent"
)


def _gemini_response() -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(MODEL_TAGS)}]}}]}


@pytest.fixture
def client():
    with TestClient(create_app(SETTINGS)) as test_client:
        yield test_client


@respx.mock
def test_the_endpoint_returns_language_and_the_five_categories(client: TestClient) -> None:
    respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json=_gemini_response()))

    # Sin 'language': el modelo lo infiere
    response = client.post("/api/tags", json={"source": SNIPPET})

    assert response.status_code == 200
    # AC de #7: estructura fija y documentada, con las cinco categorias
    assert response.json() == {
        "language": "Python",
        "tags": {
            "api_calls": ["sorted", "items", "dict"],
            "data_structures": ["dictionary", "list", "tuple"],
            "paradigm": ["functional programming", "lambda", "higher-order function"],
            "algorithm": ["dictionary sorting", "key-value sorting"],
            "domain_keywords": ["ranking", "data manipulation"],
        },
    }


def test_a_missing_source_is_a_422(client: TestClient) -> None:
    assert client.post("/api/tags", json={}).status_code == 422


def test_the_frontend_origin_may_post(client: TestClient) -> None:
    response = client.options(
        "/api/tags",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert "POST" in response.headers["access-control-allow-methods"]


# --- errores -------------------------------------------------------------


def test_an_empty_snippet_is_rejected_without_a_fallback_hint(client: TestClient) -> None:
    response = client.post("/api/tags", json={"source": "   \n  "})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == ERROR_EMPTY_SOURCE
    # No hay nada que extraer con ningun metodo: el grep tampoco ayuda
    assert "fallback" not in body


def test_without_a_key_the_tags_endpoint_says_llm_unavailable() -> None:
    # #1: el LLM es un complemento. Sin key el back arranca y el resto anda
    with TestClient(create_app(replace(SETTINGS, gemini_api_key=None))) as client:
        response = client.post("/api/tags", json={"source": SNIPPET})
        health = client.get("/health")

    assert response.status_code == 503
    assert response.json()["code"] == ERROR_LLM_UNAVAILABLE
    assert response.json()["fallback"] == "grep"
    assert health.status_code == 200


@respx.mock
def test_a_quota_error_forwards_retry_after(client: TestClient) -> None:
    respx.post(GEMINI_URL).mock(
        return_value=httpx.Response(
            429, json={"error": {"message": "quota exceeded"}}, headers={"Retry-After": "11"}
        )
    )

    response = client.post("/api/tags", json={"source": SNIPPET})

    assert response.status_code == 429
    assert response.json()["code"] == ERROR_LLM_QUOTA
    assert response.headers["retry-after"] == "11"

