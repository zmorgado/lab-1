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
landed the embedding stage as a library, which the app does not call yet. #7
added the LLM tags, and #4 the grep tags with the general search endpoint.
Everything else on that list is still to come. Issue #1 is the spec.

## Layout

```
backend/
  src/snippet_search/   the package: the app and every pipeline stage
    embeddings/         the one stage with a subpackage of its own
  tests/                pytest only
  scripts/              manual runners, never collected by pytest
```

Each stage is a flat module (`github.py`, `grep_tags.py`, `llm_tags.py`, ...)
and `pipeline.py` chains them. A stage gets a subpackage only when it spans
several files, as embeddings does. New stages go into the package, not into a
new top-level folder (#30).

## Commands

Package manager and task runner is **uv** (`backend/uv.lock`). Run everything
from `backend/`; `uv run` creates and syncs `.venv` on its own, so there is no
separate activate step, and `.python-version` pins the interpreter (3.12) so the
lockfile resolves the same way for everyone.

```
uv sync                 # install deps into backend/.venv
uv run snippet-search   # start the service on 127.0.0.1:8000
uv run pytest           # run the test suite — exits non-zero on failure
```

`HOST` and `PORT` override the bind address. For auto-reload while developing,
use uvicorn directly: `uv run uvicorn snippet_search.main:app --reload`.

**If either command dies with `ModuleNotFoundError: No module named
'snippet_search'`, prefix it with `PYTHONPATH=src`.** Some python.org builds
(3.12.8 here) skip `.pth` files whose name begins with `_`, and the editable
install is exactly `_editable_impl_snippet_search.pth` with `src/` inside it,
so the package never reaches `sys.path`. It is an interpreter quirk, not a
project misconfiguration, and `uv sync` regenerates the same file each time:

```
PYTHONPATH=src uv run uvicorn snippet_search.main:app --port 8000
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
| `POST /api/search` | the tags, the query built from them, and GitHub's results (see below) |

The proxy endpoints are a thin pass-through: they attach the credential and
forward. They do not build queries or reshape results (#8), and GitHub's error
status and body are relayed as-is for #9 to map to stable error codes. Only
`/api/search` builds a query.

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
uv run snippet-search &

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
them. It lives in `snippet_search/embeddings/`:

| File | What it holds |
| --- | --- |
| `embeddings/unixcoder.py` | Microsoft's `UniXcoder` model class, vendored with its MIT header |
| `embeddings/encoder_only_VE.py` | `verify_code_semantics(query, code_snippets, model=None)`: one cosine score per candidate |

It is a library for now: no endpoint, and nothing in the app calls it. The
first call downloads `microsoft/unixcoder-base` from Hugging Face; pass a loaded
`model` to avoid reloading it on every call. `torch`, `transformers` and
`psutil` are in the dependency list for this stage.

To see a score by hand, compare two files:

```
uv run python scripts/tester.py scripts/word_freq_A.py scripts/word_freq_B.py
```

It prints the similarity and a time/memory report. The runner and its inputs
(`word_freq_A.py`, `word_freq_B.py`, `testing_snippets.txt`) live in `scripts/`,
outside the suite, so `uv run pytest` never loads the model. On an interpreter
with the `.pth` quirk above, prefix it with `PYTHONPATH=src`.

## The search pipeline (#4)

Endpoints follow the user's steps, not the internal stages. The stages are plain
modules that don't know each other, and `pipeline.py` chains them, so the route
stays thin. Every later stage plugs into `pipeline.search()`, not into a new
endpoint: LLM tags and the user's edited list (#22), filters (#19), AST (#20),
embeddings (#21) and the ranked result shape (#8).

| Module | Stage |
| --- | --- |
| `grep_tags.py` | 1: `extract_tags(snippet)` → `Tiers`, the candidates in three tiers. Python only |
| `query.py` | 3: `build_query(tags, language)` → `SearchQuery` or `NothingToSearch` |
| `pipeline.py` | `search(github, source, language)`: extraction → query → `search/code` |

Tags come in three tiers, APIs (imports and calls), then structures (own
`def`/`class` names and `lambda`), then a few docstring words. Keywords, generic
builtins (`print`, `len`, ...), dunders and names under 3 characters are dropped.
`build_query` fills the query in the order given, up to 6 tags and 256 characters
on the `q` value, so truncation keeps the highest tiers. It takes any tag list and
quotes multi-word tags, so #22 can feed it the merged and edited list.

```
POST /api/search   {"source": "...", "language": "python"}   # language optional
→ {"tags": [...], "tiers": {"apis": [...], "structures": [...], "domain": [...]},
   "query": "... language:python", "results": <search/code body, unchanged>}
```

Both errors are 422s with a stable `code`, as in #7, and neither reaches GitHub:
`nothing_to_search` (no usable tags) and `unsupported_language`. Filters (owner,
repo, languages) and the frontend wiring are #19's.

Verify it end to end against the real API, with the server running:

```
jq -Rs '{source: .}' some_snippet.py | curl -s -X POST localhost:8000/api/search \
  -H 'Content-Type: application/json' -d @- | jq '{tags, query, total: .results.total_count}'
```

## LLM tag service (#7)

Stage 2: `POST /api/tags` takes a pasted snippet and returns the detected
language plus the five tag categories from `docs/research/solution-schematics-v2.md`
— `api_calls`, `data_structures`, `paradigm`, `algorithm`, `domain_keywords`. It
lives in `llm_tags.py` (client, prompt, `TagSet`, `LlmTagError`), `tags_api.py`
(dependency, request/response models, error handler) and the route in `app.py`. It complements the grep service (#4): grep pulls what the code says
literally, the LLM describes what it *is*. Which tags go into a query is #19.

```
POST /api/tags   {"source": "...", "language": "Python"}   # language optional
→ {"language": "Python", "tags": {"api_calls": [...], "data_structures": [...], ...}}
```

**Provider**: Google Gemini (`gemini-2.5-flash`) over plain REST with `httpx`. The
free tier needs no card, takes a JSON schema for the response and lets thinking be
switched off. Key at <https://aistudio.google.com/apikey>; limits change, read
<https://ai.google.dev/gemini-api/docs/rate-limits>. Under the free-tier
[terms](https://ai.google.dev/gemini-api/terms) Google may use the content sent to
improve its products: fine for public code pasted into a search engine, not for
anything private.

**Configuration**, read like the GitHub token (environment, then `backend/.env`):

```
GEMINI_API_KEY=          # optional
GEMINI_MODEL=...         # optional, defaults to gemini-2.5-flash
```

The key is optional: the LLM is a complement (#1), so without it the service
starts and `/api/tags` answers `llm_unavailable`.

**Errors** leave as JSON with a stable `code`; the provider's text travels in
`message` and may change.

| `code` | HTTP | Meaning |
| --- | --- | --- |
| `empty_source` | 422 | Nothing to extract from |
| `llm_auth` | 502 | Our key was rejected (not 401: it is not the user's credential) |
| `llm_quota_exhausted` | 429 | Free-tier quota spent; `Retry-After` is forwarded |
| `llm_unavailable` | 503 | No key, provider down, overloaded or unreachable |
| `llm_malformed_response` | 502 | The model answered something unparseable |
| `llm_request_failed` | 502 | Anything else |

Everything but `empty_source` also carries `"fallback": "grep"`, so the client can
carry on with grep tags alone. Nothing is retried: on failure the client falls
back to grep, and a 429 forwards `Retry-After`.

## Tests

`pytest` is the test runner, configured in `pyproject.toml` under
`[tool.pytest.ini_options]` rather than a separate `pytest.ini`. It is the runner
FastAPI's own docs are written against, so `TestClient` works as documented.
`asyncio_mode = "auto"` means async tests need no per-test marker, and
[`respx`](https://lundberg.github.io/respx/) mocks GitHub at the HTTP layer, so
**the suite never makes a network call and needs no token**.

The package uses a **src layout** (`src/snippet_search/`) and `uv sync`
installs it editable. `tests/conftest.py` still puts `src/` on `sys.path`, for the
`.pth` reason above — without it the suite cannot import `snippet_search` at
all on an affected interpreter. It also
holds the shared fixtures and points `DEFAULT_ENV_FILE` at a throwaway path, so
the suite's result does not depend on whether you happen to have a `.env`. Tests
live in `backend/tests/`, mirroring the module they cover, not colocated (that
differs from the frontend, where Vitest tests sit next to the source).

- Run everything: `uv run pytest`
- Run one file: `uv run pytest tests/test_app.py`
- Run one test by name: `uv run pytest tests/test_app.py::test_health_reports_ok`
- Run every test matching a substring: `uv run pytest -k rate_limit`

This is **separate from the frontend's `pnpm test`** (Vitest, run from
`frontend/` — see `frontend/FRONTEND.md`). Neither command runs the other, so a full local check
means running both. Nothing enforces that yet: the repo has no CI.
