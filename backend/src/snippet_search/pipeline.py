"""Orquestacion del pipeline de busqueda.

Las etapas son modulos sueltos que no se conocen entre si; este modulo las
encadena para que el endpoint quede fino. Hoy corre todo: tags del AST (#4) y
del LLM (#7), una query de search/code por tipo de tag (#19), los archivos de
cada resultado (#3), el AST (#20), los embeddings (#21) y la lista de
resultados (#8).

Las etapas 1 y 2 tambien corren solas, en `preview()`: el usuario ve los tags
antes de buscar y la busqueda corre con los que confirmo, sin volver a llamar al
LLM (#38). Faltan los tags editados (#22) y los filtros (#19).
"""

from __future__ import annotations

import functools
import textwrap
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Final, Protocol
from urllib.parse import parse_qs, urlparse

from .ast_subtrees import SnippetShape, Subtree, UnparseableSource, analyze_snippet, isolate
from .github import GitHubClient, GitHubError, RateLimit
from .ast_grep_tags import SUPPORTED_LANGUAGES, Tiers, extract_tags
from .llm_tags import KINDS, SOURCE_SEED, LlmTagError, TagSet
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
# Un tag confirmado vacio, de un tipo que no existe o que romperia 'q' (#38)
ERROR_INVALID_TAG: Final = "invalid_tag"

# Archivos de search/code que se bajan y parsean: cada uno es un request a contents
MAX_CANDIDATE_FILES: Final = 20
# Techo K de subarboles que llegan a UniXcoder (#18, unixcoder-verificacion.md)
MAX_EMBEDDED_SUBTREES: Final = 50

# La unica query cuando el LLM no esta: sale de los tiers del AST (#1)
QUERY_TIERS: Final = "tiers"
# Los tipos que puede traer un tag confirmado: los del LLM y el de los tiers
TAG_KINDS: Final[tuple[str, ...]] = (*KINDS, QUERY_TIERS)

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
class ConfirmedTag:
    """Un tag que el usuario confirmo en el preview, con la query que alimenta."""

    text: str
    kind: str


@dataclass(frozen=True)
class QueryPlan:
    """Las etapas 1 y 2: las queries que va a correr la busqueda y las anclas
    del AST, antes de gastar presupuesto de GitHub."""

    tiers: Tiers
    queries: tuple[tuple[str, SearchQuery], ...]
    # Las anclas del criterio B: APIs y estructuras del AST, y los tags que no
    # salen de el (los del LLM, o los confirmados)
    anchors: tuple[str, ...]
    llm_tags: TagSet | None = None
    llm_error: str | None = None

    def as_preview(self) -> dict[str, Any]:
        """La forma que devuelve /api/search/preview: cada tag con su origen."""
        sources = {t.text: t.source for t in self.llm_tags.tags} if self.llm_tags else {}
        return {
            "queries": [
                {
                    "kind": kind,
                    "tags": [
                        {"tag": tag, "source": sources.get(tag, SOURCE_SEED)}
                        for tag in query.tags
                    ],
                    "q": query.q,
                }
                for kind, query in self.queries
            ],
            "llm": {"error": self.llm_error},
        }


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


async def preview(source: str, language: str, *, llm: TagExtractor) -> QueryPlan:
    """Las etapas 1 y 2 solas: los tags y las queries que correria `search()`,
    sin tocar GitHub (#38)."""
    normalized = _supported(language)

    # TAGS: PART 1 (deterministic AST seed extraction, regex as fallback)
    tiers = extract_tags(source)

    # TAGS: PART 2 (LLM semantic expansion)
    llm_tags, llm_error = await _llm_tags(llm, source, normalized, tiers)

    queries = _require(_build_queries(tiers, llm_tags, normalized))
    llm_anchors = [tag.text for tag in llm_tags.tags] if llm_tags else []
    return QueryPlan(tiers, queries, _anchors(tiers, llm_anchors), llm_tags, llm_error)


