import base64

import httpx
import pytest
import respx

from code_search_proxy.github import GitHubClient, GitHubError, RateLimit

from conftest import RATE_LIMIT_HEADERS, SEARCH_BODY, SETTINGS


@pytest.fixture
async def client():
    async with GitHubClient(SETTINGS) as github:
        yield github


@respx.mock
async def test_the_client_returns_githubs_body_unchanged(client: GitHubClient) -> None:
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY, headers=RATE_LIMIT_HEADERS)
    )

    result = await client.search_code(q='"foo" language:python')

    assert result.body == SEARCH_BODY


@respx.mock
async def test_search_code_sends_the_credential_and_the_api_version(
    client: GitHubClient,
) -> None:
    route = respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY)
    )

    await client.search_code(q='"foo"')

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer ghp_fake"
    assert request.headers["accept"] == "application/vnd.github+json"
    assert request.headers["x-github-api-version"] == "2022-11-28"


@respx.mock
async def test_search_code_forwards_the_query_and_paging(client: GitHubClient) -> None:
    route = respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY)
    )

    await client.search_code(q='"foo" language:python', per_page=5, page=2)

    params = route.calls.last.request.url.params
    assert params["q"] == '"foo" language:python'
    assert params["per_page"] == "5"
    assert params["page"] == "2"


@respx.mock
async def test_search_code_surfaces_the_rate_limit(client: GitHubClient) -> None:
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY, headers=RATE_LIMIT_HEADERS)
    )

    result = await client.search_code(q='"foo"')

    assert result.rate_limit == RateLimit(
        limit=10, remaining=9, reset=1790074284, used=1, resource="code_search"
    )


@respx.mock
async def test_rate_limit_is_none_when_github_sends_no_headers(
    client: GitHubClient,
) -> None:
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY)
    )

    result = await client.search_code(q='"foo"')

    assert result.rate_limit is None


@respx.mock
async def test_search_code_raises_with_githubs_own_message(client: GitHubClient) -> None:
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(
            422,
            json={"message": "Validation Failed", "errors": [{"message": "Only 256 chars"}]},
            headers=RATE_LIMIT_HEADERS,
        )
    )

    with pytest.raises(GitHubError) as excinfo:
        await client.search_code(q='"foo"')

    error = excinfo.value
    assert error.status_code == 422
    # El body de GitHub viaja entero: #9 lo va a mapear a codigos de error
    assert error.body == {
        "message": "Validation Failed",
        "errors": [{"message": "Only 256 chars"}],
    }
    # El rate limit se conserva incluso en el camino de error
    assert error.rate_limit is not None
    assert error.rate_limit.remaining == 9


@respx.mock
async def test_get_file_contents_decodes_the_base64_payload(client: GitHubClient) -> None:
    # GitHub parte el base64 con saltos de linea cada 60 chars
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

    result = await client.get_file_contents(
        repo="octocat/Hello-World", path="app/main.py", ref="master"
    )

    assert result.body == "import os\n\ndef foo():\n    pass\n"


@respx.mock
async def test_get_file_contents_sends_the_ref(client: GitHubClient) -> None:
    route = respx.get(
        "https://api.github.com/repos/octocat/Hello-World/contents/README"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"content": base64.b64encode(b"hi").decode(), "encoding": "base64", "type": "file"},
        )
    )

    await client.get_file_contents(repo="octocat/Hello-World", path="README", ref="master")

    assert route.calls.last.request.url.params["ref"] == "master"


@respx.mock
async def test_get_file_contents_rejects_a_directory(client: GitHubClient) -> None:
    # Un path de directorio devuelve una lista JSON, no un archivo
    respx.get("https://api.github.com/repos/octocat/Hello-World/contents/app").mock(
        return_value=httpx.Response(200, json=[{"name": "main.py", "type": "file"}])
    )

    with pytest.raises(GitHubError) as excinfo:
        await client.get_file_contents(repo="octocat/Hello-World", path="app", ref="master")

    assert excinfo.value.status_code == 415


@respx.mock
async def test_get_file_contents_rejects_a_binary_file(client: GitHubClient) -> None:
    # Un blob no decodificable como UTF-8 no le sirve a la etapa de AST
    respx.get("https://api.github.com/repos/octocat/Hello-World/contents/logo.png").mock(
        return_value=httpx.Response(
            200,
            json={"content": base64.b64encode(b"\x89PNG\r\n\x1a\n\xff").decode(), "encoding": "base64", "type": "file"},
        )
    )

    with pytest.raises(GitHubError) as excinfo:
        await client.get_file_contents(
            repo="octocat/Hello-World", path="logo.png", ref="master"
        )

    assert excinfo.value.status_code == 415


@respx.mock
async def test_get_file_contents_rejects_a_file_too_large_to_inline(
    client: GitHubClient,
) -> None:
    # Arriba de 1MB GitHub devuelve el envelope con content vacio y encoding 'none'
    respx.get("https://api.github.com/repos/octocat/Hello-World/contents/big.py").mock(
        return_value=httpx.Response(
            200, json={"content": "", "encoding": "none", "type": "file", "size": 2_000_000}
        )
    )

    with pytest.raises(GitHubError) as excinfo:
        await client.get_file_contents(repo="octocat/Hello-World", path="big.py", ref="master")

    assert excinfo.value.status_code == 413


@respx.mock
async def test_a_network_failure_becomes_a_gateway_error(client: GitHubClient) -> None:
    respx.get("https://api.github.com/search/code").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    with pytest.raises(GitHubError) as excinfo:
        await client.search_code(q='"foo"')

    assert excinfo.value.status_code == 502


@respx.mock
async def test_get_file_contents_rejects_a_binary_file_that_decodes_as_utf8(
    client: GitHubClient,
) -> None:
    # Un binario de bytes bajos decodifica como UTF-8 valido: sin un chequeo
    # aparte se le entregaria a la etapa de AST como si fuera codigo
    blob = bytes([0x00, 0x01, 0x02, 0x41, 0x42, 0x43, 0x00, 0x7F])
    respx.get("https://api.github.com/repos/octocat/Hello-World/contents/data.bin").mock(
        return_value=httpx.Response(
            200,
            json={"content": base64.b64encode(blob).decode(), "encoding": "base64"},
        )
    )

    with pytest.raises(GitHubError) as excinfo:
        await client.get_file_contents(
            repo="octocat/Hello-World", path="data.bin", ref="master"
        )

    assert excinfo.value.status_code == 415


@respx.mock
async def test_malformed_base64_is_reported_as_such(client: GitHubClient) -> None:
    # Base64 roto es corrupcion de arriba, no "el archivo es binario": el
    # mensaje tiene que distinguirlos
    respx.get("https://api.github.com/repos/octocat/Hello-World/contents/broken.py").mock(
        return_value=httpx.Response(
            200, json={"content": "!!!not base64!!!", "encoding": "base64"}
        )
    )

    with pytest.raises(GitHubError) as excinfo:
        await client.get_file_contents(
            repo="octocat/Hello-World", path="broken.py", ref="master"
        )

    assert "base64" in excinfo.value.body["message"]
