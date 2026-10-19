"""Lado HTTP de la busqueda (#4, #8, #38, #43): los requests y las respuestas
de /api/search, de su preview de tags y de las explicaciones de sus resultados.

Las rutas se cuelgan en `create_app()`; el pipeline vive en `pipeline.py` y no
sabe de HTTP.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .pipeline import MAX_EMBEDDED_SUBTREES, TAG_KINDS, SelectedTag
from .result_explanations import ExplainItem
from .results import DEFAULT_MAX_RESULTS
from .tags_api import TagItem


class TagIn(BaseModel):
    # El tipo no es un Literal: uno desconocido tiene que ser un 422 con el
    # code estable del pipeline, no el 422 generico de FastAPI
    tag: str
    kind: str = Field(description=f"The query it feeds: {', '.join(TAG_KINDS)}")


class PreviewRequest(BaseModel):
    source: str = Field(description="The pasted snippet, as text")
    language: str = Field(
        default="python", description="Only Python for now; case-insensitive"
    )
    tags: list[TagIn] | None = Field(
        default=None,
        description="The tags the user selected. With them the LLM is not called again",
    )

    def selected_tags(self) -> list[SelectedTag] | None:
        if self.tags is None:
            return None
        return [SelectedTag(t.tag, t.kind) for t in self.tags]


class SearchRequest(PreviewRequest):
    # El techo es lo que llega a UniXcoder: no hay mas resultados que esos
    max_results: int = Field(
        default=DEFAULT_MAX_RESULTS,
        ge=1,
        le=MAX_EMBEDDED_SUBTREES,
        description=f"How many results to return, 1 to {MAX_EMBEDDED_SUBTREES}",
    )


# --- preview -----------------------------------------------------------------
# Espeja QueryPlan.as_preview(): lo que ve el usuario antes de buscar (#38)


class PoolTagOut(BaseModel):
    tag: str
    kind: str = Field(description="The query it feeds")
    source: str = Field(description="'seed' from the AST, 'llm' from the model")
    selected: bool = Field(description="Whether it goes into the queries unless the user changes it")


class PreviewQueryOut(BaseModel):
    kind: str = Field(description="syntactic, conceptual, paradigm, or tiers without the LLM")
    tags: list[str] = Field(description="The selected tags that fit the query, in order")
    dropped: list[str] = Field(
        description="Selected tags left out by the 6-tag or 256-character limit"
    )
    q: str | None = Field(description="The search/code query it would send; null if none fit")


class PreviewLlmOut(BaseModel):
    error: str | None = Field(description="The LLM's error code, if it failed")


class PreviewResponse(BaseModel):
    pool: list[PoolTagOut] = Field(description="Every tag offered; empty when `tags` were sent")
    queries: list[PreviewQueryOut]
    llm: PreviewLlmOut
    is_fallback: bool = Field(
        description="The snippet didn't parse, so the regex extracted the AST tags"
    )


# --- respuesta ---------------------------------------------------------------
# Espeja SearchOutcome.as_dict(): es el contrato contra el que programa el
# frontend (#19, #23), asi que aparece tipado en /openapi.json (#35)


class QueryOut(BaseModel):
    kind: str = Field(description="syntactic, conceptual, paradigm, or tiers without the LLM")
    tags: list[str]
    q: str = Field(description="The search/code query as sent")
    error: str | None = Field(description="Why GitHub rejected it, if it did")


class LlmOut(BaseModel):
    tags: list[TagItem] | None
    error: str | None = Field(description="The LLM's error code, if it failed")


class SnippetOut(BaseModel):
    category: str
    fallback: bool
    lines: int


class LocationOut(BaseModel):
    repo: str
    path: str
    html_url: str | None


class ResultQueryOut(BaseModel):
    kind: str
    q: str


class ResultOut(BaseModel):
    rank: int
    score: float = Field(description="UniXcoder cosine against the snippet")
    sha: str
    locations: list[LocationOut] = Field(description="Every public repo with this content")
    queries: list[ResultQueryOut] = Field(description="The queries that found its file")
    name: str
    node: str = Field(description="function_definition or class_definition")
    parent: str | None
    start_line: int
    end_line: int
    code: str


class SkippedOut(BaseModel):
    repo: str
    path: str
    reason: str


class SearchResponse(BaseModel):
    tiers: dict[str, list[str]]
    queries: list[QueryOut]
    llm: LlmOut
    snippet: SnippetOut
    anchors: list[str]
    results: list[ResultOut] = Field(description="Ranked by score, at most max_results")
    rejected: dict[str, int]
    skipped: list[SkippedOut] = Field(description="Public files that could not be used")
    private_excluded: int = Field(
        description="Contents found only in private repos: counted, never named"
    )
    github: dict[str, Any] = Field(
        description="search/code's body per query, without private items"
    )


# --- explicaciones (#43) -----------------------------------------------------
# Despues de /api/search: el frontend devuelve el snippet y los resultados que
# ya tiene, asi el backend no guarda nada entre los dos llamados


class ExplainItemIn(BaseModel):
    rank: int = Field(description="The result's rank, as /api/search returned it")
    repo: str = Field(description="The repo the page shows it under")
    path: str
    name: str = Field(description="'Class.method' or 'function'")
    start_line: int = Field(ge=1, description="The file line where `code` starts")
    code: str


class ExplainRequest(BaseModel):
    source: str = Field(description="The pasted snippet, as text")
    results: list[ExplainItemIn] = Field(min_length=1, max_length=MAX_EMBEDDED_SUBTREES)

    def items(self) -> list[ExplainItem]:
        return [
            ExplainItem(r.rank, r.repo, r.path, r.name, r.start_line, r.code)
            for r in self.results
        ]


class HighlightOut(BaseModel):
    start: int = Field(description="First file line, inclusive")
    end: int = Field(description="Last file line, inclusive")


class ExplanationOut(BaseModel):
    rank: int
    value: str = Field(description="What it offers next to the snippet; code names in backticks")
    suggestion: str = Field(description="What to bring into the snippet; empty if nothing")
    highlights: list[HighlightOut] = Field(description="The most interesting lines, at most 3 ranges")


class ExplainResponse(BaseModel):
    explanations: list[ExplanationOut] = Field(
        description="In rank order. A result the model didn't explain is missing"
    )
