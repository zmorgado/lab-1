"""La corrida completa: tags, search/code, contents, AST y ranking.

GitHub y el LLM se mockean en el borde HTTP o con un stub; UniXcoder se
reemplaza por un Ranker falso, porque lo que se prueba es el encadenado y no el
modelo (#21 AC). Los archivos que devuelve contents son los fixtures reales.
"""

import base64
from pathlib import Path

import httpx
import pytest
import respx

from snippet_search import pipeline
from snippet_search.github import GitHubClient
from snippet_search.llm_tags import ERROR_LLM_QUOTA, LlmTagError, TagSet
from snippet_search.pipeline import search

from conftest import SETTINGS

FIXTURES = Path(__file__).resolve().parent / "fixtures"
API = "https://api.github.com"
REF = "aac85b2bc2be0db69ed886deef72c649b70260d3"

INSERT_SORTED = '''
def insert_sorted(items, value):
    """Insert value into items keeping them sorted."""
    low, high = 0, len(items)
    while low < high:
        mid = (low + high) // 2
        if value < items[mid]:
            high = mid
        else:
            low = mid + 1
    items.insert(low, value)
'''


def item(repo: str, path: str, *, private: bool = False) -> dict:
    # La forma de un item de search/code (docs/research/tests.md), con nombres inventados
    return {
        "name": path.rsplit("/", 1)[-1],
        "path": path,
        "sha": f"sha-of-{repo}-{path}",
        "url": f"{API}/repositories/1/contents/{path}?ref={REF}",
        "html_url": f"https://github.com/{repo}/blob/{REF}/{path}",
        "repository": {"full_name": repo, "private": private},
    }


SORTING = item("example-org/sorting-utils", "lib/bisect.py")
TEMPLATE = item("example-org/django-template", "users/models.py")
PRIVATE = item("example-org/private-sorting", "lib/bisect.py", private=True)
GONE = item("example-org/gone", "lib/missing.py")


def mock_search(*items: dict) -> respx.Route:
    return respx.get(f"{API}/search/code").mock(
        return_value=httpx.Response(
            200, json={"total_count": len(items), "incomplete_results": False, "items": list(items)}
        )
    )


def mock_contents(entry: dict, fixture: str) -> respx.Route:
    content = (FIXTURES / f"{fixture}.py.txt").read_bytes()
    return respx.get(
        f"{API}/repos/{entry['repository']['full_name']}/contents/{entry['path']}"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"content": base64.b64encode(content).decode(), "encoding": "base64"},
        )
    )


class StubLlm:
    def __init__(self, tags: TagSet | None = None, error: LlmTagError | None = None) -> None:
        self.tags = tags or TagSet()
        self.error = error

    async def extract(self, source: str, *, language: str | None = None) -> TagSet:
        if self.error is not None:
            raise self.error
        return self.tags


class StubRanker:
    """Puntua por largo del codigo: determinista y distinto para cada candidato."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(self, query: str, snippets: list[str]) -> list[float]:
        self.calls.append((query, snippets))
        return [len(snippet) / 10_000 for snippet in snippets]


@pytest.fixture
async def github():
    async with GitHubClient(SETTINGS) as client:
        yield client


@respx.mock
async def test_a_full_run_ranks_the_surviving_subtrees(github: GitHubClient) -> None:
    mock_search(SORTING)
    contents = mock_contents(SORTING, "cpython_bisect")
    rank = StubRanker()

    outcome = await search(github, INSERT_SORTED, "python", llm=StubLlm(), rank=rank)

    # El archivo se pidio en el commit que dio search/code
    assert contents.calls.last.request.url.params["ref"] == REF
    assert {c.subtree.name for c in outcome.candidates} == {
        "bisect_left", "bisect_right", "insort_left", "insort_right",
    }
    # Ordenados por score, de mayor a menor
    scores = [c.score for c in outcome.candidates]
    assert scores == sorted(scores, reverse=True)
    assert outcome.candidates[0].repo == "example-org/sorting-utils"
    # UniXcoder recibe el snippet y el codigo de cada subarbol
    query, snippets = rank.calls[0]
    assert query.startswith("def insert_sorted")
    assert all(snippet.startswith("def ") for snippet in snippets)


@respx.mock
async def test_files_that_cannot_be_used_are_skipped_with_a_reason(github: GitHubClient) -> None:
    mock_search(SORTING, TEMPLATE, PRIVATE, GONE)
    mock_contents(SORTING, "cpython_bisect")
    mock_contents(TEMPLATE, "cookiecutter_users_models")
    private = respx.get(f"{API}/repos/example-org/private-sorting/contents/lib/bisect.py")
    respx.get(f"{API}/repos/example-org/gone/contents/lib/missing.py").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    outcome = await search(github, INSERT_SORTED, "python", llm=StubLlm(), rank=StubRanker())

    reasons = {skipped.repo: skipped.reason for skipped in outcome.skipped}
    assert reasons == {
        "example-org/django-template": "syntax error at line 1: not valid Python",
        "example-org/private-sorting": "private repository",
        "example-org/gone": "GitHub 404: Not Found",
    }
    # El privado ni se pide; el resto de la corrida sigue
    assert not private.called
    assert {c.repo for c in outcome.candidates} == {"example-org/sorting-utils"}


@respx.mock
async def test_llm_tags_join_the_anchors(github: GitHubClient) -> None:
    mock_search(SORTING)
    mock_contents(SORTING, "cpython_bisect")
    llm = StubLlm(TagSet(algorithm=("binary search",), paradigm=("generator",)))

    outcome = await search(github, INSERT_SORTED, "python", llm=llm, rank=StubRanker())

    # Grep primero; despues el LLM, en el orden de sus categorias
    assert outcome.anchors == ("insert", "insert_sorted", "generator", "binary search")
    assert outcome.llm_error is None


@respx.mock
async def test_a_failing_llm_leaves_the_run_on_grep_tags(github: GitHubClient) -> None:
    mock_search(SORTING)
    mock_contents(SORTING, "cpython_bisect")
    llm = StubLlm(error=LlmTagError("quota", code=ERROR_LLM_QUOTA))

    outcome = await search(github, INSERT_SORTED, "python", llm=llm, rank=StubRanker())

    assert outcome.llm_error == ERROR_LLM_QUOTA
    assert outcome.anchors == ("insert", "insert_sorted")
    assert len(outcome.candidates) == 4


@respx.mock
async def test_nothing_surviving_skips_the_model(github: GitHubClient) -> None:
    mock_search(TEMPLATE)
    mock_contents(TEMPLATE, "cookiecutter_users_models")
    rank = StubRanker()

    outcome = await search(github, INSERT_SORTED, "python", llm=StubLlm(), rank=rank)

    assert outcome.candidates == ()
    assert rank.calls == []


@respx.mock
async def test_the_embedding_budget_keeps_the_best_anchored(
    github: GitHubClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "MAX_EMBEDDED_SUBTREES", 1)
    mock_search(SORTING)
    mock_contents(SORTING, "cpython_bisect")
    rank = StubRanker()

    outcome = await search(github, INSERT_SORTED, "python", llm=StubLlm(), rank=rank)

    assert len(rank.calls[0][1]) == 1
    assert outcome.rejected["budget"] == 3
