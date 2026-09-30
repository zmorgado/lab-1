"""Lado HTTP del servicio de tags (#7).

La dependencia, los modelos y el handler de errores. La ruta se cuelga en
`create_app()` y el servicio se arma en su lifespan, al lado de GitHubClient.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .llm_tags import GeminiTagService, LlmTagError


def tag_service(request: Request) -> GeminiTagService:
    """El servicio de tags que armo el lifespan."""
    service = getattr(request.app.state, "tags", None)
    if service is None:
        # Mismo caso que github_client: TestClient sin el 'with'
        raise RuntimeError(
            "The tag service is not initialised: the app was used without its "
            "lifespan. With TestClient, use it as a context manager "
            "('with TestClient(app) as client')."
        )
    return service


TagsDep = Annotated[GeminiTagService, Depends(tag_service)]


class TagsRequest(BaseModel):
    source: str = Field(description="The pasted snippet, as text")
    language: str | None = Field(
        default=None,
        description="Optional, GitHub's spelling ('Python'). Saves the model inferring it",
    )


class TagsResponse(BaseModel):
    language: str | None
    tags: dict[str, list[str]] = Field(
        description="The five categories, in order: api_calls, data_structures, "
        "paradigm, algorithm, domain_keywords"
    )


async def handle_llm_tag_error(_: Request, error: LlmTagError) -> Response:
    """El code estable y el fallback a grep le dicen al cliente si puede seguir."""
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
    return JSONResponse(status_code=error.status_code, content=error.body, headers=headers)
