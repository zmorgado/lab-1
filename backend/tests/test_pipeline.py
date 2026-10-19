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
from snippet_search.ast_grep_tags import Tiers
from snippet_search.github import (
    ERROR_MESSAGES,
    ERROR_QUERY_INVALID,
    ERROR_UPSTREAM_UNAVAILABLE,
    GitHubClient,
    GitHubError,
)
from snippet_search.llm_tags import (
    ERROR_LLM_QUOTA,
    KIND_CONCEPTUAL,
    KIND_PARADIGM,
    KIND_SYNTACTIC,
    SOURCE_LLM,
    SOURCE_SEED,
    LlmTagError,
    Tag,
    TagSet,
)
from snippet_search.pipeline import QUERY_TIERS, search
from snippet_search.results import Result

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

# Un LLM que deja dos queries: 'insert' (sintactica) y 'value' (conceptual)
TWO_KINDS = TagSet(
    tags=(
        Tag("insert", KIND_SYNTACTIC, SOURCE_SEED),
        Tag("value", KIND_CONCEPTUAL, SOURCE_SEED),
    )
)


def mock_search(*items: dict) -> respx.Route:
    return respx.get(f"{API}/search/code").mock(
        return_value=httpx.Response(
            200, json={"total_count": len(items), "incomplete_results": False, "items": list(items)}
        )
    )


def mock_searches(by_q: dict[str, list[dict]]) -> respx.Route:
    """search/code con una respuesta por query; una que no esta vuelve vacia."""

    def respond(request: httpx.Request) -> httpx.Response:
        items = by_q.get(request.url.params["q"], [])
        return httpx.Response(
            200, json={"total_count": len(items), "incomplete_results": False, "items": items}
        )

    return respx.get(f"{API}/search/code").mock(side_effect=respond)


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
        self.tiers: Tiers | None = None

    async def extract(
        self, source: str, *, language: str | None = None, tiers: Tiers | None = None
    ) -> TagSet:
        self.tiers = tiers
        if self.error is not None:
            raise self.error
        return self.tags


def kinds(result: Result) -> tuple[str, ...]:
    """Los tipos de query que encontraron el archivo de un resultado."""
    return tuple(query.kind for query in result.queries)


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
    assert {r.name for r in outcome.results} == {
        "bisect_left", "bisect_right", "insort_left", "insort_right",
    }
    # Ordenados por score, de mayor a menor, y numerados
    scores = [r.score for r in outcome.results]
    assert scores == sorted(scores, reverse=True)
    assert [r.rank for r in outcome.results] == [1, 2, 3, 4]
    assert outcome.results[0].locations[0].repo == "example-org/sorting-utils"
    # UniXcoder recibe el snippet y el codigo de cada subarbol
    query, snippets = rank.calls[0]
    assert query.startswith("def insert_sorted")
    assert all(snippet.startswith("def ") for snippet in snippets)


@respx.mock
async def test_the_user_picks_how_many_results_come_back(github: GitHubClient) -> None:
    mock_search(SORTING)
    mock_contents(SORTING, "cpython_bisect")

    outcome = await search(
        github, INSERT_SORTED, "python", llm=StubLlm(), rank=StubRanker(), max_results=2
    )

    assert [r.rank for r in outcome.results] == [1, 2]
    # Se puntuaron los cuatro: el corte es solo de lo que se muestra
    assert len(outcome.candidates) == 4


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
        "example-org/gone": f"{ERROR_UPSTREAM_UNAVAILABLE}: {ERROR_MESSAGES[ERROR_UPSTREAM_UNAVAILABLE]}",
    }
    # El privado ni se pide ni se nombra (#8): solo se cuenta
    assert not private.called
    assert outcome.private_excluded == 1
    assert {loc.repo for r in outcome.results for loc in r.locations} == {
        "example-org/sorting-utils"
    }


@respx.mock
async def test_llm_tags_join_the_anchors(github: GitHubClient) -> None:
    mock_search(SORTING)
    mock_contents(SORTING, "cpython_bisect")
    llm = StubLlm(
        TagSet(
            tags=(
                Tag("binary search", KIND_CONCEPTUAL, SOURCE_LLM),
                Tag("generator", KIND_PARADIGM, SOURCE_LLM),
            )
        )
    )

    outcome = await search(github, INSERT_SORTED, "python", llm=llm, rank=StubRanker())

    # El AST primero; despues el LLM, en el orden de su lista
    assert outcome.anchors == ("insert", "insert_sorted", "binary search", "generator")
    assert outcome.llm_error is None
    # El LLM recibio los tiers del snippet
    assert llm.tiers == outcome.tiers


