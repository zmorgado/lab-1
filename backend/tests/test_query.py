from collections.abc import Iterable

from snippet_search.query import NothingToSearch, SearchQuery, build_query

# Candidatos ya ordenados por nivel, como los devuelve grep_tags
RANKED_TAGS = [
    "operator",
    "sorted",
    "items",
    "itemgetter",
    "rank_by_value",
    "sort",
    "scores",
    "dictionary",
]

# Cuatro tags de 60 caracteres no entran juntos en los 256 de la query
LONG_TAGS = [f"call_{letter}_" + "x" * 53 for letter in "abcd"]


def query_of(tags: Iterable[str]) -> SearchQuery:
    query = build_query(tags, "python")
    assert isinstance(query, SearchQuery)
    return query


def test_the_first_six_tags_in_the_given_order_make_the_query() -> None:
    # AC: truncar se queda con los primeros, que son los de nivel mas alto
    assert query_of(RANKED_TAGS) == SearchQuery(
        tags=("operator", "sorted", "items", "itemgetter", "rank_by_value", "sort"),
        q="operator sorted items itemgetter rank_by_value sort language:python",
    )


def test_the_query_stays_within_256_characters() -> None:
    # AC: el limite se mide sobre el valor de 'q', calificador incluido
    assert len(query_of([*LONG_TAGS, "short_def"]).q) <= 256


def test_a_tag_that_does_not_fit_is_skipped_and_the_next_one_tried() -> None:
    # El cuarto tag largo no entra; el corto que viene despues si
    assert query_of([*LONG_TAGS, "short_def"]).tags == (
        LONG_TAGS[0],
        LONG_TAGS[1],
        LONG_TAGS[2],
        "short_def",
    )


def test_a_multi_token_tag_is_quoted_to_match_as_a_unit() -> None:
    # Las tags del LLM (#7) pueden ser frases; sin comillas cada palabra matchea suelta
    assert query_of(["binary search", "bisect_left"]) == SearchQuery(
        tags=("binary search", "bisect_left"),
        q='"binary search" bisect_left language:python',
    )


def test_an_empty_tag_list_is_not_searched() -> None:
    # AC: un resultado explicito, no una query vacia
    assert build_query([], "python") == NothingToSearch()
