"""Aplicacion FastAPI del proxy (#3).

Es un pass-through fino: recibe una query ya armada, le pega la credencial y
devuelve lo que contesto GitHub. No arma queries (eso es #19) ni reformatea
resultados (eso es #8). Lo unico que agrega son los headers de rate limit, que
son la unica senal de cuanto queda del presupuesto compartido.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncIterator

from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from .config import Settings, load_settings
from .github import GitHubClient, GitHubError, RateLimit

# 'owner/name', el formato que devuelve search/code en repository.full_name
REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")

# El frontend corre en el dev server de Vite
DEV_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def github_client(request: Request) -> GitHubClient:
    """El cliente compartido que armo el lifespan."""
    client = getattr(request.app.state, "github", None)
    if client is None:
        # Pasa si se instancia TestClient sin el 'with': el lifespan no corrio y
        # el AttributeError pelado de Starlette no dice por que
        raise RuntimeError(
            "El cliente de GitHub no esta inicializado: la app se uso sin su "
            "lifespan. Con TestClient hay que usarlo como context manager "
            "('with TestClient(app) as client')."
        )
    return client


# A nivel de modulo y no adentro de create_app: con 'from __future__ import
# annotations' las anotaciones son strings, y FastAPI las resuelve contra los
# globals del modulo. Una funcion anidada no esta ahi, asi que el parametro
# terminaria tratado como query param en vez de como dependencia.
GitHubDep = Annotated[GitHubClient, Depends(github_client)]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Arma la app. Recibe Settings ya resueltos para que los tests no toquen el entorno."""
    resolved = settings if settings is not None else load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Un solo cliente para todo el proceso: comparte el pool de conexiones
        async with GitHubClient(resolved) as github:
            app.state.github = github
            yield

    app = FastAPI(
        title="LAB #1 code-search proxy",
        description="Proxy autenticado de busqueda de codigo y fetch de archivos en GitHub.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(DEV_ORIGINS),
        allow_methods=["GET"],
        allow_headers=["*"],
        # El frontend necesita poder leer el rate limit, y los headers que no son
        # 'simple' quedan ocultos a menos que se expongan explicitamente
        expose_headers=[
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "X-RateLimit-Used",
            "X-RateLimit-Resource",
        ],
    )

    @app.exception_handler(GitHubError)
    async def handle_github_error(_: Request, error: GitHubError) -> Response:
        # El status y el body de GitHub pasan tal cual: #9 los mapea a codigos estables
        return JSONResponse(
            status_code=error.status_code,
            content=error.body,
            headers=_rate_limit_headers(error.rate_limit),
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/search/code")
    async def search_code(
        github: GitHubDep,
        q: Annotated[str, Query(min_length=1, description="Query de busqueda de GitHub")],
        per_page: Annotated[int | None, Query(ge=1, le=100)] = None,
        page: Annotated[int | None, Query(ge=1)] = None,
    ) -> Response:
        if not q.strip():
            return _invalid("q no puede estar vacio")

        result = await github.search_code(q=q, per_page=per_page, page=page)
        return JSONResponse(
            content=result.body, headers=_rate_limit_headers(result.rate_limit)
        )

    @app.get("/api/contents", response_class=PlainTextResponse)
    async def get_file_contents(
        github: GitHubDep,
        repo: Annotated[str, Query(description="'owner/name', como en repository.full_name")],
        path: Annotated[str, Query(description="Ruta del archivo dentro del repo")],
        ref: Annotated[str, Query(description="Rama, tag o sha del commit")],
    ) -> Response:
        # El path viaja como query param, no en la ruta, asi que las barras de un
        # path anidado no pelean con el ruteo
        if not REPO_PATTERN.match(repo):
            return _invalid("repo tiene que tener el formato 'owner/name'")

        if not path.strip() or ".." in path.split("/"):
            return _invalid("path no es una ruta valida dentro del repo")

        if not ref.strip():
            return _invalid("ref no puede estar vacio")

        result = await github.get_file_contents(repo=repo, path=path.lstrip("/"), ref=ref)
        return PlainTextResponse(
            content=result.body,
            headers=_rate_limit_headers(result.rate_limit),
        )

    return app


def _invalid(message: str) -> JSONResponse:
    """422, el mismo status que usa FastAPI para un query param invalido."""
    return JSONResponse(status_code=422, content={"message": message})


def _rate_limit_headers(rate_limit: RateLimit | None) -> dict[str, str]:
    """Los X-RateLimit-* de GitHub, listos para reenviar.

    Se reenvian en vez de meterlos en el body para que la respuesta de busqueda
    siga siendo la de GitHub sin tocar.
    """
    if rate_limit is None:
        return {}

    values: dict[str, Any] = {
        "X-RateLimit-Limit": rate_limit.limit,
        "X-RateLimit-Remaining": rate_limit.remaining,
        "X-RateLimit-Reset": rate_limit.reset,
        "X-RateLimit-Used": rate_limit.used,
        "X-RateLimit-Resource": rate_limit.resource,
    }

    return {name: str(value) for name, value in values.items() if value is not None}
