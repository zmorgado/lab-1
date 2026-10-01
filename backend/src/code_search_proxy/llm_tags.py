"""Servicio de tags por LLM (#7).

Etapa 2 del pipeline: toma un snippet pegado y devuelve las cinco categorias de
tags de `docs/research/solution-schematics-v2.md`. Complementa al servicio de
grep (#4), no lo reemplaza: el grep saca lo que el codigo dice literal, y el LLM
lo que el codigo *es*. Que tags entran a la query se decide en #19.

El cliente es async y se usa como context manager, igual que `GitHubClient`:
las dos cosas terminan colgadas del mismo lifespan de FastAPI y un
`httpx.Client` sincrono adentro de un `async def` frenaria el event loop los
segundos que tarda el modelo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Final

import httpx

from .config import Settings

GEMINI_BASE_URL: Final = "https://generativelanguage.googleapis.com/v1beta"

# Orden de las categorias, de la mas literal a la mas descriptiva
CATEGORIES: Final[tuple[str, ...]] = (
    "api_calls",
    "data_structures",
    "paradigm",
    "algorithm",
    "domain_keywords",
)

# El modelo ignora el "at most 6 per category" del prompt cuando el archivo es
# grande, asi que el tope se aplica tambien del lado del codigo.
MAX_TAGS_PER_CATEGORY: Final = 6

MAX_SOURCE_CHARS: Final = 20_000

GEMINI_TIMEOUT_SECONDS: Final = 60.0

# Codigos de error estables para el cliente (#7 AC: "enabling fallback to grep
# extraction"). El texto del proveedor cambia y esta en ingles de Google; esto
# no cambia, y es lo que mira quien llama para decidir si cae al grep (#4).
ERROR_EMPTY_SOURCE: Final = "empty_source"
ERROR_LLM_AUTH: Final = "llm_auth"
ERROR_LLM_QUOTA: Final = "llm_quota_exhausted"
ERROR_LLM_UNAVAILABLE: Final = "llm_unavailable"
ERROR_LLM_MALFORMED: Final = "llm_malformed_response"
ERROR_LLM_FAILED: Final = "llm_request_failed"

_SYSTEM_INSTRUCTION: Final = """\
You describe a code snippet as search tags. A separate regex tool already
extracts whatever is written literally in the code (identifiers, calls,
keywords), so do not limit yourself to that. Your job is what the regex cannot
do: say what the code *is*, including things the source never spells out.

Fill five categories:

- api_calls: the library and builtin calls the code relies on, as written:
  `sorted`, `items`, `train_test_split`.
- data_structures: the data structures the code operates on, by name: `dict`,
  `defaultdict`, `DataFrame`, `heap`.
- paradigm: the programming paradigm or idiom, described in plain words even if
  no keyword names it: `higher-order function`, `comprehension`, `recursion`,
  `lambda`.
- algorithm: what the code does, the way a developer would describe it:
  `sort dict by value`, `binary search`, `memoize`.
- domain_keywords: the problem domain: `ranking`, `pagination`, `checksum`.
- language: the source language in GitHub's spelling (`Python`, `JavaScript`,
  `Jupyter Notebook`, `C++`). Infer it from the code if it was not given.

Rules:
- Never invent an API the snippet does not use or clearly imply.
- At most 6 tags per category, fewer when the snippet is short, most relevant
  first. An empty category is fine.
- Return only the JSON object. No prose, no markdown fences.\
"""

# Schema OpenAPI que Gemini respeta al generar. Con `responseMimeType` en JSON
# la respuesta viene garantizada con esta forma, asi que no hace falta parsear
# markdown ni pedirle al modelo "devolveme JSON y nada mas"
_RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "OBJECT",
    "properties": {
        **{c: {"type": "ARRAY", "items": {"type": "STRING"}} for c in CATEGORIES},
        "language": {"type": "STRING"},
    },
    "required": [*CATEGORIES, "language"],
    "propertyOrdering": [*CATEGORIES, "language"],
}


@dataclass(frozen=True)
class TagSet:
    """Las cinco categorias de la Etapa 2, ya normalizadas y deduplicadas."""

    api_calls: tuple[str, ...] = ()
    data_structures: tuple[str, ...] = ()
    paradigm: tuple[str, ...] = ()
    algorithm: tuple[str, ...] = ()
    domain_keywords: tuple[str, ...] = ()
    language: str | None = None

    def as_dict(self) -> dict[str, list[str]]:
        """Las categorias en orden, para serializar sin perder el orden."""
        return {category: list(getattr(self, category)) for category in CATEGORIES}


class LlmTagError(RuntimeError):
    """Falla del servicio de tags: entrada invalida, red, HTTP o respuesta rota.

    Es el unico tipo que sale de este modulo: quien llama no toca httpx ni JSON.

    Lleva `status_code` y `body` como `GitHubError`, para que el handler de
    FastAPI sea parecido de los dos lados. `code` es el identificador estable que
    mira el cliente; el texto del proveedor viaja en `message` y puede cambiar.

    El status sale del `code` y no del que mando Gemini: un 401 de arriba es
    *nuestra* key, y reenviarlo haria pensar al browser que el usuario no esta
    autenticado. Solo la cuota viaja como 429, para que el cliente reintente.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = ERROR_LLM_FAILED,
        retry_after: int | None = None,
    ) -> None:
        self.code = code
        self.status_code = {
            ERROR_EMPTY_SOURCE: 422,
            ERROR_LLM_QUOTA: 429,
            ERROR_LLM_UNAVAILABLE: 503,
        }.get(code, 502)
        self.retry_after = retry_after
        # El pipeline puede seguir con los tags del grep (#4) salvo que el
        # problema sea el snippet mismo: ahi el grep tampoco tiene que leer
        self.fallback = None if code == ERROR_EMPTY_SOURCE else "grep"
        super().__init__(message)

    @property
    def body(self) -> dict[str, Any]:
        """El cuerpo JSON de la respuesta, con la misma forma que usa el proxy."""
        payload: dict[str, Any] = {"code": self.code, "message": str(self)}
        if self.fallback is not None:
            payload["fallback"] = self.fallback
        return payload


