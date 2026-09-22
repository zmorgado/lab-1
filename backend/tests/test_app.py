import base64

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from code_search_proxy.app import create_app

from conftest import RATE_LIMIT_HEADERS, SEARCH_BODY, SETTINGS


@pytest.fixture
def client():
    with TestClient(create_app(SETTINGS)) as test_client:
        yield test_client


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@respx.mock
def test_the_endpoint_returns_githubs_body_unchanged(client: TestClient) -> None:
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY, headers=RATE_LIMIT_HEADERS)
    )

    response = client.get("/api/search/code", params={"q": '"foo" language:python'})

    assert response.status_code == 200
    # AC: la respuesta de GitHub vuelve sin tocar
    assert response.json() == SEARCH_BODY


@respx.mock
def test_search_code_forwards_the_rate_limit_headers(client: TestClient) -> None:
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY, headers=RATE_LIMIT_HEADERS)
    )

    response = client.get("/api/search/code", params={"q": '"foo"'})

    # AC: el rate limit de arriba se expone, no se traga
    assert response.headers["x-ratelimit-limit"] == "10"
    assert response.headers["x-ratelimit-remaining"] == "9"
    assert response.headers["x-ratelimit-reset"] == "1790074284"
    assert response.headers["x-ratelimit-resource"] == "code_search"


@respx.mock
def test_search_code_passes_the_query_through(client: TestClient) -> None:
    route = respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY)
    )

    client.get(
        "/api/search/code", params={"q": '"foo" language:python', "per_page": 5, "page": 2}
    )

    params = route.calls.last.request.url.params
    assert params["q"] == '"foo" language:python'
    assert params["per_page"] == "5"
    assert params["page"] == "2"


def test_search_code_requires_a_query(client: TestClient) -> None:
    response = client.get("/api/search/code")

    assert response.status_code == 422


def test_search_code_rejects_a_blank_query(client: TestClient) -> None:
    response = client.get("/api/search/code", params={"q": "   "})

    assert response.status_code == 422


@respx.mock
def test_search_code_relays_githubs_error_status_and_body(client: TestClient) -> None:
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(
            422,
            json={"message": "Validation Failed", "errors": [{"message": "Only 256 chars"}]},
            headers=RATE_LIMIT_HEADERS,
        )
    )

    response = client.get("/api/search/code", params={"q": '"foo"'})

    assert response.status_code == 422
    # El body original de GitHub sobrevive: #9 lo mapea a codigos estables
    assert response.json() == {
        "message": "Validation Failed",
        "errors": [{"message": "Only 256 chars"}],
    }


@respx.mock
def test_rate_limit_headers_survive_an_error(client: TestClient) -> None:
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers=RATE_LIMIT_HEADERS | {"X-RateLimit-Remaining": "0"},
        )
    )

    response = client.get("/api/search/code", params={"q": '"foo"'})

    assert response.status_code == 403
    # Justo cuando mas importa saber cuanto queda
    assert response.headers["x-ratelimit-remaining"] == "0"
    assert response.headers["x-ratelimit-reset"] == "1790074284"


@respx.mock
def test_get_file_contents_returns_plain_source(client: TestClient) -> None:
    encoded = base64.b64encode(b"import os\n\ndef foo():\n    pass\n").decode()
    respx.get(
        "https://api.github.com/repos/octocat/Hello-World/contents/app/main.py"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"content": f"{encoded}\n", "encoding": "base64", "type": "file"},
            headers=RATE_LIMIT_HEADERS,
        )
    )

    response = client.get(
        "/api/contents",
        params={"repo": "octocat/Hello-World", "path": "app/main.py", "ref": "master"},
    )

    assert response.status_code == 200
    assert response.text == "import os\n\ndef foo():\n    pass\n"
    assert response.headers["content-type"].startswith("text/plain")


@respx.mock
def test_get_file_contents_handles_a_nested_path(client: TestClient) -> None:
    # El path llega como query param, asi que las barras no rompen el ruteo
    route = respx.get(
        "https://api.github.com/repos/octocat/Hello-World/contents/a/b/c/deep.py"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"content": base64.b64encode(b"x = 1\n").decode(), "encoding": "base64"},
        )
    )

    response = client.get(
        "/api/contents",
        params={"repo": "octocat/Hello-World", "path": "a/b/c/deep.py", "ref": "main"},
    )

    assert response.status_code == 200
    assert route.called


@respx.mock
def test_get_file_contents_forwards_the_rate_limit(client: TestClient) -> None:
    respx.get("https://api.github.com/repos/octocat/Hello-World/contents/README").mock(
        return_value=httpx.Response(
            200,
            json={"content": base64.b64encode(b"hi").decode(), "encoding": "base64"},
            headers=RATE_LIMIT_HEADERS | {"X-RateLimit-Resource": "core"},
        )
    )

    response = client.get(
        "/api/contents",
        params={"repo": "octocat/Hello-World", "path": "README", "ref": "master"},
    )

    # contents gasta del presupuesto 'core', no del de code_search
    assert response.headers["x-ratelimit-resource"] == "core"


def test_get_file_contents_rejects_a_malformed_repo(client: TestClient) -> None:
    # Sin 'owner/name' el path de GitHub sale mal armado
    response = client.get(
        "/api/contents", params={"repo": "not-a-full-name", "path": "a.py", "ref": "main"}
    )

    assert response.status_code == 422


def test_get_file_contents_rejects_a_path_escaping_the_repo(client: TestClient) -> None:
    response = client.get(
        "/api/contents",
        params={"repo": "octocat/Hello-World", "path": "../../etc/passwd", "ref": "main"},
    )

    assert response.status_code == 422


@respx.mock
def test_get_file_contents_relays_a_missing_file(client: TestClient) -> None:
    respx.get("https://api.github.com/repos/octocat/Hello-World/contents/nope.py").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    response = client.get(
        "/api/contents",
        params={"repo": "octocat/Hello-World", "path": "nope.py", "ref": "main"},
    )

    assert response.status_code == 404


@respx.mock
def test_an_unreachable_github_becomes_a_502(client: TestClient) -> None:
    respx.get("https://api.github.com/search/code").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    response = client.get("/api/search/code", params={"q": '"foo"'})

    assert response.status_code == 502


@respx.mock
def test_the_token_never_reaches_the_client(client: TestClient) -> None:
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY, headers=RATE_LIMIT_HEADERS)
    )

    response = client.get("/api/search/code", params={"q": '"foo"'})

    # AC: la credencial vive solo del lado del servidor
    assert "ghp_fake" not in response.text
    assert "ghp_fake" not in str(response.headers)


def test_using_the_app_without_its_lifespan_says_so() -> None:
    # Sin el 'with', el lifespan no corre y no hay cliente: el error tiene que
    # explicar por que, no ser un AttributeError pelado de Starlette
    bare = TestClient(create_app(SETTINGS))

    with pytest.raises(RuntimeError, match="lifespan"):
        bare.get("/api/search/code", params={"q": '"foo"'})
