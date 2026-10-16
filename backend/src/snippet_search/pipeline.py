"""Orquestacion del pipeline de busqueda.

Las etapas son modulos sueltos que no se conocen entre si; este modulo las
encadena para que el endpoint quede fino. Hoy corre todo: tags del AST (#4) y
del LLM (#7), una query de search/code por tipo de tag (#19), los archivos de
cada resultado (#3), el AST (#20), los embeddings (#21) y la lista de
resultados (#8). Faltan los tags editados (#22) y los filtros (#19).
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
from .llm_tags import KINDS, LlmTagError, TagSet
from .query import SearchQuery, build_query
from .results import (
    DEFAULT_MAX_RESULTS,
    Candidate,
    MergedFile,
    Result,
    merge_files,
    repo_of,
    to_results,
    without_private,
)

# Codigos estables, como los de #7: en los dos casos no se llega a buscar
ERROR_NOTHING_TO_SEARCH: Final = "nothing_to_search"
ERROR_UNSUPPORTED_LANGUAGE: Final = "unsupported_language"

# Archivos de search/code que se bajan y parsean: cada uno es un request a contents
MAX_CANDIDATE_FILES: Final = 20
# Techo K de subarboles que llegan a UniXcoder (#18, unixcoder-verificacion.md)
MAX_EMBEDDED_SUBTREES: Final = 50

# La unica query cuando el LLM no esta: sale de los tiers del AST (#1)
QUERY_TIERS: Final = "tiers"

UNIXCODER_MODEL: Final = "microsoft/unixcoder-base"

# Puntua el snippet contra cada candidato: un coseno por candidato, en orden
Ranker = Callable[[str, list[str]], list[float]]


class TagExtractor(Protocol):
    async def extract(self, source: str, *, language: str | None = None, tiers: Tiers | None = None) -> TagSet: ...


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
class Skipped:
    repo: str
    path: str
    reason: str


@dataclass(frozen=True)
class QueryRun:
    """Una query de search/code: el tipo de tag que la armo, y lo que devolvio
    GitHub o el motivo por el que fallo."""

    kind: str
    query: SearchQuery
    # El body de search/code sin tocar: reformatearlo es #8
    body: Any = None
    error: str | None = None


@dataclass(frozen=True)
class SearchOutcome:
    tiers: Tiers
    queries: tuple[QueryRun, ...]
    rate_limit: RateLimit | None
    snippet: SnippetShape
    llm_tags: TagSet | None
    llm_error: str | None
    anchors: tuple[str, ...]
    # Lo que ve el usuario (#8)
    results: tuple[Result, ...] = ()
    # Los subarboles con score, sin ordenar ni cortar: para debuggear
    candidates: tuple[Candidate, ...] = ()
    skipped: tuple[Skipped, ...] = ()
    # Contenidos que solo estaban en repos privados: se cuentan, no se nombran
    private_excluded: int = 0
    rejected: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tiers": asdict(self.tiers),
            "queries": [
                {"kind": r.kind, "tags": list(r.query.tags), "q": r.query.q, "error": r.error}
                for r in self.queries
            ],
            "llm": {
                "tags": self.llm_tags.as_list() if self.llm_tags else None,
                "error": self.llm_error,
            },
            "snippet": asdict(self.snippet),
            "anchors": list(self.anchors),
            "results": [asdict(r) for r in self.results],
            "rejected": self.rejected,
            "skipped": [asdict(s) for s in self.skipped],
            "private_excluded": self.private_excluded,
            # Las respuestas crudas de search/code, sin los items privados
            "github": {r.kind: without_private(r.body) for r in self.queries},
        }


async def search(
    github: GitHubClient,
    source: str,
    language: str,
    *,
    llm: TagExtractor,
    rank: Ranker,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> SearchOutcome:
    """Del snippet pegado a los resultados (#8): subarboles de GitHub ordenados
    por coseno, hasta `max_results`."""
    normalized = language.lower()
    if normalized not in SUPPORTED_LANGUAGES:
        raise SearchError(
            f"Only Python snippets are supported for now, not {language!r}.",
            ERROR_UNSUPPORTED_LANGUAGE,
        )

    # TAGS: PART 1 (deterministic AST seed extraction, regex as fallback)
    tiers = extract_tags(source)

    # TAGS: PART 2 (LLM semantic expansion)
    llm_tags, llm_error = await _llm_tags(llm, source, normalized, tiers)

    queries = _build_queries(tiers, llm_tags, normalized)
    if not queries:
        raise SearchError(
            "The snippet has no distinctive terms to search for.",
            ERROR_NOTHING_TO_SEARCH,
        )

    snippet = analyze_snippet(source)

    # [TAGS github]
    #input(A) -> grep(A) -> AST(A) -> TAGS PRELIM: a) generarlos con grep -> interpret LLM                                    
    #                                                  +
    #                                                 sumar pequeño parrafo de contexto

    #[TAGS ANCLAS (resultados de llm + algun otro creterio de afinamiento)] -> pruning.




    #[TAGS] -> query github REQUERIMIENTOS: ambiguedad para no hacer una busqueda explicita y perdernos de casos
    #[TAGS ANCLAS] -> pruning de los resultados de github search code. REQUERIMIENTOS: mayor nivel de espeficididad (sumar tags o reemplazar de los TAGS busqueda)

    runs, rate_limit = await _run_queries(github, queries)
    files, private_excluded = merge_files(
        [(run.kind, run.body) for run in runs], MAX_CANDIDATE_FILES
    )

    # En serie a proposito, como las queries: GitHub pide no mandarle requests
    # concurrentes, para no pisar el limite secundario
    fetched = []
    for file in files:
        fetched.append(await _fetch(github, file))

    # Las anclas del criterio B: APIs y estructuras del AST, y toda la lista del
    # LLM (lo conceptual y las alternativas que ast_grep no ve)
    llm_anchors = [tag.text for tag in llm_tags.tags] if llm_tags else []
    anchors = tuple(dict.fromkeys([*tiers.apis, *tiers.structures, *llm_anchors]))

    found, skipped, rejected = _isolate_files(fetched, snippet, anchors)

    # Sobre el techo pasan primero los de archivos que encontraron mas queries,
    # despues los que matchearon mas anclas; a igualdad, el orden del merge
    found.sort(key=lambda pair: (len(pair[0].queries), len(pair[1].anchors)), reverse=True)
    rejected["budget"] = max(0, len(found) - MAX_EMBEDDED_SUBTREES)
    candidates = _rank(rank, source, found[:MAX_EMBEDDED_SUBTREES])
    results = to_results(candidates, {run.kind: run.query.q for run in runs}, max_results)

    return SearchOutcome(
        tiers=tiers,
        queries=tuple(runs),
        rate_limit=rate_limit,
        snippet=snippet,
        llm_tags=llm_tags,
        llm_error=llm_error,
        anchors=anchors,
        results=results,
        candidates=candidates,
        skipped=tuple(skipped),
        private_excluded=private_excluded,
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
    fetched: list[tuple[MergedFile, str | None, str | None]],
    snippet: SnippetShape,
    anchors: tuple[str, ...],
) -> tuple[list[tuple[MergedFile, Subtree]], list[Skipped], dict[str, int]]:
    """Corre el AST sobre cada archivo. Uno que no se trajo o no parsea se
    saltea con su motivo, sin cortar la corrida."""
    found: list[tuple[MergedFile, Subtree]] = []
    skipped: list[Skipped] = []
    rejected = {"A": 0, "C": 0, "B": 0, "length": 0, "budget": 0}

    for file, code, reason in fetched:
        if code is not None:
            try:
                isolation = isolate(code, snippet, anchors)
            except UnparseableSource as error:
                reason = str(error)
            else:
                found.extend((file, subtree) for subtree in isolation.subtrees)
                for criterion, count in isolation.rejected.items():
                    rejected[criterion] += count
        if reason is not None:
            first = file.locations[0]
            skipped.append(Skipped(first.repo, first.path, reason))

    return found, skipped, rejected


def _rank(
    rank: Ranker, source: str, found: list[tuple[MergedFile, Subtree]]
) -> tuple[Candidate, ...]:
    """Un coseno por subarbol. El orden y el corte son de to_results (#8)."""
    if not found:
        return ()

    # Futuro: UniXcoder bloquea el event loop mientras embebe; correrlo en un
    # thread con asyncio.to_thread (y volver async a _rank)
    scores = rank(textwrap.dedent(source).strip(), [subtree.code for _, subtree in found])
    return tuple(
        Candidate(file, subtree, score) for (file, subtree), score in zip(found, scores)
    )


def _build_queries(
    tiers: Tiers, llm_tags: TagSet | None, language: str
) -> list[tuple[str, SearchQuery]]:
    """Una query por tipo de tag del LLM (#19): sintactica, conceptual y de
    paradigma. Un seed que el LLM descarto (un modulo interno como
    'ringr_agents') no entra en ninguna.

    Sin LLM, o si no dejo nada buscable, una sola query con los tiers (#1).
    """
    queries: list[tuple[str, SearchQuery]] = []
    if llm_tags is not None:
        for kind in KINDS:
            query = build_query([t.text for t in llm_tags.tags if t.kind == kind], language)
            if isinstance(query, SearchQuery):
                queries.append((kind, query))
    if queries:
        return queries
    query = build_query(tiers.ordered(), language)
    return [(QUERY_TIERS, query)] if isinstance(query, SearchQuery) else []


async def _run_queries(
    github: GitHubClient, queries: list[tuple[str, SearchQuery]]
) -> tuple[list[QueryRun], RateLimit | None]:
    """Corre las queries una por una: GitHub pide requests en serie y no
    concurrentes, para no pisar el limite secundario. Una que falla no corta
    las otras; si fallan todas, sale el error de la primera."""
    runs: list[QueryRun] = []
    errors: list[GitHubError] = []
    rate_limit: RateLimit | None = None
    for kind, query in queries:
        try:
            response = await github.search_code(q=query.q, per_page=MAX_CANDIDATE_FILES)
        except GitHubError as error:
            errors.append(error)
            runs.append(QueryRun(kind, query, error=_github_reason(error)))
            continue
        # El ultimo que respondio trae el limite mas al dia
        rate_limit = response.rate_limit or rate_limit
        runs.append(QueryRun(kind, query, body=response.body))
    if len(errors) == len(runs):
        raise errors[0]
    return runs, rate_limit


async def _llm_tags(
    llm: TagExtractor, source: str, language: str, tiers: Tiers
) -> tuple[TagSet | None, str | None]:
    # El LLM es un complemento: si falla, la corrida sigue con el grep
    try:
        return await llm.extract(source, language=language, tiers=tiers), None
    except LlmTagError as error:
        return None, error.code


async def _fetch(
    github: GitHubClient, file: MergedFile
) -> tuple[MergedFile, str | None, str | None]:
    """El archivo de un resultado, o el motivo por el que no se pudo traer.

    Nunca llega uno privado: merge_files ya los dejo afuera (#8).
    """
    item = file.item
    ref = parse_qs(urlparse(item.get("url", "")).query).get("ref", [None])[0]
    if ref is None:
        return file, None, "the search result carries no ref to fetch"

    try:
        response = await github.get_file_contents(repo_of(item), item.get("path", ""), ref)
    except GitHubError as error:
        return file, None, _github_reason(error)
    return file, response.body, None


def _github_reason(error: GitHubError) -> str:
    message = error.body.get("message") if isinstance(error.body, dict) else None
    return f"GitHub {error.status_code}: {message or 'no message'}"
