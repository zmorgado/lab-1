"""Servicio de tags por LLM (#7, #22).

Etapa 2, parte 2 del pipeline: toma el snippet pegado y los tiers que saco el
AST (#4), y devuelve una sola lista de tags, la mas relevante primero. Cada tag
dice a cual de las tres queries de #19 va y si ya estaba en los tiers o lo sumo
el modelo. Complementa al AST, no lo reemplaza: el merge con lo que edita el
usuario es de #22.

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

from .ast_grep_tags import Tiers
from .config import Settings

GEMINI_BASE_URL: Final = "https://generativelanguage.googleapis.com/v1beta"

# El tipo decide a cual de las tres queries de #19 va el tag
KIND_SYNTACTIC: Final = "syntactic"
KIND_CONCEPTUAL: Final = "conceptual"
KIND_PARADIGM: Final = "paradigm"
KINDS: Final[tuple[str, ...]] = (KIND_SYNTACTIC, KIND_CONCEPTUAL, KIND_PARADIGM)

# De donde salio el tag. Lo decide el codigo comparando con los tiers, no el modelo
SOURCE_SEED: Final = "seed"
SOURCE_LLM: Final = "llm"

# Cada tipo llena una query de 6 tags (#19), asi que mas no sirve. El modelo a
# veces ignora el tope del prompt, por eso se aplica tambien del lado del codigo
MAX_TAGS_PER_KIND: Final = 6

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
You turn a code snippet into tags for GitHub code search, to find functional
clones of it: code that does the same thing, whether it is written the same
way or in another style or library. The search matches text, not meaning: a
tag only finds files that contain it, in code, names or comments.

You get the snippet and the seed tags a parser already pulled out of its AST,
in tiers:
- apis: imported modules and the functions and methods it calls
- structures: the names it defines (functions, classes) and constructs such
  as `lambda`
- domain: words from its docstrings

Return one list of tags that covers both what the code says and what it does.
Keep the seeds that would help find code doing the same thing, drop the ones
that would not, and add what the seeds miss.

Give every tag a kind. The kind decides which search query the tag feeds:
- syntactic: the concrete identifiers, standard methods and container types a
  near-literal copy would share (`sorted`, `items`, `defaultdict`).
- conceptual: the code's goal and domain, in the words programmers write in
  names and comments. Turn the snippet's own names into intent terms and
  synonyms: `rank_dict` -> `sort_by_value`, `ranking`, `top_k`.
- paradigm: other ways to write the same thing. Alternative idioms (`lambda`
  -> `itemgetter`, a loop -> a comprehension or vectorized operations) and
  alternative libraries (`dict` -> `DataFrame`, a hand-written cosine ->
  `cdist` or `cosine_similarity`).

Also return `language`: the source language in GitHub's spelling (`Python`,
`JavaScript`, `Jupyter Notebook`, `C++`). Infer it from the code if it was not
given.

Rules:
- Prefer words that appear in real code over descriptions of it: `itemgetter`
  finds code, `higher-order function` mostly does not.
- Keep tags short: one identifier, or at most three words.
- Skip names every snippet has: `self`, `print`, `len`, `range`, `str`,
  `list`, `dict`.
- Drop imports of modules only one project would have: company-internal or
  project-local packages (`ringr_agents`, `myapp.utils`). No other repository
  contains them. Keep the standard library and well-known public packages
  (`pydantic`, `numpy`).
- When you keep a seed, copy it exactly as given.
- Never invent an API. Add only real ones: those the snippet uses or, as
  `paradigm`, those another implementation of the same thing really uses.
- At most 6 tags per kind, most relevant first: each kind feeds one query,
  and a file has to match every term in it. Fewer when the snippet is short;
  an empty kind is fine.
- Write tags, not queries: no qualifiers such as `language:`. The search
  builds the queries from the list.
- Return only the JSON object. No prose, no markdown fences.\
"""



# Schema OpenAPI que Gemini respeta al generar. Con `responseMimeType` en JSON
# la respuesta viene garantizada con esta forma, asi que no hace falta parsear
# markdown ni pedirle al modelo "devolveme JSON y nada mas"
_RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "OBJECT",
    "properties": {
        "tags": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "tag": {"type": "STRING"},
                    "kind": {"type": "STRING", "format": "enum", "enum": list(KINDS)},
                },
                "required": ["tag", "kind"],
                "propertyOrdering": ["tag", "kind"],
            },
        },
        "language": {"type": "STRING"},
    },
    "required": ["tags", "language"],
    "propertyOrdering": ["tags", "language"],
}


