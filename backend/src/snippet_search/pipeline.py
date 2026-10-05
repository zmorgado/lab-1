"""Orquestacion del pipeline de busqueda.

Las etapas son modulos sueltos que no se conocen entre si; este modulo las
encadena para que el endpoint quede fino. Hoy corre todo: tags por grep (#4) y
por LLM (#7), query y search/code, los archivos de cada resultado (#3), el AST
(#20) y los embeddings (#21). Faltan los tags editados (#22), los filtros (#19)
y el formato final de resultados (#8).
"""

from __future__ import annotations

import functools
import textwrap
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Final, Protocol
from urllib.parse import parse_qs, urlparse

from .ast_subtrees import SnippetShape, Subtree, UnparseableSource, analyze_snippet, isolate
from .github import GitHubClient, GitHubError, RateLimit
from .ast_grep_tags import SUPPORTED_LANGUAGES, Tiers, extract_tags
from .llm_tags import LlmTagError, TagSet
from .query import NothingToSearch, SearchQuery, build_query

# Codigos estables, como los de #7: en los dos casos no se llega a buscar
ERROR_NOTHING_TO_SEARCH: Final = "nothing_to_search"
ERROR_UNSUPPORTED_LANGUAGE: Final = "unsupported_language"

# Archivos de search/code que se bajan y parsean: cada uno es un request a contents
MAX_CANDIDATE_FILES: Final = 20
# Techo K de subarboles que llegan a UniXcoder (#18, unixcoder-verificacion.md)
MAX_EMBEDDED_SUBTREES: Final = 50

UNIXCODER_MODEL: Final = "microsoft/unixcoder-base"

# Puntua el snippet contra cada candidato: un coseno por candidato, en orden
Ranker = Callable[[str, list[str]], list[float]]


class TagExtractor(Protocol):
    async def extract(self, source: str, *, language: str | None = None) -> TagSet: ...


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
class Candidate:
    """Un subarbol que llego a los embeddings, con el archivo del que salio."""

    repo: str
    path: str
    sha: str
    html_url: str | None
    subtree: Subtree
    score: float


@dataclass(frozen=True)
class Skipped:
    repo: str
    path: str
    reason: str


@dataclass(frozen=True)
class SearchOutcome:
    tiers: Tiers
    query: SearchQuery
    # El body de search/code sin tocar: reformatearlo es #8
    results: Any
    rate_limit: RateLimit | None
    snippet: SnippetShape
    llm_tags: TagSet | None
    llm_error: str | None
    anchors: tuple[str, ...]
    candidates: tuple[Candidate, ...] = ()
    skipped: tuple[Skipped, ...] = ()
    rejected: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tags": list(self.query.tags),
            "tiers": asdict(self.tiers),
            "query": self.query.q,
            "llm": {
                "tags": self.llm_tags.as_dict() if self.llm_tags else None,
                "error": self.llm_error,
            },
            "snippet": asdict(self.snippet),
            "anchors": list(self.anchors),
            "candidates": [
                {
                    "repo": c.repo,
                    "path": c.path,
                    "sha": c.sha,
                    "html_url": c.html_url,
                    "score": c.score,
                    **asdict(c.subtree),
                }
                for c in self.candidates
            ],
            "rejected": self.rejected,
            "skipped": [asdict(s) for s in self.skipped],
            "results": self.results,
        }


async def search(
    github: GitHubClient,
    source: str,
    language: str,
    *,
    llm: TagExtractor,
    rank: Ranker,
) -> SearchOutcome:
    """Del snippet pegado a los subarboles de GitHub, ordenados por coseno."""
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

    snippet = analyze_snippet(source)

    # Por ahora todo en secuencia, para poder seguirlo linea por linea.
    # Futuro: el LLM tarda, asi que deberia arrancar aca con asyncio.create_task,
    # correr mientras se busca y se bajan los archivos, y esperarse recien antes
    # de armar las anclas (cancelandolo en un finally si la busqueda falla)
    llm_tags, llm_error = await _llm_tags(llm, source, normalized)

    # [TAGS github]
    #input(A) -> grep(A) -> AST(A) -> TAGS PRELIM: a) generarlos con grep -> interpret LLM                                    
    #                                                  +
    #                                                 sumar pequeño parrafo de contexto

    #[TAGS ANCLAS (resultados de llm + algun otro creterio de afinamiento)] -> pruning.




    #[TAGS] -> query github REQUERIMIENTOS: ambiguedad para no hacer una busqueda explicita y perdernos de casos
    #[TAGS ANCLAS] -> pruning de los resultados de github search code. REQUERIMIENTOS: mayor nivel de espeficididad (sumar tags o reemplazar de los TAGS busqueda)

    response = await github.search_code(q=query.q, per_page=MAX_CANDIDATE_FILES)
    items = response.body.get("items", [])[:MAX_CANDIDATE_FILES]

    # Futuro: los archivos no dependen entre si; pedirlos todos juntos con asyncio.gather
    fetched = []
    for item in items:
        fetched.append(await _fetch(github, item))

    # Las anclas del criterio B: APIs y estructuras del grep, y todo lo del LLM
    # (algoritmo, paradigma: lo conceptual que el grep no ve)
    llm_anchors = [tag for tags in llm_tags.as_dict().values() for tag in tags] if llm_tags else []
    anchors = tuple(dict.fromkeys([*tiers.apis, *tiers.structures, *llm_anchors]))

    found, skipped, rejected = _isolate_files(fetched, snippet, anchors)

    # Sobre el techo, pasan los que matchearon mas anclas; a igualdad, el orden de GitHub
    found.sort(key=lambda pair: len(pair[1].anchors), reverse=True)
    rejected["budget"] = max(0, len(found) - MAX_EMBEDDED_SUBTREES)
    candidates = _rank(rank, source, found[:MAX_EMBEDDED_SUBTREES])

    return SearchOutcome(
        tiers=tiers,
        query=query,
        results=response.body,
        rate_limit=response.rate_limit,
        snippet=snippet,
        llm_tags=llm_tags,
        llm_error=llm_error,
        anchors=anchors,
        candidates=tuple(candidates),
        skipped=tuple(skipped),
        rejected=rejected,
    )


