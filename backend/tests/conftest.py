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

# La forma real que devuelve search/code (docs/research/tests.md), sin los campos
# que el proxy no toca. Los nombres son inventados a proposito: nada de repos
# reales, menos todavia privados, en una fixture que se commitea.
#
# Los dos items comparten el mismo 'sha': es el caso real del research (el mismo
# blob aparece en varios repos) y lo que #8 tiene que deduplicar. El segundo es
# privado, que es lo que #8 tiene que excluir.
SEARCH_BODY = {
    "total_count": 2,
    "incomplete_results": False,
    "items": [
        {
            "name": "document_ai.py",
            "path": "app/services/document_ai.py",
            "sha": "c94096de9cefc0fa90434a3b65d043540e5b120e",
            "repository": {"full_name": "example-org/public-sample", "private": False},
        },
        {
            "name": "document_ai.py",
            "path": "app/services/document_ai.py",
            "sha": "c94096de9cefc0fa90434a3b65d043540e5b120e",
            "repository": {"full_name": "example-org/private-sample", "private": True},
        },
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
def isolate_from_local_credentials(monkeypatch, tmp_path):
    """Aisla la suite de las credenciales de la maquina.

    load_settings busca el token en backend/.env y despues en el 'gh' CLI. Las
    dos cosas existen en la maquina de quien desarrolla, asi que sin aislar, los
    tests de 'falta la credencial' agarran una de verdad y pasan en verde sin
    probar nada. El resultado no puede depender del setup local.

    Un test que quiera el fallback de 'gh' pisa read_gh_cli_token el mismo.
    """
    monkeypatch.setattr(
        "code_search_proxy.config.DEFAULT_ENV_FILE", tmp_path / "nonexistent.env"
    )
    monkeypatch.setattr("code_search_proxy.config.read_gh_cli_token", lambda: None)
