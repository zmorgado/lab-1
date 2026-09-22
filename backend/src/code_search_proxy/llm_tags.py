"""Servicio de tags por LLM (#7).

Etapa 2 del pipeline: toma un snippet pegado o un archivo entero y devuelve las
cinco categorias de tags de `docs/research/solution-schematics-v2.md`.
Complementa al servicio de grep (#4), no lo reemplaza.

El cliente es async y se usa como context manager, igual que `GitHubClient` en
el proxy (#3): las dos cosas terminan colgadas del mismo lifespan de FastAPI y
un `httpx.Client` sincrono adentro de un `async def` frenaria el event loop los
segundos que tarda el modelo.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from code_search_proxy.constants.app_constants import (
    BACKOFF_BASE_SECONDS,
    DEFAULT_MAX_QUERY_TAGS,
    ERROR_EMPTY_SOURCE,
    ERROR_LLM_FAILED,
    ERROR_LLM_MALFORMED,
    ERROR_LLM_UNAVAILABLE,
    GEMINI_BASE_URL,
    GENERIC_TAGS,
    MAX_ATTEMPTS,
    MAX_QUERY_LENGTH,
    MAX_RETRY_AFTER_SECONDS,
    MAX_SOURCE_CHARS,
    MAX_SUGGESTED_TAGS,
    MAX_TAGS_PER_CATEGORY,
    MIN_TAG_LENGTH,
    RETRYABLE_STATUS,
    TIER_ORDER,
    _SYSTEM_INSTRUCTION,
)
from code_search_proxy.contracts.llm_response_schema import _RESPONSE_SCHEMA
from code_search_proxy.contracts.tags_set import TagSet
from code_search_proxy.errors.llm_tag_error import (
    LlmTagError,
    _error_code,
    _error_message,
    _retry_after_seconds,
    _status_for,
)
from code_search_proxy.llm_config import GeminiSettings


class GeminiTagService:
    """Cliente del servicio de tags por LLM.

    Se acepta un `httpx.AsyncClient` inyectado para que los tests corran contra
    un MockTransport: la suite no toca la red ni consume cuota del free tier.
    """

    def __init__(
        self,
        settings: GeminiSettings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=settings.timeout)

    @property
    def model(self) -> str:
        return self._settings.model

    @property
    def timeout(self) -> float:
        return self._settings.timeout

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
        # Solo se cierra el cliente que armo este servicio; uno inyectado es del
        # que llama y puede seguir usandose para el resto del pipeline.
        if self._owns_client:
            await self._client.aclose()

    async def extract(
        self,
        source: str,
        *,
        language: str | None = None,
        filename: str | None = None,
    ) -> TagSet:
        """Saca los tags de un snippet pegado o de un archivo entero.

        `language` y `filename` son opcionales: si vienen, el modelo no tiene
        que inferir el lenguaje, que es donde mas se equivoca con snippets
        cortos o con sintaxis compartida entre lenguajes.
        """
        if not source or not source.strip():
            raise LlmTagError(
                "Empty source: nothing to extract tags from.",
                code=ERROR_EMPTY_SOURCE,
                status_code=422,
            )

        payload = self._build_payload(source, language=language, filename=filename)
        data = await self._post(payload)
        return self._to_tag_set(data, fallback_language=language)

    # --- interno ---------------------------------------------------------

    def _build_payload(
        self, source: str, *, language: str | None, filename: str | None
    ) -> dict[str, Any]:
        header = []
        if filename:
            header.append(f"Filename: {filename}")
        if language:
            header.append(f"Language: {language}")
        header.append("Code:")
        prompt = "\n".join(header) + "\n\n" + source[:MAX_SOURCE_CHARS]

        return {
            "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                # temperature 0: la extraccion de tags tiene que ser estable;
                # dos corridas sobre el mismo snippet deben dar la misma query.
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
        response = await self._send_with_retries(payload)

        try:
            body = response.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            # Sin `candidates` la causa tipica es un corte por filtro de safety
            # o por maxTokens; `promptFeedback` lo aclara cuando viene.
            raise _malformed(f"Malformed LLM response: {exc}") from exc

        try:
            data = json.loads(text)
        except ValueError as exc:
            raise _malformed(f"LLM returned non-JSON content: {exc}") from exc

        if not isinstance(data, dict):
            raise _malformed("LLM returned JSON that is not an object.")
        return data

    async def _send_with_retries(self, payload: dict[str, Any]) -> httpx.Response:
        """Manda el request, reintentando lo que es transitorio.

        El free tier devuelve 503 "high demand" de forma intermitente: una
        corrida falla despues de un minuto y la siguiente contesta en cinco
        segundos. Sin reintento eso le llega al usuario como si el servicio
        estuviera roto. Un 401/403 no se reintenta: la key no mejora sola.
        """
        url = f"{GEMINI_BASE_URL}/models/{self.model}:generateContent"
        headers = {
            "x-goog-api-key": self._settings.api_key,
            "Content-Type": "application/json",
        }

        last_error: LlmTagError | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await self._client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                # Timeout, DNS, conexion cortada: transitorio, se reintenta.
                last_error = LlmTagError(
                    f"LLM request failed: {exc}",
                    code=ERROR_LLM_UNAVAILABLE,
                    status_code=_status_for(ERROR_LLM_UNAVAILABLE),
                )
            else:
                if response.status_code == 200:
                    return response

                code = _error_code(response.status_code)
                last_error = LlmTagError(
                    _error_message(response),
                    code=code,
                    status_code=_status_for(code),
                    retry_after=_retry_after_seconds(response),
                )
                if response.status_code not in RETRYABLE_STATUS:
                    raise last_error

            if attempt == MAX_ATTEMPTS:
                break
            await asyncio.sleep(_backoff_seconds(attempt, last_error.retry_after))

        if last_error is None:  # pragma: no cover - el loop corre al menos una vez
            last_error = LlmTagError(
                "LLM request failed for an unknown reason.", code=ERROR_LLM_FAILED
            )
        raise last_error

    def _to_tag_set(
        self, data: dict[str, Any], *, fallback_language: str | None
    ) -> TagSet:
        """Normaliza la salida del modelo antes de dejarla entrar al dominio.

        El schema garantiza la forma, no el contenido: igual se filtran vacios,
        se saca el ruido generico, se deduplica y se aplica el tope por
        categoria, porque el modelo ignora el "at most 6" del prompt cuando el
        archivo es grande y cada tag de mas solo recorta resultados.
        """
        categories = {category: _clean(data.get(category)) for category in TIER_ORDER}
        language = data.get("language") or fallback_language
        tags = TagSet(
            **categories,
            language=language.strip() if isinstance(language, str) else None,
        )
        return replace(tags, suggested=_suggested(data.get("suggested"), tags))


def _malformed(message: str) -> LlmTagError:
    return LlmTagError(
        message,
        code=ERROR_LLM_MALFORMED,
        status_code=_status_for(ERROR_LLM_MALFORMED),
    )


def _clean(values: Any, max_tags: int = MAX_TAGS_PER_CATEGORY) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        tag = value.strip()
        key = tag.casefold()
        if len(tag) < MIN_TAG_LENGTH or key in seen or key in GENERIC_TAGS:
            continue
        seen.add(key)
        cleaned.append(tag)
        if len(cleaned) >= max_tags:
            break
    return tuple(cleaned)


def _suggested(values: Any, tags: TagSet) -> tuple[str, ...]:
    """Valida la pre-seleccion del modelo contra los tags que el mismo emitio.

    El modelo tiene que elegir *entre* las cinco categorias, no inventar
    strings nuevos: `suggested` es lo que el picker de #22 muestra tildado, y
    un tag que no esta en la lista no tiene casilla que tildar. Se conserva el
    orden del modelo (va de mas a menos distintivo) pero la grafia de la
    categoria, que es la que ve el usuario.

    Si el modelo no devolvio nada usable se cae a los tags de la query, para
    que el picker nunca abra sin nada marcado. No se completa hasta cinco
    cuando el modelo eligio menos: el prompt pide explicitamente que prefiera
    quedarse corto antes que rellenar con ruido.
    """
    canonical = {tag.casefold(): tag for tag in tags.ordered_tags()}

    seen: set[str] = set()
    picked: list[str] = []
    for value in values if isinstance(values, list) else ():
        if not isinstance(value, str):
            continue
        key = value.strip().casefold()
        if key in seen or key not in canonical:
            continue
        seen.add(key)
        picked.append(canonical[key])
        if len(picked) >= MAX_SUGGESTED_TAGS:
            break

    return tuple(picked) or tuple(tags.query_tags(max_tags=MAX_SUGGESTED_TAGS))


def _backoff_seconds(attempt: int, retry_after: int | None) -> float:
    """Cuanto esperar antes del proximo intento.

    Si el proveedor dijo cuanto esperar se le hace caso, con un techo: un
    Retry-After de minutos deja el request colgado, y eso es peor que fallar
    rapido y dejar que el cliente caiga al grep (#4).
    """
    if retry_after is not None:
        return float(min(retry_after, MAX_RETRY_AFTER_SECONDS))
    return BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))


# --- smoke manual --------------------------------------------------------


def _step(message: str) -> None:
    """Una linea de progreso a stderr, con flush.

    Va a stderr y no a stdout para que el resultado (los tags y la query) se
    pueda pipear solo. El flush es necesario: sin el, Python bufferea y no se
    ve nada hasta que el proceso termina, que es justo lo que no sirve cuando
    la llamada al LLM tarda.
    """
    import sys

    print(f"  {message}", file=sys.stderr, flush=True)


async def _run(path: Path, language: str | None) -> int:
    import sys
    import time

    from code_search_proxy.llm_config import GeminiConfigError, load_gemini_settings

    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _step(f"file      {path.resolve()}")
    _step(f"read      {len(source):,} chars, {source.count(chr(10)) + 1} lines")
    if len(source) > MAX_SOURCE_CHARS:
        _step(f"truncated to {MAX_SOURCE_CHARS:,} chars before sending")

    try:
        settings = load_gemini_settings()
    except GeminiConfigError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1

    # La key no se imprime, ni siquiera enmascarada: no hace falta verla para
    # saber que esta cargada, y el stderr de una terminal termina pegado en un
    # issue.
    _step(f"key       loaded ({len(settings.api_key)} chars)")
    _step(f"model     {settings.model}  (timeout {settings.timeout:.0f}s)")
    _step(f"language  {language or 'not given, model will infer it'}")
    _step("sending   waiting for the LLM, this usually takes a few seconds...")

    started = time.monotonic()
    try:
        async with GeminiTagService(settings) as service:
            tags = await service.extract(source, language=language, filename=path.name)
    except LlmTagError as exc:
        elapsed = time.monotonic() - started
        print(f"error after {elapsed:.1f}s [{exc.code}]: {exc}", file=sys.stderr)
        if exc.fallback:
            print(
                f"hint: the pipeline can still run on the {exc.fallback} tags "
                "(#4); this stage complements them, it is not a hard dependency.",
                file=sys.stderr,
            )
        if "timed out" in str(exc):
            # El caso que mas confunde: no es la key ni el codigo, es latencia.
            print(
                "hint: raise the ceiling with GEMINI_TIMEOUT=120, or try a "
                "smaller file first.",
                file=sys.stderr,
            )
        return 1

    elapsed = time.monotonic() - started
    total = len(tags.ordered_tags())
    _step(f"answered  in {elapsed:.1f}s, {total} unique tags across 5 categories")
    _step("")

    for category in TIER_ORDER:
        print(f"{category:>16}: {', '.join(getattr(tags, category)) or '-'}")
    print(f"{'language':>16}: {tags.language or '-'}")
    print(f"{'suggested':>16}: {', '.join(tags.suggested) or '-'}")

    query = tags.to_query()
    in_query = len(tags.query_tags())
    print("")
    print(f"{'q':>16}: {query}")
    print(f"{'length':>16}: {len(query)}/{MAX_QUERY_LENGTH} chars")
    # Lo importante no es cuanto espacio quedo libre sino cuantos terminos se
    # estan AND-eando: ese es el numero que decide si GitHub devuelve algo.
    print(
        f"{'terms in q':>16}: {in_query} of {total} tags "
        f"(top {DEFAULT_MAX_QUERY_TAGS} literal ones; GitHub ANDs them)"
    )
    return 0


def _main(argv: list[str]) -> int:
    """Smoke manual: `uv run python -m code_search_proxy.llm_tags <archivo>`.

    Sirve para ver tags reales contra la API sin levantar el servicio. Los
    tests no lo usan: ahi el transporte es un mock.
    """
    if not argv:
        print("usage: python -m code_search_proxy.llm_tags <file> [language]")
        return 2

    return asyncio.run(_run(Path(argv[0]), argv[1] if len(argv) > 1 else None))


if __name__ == "__main__":  # pragma: no cover
    import sys

    raise SystemExit(_main(sys.argv[1:]))
