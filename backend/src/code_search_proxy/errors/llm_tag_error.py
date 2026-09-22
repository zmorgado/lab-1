"""El unico error que sale del servicio de tags (#7)."""

from __future__ import annotations

from typing import Any

import httpx

from code_search_proxy.constants.app_constants import (
    ERROR_LLM_AUTH,
    ERROR_LLM_FAILED,
    ERROR_LLM_QUOTA,
    ERROR_LLM_UNAVAILABLE,
    FALLBACK_TO_GREP,
)


class LlmTagError(RuntimeError):
    """Falla del servicio de tags: entrada invalida, red, HTTP o respuesta rota.

    Es el unico tipo que sale de este modulo, igual que `getAxiosData` en el
    frontend deja pasar solo `Error`: quien llama no toca httpx ni JSON.

    Lleva `status_code` y `body` como `GitHubError` en el proxy (#3), para que
    el handler de FastAPI sea el mismo de los dos lados. `code` es el
    identificador estable que mira el cliente; el texto del proveedor viaja en
    `message` y puede cambiar cuando quiera.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = ERROR_LLM_FAILED,
        status_code: int = 502,
        retry_after: int | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.retry_after = retry_after
        # El pipeline puede seguir con los tags del grep (#4) salvo que el
        # problema sea el snippet mismo.
        self.fallback = "grep" if code in FALLBACK_TO_GREP else None
        super().__init__(message)

    @property
    def body(self) -> dict[str, Any]:
        """El cuerpo JSON de la respuesta, con la misma forma que usa el proxy."""
        payload: dict[str, Any] = {"code": self.code, "message": str(self)}
        if self.fallback is not None:
            payload["fallback"] = self.fallback
        if self.retry_after is not None:
            payload["retry_after"] = self.retry_after
        return payload


def _retry_after_seconds(response: httpx.Response) -> int | None:
    """El `Retry-After` en segundos, o None si no vino o no es un numero.

    La cabecera tambien admite una fecha HTTP; no la traducimos, igual que el
    cliente de GitHub en #3.
    """
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _error_message(response: httpx.Response) -> str:
    """Desenvuelve el cuerpo de error de Gemini: {"error": {"message": ...}}.

    Mismo rol que `getAxiosData` en el frontend: el detalle util del proveedor
    queda en el mensaje, pero el tipo que ve quien llama es siempre
    LlmTagError.
    """
    detail = ""
    try:
        payload = response.json()
    except ValueError:
        detail = response.text[:200]
    else:
        # El cuerpo de error *deberia* ser un objeto, pero un 502 de un proxy
        # intermedio puede devolver una lista o un string y `.get` explotaria
        # con un AttributeError, que no es LlmTagError y se escaparia del modulo.
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                detail = str(error.get("message", ""))
            elif error is not None:
                detail = str(error)
        else:
            detail = str(payload)[:200]

    status = response.status_code
    if status in (401, 403):
        return f"LLM rejected the API key ({status}): {detail}"
    if status == 429:
        return f"LLM quota exhausted ({status}): {detail}"
    return f"LLM request failed with HTTP {status}: {detail}"


def _error_code(status: int) -> str:
    """El codigo estable que le corresponde a un status de Gemini."""
    if status in (401, 403):
        return ERROR_LLM_AUTH
    if status == 429:
        return ERROR_LLM_QUOTA
    if status >= 500:
        return ERROR_LLM_UNAVAILABLE
    return ERROR_LLM_FAILED


def _status_for(code: str) -> int:
    """El status HTTP con el que el servicio contesta ese codigo.

    A diferencia del proxy (#3), el status de arriba no se reenvia tal cual: un
    401 de Gemini significa que *nuestra* key esta mal, y devolverselo al
    browser haria pensar que el usuario no esta autenticado. Los problemas de
    infraestructura propia salen como 502; solo la cuota viaja como 429, que es
    lo que el cliente necesita distinguir para reintentar mas tarde.
    """
    if code == ERROR_LLM_QUOTA:
        return 429
    if code == ERROR_LLM_UNAVAILABLE:
        return 503
    return 502
