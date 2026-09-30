"""Entrypoint del servicio (#3).

'uv run code-search-proxy' entra por main(); 'uvicorn code_search_proxy.main:app'
entra por app. Los dos caminos resuelven la config al arrancar, asi que si falta
la credencial el proceso muere ahi y no en el primer request.
"""

from __future__ import annotations

import os
import sys

from fastapi import FastAPI

from .app import create_app
from .config import MissingCredentialError, load_settings

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def _build_app() -> FastAPI:
    """Arma la app, traduciendo una credencial faltante a una salida legible."""
    try:
        return create_app(load_settings())
    except MissingCredentialError as error:
        # Sin traceback: lo que importa es el mensaje accionable
        print(f"\n{error}\n", file=sys.stderr)
        raise SystemExit(1) from error


app = _build_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("HOST", DEFAULT_HOST),
        port=int(os.environ.get("PORT", DEFAULT_PORT)),
    )


if __name__ == "__main__":
    main()
