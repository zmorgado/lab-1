# Backend

Python service for LAB #1, living in `backend/`. It holds the whole pipeline —
see the stack decision on #3 for why it is Python rather than Node/TS:

- the authenticated GitHub proxy: code search and file fetching (#3)
- query building and execution, moved out of the frontend (#19)
- grep tag extraction (#4) and the LLM tag service (#7)
- the AST stage: parse, isolate subtrees, prune (#20)
- the embedding stage: UniXcoder + cosine ranking (#21, after the #18 spike)
- the result mapper the frontend renders (#8) and error codes (#9)

#3 landed the first two endpoints and the app skeleton (FastAPI + uvicorn). #21
landed the embedding stage as a library in `services/`, which the app does not
call yet. Everything else on that list is still to come. Issue #1 is the spec.

The layout is about to change: `services/` moves into the package, which is
renamed `snippet_search`, and the frontend moves to `frontend/`. See *Decided
restructure* in `CLAUDE.md`.

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

**If either command dies with `ModuleNotFoundError: No module named
'code_search_proxy'`, prefix it with `PYTHONPATH=src`.** Some python.org builds
(3.12.8 here) skip `.pth` files whose name begins with `_`, and the editable
install is exactly `_editable_impl_code_search_proxy.pth` with `src/` inside it,
so the package never reaches `sys.path`. It is an interpreter quirk, not a
project misconfiguration, and `uv sync` regenerates the same file each time:

```
PYTHONPATH=src uv run uvicorn code_search_proxy.main:app --port 8000
```

`uv run pytest` is unaffected — `tests/conftest.py` sets the path itself.

## The credential

The service **will not start without a GitHub token**: `search/code` rejects
anonymous requests. The token is read server-side only and never reaches the
client bundle. Startup fails with an actionable message, not a traceback, when it
is missing.

It is resolved in this order, so anything explicit beats anything ambient:

1. **`GITHUB_TOKEN` in the environment** — `export GITHUB_TOKEN=$(gh auth token)`
2. **`backend/.env`** — `cp .env.example .env`, then fill it in
3. **The `gh` CLI** — nothing to configure if `gh auth status` is already green

Step 3 means a machine with an authenticated `gh` needs **no setup at all**: the
service shells out to `gh auth token` (~75ms, once at startup) and uses that. It
is a local-development convenience only — `gh` is not a dependency, and if it is
missing, logged out, or slow, the fallback yields nothing and startup fails with
the usual message. **Deployments set `GITHUB_TOKEN`**; there is no `gh` there.

One caveat: a `gh` token carries whatever scopes you granted the CLI, typically
`repo`, which is broader than the `public_repo` this needs and can read private
repositories. Fine locally, but not what you would deploy with.

`backend/.env` is gitignored; `.env.example` is the committed template.
`GITHUB_API_URL` optionally points the proxy at another instance (GitHub
Enterprise, or a fake in tests).

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
  --data-urlencode 'q="def get_adapter" repo:psf/requests language:python'

curl -s -G localhost:8000/api/contents \
  --data-urlencode 'repo=octocat/Hello-World' \
  --data-urlencode 'path=README' \
  --data-urlencode 'ref=master'
```

Both targets are long-lived public repositories, so this check works for anyone
with a token, whatever their access. Note that a search run against **your** own
token also returns private repositories you can see (`docs/research/tests.md`
shows one), which is why #8 dedupes on `sha` and drops private hits.

## Embedding stage (#21)

UniXcoder embeds the snippet and the candidates, and cosine similarity scores
them. It lives in `services/`, a second top-level package next to
`code_search_proxy` (both listed under `packages` in `pyproject.toml`):

| File | What it holds |
| --- | --- |
| `services/unixcoder.py` | Microsoft's `UniXcoder` model class, vendored with its MIT header |
| `services/encoder_only_VE.py` | `verify_code_semantics(query, code_snippets, model=None)`: one cosine score per candidate |

It is a library for now: no endpoint, and nothing in the app calls it. The
first call downloads `microsoft/unixcoder-base` from Hugging Face; pass a loaded
`model` to avoid reloading it on every call. `torch`, `transformers` and
`psutil` are in the dependency list for this stage.

To see a score by hand, compare two files:

```
uv run python tests/tester.py tests/word_freq_A.py tests/word_freq_B.py
```

It prints the similarity and a time/memory report. On an interpreter with the
`.pth` quirk above, `No module named 'services'` is fixed the same way, with
`PYTHONPATH=.` instead of `PYTHONPATH=src`.

## Tests

`pytest` is the test runner, configured in `pyproject.toml` under
`[tool.pytest.ini_options]` rather than a separate `pytest.ini`. It is the runner
FastAPI's own docs are written against, so `TestClient` works as documented.
`asyncio_mode = "auto"` means async tests need no per-test marker, and
[`respx`](https://lundberg.github.io/respx/) mocks GitHub at the HTTP layer, so
**the suite never makes a network call and needs no token**.

The package uses a **src layout** (`src/code_search_proxy/`) and `uv sync`
installs it editable. `tests/conftest.py` still puts `src/` on `sys.path`, for the
`.pth` reason above — without it the suite cannot import `code_search_proxy` at
all on an affected interpreter. It also
holds the shared fixtures and points `DEFAULT_ENV_FILE` at a throwaway path, so
the suite's result does not depend on whether you happen to have a `.env`. Tests
live in `backend/tests/`, mirroring the module they cover, not colocated (that
differs from the frontend, where Vitest tests sit next to the source).

Not everything in `backend/tests/` is a test. `tester.py`, `word_freq_A.py`,
`word_freq_B.py` and `testing_snippets.txt` are the manual UniXcoder runner and
its inputs. pytest only collects `test_*.py`, so `uv run pytest` never loads the
model.

- Run everything: `uv run pytest`
- Run one file: `uv run pytest tests/test_app.py`
- Run one test by name: `uv run pytest tests/test_app.py::test_health_reports_ok`
- Run every test matching a substring: `uv run pytest -k rate_limit`

This is **separate from the frontend's `pnpm test`** (Vitest, run from the repo
root — see `FRONTEND.md`). Neither command runs the other, so a full local check
means running both. Nothing enforces that yet: the repo has no CI.