class GeminiTagService:
    """Cliente del servicio de tags por LLM.

    Se acepta un `httpx.AsyncClient` inyectado para que los tests corran contra
    un MockTransport: la suite no toca la red ni consume cuota del free tier.
    """

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(timeout=GEMINI_TIMEOUT_SECONDS)

    async def __aenter__(self) -> "GeminiTagService":
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

    async def extract(self, source: str, *, language: str | None = None) -> TagSet:
        """Saca los tags de un snippet pegado.

        `language` es opcional: si viene, el modelo no tiene que inferir el
        lenguaje, que es donde mas se equivoca con snippets cortos o con
        sintaxis compartida entre lenguajes.
        """
        if not source.strip():
            raise LlmTagError(
                "Empty source: nothing to extract tags from.", code=ERROR_EMPTY_SOURCE
            )

        if not self._settings.gemini_api_key:
            # El LLM es un complemento: sin key el resto del servicio anda y el
            # cliente cae al grep, igual que si el proveedor estuviera caido
            raise LlmTagError(
                "The LLM is not configured: GEMINI_API_KEY is empty.",
                code=ERROR_LLM_UNAVAILABLE,
            )

        payload = self._build_payload(source, language=language)
        data = await self._post(payload)
        return self._to_tag_set(data, fallback_language=language)

    # --- interno ---------------------------------------------------------

    def _build_payload(self, source: str, *, language: str | None) -> dict[str, Any]:
        header = f"Language: {language}\n" if language else ""
        prompt = f"{header}Code:\n\n{source[:MAX_SOURCE_CHARS]}"

        return {
            "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                # temperature 0: la extraccion de tags tiene que ser estable;
                # dos corridas sobre el mismo snippet deben dar los mismos tags.
                "temperature": 0.0,
                "responseMimeType": "application/json",
                "responseSchema": _RESPONSE_SCHEMA,
                # Sacar tags es leer, no razonar: sin thinking la respuesta
                # baja de decenas de segundos a pocos, y no gasta cuota en
                # tokens de pensamiento que nadie lee.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{GEMINI_BASE_URL}/models/{self._settings.gemini_model}:generateContent"
        headers = {"x-goog-api-key": self._settings.gemini_api_key or ""}

        try:
            response = await self._client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            # Timeout, DNS, conexion cortada
            raise LlmTagError(
                f"LLM request failed: {exc}", code=ERROR_LLM_UNAVAILABLE
            ) from exc

        if response.status_code != 200:
            raise LlmTagError(
                f"Gemini answered HTTP {response.status_code}: {response.text[:200]}",
                code=_error_code(response.status_code),
                retry_after=_retry_after_seconds(response),
            )

        try:
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            # Sin `candidates` la causa tipica es un corte por filtro de safety
            # o por maxTokens; `promptFeedback` lo aclara cuando viene.
            raise LlmTagError(
                f"Malformed LLM response: {exc}", code=ERROR_LLM_MALFORMED
            ) from exc

        try:
            data = json.loads(text)
        except ValueError as exc:
            raise LlmTagError(
                f"LLM returned non-JSON content: {exc}", code=ERROR_LLM_MALFORMED
            ) from exc

        if not isinstance(data, dict):
            raise LlmTagError(
                "LLM returned JSON that is not an object.", code=ERROR_LLM_MALFORMED
            )
        return data

    def _to_tag_set(
        self, data: dict[str, Any], *, fallback_language: str | None
    ) -> TagSet:
        """Normaliza la salida del modelo antes de dejarla entrar al dominio.

        El schema garantiza la forma (listas de strings), no el contenido: igual
        se filtran vacios, se deduplica y se aplica el tope por categoria.
        """
        categories = {category: _clean(data.get(category)) for category in CATEGORIES}
        language = data.get("language") or fallback_language
        return TagSet(
            **categories,
            language=language.strip() if isinstance(language, str) else None,
        )


def _clean(values: list[str] | None) -> tuple[str, ...]:
    # dict.fromkeys deduplica conservando el orden del modelo
    unique = dict.fromkeys(tag.strip() for tag in values or () if tag.strip())
    return tuple(unique)[:MAX_TAGS_PER_CATEGORY]


def _retry_after_seconds(response: httpx.Response) -> int | None:
    """El `Retry-After` en segundos, o None si no vino o no es un numero.

    La cabecera tambien admite una fecha HTTP; no la traducimos, igual que el
    cliente de GitHub.
    """
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _error_code(status: int) -> str:
    """El codigo estable que le corresponde a un status de Gemini."""
    if status in (401, 403):
        return ERROR_LLM_AUTH
    if status == 429:
        return ERROR_LLM_QUOTA
    if status >= 500:
        return ERROR_LLM_UNAVAILABLE
    return ERROR_LLM_FAILED

