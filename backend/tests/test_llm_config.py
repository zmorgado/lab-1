"""Tests de la configuracion del servicio de tags (#7).

AC de #7: "API keys sourced from server configuration exclusively". Aca se
prueba de donde sale la key y que el arranque falle con un mensaje accionable
cuando no esta.
"""

from __future__ import annotations

import pytest

from code_search_proxy.constants.app_constants import (
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
)
from code_search_proxy.llm_config import (
    GeminiConfigError,
    MissingGeminiKeyError,
    load_gemini_settings,
)


@pytest.fixture
def env_file(tmp_path):
    """Un .env de mentira, para no depender del de la maquina."""

    def write(contents: str):
        path = tmp_path / ".env"
        path.write_text(contents, encoding="utf-8")
        return [path]

    return write


def test_the_key_comes_from_the_environment(env_file) -> None:
    settings = load_gemini_settings({"GEMINI_API_KEY": "from-env"}, env_files=[])

    assert settings.api_key == "from-env"
    assert settings.model == DEFAULT_MODEL
    assert settings.timeout == DEFAULT_TIMEOUT_SECONDS


def test_the_key_can_come_from_a_dotenv_file(env_file) -> None:
    files = env_file('GEMINI_API_KEY = "from-file"\n')

    settings = load_gemini_settings({}, env_files=files)

    assert settings.api_key == "from-file"


def test_the_environment_wins_over_the_dotenv_file(env_file) -> None:
    files = env_file("GEMINI_API_KEY=from-file\n")

    settings = load_gemini_settings({"GEMINI_API_KEY": "from-env"}, env_files=files)

    # Un export puntual tiene que ganar sobre lo que quedo escrito en el .env.
    assert settings.api_key == "from-env"


def test_the_model_can_be_overridden(env_file) -> None:
    # El bug viejo: GEMINI_MODEL quedaba ignorado porque el default ya era truthy.
    settings = load_gemini_settings(
        {"GEMINI_API_KEY": "k", "GEMINI_MODEL": "gemini-3-pro-preview"}, env_files=[]
    )

    assert settings.model == "gemini-3-pro-preview"


def test_the_timeout_can_be_overridden(env_file) -> None:
    settings = load_gemini_settings(
        {"GEMINI_API_KEY": "k", "GEMINI_TIMEOUT": "120"}, env_files=[]
    )

    assert settings.timeout == 120.0


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_an_invalid_timeout_is_a_config_error_not_a_bare_value_error(value: str) -> None:
    # Antes explotaba con ValueError desde el constructor del cliente, a mitad
    # de camino y sin decir que variable estaba mal.
    with pytest.raises(GeminiConfigError, match="GEMINI_TIMEOUT"):
        load_gemini_settings({"GEMINI_API_KEY": "k", "GEMINI_TIMEOUT": value}, env_files=[])


def test_an_empty_timeout_falls_back_to_the_default() -> None:
    settings = load_gemini_settings(
        {"GEMINI_API_KEY": "k", "GEMINI_TIMEOUT": "  "}, env_files=[]
    )

    assert settings.timeout == DEFAULT_TIMEOUT_SECONDS


def test_a_missing_key_fails_at_startup_with_an_actionable_message() -> None:
    with pytest.raises(MissingGeminiKeyError) as exc:
        load_gemini_settings({}, env_files=[])

    message = str(exc.value)
    assert "GEMINI_API_KEY is not configured" in message
    assert "aistudio.google.com/apikey" in message


def test_an_empty_key_counts_as_missing(env_file) -> None:
    # 'GEMINI_API_KEY=' en un .env define la variable pero no aporta credencial.
    files = env_file("GEMINI_API_KEY=\n")

    with pytest.raises(MissingGeminiKeyError):
        load_gemini_settings({}, env_files=files)


def test_the_key_is_kept_out_of_the_repr() -> None:
    settings = load_gemini_settings({"GEMINI_API_KEY": "super-secret"}, env_files=[])

    # Un traceback o un log no pueden filtrar la credencial.
    assert "super-secret" not in repr(settings)