def unixcoder_rank(query: str, snippets: list[str]) -> list[float]:
    """El Ranker real: UniXcoder cargado una sola vez por proceso."""
    from .embeddings.encoder_only_VE import verify_code_semantics

    return verify_code_semantics(query, snippets, model=_unixcoder())


@functools.cache
def _unixcoder() -> Any:
    # Import diferido: torch tarda en cargar y los tests no lo necesitan
    import torch

    from .embeddings.unixcoder import UniXcoder

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = UniXcoder(UNIXCODER_MODEL).to(device)
    model.eval()
    return model


def _isolate_files(
    fetched: list[tuple[dict[str, Any], str | None, str | None]],
    snippet: SnippetShape,
    anchors: tuple[str, ...],
) -> tuple[list[tuple[dict[str, Any], Subtree]], list[Skipped], dict[str, int]]:
    """Corre el AST sobre cada archivo. Uno que no se trajo o no parsea se
    saltea con su motivo, sin cortar la corrida."""
    found: list[tuple[dict[str, Any], Subtree]] = []
    skipped: list[Skipped] = []
    rejected = {"A": 0, "C": 0, "B": 0, "length": 0, "budget": 0}

    for item, code, reason in fetched:
        if code is not None:
            try:
                isolation = isolate(code, snippet, anchors)
            except UnparseableSource as error:
                reason = str(error)
            else:
                found.extend((item, subtree) for subtree in isolation.subtrees)
                for criterion, count in isolation.rejected.items():
                    rejected[criterion] += count
        if reason is not None:
            skipped.append(Skipped(_repo(item), item.get("path", ""), reason))

    return found, skipped, rejected


def _rank(
    rank: Ranker, source: str, found: list[tuple[dict[str, Any], Subtree]]
) -> tuple[Candidate, ...]:
    if not found:
        return ()

    # Futuro: UniXcoder bloquea el event loop mientras embebe; correrlo en un
    # thread con asyncio.to_thread (y volver async a _rank)
    scores = rank(textwrap.dedent(source).strip(), [subtree.code for _, subtree in found])
    candidates = (
        Candidate(
            repo=_repo(item),
            path=item.get("path", ""),
            sha=item.get("sha", ""),
            html_url=item.get("html_url"),
            subtree=subtree,
            score=score,
        )
        for (item, subtree), score in zip(found, scores)
    )
    return tuple(sorted(candidates, key=lambda candidate: candidate.score, reverse=True))


async def _llm_tags(
    llm: TagExtractor, source: str, language: str
) -> tuple[TagSet | None, str | None]:
    # El LLM es un complemento: si falla, la corrida sigue con el grep
    try:
        return await llm.extract(source, language=language), None
    except LlmTagError as error:
        return None, error.code


async def _fetch(
    github: GitHubClient, item: dict[str, Any]
) -> tuple[dict[str, Any], str | None, str | None]:
    """El archivo de un resultado, o el motivo por el que no se pudo traer."""
    if item.get("repository", {}).get("private"):
        # Un solo token para todos: el codigo privado no sale de aca (#1)
        return item, None, "private repository"

    ref = parse_qs(urlparse(item.get("url", "")).query).get("ref", [None])[0]
    if ref is None:
        return item, None, "the search result carries no ref to fetch"

    try:
        response = await github.get_file_contents(_repo(item), item.get("path", ""), ref)
    except GitHubError as error:
        message = error.body.get("message") if isinstance(error.body, dict) else None
        return item, None, f"GitHub {error.status_code}: {message or 'no message'}"
    return item, response.body, None


def _repo(item: dict[str, Any]) -> str:
    return item.get("repository", {}).get("full_name", "")
