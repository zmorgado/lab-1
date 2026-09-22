"""Carga de configuracion del servicio de tags por LLM (#7).

Mismo contrato que `config.py` del proxy (#3): la credencial se resuelve al
arrancar, vive solo del lado del servidor y nunca viaja al bundle del cliente.
Si falta, el proceso muere ahi con un mensaje que dice que hacer, y no con un
KeyError a mitad del primer request.

Vive en su propio modulo y no adentro de `config.py` para no chocar con #3
mientras esta en review. Cuando los dos esten en main, `GeminiSettings` se
puede plegar adentro de `Settings` sin tocar a quien lo usa.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from dotenv import dotenv_values

from code_search_proxy.constants.app_constants import (
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    GEMINI_API_KEY_ENV,
    GEMINI_MODEL_ENV,
    GEMINI_TIMEOUT_ENV,
)

# backend/.env, al lado del pyproject: la misma convencion que el proxy (#3).
BACKEND_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"
# La raiz del repo tambien se mira, porque la key ya estaba ahi antes de que #3
# fijara la convencion. backend/.env gana si define la misma variable.
ROOT_ENV_FILE = BACKEND_ENV_FILE.parent.parent / ".env"
DEFAULT_ENV_FILES: tuple[Path, ...] = (ROOT_ENV_FILE, BACKEND_ENV_FILE)

# Prosa que lee el operador en la terminal: en ingles, como el resto de la
# documentacion de arranque (BACKEND.md).
MISSING_CREDENTIAL_MESSAGE = (
    f"{GEMINI_API_KEY_ENV} is not configured.\n"
    "\n"
    "The tag service cannot start without a credential: it calls the Gemini\n"
    "API on every extraction. Either of these works:\n"
    "\n"
    f"    export {GEMINI_API_KEY_ENV}=...\n"
    f'    echo "{GEMINI_API_KEY_ENV}=..." >> backend/.env\n'
    "\n"
    "Get a free key at https://aistudio.google.com/apikey (no card needed).\n"
    "See BACKEND.md."
)


class GeminiConfigError(RuntimeError):
    """La configuracion del servicio de tags no se puede resolver."""


class MissingGeminiKeyError(GeminiConfigError):
    """La API key de Gemini no esta configurada: el servicio no puede arrancar."""


@dataclass(frozen=True)
class GeminiSettings:
    """Configuracion del servicio de tags resuelta al arranque."""

    # repr=False para que la key no aparezca en un traceback ni en un log
    api_key: str = field(repr=False)
    model: str = DEFAULT_MODEL
    timeout: float = DEFAULT_TIMEOUT_SECONDS


def load_gemini_settings(
    environ: Mapping[str, str] | None = None,
    env_files: Sequence[Path] | None = None,
) -> GeminiSettings:
    """Arma los GeminiSettings desde el entorno, con los .env como respaldo.

    Recibe el mapping por parametro (y no lee os.environ directo) para que los
    tests puedan pasar un entorno armado sin tocar el proceso, igual que
    `load_settings` en #3.
    """
    environment = os.environ if environ is None else environ
    paths = DEFAULT_ENV_FILES if env_files is None else env_files

    source: dict[str, str] = {}
    for path in paths:
        if path.is_file():
            source.update(
                {key: value for key, value in dotenv_values(path).items() if value}
            )
    # El entorno real pisa a los archivos: un export puntual gana sobre el .env
    source.update(environment)

    # Vacio y ausente son el mismo caso: un '.env' con 'GEMINI_API_KEY=' define
    # la variable pero no aporta credencial.
    api_key = source.get(GEMINI_API_KEY_ENV, "").strip()
    if not api_key:
        raise MissingGeminiKeyError(MISSING_CREDENTIAL_MESSAGE)

    model = source.get(GEMINI_MODEL_ENV, "").strip() or DEFAULT_MODEL
    timeout = _timeout_from(source.get(GEMINI_TIMEOUT_ENV))

    return GeminiSettings(api_key=api_key, model=model, timeout=timeout)


def _timeout_from(raw: str | None) -> float:
    """Traduce GEMINI_TIMEOUT a segundos.

    Un valor invalido es un error de configuracion explicito y no un
    ValueError pelado desde el constructor del cliente: el operador escribio
    algo que no es un numero y tiene que enterarse al arrancar.
    """
    if raw is None or not raw.strip():
        return DEFAULT_TIMEOUT_SECONDS

    try:
        timeout = float(raw)
    except ValueError as error:
        raise GeminiConfigError(
            f"{GEMINI_TIMEOUT_ENV} must be a number of seconds, got {raw!r}."
        ) from error

    if timeout <= 0:
        raise GeminiConfigError(
            f"{GEMINI_TIMEOUT_ENV} must be greater than zero, got {raw!r}."
        )
    return timeout
