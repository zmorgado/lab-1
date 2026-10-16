"""Lado HTTP de la busqueda (#4, #8): el request y la respuesta de /api/search.

La ruta se cuelga en `create_app()`; el pipeline vive en `pipeline.py` y no sabe
de HTTP.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .pipeline import MAX_EMBEDDED_SUBTREES
from .results import DEFAULT_MAX_RESULTS
from .tags_api import TagItem


class SearchRequest(BaseModel):
    source: str = Field(description="The pasted snippet, as text")
    language: str = Field(
        default="python", description="Only Python for now; case-insensitive"
    )
    # El techo es lo que llega a UniXcoder: no hay mas resultados que esos
    max_results: int = Field(
        default=DEFAULT_MAX_RESULTS,
        ge=1,
        le=MAX_EMBEDDED_SUBTREES,
        description=f"How many results to return, 1 to {MAX_EMBEDDED_SUBTREES}",
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
