"""Configuracion y fixtures compartidas de la suite.

Asegura que 'src/' este en sys.path antes de importar el paquete.

El paquete se instala editable (src layout), pero eso no alcanza: algunos builds
de python.org (3.12.8 aca) saltean los .pth cuyo nombre arranca con '_'
("Skipping hidden .pth file"), y el editable se instala justamente como
'_editable_impl_code_search_proxy.pth' con la ruta a src/ adentro. Queda
ignorado y el import de code_search_proxy falla aunque el archivo este bien.

Asegurar la ruta aca hace que la suite no dependa de ese detalle del
interprete. Ver BACKEND.md.
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from code_search_proxy.config import Settings  # noqa: E402

SETTINGS = Settings(github_token="ghp_fake", github_api_url="https://api.github.com")

# Recortado de docs/research/tests.md: la forma real, sin los campos que no se tocan
SEARCH_BODY = {
    "total_count": 1,
    "incomplete_results": False,
    "items": [
        {
            "name": "document_ai.py",
            "path": "app/services/document_ai.py",
            "sha": "c94096de9cefc0fa90434a3b65d043540e5b120e",
            "repository": {"full_name": "WeAreNubi/family-bot", "private": True},
        }
    ],
}

# Los valores reales que devuelve la API: el presupuesto de code_search es de 10/min
RATE_LIMIT_HEADERS = {
    "X-RateLimit-Limit": "10",
    "X-RateLimit-Remaining": "9",
    "X-RateLimit-Reset": "1790074284",
    "X-RateLimit-Used": "1",
    "X-RateLimit-Resource": "code_search",
}


@pytest.fixture(autouse=True)
def isolate_from_the_local_env_file(monkeypatch, tmp_path):
    """Aisla la suite de backend/.env.

    load_settings cae a DEFAULT_ENV_FILE cuando no le pasan uno. Con el .env que
    documenta BACKEND.md, los tests de 'falta la credencial' tomaban el token de
    ahi y pasaban en verde sin probar nada. Apuntarlo a una ruta inexistente hace
    que el resultado no dependa de si el que corre la suite tiene .env o no.
    """
    monkeypatch.setattr(
        "code_search_proxy.config.DEFAULT_ENV_FILE", tmp_path / "nonexistent.env"
    )