@respx.mock
async def test_each_kind_of_tag_runs_its_own_query(github: GitHubClient) -> None:
    search_route = mock_search(SORTING)
    mock_contents(SORTING, "cpython_bisect")
    # Se quedo con 'insert' y 'value' y sumo 'bisect'; 'insert_sorted' e 'into' no le sirven
    llm = StubLlm(
        TagSet(
            tags=(
                Tag("insert", KIND_SYNTACTIC, SOURCE_SEED),
                Tag("value", KIND_CONCEPTUAL, SOURCE_SEED),
                Tag("bisect", KIND_PARADIGM, SOURCE_LLM),
            )
        )
    )

    outcome = await search(github, INSERT_SORTED, "python", llm=llm, rank=StubRanker())

    # Una por tipo, en serie y en el orden de los tipos
    sent = [call.request.url.params["q"] for call in search_route.calls]
    assert sent == ["insert language:python", "value language:python", "bisect language:python"]
    assert [run.kind for run in outcome.queries] == [KIND_SYNTACTIC, KIND_CONCEPTUAL, KIND_PARADIGM]
    # El seed que el LLM descarto no entra en ninguna
    assert not any("insert_sorted" in q for q in sent)


@respx.mock
async def test_files_found_by_more_queries_are_fetched_first(
    github: GitHubClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "MAX_CANDIDATE_FILES", 1)
    # TEMPLATE sale primero en la sintactica, pero SORTING lo encontraron las dos
    mock_searches(
        {"insert language:python": [TEMPLATE, SORTING], "value language:python": [SORTING]}
    )
    template = mock_contents(TEMPLATE, "cookiecutter_users_models")
    mock_contents(SORTING, "cpython_bisect")

    outcome = await search(github, INSERT_SORTED, "python", llm=StubLlm(TWO_KINDS), rank=StubRanker())

    assert not template.called
    assert {kinds(r) for r in outcome.results} == {(KIND_SYNTACTIC, KIND_CONCEPTUAL)}


@respx.mock
async def test_the_same_content_in_two_repos_is_one_file_fetched_from_the_public_one(
    github: GitHubClient,
) -> None:
    private_copy = {**PRIVATE, "sha": SORTING["sha"]}
    mock_searches(
        {"insert language:python": [private_copy], "value language:python": [SORTING]}
    )
    private = respx.get(f"{API}/repos/example-org/private-sorting/contents/lib/bisect.py")
    mock_contents(SORTING, "cpython_bisect")

    outcome = await search(github, INSERT_SORTED, "python", llm=StubLlm(TWO_KINDS), rank=StubRanker())

    # Mismo sha: un solo archivo, encontrado por las dos queries, y se baja del publico
    assert not private.called
    assert outcome.skipped == ()
    # Tiene copia publica, asi que no cuenta como privado excluido
    assert outcome.private_excluded == 0
    assert {(r.locations[0].repo, kinds(r)) for r in outcome.results} == {
        ("example-org/sorting-utils", (KIND_SYNTACTIC, KIND_CONCEPTUAL))
    }


@respx.mock
async def test_a_failing_query_does_not_sink_the_others(github: GitHubClient) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.params["q"] == "insert language:python":
            return httpx.Response(422, json={"message": "Validation Failed"})
        return httpx.Response(
            200, json={"total_count": 1, "incomplete_results": False, "items": [SORTING]}
        )

    respx.get(f"{API}/search/code").mock(side_effect=respond)
    mock_contents(SORTING, "cpython_bisect")

    outcome = await search(github, INSERT_SORTED, "python", llm=StubLlm(TWO_KINDS), rank=StubRanker())

    assert {run.kind: run.error for run in outcome.queries} == {
        KIND_SYNTACTIC: f"{ERROR_QUERY_INVALID}: {ERROR_MESSAGES[ERROR_QUERY_INVALID]}",
        KIND_CONCEPTUAL: None,
    }
    assert {kinds(r) for r in outcome.results} == {(KIND_CONCEPTUAL,)}


@respx.mock
async def test_if_every_query_fails_the_search_fails(github: GitHubClient) -> None:
    respx.get(f"{API}/search/code").mock(
        return_value=httpx.Response(403, json={"message": "API rate limit exceeded"})
    )

    with pytest.raises(GitHubError) as exc:
        await search(github, INSERT_SORTED, "python", llm=StubLlm(TWO_KINDS), rank=StubRanker())

    assert exc.value.status_code == 403
    assert exc.value.code == "rate_limited"


@respx.mock
async def test_a_failing_llm_leaves_the_run_on_grep_tags(github: GitHubClient) -> None:
    mock_search(SORTING)
    mock_contents(SORTING, "cpython_bisect")
    llm = StubLlm(error=LlmTagError("quota", code=ERROR_LLM_QUOTA))

    outcome = await search(github, INSERT_SORTED, "python", llm=llm, rank=StubRanker())

    assert outcome.llm_error == ERROR_LLM_QUOTA
    # Sin LLM no hay tipos: una sola query con los tiers, como antes de #19,
    # ordenada por peso (#22): el nombre propio y el dominio antes que la API
    assert [(run.kind, run.query.tags) for run in outcome.queries] == [
        (QUERY_TIERS, ("insert_sorted", "value", "into", "insert"))
    ]
    assert outcome.anchors == ("insert", "insert_sorted")
    assert len(outcome.results) == 4


@respx.mock
async def test_nothing_surviving_skips_the_model(github: GitHubClient) -> None:
    mock_search(TEMPLATE)
    mock_contents(TEMPLATE, "cookiecutter_users_models")
    rank = StubRanker()

    outcome = await search(github, INSERT_SORTED, "python", llm=StubLlm(), rank=rank)

    assert outcome.results == ()
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
