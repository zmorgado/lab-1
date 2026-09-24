"""Endpoint HTTP del servicio de tags (#7).

Expone `GeminiTagService` como router de FastAPI, con la misma forma que el
proxy (#3): el servicio se arma una vez en el lifespan y los handlers lo
reciben ya construido, la credencial no sale del server, y los errores salen
por un exception handler y no por un try/except en cada ruta.

Esta en su propio modulo, y no adentro de `app.py`, para no chocar con #3
mientras esta en review. Cuando los dos esten en main, `create_app` suma dos
lineas:

    app.include_router(create_tags_router(tag_service))
    app.add_exception_handler(LlmTagError, handle_llm_tag_error)

y `create_tags_app` de aca abajo se puede borrar.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Body, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from code_search_proxy.constants.app_constants import (
    DEFAULT_MAX_QUERY_TAGS,
    ERROR_SOURCE_NOT_TEXT,
    MAX_QUERY_LENGTH,
    MAX_SOURCE_CHARS,
    QUERY_TIERS,
    TIER_ORDER,
)
from code_search_proxy.contracts.tags_set import TagSet
from code_search_proxy.errors.llm_tag_error import LlmTagError
from code_search_proxy.llm_config import GeminiSettings, load_gemini_settings
from code_search_proxy.llm_tags import GeminiTagService

# El frontend corre en el dev server de Vite
DEV_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")

# Tope defensivo del lado del server: el snippet se trunca a MAX_SOURCE_CHARS
# antes de salir, pero recibir megabytes para tirarlos es trabajo al pedo.
MAX_UPLOAD_BYTES = MAX_SOURCE_CHARS * 4


class TagsRequest(BaseModel):
    """Lo que manda el frontend: el snippet pegado, y nada mas si no quiere."""

    source: str = Field(description="The pasted snippet or whole file, as text")
    language: str | None = Field(
        default=None,
        description=(
            "Optional. GitHub's spelling ('Python', 'Jupyter Notebook'). When "
            "given, the model does not have to infer it, which is where it "
            "mostly errs on short snippets."
        ),
    )
    filename: str | None = Field(
        default=None, description="Optional. Helps the model pin the language"
    )
    max_query_tags: int | None = Field(
        default=DEFAULT_MAX_QUERY_TAGS,
        ge=1,
        description=(
            "How many tags the suggested query may AND together. Null means no "
            "cap, which is almost always the wrong answer: see 'query' below."
        ),
    )


class TagsResponse(BaseModel):
    """Todo lo que saco el modelo, sin decidir por el que llama.

    Devuelve las cinco categorias completas *y* la query sugerida: #22 deja que
    el usuario elija tags a mano, asi que el servicio no puede quedarse solo con
    los que usaria el mismo.
    """

    language: str | None = Field(description="Language the model detected, or the one given")
    tags: dict[str, list[str]] = Field(
        description="The five categories, in tier order, cleaned and deduplicated"
    )
    ordered_tags: list[str] = Field(
        description="Every tag flattened into one tier-ordered list, deduplicated"
    )
    suggested: list[str] = Field(
        description=(
            "The model's own pick of the tags most likely to surface a different "
            "file with the same intent, best first. Always a subset of 'tags'. "
            "Meant as the pre-ticked boxes in the tag picker (#22), not as a "
            "decision: the user still chooses"
        )
    )
    query: str = Field(
        description=(
            "A ready-to-use 'q' for GET /api/search/code. Deliberately short: "
            "GitHub ANDs the terms, so a query holding every tag matches nothing"
        )
    )
    query_tags: list[str] = Field(description="The tags that went into 'query', in order")
    query_length: int = Field(description=f"Length of 'query'; the cap is {MAX_QUERY_LENGTH}")
    query_tiers: list[str] = Field(
        description="The categories 'query' draws from; the others are not literal enough"
    )
    model: str = Field(description="The LLM that answered")
    truncated: bool = Field(description="Whether the source was cut at the size ceiling")
    elapsed_ms: int = Field(description="Round trip to the provider")


def _to_response(
    tags: TagSet,
    *,
    model: str,
    truncated: bool,
    elapsed_ms: int,
    max_query_tags: int | None,
) -> TagsResponse:
    return TagsResponse(
        language=tags.language,
        tags=tags.as_dict(),
        ordered_tags=tags.ordered_tags(),
        suggested=list(tags.suggested),
        query=tags.to_query(max_tags=max_query_tags),
        query_tags=tags.query_tags(max_tags=max_query_tags),
        query_length=len(tags.to_query(max_tags=max_query_tags)),
        query_tiers=list(QUERY_TIERS),
        model=model,
        truncated=truncated,
        elapsed_ms=elapsed_ms,
    )


async def handle_llm_tag_error(_: Request, error: LlmTagError) -> Response:
    """El unico lugar donde un LlmTagError se vuelve una respuesta HTTP.

    El body lleva un `code` estable y, cuando corresponde, `fallback: "grep"`:
    con eso el cliente decide si sigue con los tags del servicio de grep (#4) o
    si el problema es el snippet y no hay nada que hacer.
    """
    headers = {}
    if error.retry_after is not None:
        headers["Retry-After"] = str(error.retry_after)
    return JSONResponse(
        status_code=error.status_code, content=error.body, headers=headers
    )


def tag_service(request: Request) -> GeminiTagService:
    """El servicio compartido que armo el lifespan."""
    service = getattr(request.app.state, "tags", None)
    if service is None:
        # Pasa si se instancia TestClient sin el 'with': el lifespan no corrio y
        # el AttributeError pelado de Starlette no dice por que
        raise RuntimeError(
            "The tag service is not initialised: the app was used without its "
            "lifespan. With TestClient, use it as a context manager "
            "('with TestClient(app) as client')."
        )
    return service


def create_tags_router(service: GeminiTagService | None = None) -> APIRouter:
    """Arma el router. Sin `service`, cada request toma el del app.state.

    Las dos formas existen porque #3 arma su cliente en el lifespan y aca
    conviene poder inyectar uno ya hecho desde un test.
    """
    router = APIRouter(prefix="/api", tags=["tags"])

    def resolve(request: Request) -> GeminiTagService:
        return service if service is not None else tag_service(request)

    async def extract(
        request: Request,
        source: str,
        language: str | None,
        filename: str | None,
        max_query_tags: int | None,
    ) -> TagsResponse:
        resolved = resolve(request)
        truncated = len(source) > MAX_SOURCE_CHARS
        started = time.monotonic()
        tags = await resolved.extract(source, language=language, filename=filename)
        return _to_response(
            tags,
            model=resolved.model,
            truncated=truncated,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            max_query_tags=max_query_tags,
        )

    @router.post("/tags", response_model=TagsResponse)
    async def extract_tags(request: Request, payload: TagsRequest) -> TagsResponse:
        """Tags de un snippet mandado como JSON. Lo que va a usar el frontend."""
        return await extract(
            request,
            source=payload.source,
            language=payload.language,
            filename=payload.filename,
            max_query_tags=payload.max_query_tags,
        )

    @router.post("/tags/file", response_model=TagsResponse)
    async def extract_tags_from_file(
        request: Request,
        body: Annotated[bytes, Body(media_type="application/octet-stream")],
        filename: Annotated[str | None, Query(description="Name of the uploaded file")] = None,
        language: Annotated[str | None, Query(description="GitHub's spelling of the language")] = None,
        max_query_tags: Annotated[int | None, Query(ge=1)] = DEFAULT_MAX_QUERY_TAGS,
    ) -> TagsResponse:
        """Tags de un archivo mandado como cuerpo crudo.

            curl -X POST --data-binary @file.py \\
                 'http://127.0.0.1:8001/api/tags/file?filename=file.py'

        El archivo viaja como body y no como multipart a proposito: multipart
        obligaria a sumar `python-multipart`, y un solo archivo por request no
        necesita el sobre.
        """
        if len(body) > MAX_UPLOAD_BYTES:
            raise LlmTagError(
                f"File is too large: the ceiling is {MAX_UPLOAD_BYTES:,} bytes.",
                code=ERROR_SOURCE_NOT_TEXT,
                status_code=413,
            )

        try:
            source = body.decode("utf-8")
        except UnicodeDecodeError as error:
            # Mismo criterio que el proxy con los blobs de GitHub: si no es
            # texto UTF-8 no hay snippet que mandarle al modelo.
            raise LlmTagError(
                "File is not decodable UTF-8 text.",
                code=ERROR_SOURCE_NOT_TEXT,
                status_code=422,
            ) from error

        return await extract(
            request,
            source=source,
            language=language,
            filename=filename,
            max_query_tags=max_query_tags,
        )

    return router


def create_tags_app(settings: GeminiSettings | None = None) -> FastAPI:
    """App suelta para correr solo esta etapa mientras #3 esta en review.

    Recibe Settings ya resueltos para que los tests no toquen el entorno, igual
    que `create_app` en #3.
    """
    resolved = settings if settings is not None else load_gemini_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Un solo cliente para todo el proceso: comparte el pool de conexiones
        async with GeminiTagService(resolved) as service:
            app.state.tags = service
            yield

    app = FastAPI(
        title="LAB #1 LLM tag service",
        description="Extracts the five tag categories from a code snippet.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(DEV_ORIGINS),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=["Retry-After"],
    )

    app.add_exception_handler(LlmTagError, handle_llm_tag_error)
    app.include_router(create_tags_router())

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "tiers": ",".join(TIER_ORDER)}

    return app


def main() -> None:
    """Entrypoint: `uv run llm-tag-service`.

    Resuelve la config al arrancar, asi que si falta la key el proceso muere
    aca y no en el primer request. Puerto 8001 para no pelear con el proxy de
    #3, que toma el 8000.
    """
    import os
    import sys

    import uvicorn

    from code_search_proxy.llm_config import GeminiConfigError

    try:
        app = create_tags_app()
    except GeminiConfigError as error:
        # Sin traceback: lo que importa es el mensaje accionable
        print(f"\n{error}\n", file=sys.stderr)
        raise SystemExit(1) from error

    uvicorn.run(
        app,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", 8001)),
    )
