"""Orquestacion del pipeline de busqueda.

Las etapas son modulos sueltos que no se conocen entre si; este modulo las
encadena para que el endpoint quede fino. Hoy: tags por grep (#4), query y
search/code. Despues se suman aca los tags del LLM y los editados (#22), los
filtros (#19), el AST (#20), los embeddings (#21) y el ranking (#8).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Final

from .github import GitHubClient, RateLimit
from .grep_tags import SUPPORTED_LANGUAGES, Tiers, extract_tags
from .query import NothingToSearch, SearchQuery, build_query

# Codigos estables, como los de #7: en los dos casos no se llega a buscar
ERROR_NOTHING_TO_SEARCH: Final = "nothing_to_search"
ERROR_UNSUPPORTED_LANGUAGE: Final = "unsupported_language"


class SearchError(Exception):
    """El pedido no se puede buscar. Lleva status y body como LlmTagError."""

    status_code = 422

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code

    @property
    def body(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


@dataclass(frozen=True)
class SearchOutcome:
    tiers: Tiers
    query: SearchQuery
    # El body de search/code sin tocar: reformatearlo es #8
    results: Any
    rate_limit: RateLimit | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "tags": list(self.query.tags),
            "tiers": asdict(self.tiers),
            "query": self.query.q,
            "results": self.results,
        }


async def search(github: GitHubClient, source: str, language: str) -> SearchOutcome:
    """Del snippet pegado a los resultados de GitHub."""
    normalized = language.lower()
    if normalized not in SUPPORTED_LANGUAGES:
        raise SearchError(
            f"Only Python snippets are supported for now, not {language!r}.",
            ERROR_UNSUPPORTED_LANGUAGE,
        )

    tiers = extract_tags(source)
    query = build_query(tiers.ordered(), normalized)
    if isinstance(query, NothingToSearch):
        raise SearchError(
            "The snippet has no distinctive terms to search for.",
            ERROR_NOTHING_TO_SEARCH,
        )

    response = await github.search_code(q=query.q)
    return SearchOutcome(
        tiers=tiers, query=query, results=response.body, rate_limit=response.rate_limit
    )
