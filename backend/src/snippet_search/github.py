"""Cliente HTTP contra la API de GitHub (#3).

Dos operaciones, las dos con la misma credencial y el mismo presupuesto de rate
limit: buscar codigo y traer el contenido de un archivo candidato. El cliente no
arma queries ni reformatea resultados — de eso se encargan #19 y #8.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Final, Generic, TypeVar

import httpx

from .config import Settings

# Version de la API fijada a mano: sin este header GitHub sirve la version por
# defecto, que puede cambiar debajo nuestro
GITHUB_API_VERSION = "2022-11-28"

REQUEST_TIMEOUT_SECONDS = 30.0

# Arriba de 1MB la API de contents no manda el blob inline (encoding 'none')
LARGE_FILE_STATUS = 413
UNUSABLE_CONTENT_STATUS = 415
UPSTREAM_UNREACHABLE_STATUS = 502

# No aparece en texto y si en cualquier binario
NUL_BYTE = b"\x00"

# Codigos estables de error (#9). Salen del status, nunca del texto que manda
# GitHub: esa prosa puede cambiar sin aviso. El frontend traduce el code a la
# copy que ve el usuario.
ERROR_UNAUTHENTICATED: Final = "unauthenticated"
ERROR_RATE_LIMITED: Final = "rate_limited"
ERROR_QUERY_INVALID: Final = "query_invalid"
ERROR_UPSTREAM_UNAVAILABLE: Final = "upstream_unavailable"
# El archivo existe pero no se puede usar como fuente (directorio, binario,
# demasiado grande): no es una falla de GitHub ni algo que se arregle en la query
ERROR_CONTENT_UNUSABLE: Final = "content_unusable"

ERROR_MESSAGES: Final[dict[str, str]] = {
    ERROR_UNAUTHENTICATED: (
        "The GitHub credential is missing or was rejected. This is a "
        "configuration problem on the service's side, not the user's query."
    ),
    ERROR_RATE_LIMITED: (
        "GitHub's shared search budget is exhausted. Wait a moment and try again."
    ),
    ERROR_QUERY_INVALID: (
        "GitHub rejected the search query. Change the tags or the snippet and try again."
    ),
    ERROR_UPSTREAM_UNAVAILABLE: (
        "GitHub could not be reached or is unavailable. Try again in a while."
    ),
    ERROR_CONTENT_UNUSABLE: "The file could not be read as source code.",
}

T = TypeVar("T")


@dataclass(frozen=True)
class RateLimit:
    """Presupuesto de rate limit reportado por GitHub en los headers.

    El token es uno solo para todos los usuarios, asi que este presupuesto es
    compartido: es la unica senal que tiene el resto del sistema para saber
    cuanto queda.
    """

    limit: int | None = None
    remaining: int | None = None
    reset: int | None = None
    used: int | None = None
    resource: str | None = None
    # Solo viene en el limite secundario (403/429), y es la unica pista de
    # cuanto hay que esperar
    retry_after: int | None = None

    @classmethod
    def from_headers(cls, headers: httpx.Headers) -> "RateLimit | None":
        """Lee los X-RateLimit-* de una respuesta, o None si no vinieron."""

        def number(name: str) -> int | None:
            raw = headers.get(f"x-ratelimit-{name}")
            if raw is None:
                return None
            try:
                return int(raw)
            except ValueError:
                # Un header malformado no puede tumbar un request que anduvo
                return None

        resource = headers.get("x-ratelimit-resource")
        values = {name: number(name) for name in ("limit", "remaining", "reset", "used")}

        retry_after = headers.get("retry-after")
        try:
            values["retry_after"] = None if retry_after is None else int(retry_after)
        except ValueError:
            # Retry-After tambien admite una fecha HTTP; no la traducimos
            values["retry_after"] = None

        if resource is None and all(value is None for value in values.values()):
            return None

        return cls(resource=resource, **values)


@dataclass(frozen=True)
class GitHubResponse(Generic[T]):
    """Lo que devolvio GitHub, junto con el rate limit que informo al hacerlo."""

    body: T
    rate_limit: RateLimit | None = None


class GitHubError(Exception):
    """GitHub rechazo el request, o no se lo pudo alcanzar.

    El `code` es estable y sale del status (#9); el `body` original se conserva
    para diagnostico, pero no viaja al cliente.
    """

    def __init__(
        self,
        status_code: int,
        body: Any,
        rate_limit: RateLimit | None = None,
    ) -> None:
        self.status_code = status_code
        self.body = body
        self.rate_limit = rate_limit
        self.code = error_code(status_code)
        super().__init__(f"GitHub responded {status_code} ({self.code}): {body!r}")

    @property
    def message(self) -> str:
        """La copy estable del code, en ingles como el resto de la API."""
        return ERROR_MESSAGES[self.code]

    @property
    def as_body(self) -> dict[str, str]:
        """El cuerpo JSON del error, con la misma forma que el resto del proxy."""
        return {"code": self.code, "message": self.message}


def error_code(status_code: int) -> str:
    """El code estable que le corresponde a un status de GitHub.

    No mira el body: GitHub devuelve 403 tanto por rate limit primario como por
    secundario, y en esta API eso es lo que significa casi siempre. Una
    credencial rechazada es 401; si falta del todo, el servicio no arranca.
    """
    if status_code in (LARGE_FILE_STATUS, UNUSABLE_CONTENT_STATUS):
        return ERROR_CONTENT_UNUSABLE
    if status_code == 401:
        return ERROR_UNAUTHENTICATED
    if status_code in (403, 429):
        return ERROR_RATE_LIMITED
    if status_code in (400, 422):
        return ERROR_QUERY_INVALID
    return ERROR_UPSTREAM_UNAVAILABLE


class GitHubClient:
    """Cliente async sobre httpx. Se usa como context manager."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=settings.github_api_url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search_code(
        self, q: str, per_page: int | None = None, page: int | None = None
    ) -> GitHubResponse[Any]:
        """Corre una busqueda en search/code y devuelve el body tal cual vino."""
        params: dict[str, Any] = {"q": q}
        if per_page is not None:
            params["per_page"] = per_page
        if page is not None:
            params["page"] = page

        response = await self._get("/search/code", params=params)
        return GitHubResponse(body=response.json(), rate_limit=RateLimit.from_headers(response.headers))

    async def get_file_contents(self, repo: str, path: str, ref: str) -> GitHubResponse[str]:
        """Trae el contenido de un archivo, ya decodificado a texto.

        search/code devuelve repo, path y sha pero no el codigo, y la etapa de
        AST necesita el archivo real.
        """
        response = await self._get(
            f"/repos/{repo}/contents/{path}", params={"ref": ref}
        )
        rate_limit = RateLimit.from_headers(response.headers)
        payload = response.json()

        if not isinstance(payload, dict):
            # Un directorio devuelve una lista; no hay archivo que parsear
            raise GitHubError(
                UNUSABLE_CONTENT_STATUS,
                {"message": f"'{path}' is a directory, not a file"},
                rate_limit,
            )

        if payload.get("encoding") != "base64":
            # 'none' es lo que manda GitHub cuando el blob pasa el limite de 1MB
            raise GitHubError(
                LARGE_FILE_STATUS,
                {
                    "message": (
                        f"'{path}' is not returned inline by the contents API "
                        f"(encoding: {payload.get('encoding')!r}); it is too large"
                    )
                },
                rate_limit,
            )

        try:
            # GitHub parte el base64 con saltos de linea cada 60 chars
            raw = base64.b64decode(payload.get("content", ""), validate=False)
        except binascii.Error as error:
            # Base64 roto es corrupcion de arriba, no un archivo binario
            raise GitHubError(
                UNUSABLE_CONTENT_STATUS,
                {"message": f"'{path}' did not arrive as valid base64"},
                rate_limit,
            ) from error

        # Un binario de bytes bajos decodifica como UTF-8 valido, asi que decodificar
        # no alcanza para detectarlo. El byte NUL es la heuristica habitual (la misma
        # que usa git): no aparece en texto, si en cualquier binario.
        if NUL_BYTE in raw:
            raise GitHubError(
                UNUSABLE_CONTENT_STATUS,
                {"message": f"'{path}' looks like a binary file, not source"},
                rate_limit,
            )

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            # No es UTF-8: la etapa de AST no lo puede parsear
            raise GitHubError(
                UNUSABLE_CONTENT_STATUS,
                {"message": f"'{path}' is not decodable UTF-8 text"},
                rate_limit,
            ) from error

        return GitHubResponse(body=text, rate_limit=rate_limit)

    async def _get(self, url: str, params: dict[str, Any]) -> httpx.Response:
        try:
            response = await self._client.get(url, params=params)
        except httpx.HTTPError as error:
            # Timeout, DNS, conexion cortada: para el cliente es un 502, no un 500
            raise GitHubError(
                UPSTREAM_UNREACHABLE_STATUS,
                {"message": f"Could not reach the GitHub API: {error}"},
            ) from error

        if response.is_error:
            raise GitHubError(
                response.status_code,
                _body_of(response),
                RateLimit.from_headers(response.headers),
            )

        return response


def _body_of(response: httpx.Response) -> Any:
    """El body de error de GitHub, o su texto pelado si no es JSON."""
    try:
        return response.json()
    except ValueError:
        return {"message": response.text}
