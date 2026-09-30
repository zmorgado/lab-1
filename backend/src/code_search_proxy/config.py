"""Carga de configuracion del proxy (#3).

La credencial vive solo del lado del servidor: se lee del entorno al arrancar y
nunca viaja al bundle del cliente. Si falta, el arranque tiene que reventar con
un mensaje que diga que hacer, no con un KeyError a mitad del primer request.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values

GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
GITHUB_API_URL_ENV = "GITHUB_API_URL"

# backend/.env, al lado del pyproject. Esta gitignoreado: es para desarrollo local
DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"

DEFAULT_GITHUB_API_URL = "https://api.github.com"

# 'gh' guarda el token en el keyring del sistema, asi que sacarlo cuesta un
# proceso. Es rapido (~75ms), pero no puede colgar el arranque
GH_TIMEOUT_SECONDS = 5.0

# Prosa que lee el operador en la terminal: en ingles, como el resto de la
# documentacion de arranque (BACKEND.md)
MISSING_CREDENTIAL_MESSAGE = (
    f"{GITHUB_TOKEN_ENV} is not configured.\n"
    "\n"
    "The proxy cannot start without a credential: GitHub's code-search API\n"
    "rejects anonymous requests. Any of these works, in this order:\n"
    "\n"
    f"    export {GITHUB_TOKEN_ENV}=$(gh auth token)\n"
    "    echo \"GITHUB_TOKEN=$(gh auth token)\" >> backend/.env\n"
    "    gh auth login   # then just restart: the CLI token is picked up\n"
    "\n"
    "The token needs the 'public_repo' scope. See BACKEND.md."
)


class MissingCredentialError(RuntimeError):
    """El token de GitHub no esta configurado: el servicio no puede arrancar."""


def read_gh_cli_token() -> str | None:
    """El token del 'gh' CLI, o None si no se lo puede conseguir.

    Ultimo recurso para desarrollo local: en una maquina donde 'gh' ya esta
    logueado no hay que configurar nada. 'gh' no es una dependencia del
    servicio, asi que cualquier falla aca es un None, no una excepcion.
    """
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        # No esta instalado, no es ejecutable, o se colgo
        return None

    if result.returncode != 0:
        # 'gh' instalado pero sin login
        return None

    return result.stdout.strip() or None


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

    # Orden: entorno, backend/.env, y recien ahi el 'gh' CLI. Lo explicito
    # siempre gana sobre lo que haya logueado en la maquina
    token = source.get(GITHUB_TOKEN_ENV, "").strip() or (read_gh_cli_token() or "")
    if not token:
        # Vacio y ausente son el mismo caso: un '.env' con 'GITHUB_TOKEN=' define
        # la variable pero no aporta credencial
        raise MissingCredentialError(MISSING_CREDENTIAL_MESSAGE)

    api_url = source.get(GITHUB_API_URL_ENV, "").strip() or DEFAULT_GITHUB_API_URL

    return Settings(github_token=token, github_api_url=api_url.rstrip("/"))
