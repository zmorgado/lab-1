"""Carga de configuracion del proxy (#3).

La credencial vive solo del lado del servidor: se lee del entorno al arrancar y
nunca viaja al bundle del cliente. Si falta, el arranque tiene que reventar con
un mensaje que diga que hacer, no con un KeyError a mitad del primer request.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values

GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
GITHUB_API_URL_ENV = "GITHUB_API_URL"

# backend/.env, al lado del pyproject. Esta gitignoreado: es para desarrollo local
DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"

DEFAULT_GITHUB_API_URL = "https://api.github.com"

MISSING_CREDENTIAL_MESSAGE = (
    f"{GITHUB_TOKEN_ENV} no esta configurado.\n"
    "\n"
    "El proxy no puede arrancar sin credencial: la API de busqueda de codigo de\n"
    "GitHub rechaza los requests anonimos. Exporta un token con scope 'public_repo'\n"
    "antes de levantar el servicio:\n"
    "\n"
    f"    export {GITHUB_TOKEN_ENV}=$(gh auth token)\n"
    "\n"
    "o ponelo en backend/.env (que esta gitignoreado). Ver BACKEND.md."
)


class MissingCredentialError(RuntimeError):
    """El token de GitHub no esta configurado: el servicio no puede arrancar."""


@dataclass(frozen=True)
class Settings:
    """Configuracion del servicio resuelta al arranque."""

    # repr=False para que el token no aparezca en un traceback ni en un log
    github_token: str = field(repr=False)
    github_api_url: str = DEFAULT_GITHUB_API_URL


def load_settings(
    environ: Mapping[str, str] | None = None, env_file: Path | None = None
) -> Settings:
    """Arma los Settings desde el entorno, con backend/.env como respaldo.

    Recibe el mapping por parametro (y no lee os.environ directo) para que los
    tests puedan pasar un entorno armado sin tocar el proceso.
    """
    environment = os.environ if environ is None else environ
    path = DEFAULT_ENV_FILE if env_file is None else env_file

    # El entorno real pisa al archivo: un export puntual gana sobre el .env
    from_file = (
        {key: value for key, value in dotenv_values(path).items() if value is not None}
        if path.is_file()
        else {}
    )
    source: Mapping[str, str] = {**from_file, **environment}

    token = source.get(GITHUB_TOKEN_ENV, "").strip()
    if not token:
        # Vacio y ausente son el mismo caso: un '.env' con 'GITHUB_TOKEN=' define
        # la variable pero no aporta credencial
        raise MissingCredentialError(MISSING_CREDENTIAL_MESSAGE)

    api_url = source.get(GITHUB_API_URL_ENV, "").strip() or DEFAULT_GITHUB_API_URL

    return Settings(github_token=token, github_api_url=api_url.rstrip("/"))