@dataclass(frozen=True)
class Tag:
    """Un tag de la lista: el texto, la query de #19 que alimenta y de donde salio."""

    text: str
    kind: str
    source: str


@dataclass(frozen=True)
class TagSet:
    """La lista de la Etapa 2, ya normalizada: la mas relevante primero."""

    tags: tuple[Tag, ...] = ()
    language: str | None = None

    def as_list(self) -> list[dict[str, str]]:
        """La forma que devuelven /api/tags y /api/search."""
        return [{"tag": t.text, "kind": t.kind, "source": t.source} for t in self.tags]


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

    async def extract(
        self, source: str, *, language: str | None = None, tiers: Tiers | None = None
    ) -> TagSet:
        """Saca los tags de un snippet pegado.

        `tiers` son los tags que ya saco el AST (#4): el modelo se queda con los
        que sirven y suma lo que les falta. Sin tiers trabaja solo con el codigo.

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

        payload = self._build_payload(source, language=language, tiers=tiers)
        data = await self._post(payload)
        return self._to_tag_set(data, tiers=tiers, fallback_language=language)

    # --- interno ---------------------------------------------------------

    def _build_payload(
        self, source: str, *, language: str | None, tiers: Tiers | None
    ) -> dict[str, Any]:
        header = f"Language: {language}\n" if language else ""
        prompt = f"{header}{_seed_lines(tiers)}Code:\n\n{source[:MAX_SOURCE_CHARS]}"

        return {
            "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                # temperature 0: la extraccion de tags tiene que ser estable;
                # dos corridas sobre el mismo snippet deben dar los mismos tags.
                "temperature": 0.0,
                "responseMimeType": "application/json",
                "responseSchema": _RESPONSE_SCHEMA,
                # Sin thinkingConfig a proposito: thinkingBudget lo rechazan con
                # 400 los modelos 3.x (gemini-3.5-flash-lite), y el parametro que
                # lo reemplaza depende del modelo. Cada familia usa su default.
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
        self, data: dict[str, Any], *, tiers: Tiers | None, fallback_language: str | None
    ) -> TagSet:
        """Normaliza la salida del modelo antes de dejarla entrar al dominio.

        El schema garantiza la forma, no el contenido: igual se filtran vacios y
        tipos desconocidos, se deduplica y se aplica el tope por tipo.
        """
        seeds = frozenset(tag.lower() for tag in tiers.ordered()) if tiers else frozenset()
        language = data.get("language") or fallback_language
        return TagSet(
            tags=_clean(data.get("tags"), seeds),
            language=language.strip() if isinstance(language, str) else None,
        )


def _seed_lines(tiers: Tiers | None) -> str:
    """Los tiers como los lee el modelo: un renglon por tier."""
    if tiers is None:
        return ""
    # Solo los tres tiers: `imports` repite parte de `apis` e `is_fallback` es un flag (#22)
    lines = [
        f"- {name}: {', '.join(tags) or '(none)'}"
        for name, tags in (
            ("apis", tiers.apis),
            ("structures", tiers.structures),
            ("domain", tiers.domain),
        )
    ]
    return "Seed tags:\n" + "\n".join(lines) + "\n\n"


def _clean(items: Any, seeds: frozenset[str]) -> tuple[Tag, ...]:
    """Los tags del modelo en su orden, sin vacios, repetidos ni tipos inventados."""
    kept: list[Tag] = []
    seen: set[str] = set()
    per_kind = dict.fromkeys(KINDS, 0)
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        text, kind = item.get("tag"), item.get("kind")
        if not isinstance(text, str) or kind not in KINDS:
            continue
        text = text.strip()
        # 'Sort' y 'sort' cuentan como el mismo tag
        key = text.lower()
        if not text or key in seen or per_kind[kind] == MAX_TAGS_PER_KIND:
            continue
        seen.add(key)
        per_kind[kind] += 1
        kept.append(Tag(text, kind, SOURCE_SEED if key in seeds else SOURCE_LLM))
    return tuple(kept)


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
