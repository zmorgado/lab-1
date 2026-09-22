# Backend

Python service for LAB #1, living in `backend/`. It holds the whole pipeline —
see the stack decision on #3 for why it is Python rather than Node/TS:

- the authenticated GitHub proxy: code search and file fetching (#3)
- query building and execution, moved out of the frontend (#19)
- grep tag extraction (#4) and the LLM tag service (#7)
- the AST stage: parse, isolate subtrees, prune (#20)
- the embedding stage: UniXcoder + cosine ranking (#21, after the #18 spike)
- the result mapper the frontend renders (#8) and error codes (#9)

#3 landed the first two endpoints and the app skeleton (FastAPI + uvicorn);
everything else on that list is still to come. Issue #1 is the spec.

## Commands

Package manager and task runner is **uv** (`backend/uv.lock`). Run everything
from `backend/`; `uv run` creates and syncs `.venv` on its own, so there is no
separate activate step, and `.python-version` pins the interpreter (3.12) so the
lockfile resolves the same way for everyone.

```
uv sync                 # install deps into backend/.venv
uv run code-search-proxy   # start the service on 127.0.0.1:8000
uv run pytest           # run the test suite — exits non-zero on failure
```

`HOST` and `PORT` override the bind address. For auto-reload while developing,
use uvicorn directly: `uv run uvicorn code_search_proxy.main:app --reload`.

## The credential

The service **will not start without a GitHub token**: `search/code` rejects
anonymous requests. The token is read server-side only and never reaches the
client bundle. Startup fails with an actionable message, not a traceback, when it
is missing.

Supply it either way — the real environment wins over the file:

```
export GITHUB_TOKEN=$(gh auth token)        # one-off

cp .env.example .env                         # or persist it locally
echo "GITHUB_TOKEN=$(gh auth token)" >> .env
```

`backend/.env` is gitignored; `.env.example` is the committed template. The token
needs the `public_repo` scope. `GITHUB_API_URL` optionally points the proxy at
another instance (GitHub Enterprise, or a fake in tests).

## Endpoints

| Endpoint | Returns |
| --- | --- |
| `GET /health` | `{"status": "ok"}` |
| `GET /api/search/code?q=&per_page=&page=` | GitHub's `search/code` response **unchanged** |
| `GET /api/contents?repo=&path=&ref=` | the file's source as `text/plain` |

The proxy is a thin pass-through: it attaches the credential and forwards. It
does not build queries (#19) or reshape results (#8), and GitHub's error status
and body are relayed as-is for #9 to map to stable error codes.

`/api/contents` base64-decodes GitHub's envelope and returns just the source,
which is what the AST stage (#20) needs; `search/code` gives back repo, path and
sha but not the code. `repo` is `owner/name` as it appears in
`repository.full_name`. A directory or a non-UTF-8 blob is a `415`; a file over
GitHub's 1MB inline limit is a `413`.

**Rate limit.** One token serves every user, so the budget is shared. GitHub's
`X-RateLimit-*` headers are forwarded on every response, errors included, rather
than being swallowed at the proxy — that is the only signal downstream has. Code
search is a far tighter budget than the rest (`X-RateLimit-Resource: code_search`,
10/min) and `/api/contents` spends the separate `core` budget.

Verify it end to end against the real API:

```
export GITHUB_TOKEN=$(gh auth token)
uv run code-search-proxy &

curl -sD - -G localhost:8000/api/search/code \
  --data-urlencode 'q="_analyze_document_payload_sync" language:python'

curl -s -G localhost:8000/api/contents \
  --data-urlencode 'repo=zmorgado/wapp-bot' \
  --data-urlencode 'path=app/services/document_ai.py' \
  --data-urlencode 'ref=HEAD'
```

## Tests

`pytest` is the test runner, configured in `pyproject.toml` under
`[tool.pytest.ini_options]` rather than a separate `pytest.ini`. It is the runner
FastAPI's own docs are written against, so `TestClient` works as documented.
`asyncio_mode = "auto"` means async tests need no per-test marker, and
[`respx`](https://lundberg.github.io/respx/) mocks GitHub at the HTTP layer, so
**the suite never makes a network call and needs no token**.

The package uses a **src layout** (`src/code_search_proxy/`) and `uv sync`
installs it editable. `tests/conftest.py` still puts `src/` on `sys.path`: `uv
run` can reinstall the package while starting up, i.e. after Python has already
processed `site-packages`, and in that run the regenerated `.pth` is never read.
Without it the suite fails to import `code_search_proxy` intermittently. It also
holds the shared fixtures and points `DEFAULT_ENV_FILE` at a throwaway path, so
the suite's result does not depend on whether you happen to have a `.env`. Tests
live in `backend/tests/`, mirroring the module they cover, not colocated (that
differs from the frontend, where Vitest tests sit next to the source).

- Run everything: `uv run pytest`
- Run one file: `uv run pytest tests/test_app.py`
- Run one test by name: `uv run pytest tests/test_app.py::test_health_reports_ok`
- Run every test matching a substring: `uv run pytest -k rate_limit`

This is **separate from the frontend's `pnpm test`** (Vitest, run from the repo
root — see `FRONTEND.md`). Neither command runs the other, so a full local check
means running both. Nothing enforces that yet: the repo has no CI.
