"""Tests de la etapa de resultados (#8).

Funciones puras: entran las respuestas de search/code y los candidatos con su
score, salen archivos y resultados. Sin red ni mocks.
"""

from __future__ import annotations

from snippet_search.ast_subtrees import Subtree
from snippet_search.llm_tags import KIND_CONCEPTUAL, KIND_SYNTACTIC
from snippet_search.results import (
    Candidate,
    Location,
    MergedFile,
    ResultQuery,
    merge_files,
    to_results,
)

from conftest import SEARCH_BODY

QUERY_TEXT = {KIND_SYNTACTIC: "sorted items language:python"}
SHA = "c94096de9cefc0fa90434a3b65d043540e5b120e"
PATH = "app/services/document_ai.py"


def item(repo: str, path: str, *, sha: str) -> dict:
    """Un item de search/code con lo que la etapa lee."""
    return {
        "path": path,
        "sha": sha,
        "html_url": f"https://github.com/{repo}/blob/c0ffee/{path}",
        "repository": {"full_name": repo, "private": False},
    }


def body(*items: dict) -> dict:
    return {"total_count": len(items), "incomplete_results": False, "items": list(items)}


def candidate(repo: str, path: str, *, line: int, score: float, sha: str) -> Candidate:
    """Un subarbol con su score, salido de un archivo que encontro la sintactica."""
    found = item(repo, path, sha=sha)
    file = MergedFile(sha, found, (KIND_SYNTACTIC,), (Location(repo, path, found["html_url"]),))
    subtree = Subtree(
        code=f"def f{line}(items):\n    return sorted(items)",
        kind="function_definition",
        name=f"f{line}",
        parent=None,
        start_line=line,
        end_line=line + 1,
        anchors=("sorted",),
    )
    return Candidate(file, subtree, score)


# --- merge_files -------------------------------------------------------------


def test_the_same_content_in_a_private_and_a_public_repo_is_one_public_file() -> None:
    # El caso de tests.md, con el privado primero: tiene que ganar el publico
    private_first = {**SEARCH_BODY, "items": list(reversed(SEARCH_BODY["items"]))}

    files, private_excluded = merge_files([(KIND_SYNTACTIC, private_first)], limit=20)

    assert [f.sha for f in files] == [SHA]
    assert files[0].locations == (Location("example-org/public-sample", PATH, None),)
    # Lo que se baja es la copia publica
    assert files[0].item["repository"]["full_name"] == "example-org/public-sample"
    assert private_excluded == 0


def test_content_only_in_private_repos_is_dropped_and_counted_once() -> None:
    private_only = {"items": [SEARCH_BODY["items"][1]]}

    # Dos queries trajeron el mismo contenido privado: cuenta como uno
    files, private_excluded = merge_files(
        [(KIND_SYNTACTIC, private_only), (KIND_CONCEPTUAL, private_only)], limit=20
    )

    assert files == []
    assert private_excluded == 1


def test_the_same_content_in_two_public_repos_keeps_both_locations_once() -> None:
    first = item("example-org/first", "lib/rank.py", sha="same")
    fork = item("other-org/fork", "vendor/rank.py", sha="same")

    files, _ = merge_files(
        [(KIND_SYNTACTIC, body(first, fork)), (KIND_CONCEPTUAL, body(first))], limit=20
    )

    assert len(files) == 1
    assert files[0].locations == (
        Location("example-org/first", "lib/rank.py", "https://github.com/example-org/first/blob/c0ffee/lib/rank.py"),
        Location("other-org/fork", "vendor/rank.py", "https://github.com/other-org/fork/blob/c0ffee/vendor/rank.py"),
    )


def test_files_found_by_more_queries_come_first_and_survive_the_limit() -> None:
    # 'listed_first' encabeza la sintactica, pero 'found_twice' lo encontraron dos
    listed_first = item("example-org/a", "a.py", sha="a")
    found_twice = item("example-org/b", "b.py", sha="b")
    bodies = [(KIND_SYNTACTIC, body(listed_first, found_twice)), (KIND_CONCEPTUAL, body(found_twice))]

    everything, _ = merge_files(bodies, limit=20)
    one, _ = merge_files(bodies, limit=1)

    assert [f.sha for f in everything] == ["b", "a"]
    assert [(f.sha, f.queries) for f in one] == [("b", (KIND_SYNTACTIC, KIND_CONCEPTUAL))]


