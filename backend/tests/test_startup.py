import subprocess
import sys
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parent.parent / "src")

# Arranca el entrypoint en un proceso aparte: importar main con el entorno vacio
# tiene que matar el proceso, y eso no se puede testear adentro del de pytest.
#
# DEFAULT_ENV_FILE se apunta a una ruta inexistente antes de importar main: si no,
# un backend/.env real (el setup que documenta BACKEND.md) da la credencial y los
# tests de "falta la credencial" pasan en verde sin probar nada.
IMPORT_MAIN = (
    "from pathlib import Path;"
    "import code_search_proxy.config as config;"
    "config.DEFAULT_ENV_FILE = Path('/nonexistent/.env');"
    "import code_search_proxy.main"
)


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", IMPORT_MAIN],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": SRC, "PATH": "/usr/bin:/bin", **env},
    )


def test_startup_fails_when_the_credential_is_missing() -> None:
    result = _run({})

    assert result.returncode == 1


def test_startup_failure_names_the_variable_and_how_to_set_it() -> None:
    # AC: el mensaje tiene que ser accionable, no un traceback
    result = _run({})

    assert "GITHUB_TOKEN" in result.stderr
    assert "gh auth token" in result.stderr
    assert "BACKEND.md" in result.stderr


def test_startup_failure_does_not_dump_a_traceback() -> None:
    result = _run({})

    assert "Traceback" not in result.stderr


def test_startup_succeeds_with_a_credential() -> None:
    result = _run({"GITHUB_TOKEN": "ghp_fake"})

    assert result.returncode == 0, result.stderr


def test_a_local_env_file_does_not_mask_the_missing_credential(tmp_path) -> None:
    """Regresion: estos tests pasaban en verde solo si no habia backend/.env.

    Con el .env que documenta BACKEND.md, load_settings tomaba la credencial de
    ahi y el caso 'falta la credencial' no se probaba nunca.
    """
    from code_search_proxy.config import MissingCredentialError, load_settings

    env_file = tmp_path / ".env"
    env_file.write_text("GITHUB_TOKEN=ghp_from_a_local_file\n")

    # Pedir explicitamente 'sin archivo' tiene que fallar aunque exista uno
    with pytest.raises(MissingCredentialError):
        load_settings({}, env_file=tmp_path / "nonexistent.env")
