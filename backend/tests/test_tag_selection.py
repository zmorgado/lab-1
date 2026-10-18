"""Tests del nodo de seleccion de tags (#22): el pool que ve el usuario.

Los seeds salen del extractor real sobre snippets reales; el LLM es un TagSet
armado a mano, como en test_pipeline.py.
"""

from dataclasses import replace

from snippet_search.ast_grep_tags import extract_tags
from snippet_search.llm_tags import (
    KIND_CONCEPTUAL,
    KIND_PARADIGM,
    KIND_SYNTACTIC,
    SOURCE_LLM,
    SOURCE_SEED,
    Tag,
    TagSet,
)
from snippet_search.tag_selection import POOL_SIZE, QUERY_TIERS, select

RANK_CANDIDATES = '''
import math
from typing import Sequence

def rank_candidates(query, candidates):
    """Cosine similarity ranking."""
    scores = [math.fsum(q * c for q, c in zip(query, cand)) for cand in candidates]
    return sorted(zip(scores, candidates), key=lambda pair: pair[0], reverse=True)
'''


def _summary(pool) -> list[tuple[str, str, str, bool]]:
    return [(tag.text, tag.kind, tag.source, tag.selected) for tag in pool]


def test_names_and_domain_words_rank_above_apis_and_imports_go_last() -> None:
    pool = select(extract_tags(RANK_CANDIDATES), None, "python")

    # Sin el LLM, una sola query de tiers: entran los primeros seis por peso
    assert [(tag.text, tag.selected) for tag in pool] == [
        ("rank_candidates", True),
        ("cosine", True),
        ("similarity", True),
        ("ranking", True),
        ("fsum", True),
        ("sorted", True),
        ("lambda", False),
        ("math", False),
        ("typing", False),
    ]
    assert {(tag.kind, tag.source) for tag in pool} == {(QUERY_TIERS, SOURCE_SEED)}


def test_with_the_model_its_tags_are_selected_and_the_seeds_it_dropped_are_offered() -> None:
    llm = TagSet(
        tags=(
            Tag("sorted", KIND_SYNTACTIC, SOURCE_SEED),
            Tag("fsum", KIND_SYNTACTIC, SOURCE_SEED),
            Tag("cosine_similarity", KIND_CONCEPTUAL, SOURCE_LLM),
            Tag("ranking", KIND_CONCEPTUAL, SOURCE_SEED),
            Tag("numpy", KIND_PARADIGM, SOURCE_LLM),
            Tag("lambda", KIND_PARADIGM, SOURCE_SEED),
        )
    )

    pool = select(extract_tags(RANK_CANDIDATES), llm, "python")

    assert _summary(pool) == [
        ("cosine_similarity", KIND_CONCEPTUAL, SOURCE_LLM, True),
        ("ranking", KIND_CONCEPTUAL, SOURCE_SEED, True),
        ("rank_candidates", KIND_SYNTACTIC, SOURCE_SEED, False),
        ("cosine", KIND_CONCEPTUAL, SOURCE_SEED, False),
        ("similarity", KIND_CONCEPTUAL, SOURCE_SEED, False),
        ("sorted", KIND_SYNTACTIC, SOURCE_SEED, True),
        ("fsum", KIND_SYNTACTIC, SOURCE_SEED, True),
        ("numpy", KIND_PARADIGM, SOURCE_LLM, True),
        ("lambda", KIND_PARADIGM, SOURCE_SEED, True),
        ("math", KIND_PARADIGM, SOURCE_SEED, False),
        ("typing", KIND_PARADIGM, SOURCE_SEED, False),
    ]


def test_a_model_that_leaves_nothing_searchable_falls_back_to_the_seeds() -> None:
    pool = select(extract_tags(RANK_CANDIDATES), TagSet(), "python")

    assert {tag.kind for tag in pool} == {QUERY_TIERS}


def test_the_pool_holds_at_most_twenty_and_cuts_the_lightest() -> None:
    many = "import os\n" + "".join(f"def step_{n:02}():\n    return {n}\n" for n in range(25))

    pool = select(extract_tags(many), None, "python")

    assert len(pool) == POOL_SIZE == 20
    assert [tag.text for tag in pool] == [f"step_{n:02}" for n in range(20)]


def test_the_pool_is_the_same_whichever_path_extracted_the_seeds() -> None:
    tiers = extract_tags(RANK_CANDIDATES)

    assert select(replace(tiers, is_fallback=True), None, "python") == select(tiers, None, "python")


def test_a_snippet_that_does_not_parse_still_merges_with_imports_last() -> None:
    broken = 'import math\n\ndef rank(items):\n    """Cosine ranking."""\n    return sorted(items\n'
    tiers = extract_tags(broken)

    pool = select(tiers, None, "python")

    assert tiers.is_fallback
    assert [tag.text for tag in pool] == ["rank", "cosine", "ranking", "sorted", "math"]
