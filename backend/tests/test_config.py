import pytest

from code_search_proxy.config import MissingCredentialError, Settings, load_settings


def test_load_settings_reads_the_token_from_the_environment() -> None:
    settings = load_settings({"GITHUB_TOKEN": "ghp_fake"})

    assert settings.github_token == "ghp_fake"


def test_load_settings_fails_loudly_when_the_token_is_missing() -> None:
    # AC: el arranque revienta con un mensaje accionable, no con un KeyError pelado
    with pytest.raises(MissingCredentialError) as excinfo:
        load_settings({})

    message = str(excinfo.value)
    assert "GITHUB_TOKEN" in message
    assert "BACKEND.md" in message


def test_load_settings_treats_a_blank_token_as_missing() -> None:
    # Un .env con 'GITHUB_TOKEN=' define la variable pero no da credencial
    with pytest.raises(MissingCredentialError):
        load_settings({"GITHUB_TOKEN": "   "})


def test_settings_carry_the_github_api_base_url() -> None:
    settings = load_settings({"GITHUB_TOKEN": "ghp_fake"})

    assert settings.github_api_url == "https://api.github.com"


def test_github_api_url_can_be_overridden() -> None:
    # El override existe para apuntar los tests a un servidor falso
    settings = load_settings(
        {"GITHUB_TOKEN": "ghp_fake", "GITHUB_API_URL": "https://ghe.example.com/api/v3"}
    )

    assert settings.github_api_url == "https://ghe.example.com/api/v3"


def test_settings_do_not_leak_the_token_in_their_repr() -> None:
    # El token no puede aparecer en un traceback ni en un log de arranque
    settings = Settings(github_token="ghp_supersecret")

    assert "ghp_supersecret" not in repr(settings)


def test_env_file_values_are_loaded(tmp_path) -> None:
    # El mensaje de arranque ofrece backend/.env como alternativa al export,
    # asi que tiene que funcionar de verdad
    env_file = tmp_path / ".env"
    env_file.write_text("GITHUB_TOKEN=ghp_from_file\n")

    settings = load_settings({}, env_file=env_file)

    assert settings.github_token == "ghp_from_file"


def test_the_real_environment_wins_over_the_env_file(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GITHUB_TOKEN=ghp_from_file\n")

    settings = load_settings({"GITHUB_TOKEN": "ghp_from_env"}, env_file=env_file)

    assert settings.github_token == "ghp_from_env"


def test_a_missing_env_file_is_not_an_error(tmp_path) -> None:
    settings = load_settings({"GITHUB_TOKEN": "ghp_fake"}, env_file=tmp_path / "nope.env")

    assert settings.github_token == "ghp_fake"


def test_env_file_ignores_comments_and_blank_lines(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("# un comentario\n\nGITHUB_TOKEN=ghp_fake\n")

    settings = load_settings({}, env_file=env_file)

    assert settings.github_token == "ghp_fake"


def test_env_file_strips_surrounding_quotes(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('GITHUB_TOKEN="ghp_quoted"\n')

    settings = load_settings({}, env_file=env_file)

    assert settings.github_token == "ghp_quoted"
