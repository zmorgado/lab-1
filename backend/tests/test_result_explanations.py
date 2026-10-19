"""Tests de las explicaciones de resultados (#43).

El modulo se prueba con un modelo falso que guarda el payload: importa que le
llega al modelo y que sale limpio, no el texto del prompt. La ruta se prueba
con Gemini mockeado con respx, como en `test_tags_api.py`.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from snippet_search.app import create_app
from snippet_search.llm_tags import (
    ERROR_EMPTY_SOURCE,
    ERROR_LLM_QUOTA,
    ERROR_LLM_UNAVAILABLE,
    LlmTagError,
)
from snippet_search.result_explanations import (
    MAX_CANDIDATE_CHARS,
    MAX_HIGHLIGHTS,
    ExplainItem,
    Explanation,
    explain,
)

from conftest import SETTINGS as BASE_SETTINGS
from test_llm_tags import SNIPPET

SETTINGS = replace(BASE_SETTINGS, gemini_api_key="test-key")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{SETTINGS.gemini_model}:generateContent"
)

# Dos resultados como los manda la pagina: el codigo arranca en su linea del archivo
TOP_KEYS = ExplainItem(
    rank=1,
    repo="example-org/stats",
    path="stats/ranking.py",
    name="top_keys",
    start_line=40,
    code=(
        "def top_keys(d, n=None):\n"
        "    ordered = sorted(d, key=d.get, reverse=True)\n"
        "    return ordered[:n] if n else ordered\n"
    ),
)
BY_VALUE = ExplainItem(
    rank=2,
    repo="example-org/tools",
    path="tools/sorting.py",
    name="by_value",
    start_line=14,
    code="def by_value(pairs):\n    return sorted(pairs, key=itemgetter(1))\n",
)


class FakeModel:
    """Contesta lo que el caso necesita y guarda lo que le llego."""

    def __init__(self, *entries: dict[str, Any]) -> None:
        self.answer = {"explanations": list(entries)}
        self.payloads: list[dict[str, Any]] = []

    async def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        return self.answer

    @property
    def prompt(self) -> str:
        return self.payloads[0]["contents"][0]["parts"][0]["text"]


def _entry(
    rank: Any,
    value: Any = "Sorts keys by score, like your snippet.",
    suggestion: Any = "",
    highlights: tuple[tuple[Any, Any], ...] = (),
) -> dict[str, Any]:
    return {
        "rank": rank,
        "value": value,
        "suggestion": suggestion,
        "highlights": [{"start": start, "end": end} for start, end in highlights],
    }


# --- el modulo -----------------------------------------------------------------


async def test_the_model_gets_the_snippet_and_each_result_with_its_file_lines() -> None:
    model = FakeModel()

    await explain(model, SNIPPET, [TOP_KEYS, BY_VALUE])

    prompt = model.prompt
    assert "def rank_dictionary_by_value(input_dict, reverse_order=True):" in prompt
    assert "rank 1: top_keys in example-org/stats/stats/ranking.py" in prompt
    # El modelo subraya con los numeros del archivo, asi que los tiene que ver
    assert "   40 | def top_keys(d, n=None):" in prompt
    assert "   42 |     return ordered[:n] if n else ordered" in prompt
    assert "   15 |     return sorted(pairs, key=itemgetter(1))" in prompt


async def test_each_result_gets_its_value_suggestion_and_lines() -> None:
    model = FakeModel(
        _entry(1, "Cuts to the top `n`.", "Accept an optional `n`.", ((42, 42),)),
        _entry(2, "Sorts pairs with `itemgetter`.", "", ((14, 15),)),
    )

    notes = await explain(model, SNIPPET, [TOP_KEYS, BY_VALUE])

    assert notes == {
        1: Explanation("Cuts to the top `n`.", "Accept an optional `n`.", ((42, 42),)),
        2: Explanation("Sorts pairs with `itemgetter`.", "", ((14, 15),)),
    }


async def test_a_result_the_model_skipped_is_missing_not_invented() -> None:
    notes = await explain(FakeModel(_entry(2)), SNIPPET, [TOP_KEYS, BY_VALUE])

    assert list(notes) == [2]


@pytest.mark.parametrize(
    "entry",
    [
        _entry(9),  # un puesto que no se pidio
        _entry("1"),  # un puesto que no es un numero
        _entry(1, value="   "),  # sin valor no hay nada que mostrar
        _entry(1, value=None),
    ],
)
async def test_entries_that_name_no_requested_result_or_say_nothing_are_dropped(
    entry: dict[str, Any],
) -> None:
    assert await explain(FakeModel(entry), SNIPPET, [TOP_KEYS]) == {}


async def test_the_first_answer_for_a_result_wins() -> None:
    model = FakeModel(_entry(1, "First."), _entry(1, "Second."))

    notes = await explain(model, SNIPPET, [TOP_KEYS])

    assert notes[1].value == "First."


async def test_a_missing_suggestion_is_an_empty_one() -> None:
    notes = await explain(FakeModel(_entry(1, suggestion=None)), SNIPPET, [TOP_KEYS])

    assert notes[1].suggestion == ""


async def test_highlights_are_clipped_to_the_lines_the_model_saw() -> None:
    # TOP_KEYS ocupa las lineas 40 a 42
    model = FakeModel(_entry(1, highlights=((38, 41), (42, 99), (50, 60), (41, 40), ("40", 41))))

    notes = await explain(model, SNIPPET, [TOP_KEYS])

    assert notes[1].highlights == ((40, 41), (42, 42))


async def test_at_most_three_highlights_per_result() -> None:
    ranges = tuple((line, line) for line in range(40, 43)) + ((40, 42),)
    model = FakeModel(_entry(1, highlights=ranges))

    notes = await explain(model, SNIPPET, [TOP_KEYS])

    assert len(notes[1].highlights) == MAX_HIGHLIGHTS == 3


async def test_long_code_is_cut_by_whole_lines_and_so_are_its_highlights() -> None:
    # 50 caracteres por linea con el salto: entran justo las primeras 80
    line = "x = 1".ljust(49)
    long = ExplainItem(1, "example-org/big", "big.py", "big", 1, f"{line}\n" * 200)
    model = FakeModel(_entry(1, highlights=((79, 85),)))

    notes = await explain(model, SNIPPET, [long])

    fits = MAX_CANDIDATE_CHARS // 50
    assert f"{fits:>5} | {line}" in model.prompt
    assert f"{fits + 1:>5} | " not in model.prompt
    assert notes[1].highlights == ((79, fits),)


async def test_an_empty_snippet_is_rejected_before_spending_quota() -> None:
    model = FakeModel()

    with pytest.raises(LlmTagError) as exc:
        await explain(model, "  \n ", [TOP_KEYS])

    assert exc.value.code == ERROR_EMPTY_SOURCE
    assert model.payloads == []


# --- la ruta -------------------------------------------------------------------


def _request(*items: ExplainItem) -> dict[str, Any]:
    return {
        "source": SNIPPET,
        "results": [
            {
                "rank": item.rank,
                "repo": item.repo,
                "path": item.path,
                "name": item.name,
                "start_line": item.start_line,
                "code": item.code,
            }
            for item in items
        ],
    }


def _gemini_response(*entries: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"explanations": list(entries)})
    return {"candidates": [{"content": {"parts": [{"text": body}]}}]}


@pytest.fixture
def client():
    with TestClient(create_app(SETTINGS)) as test_client:
        yield test_client


@respx.mock
def test_the_route_answers_in_rank_order(client: TestClient) -> None:
    respx.post(GEMINI_URL).mock(
        return_value=httpx.Response(
            200,
            json=_gemini_response(
                _entry(2, "Sorts pairs.", "", ()),
                _entry(1, "Cuts to the top `n`.", "Accept an optional `n`.", ((42, 42),)),
            ),
        )
    )

    response = client.post("/api/search/explain", json=_request(TOP_KEYS, BY_VALUE))

    assert response.status_code == 200
    assert response.json() == {
        "explanations": [
            {
                "rank": 1,
                "value": "Cuts to the top `n`.",
                "suggestion": "Accept an optional `n`.",
                "highlights": [{"start": 42, "end": 42}],
            },
            {"rank": 2, "value": "Sorts pairs.", "suggestion": "", "highlights": []},
        ]
    }


def test_no_results_is_a_422_before_the_model(client: TestClient) -> None:
    # Sin respx: si la ruta llamara al modelo, el test saldria a la red y fallaria
    response = client.post("/api/search/explain", json={"source": SNIPPET, "results": []})

    assert response.status_code == 422


def test_without_a_key_the_route_says_llm_unavailable() -> None:
    with TestClient(create_app(replace(SETTINGS, gemini_api_key=None))) as client:
        response = client.post("/api/search/explain", json=_request(TOP_KEYS))

    assert response.status_code == 503
    assert response.json()["code"] == ERROR_LLM_UNAVAILABLE


@respx.mock
def test_a_quota_error_keeps_its_code_and_retry_after(client: TestClient) -> None:
    respx.post(GEMINI_URL).mock(
        return_value=httpx.Response(
            429, json={"error": {"message": "quota exceeded"}}, headers={"Retry-After": "11"}
        )
    )

    response = client.post("/api/search/explain", json=_request(TOP_KEYS))

    assert response.status_code == 429
    assert response.json()["code"] == ERROR_LLM_QUOTA
    assert response.headers["retry-after"] == "11"


def test_the_explanations_are_typed_in_openapi(client: TestClient) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    assert "/api/search/explain" in client.get("/openapi.json").json()["paths"]
    assert set(schemas["ExplanationOut"]["required"]) == {
        "rank",
        "value",
        "suggestion",
        "highlights",
    }
    assert "start_line" in schemas["ExplainItemIn"]["required"]