async def search(
    github: GitHubClient,
    source: str,
    language: str,
    *,
    llm: TagExtractor,
    rank: Ranker,
    max_results: int = DEFAULT_MAX_RESULTS,
    tags: Sequence[ConfirmedTag] | None = None,
) -> SearchOutcome:
    """Del snippet pegado a los resultados (#8): subarboles de GitHub ordenados
    por coseno, hasta `max_results`.

    Con `tags`, los que el usuario confirmo en el preview, la busqueda corre
    sobre esos y no vuelve a llamar al LLM (#38).
    """
    if tags is None:
        plan = await preview(source, language, llm=llm)
    else:
        plan = _confirmed_plan(source, language, tags)
    tiers, queries, anchors = plan.tiers, plan.queries, plan.anchors

    snippet = analyze_snippet(source)

    # [TAGS github]
    #input(A) -> grep(A) -> AST(A) -> TAGS PRELIM: a) generarlos con grep -> interpret LLM                                    
    #                                                  +
    #                                                 sumar pequeño parrafo de contexto

    #[TAGS ANCLAS (resultados de llm + algun otro creterio de afinamiento)] -> pruning.




    #[TAGS] -> query github REQUERIMIENTOS: ambiguedad para no hacer una busqueda explicita y perdernos de casos
    #[TAGS ANCLAS] -> pruning de los resultados de github search code. REQUERIMIENTOS: mayor nivel de espeficididad (sumar tags o reemplazar de los TAGS busqueda)

    runs, rate_limit = await _run_queries(github, list(queries))
    files, private_excluded = merge_files(
        [(run.kind, run.body) for run in runs], MAX_CANDIDATE_FILES
    )

    # En serie a proposito, como las queries: GitHub pide no mandarle requests
    # concurrentes, para no pisar el limite secundario
    fetched = []
    for file in files:
        fetched.append(await _fetch(github, file))

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
        llm_tags=plan.llm_tags,
        llm_error=plan.llm_error,
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


def _supported(language: str) -> str:
    normalized = language.lower()
    if normalized not in SUPPORTED_LANGUAGES:
        raise SearchError(
            f"Only Python snippets are supported for now, not {language!r}.",
            ERROR_UNSUPPORTED_LANGUAGE,
        )
    return normalized


def _require(
    queries: list[tuple[str, SearchQuery]],
) -> tuple[tuple[str, SearchQuery], ...]:
    if not queries:
        raise SearchError(
            "The snippet has no distinctive terms to search for.",
            ERROR_NOTHING_TO_SEARCH,
        )
    return tuple(queries)


def _anchors(tiers: Tiers, extra: Sequence[str]) -> tuple[str, ...]:
    # Lo conceptual y las alternativas que ast_grep no ve entran por `extra`
    return tuple(dict.fromkeys([*tiers.apis, *tiers.structures, *extra]))


def _confirmed_plan(source: str, language: str, tags: Sequence[ConfirmedTag]) -> QueryPlan:
    """Una query por tipo con los tags que confirmo el usuario. Los tiers se
    recalculan: son deterministicos y no cuestan nada."""
    normalized = _supported(language)
    texts = [_checked(tag) for tag in tags]
    queries: list[tuple[str, SearchQuery]] = []
    for kind in TAG_KINDS:
        query = build_query([text for text, tag in zip(texts, tags) if tag.kind == kind], normalized)
        if isinstance(query, SearchQuery):
            queries.append((kind, query))
    tiers = extract_tags(source)
    return QueryPlan(tiers, _require(queries), _anchors(tiers, texts))


def _checked(tag: ConfirmedTag) -> str:
    """El texto del tag, o un 422 antes de llamar a GitHub."""
    text = tag.text.strip()
    if not text:
        raise SearchError("A confirmed tag is empty.", ERROR_INVALID_TAG)
    if tag.kind not in TAG_KINDS:
        raise SearchError(
            f"Unknown tag kind {tag.kind!r}: expected one of {', '.join(TAG_KINDS)}.",
            ERROR_INVALID_TAG,
        )
    # Las comillas ya delimitan las frases de varias palabras en 'q'
    if '"' in text:
        raise SearchError(
            f"The tag {text!r} has a double quote, which would break the query.",
            ERROR_INVALID_TAG,
        )
    return text


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