def test_a_query_that_only_saw_the_private_copy_still_found_the_content() -> None:
    public, private = SEARCH_BODY["items"]

    files, private_excluded = merge_files(
        [(KIND_SYNTACTIC, body(private)), (KIND_CONCEPTUAL, body(public))], limit=20
    )

    # Las dos queries encontraron ese contenido; el repo privado no aparece
    assert [(f.queries, f.locations[0].repo) for f in files] == [
        ((KIND_SYNTACTIC, KIND_CONCEPTUAL), "example-org/public-sample")
    ]
    assert private_excluded == 0


# --- to_results --------------------------------------------------------------


def test_results_go_by_score_with_ties_broken_by_repo_path_and_line() -> None:
    candidates = [
        candidate("example-org/b", "b.py", line=10, score=0.5, sha="b"),
        candidate("example-org/a", "a.py", line=3, score=0.9, sha="a"),
        candidate("example-org/b", "b.py", line=2, score=0.5, sha="b"),
        candidate("example-org/a", "z.py", line=1, score=0.5, sha="z"),
    ]

    results = to_results(candidates, QUERY_TEXT, max_results=10)

    # 0.9 primero; los tres 0.5 por repo, despues path, despues linea
    assert [(r.rank, r.sha, r.start_line) for r in results] == [
        (1, "a", 3),
        (2, "z", 1),
        (3, "b", 2),
        (4, "b", 10),
    ]


def test_ties_in_the_same_repo_are_broken_by_path() -> None:
    candidates = [
        candidate("example-org/a", "z.py", line=1, score=0.5, sha="z"),
        candidate("example-org/a", "b.py", line=1, score=0.5, sha="b"),
    ]

    results = to_results(candidates, QUERY_TEXT, max_results=10)

    assert [r.sha for r in results] == ["b", "z"]


def test_the_order_does_not_depend_on_how_github_listed_the_locations() -> None:
    original = Location("example-org/a", "a.py", None)
    fork = Location("other-org/fork", "a.py", None)
    other = candidate("example-org/c", "c.py", line=1, score=0.5, sha="c")
    same = candidate("example-org/a", "a.py", line=1, score=0.5, sha="same")

    def ordered(locations: tuple[Location, ...]) -> list[str]:
        file = MergedFile("same", same.file.item, (KIND_SYNTACTIC,), locations)
        listed = Candidate(file, same.subtree, same.score)
        return [r.sha for r in to_results([other, listed], QUERY_TEXT, max_results=10)]

    # El mismo contenido listado como [fork, original] o [original, fork]
    assert ordered((fork, original)) == ordered((original, fork)) == ["same", "c"]


def test_only_the_best_max_results_are_returned() -> None:
    candidates = [
        candidate("example-org/a", "a.py", line=1, score=0.2, sha="low"),
        candidate("example-org/a", "a.py", line=5, score=0.8, sha="high"),
        candidate("example-org/a", "a.py", line=9, score=0.6, sha="mid"),
    ]

    results = to_results(candidates, QUERY_TEXT, max_results=2)

    assert [(r.rank, r.sha) for r in results] == [(1, "high"), (2, "mid")]


def test_a_result_carries_every_repo_and_the_text_of_each_query_that_found_it() -> None:
    first = item("example-org/first", "lib/rank.py", sha="same")
    fork = item("other-org/fork", "vendor/rank.py", sha="same")
    files, _ = merge_files(
        [(KIND_SYNTACTIC, body(first)), (KIND_CONCEPTUAL, body(fork))], limit=20
    )
    subtree = candidate("example-org/first", "lib/rank.py", line=4, score=0.7, sha="same").subtree
    query_text = {KIND_SYNTACTIC: "sorted items language:python", KIND_CONCEPTUAL: "ranking language:python"}

    (result,) = to_results([Candidate(files[0], subtree, 0.7)], query_text, max_results=10)

    assert [loc.repo for loc in result.locations] == ["example-org/first", "other-org/fork"]
    assert result.queries == (
        ResultQuery(KIND_SYNTACTIC, "sorted items language:python"),
        ResultQuery(KIND_CONCEPTUAL, "ranking language:python"),
    )


def test_nothing_ranked_gives_an_explicit_empty_result() -> None:
    assert to_results([], QUERY_TEXT, max_results=10) == ()
