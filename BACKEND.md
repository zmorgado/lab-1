# Backend

Python service for LAB #1, living in `backend/`. It holds the whole pipeline —
see the stack decision on #3 for why it is Python rather than Node/TS:

- the authenticated GitHub proxy: code search and file fetching (#3)
- query building and execution, moved out of the frontend (#19)
- grep tag extraction (#4) and the LLM tag service (#7)
- the AST stage: parse, isolate subtrees, prune (#20)
- the embedding stage: UniXcoder + cosine ranking (#21, after the #18 spike)
- the result mapper the frontend renders (#8) and error codes (#9)

#7 landed the tag-extraction endpoint; #3 brings the proxy endpoints and the
shared app skeleton. Everything else on that list is still to come. Issue #1 is
the spec.

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

## LLM tag service (#7)

Stage 2 of the pipeline: it sends a pasted snippet or a whole file to an LLM and
gets back the five tag categories from `docs/research/solution-schematics-v2.md`
— API calls, data structures, paradigm, algorithm and domain keywords — plus the
detected language.

| File | What it holds |
| --- | --- |
| `llm_tags.py` | `GeminiTagService`: the async client, retries and normalisation |
| `llm_config.py` | `GeminiSettings` and `load_gemini_settings()`: credentials, resolved at startup |
| `tags_api.py` | the FastAPI router, plus a temporary standalone app to run this stage alone |
| `contracts/tags_set.py` | `TagSet`: the five categories and how a `q` is built from them |
| `constants/app_constants.py` | the prompt, the tiers, the caps, the stable error codes |

It complements the grep service (#4), it does not replace it. Grep pulls what is
literally written in the snippet; the LLM names what the code *is* and proposes
terms that are likely to appear in someone else's equivalent code. Both sources
merge into the tier-ordered list #22 lets the user edit. When the provider is
down or out of quota the service says so in a way the caller can act on, so the
pipeline can keep going on grep tags alone — see *Errors* below.

### Provider, limits and terms

**Google Gemini**, model `gemini-2.5-flash`, over plain REST through `httpx` —
no extra SDK, and the same HTTP client the GitHub proxy (#3) uses. Chosen
because the free tier needs no card, the API takes a JSON schema for the
response, and thinking can be switched off, which is what keeps a call in the
single-digit seconds.

- **Key**: <https://aistudio.google.com/apikey>, free, no card.
- **Rate limits**: per-minute requests, per-minute tokens and per-day requests,
  all per project. Google changes the numbers, so read them at
  <https://ai.google.dev/gemini-api/docs/rate-limits> rather than trusting a
  figure copied here. What matters for us: the ceiling is low enough that one
  extraction per pasted snippet is fine and a batch job is not.
- **Terms**: <https://ai.google.dev/gemini-api/terms>. The free tier is the
  "unpaid services" case, and **Google may use the content sent through it to
  improve their products**. The paid tiers do not carry that clause. For this
  project it is public code being pasted into a search engine, so it is an
  acceptable trade; it would not be for anything private, and that is worth
  saying out loud before anyone wires this into something else.
- **Observed behaviour**: the free tier returns `503 "This model is currently
  experiencing high demand"` intermittently — one call fails after a minute and
  the next answers in five seconds. The service retries those (see *Errors*).

### Configuration

Credentials are read from the environment at startup and never reach the client
bundle, the same contract as the proxy in #3. `backend/.env` is the local
development file and is gitignored (the repo root `.env` is read too, for the
key that already lived there).

```
GEMINI_API_KEY=...       # required; the service refuses to start without it
GEMINI_MODEL=...         # optional, defaults to gemini-2.5-flash
GEMINI_TIMEOUT=120       # optional, seconds, defaults to 60
```

A missing key is a startup failure with an actionable message, not a 500 on the
first request. A `GEMINI_TIMEOUT` that is not a positive number is a startup
failure too, and it says which variable is wrong.

### Running it

> **Temporary.** Until the proxy app from #3 is merged there is no service to
> hang this router on, so `tags_api.py` also carries a standalone app
> (`create_tags_app()`) and its own `llm-tag-service` entrypoint, purely so this
> stage can be run and tested on its own. Both go away at merge — see *Merging
> with #3* below. The router, the request and response models and the error
> handler are not temporary: those are the endpoint #7 asks for.

```
uv run llm-tag-service          # http://127.0.0.1:8001 (the proxy takes 8000)
```

Two endpoints, both returning the same body:

```
POST /api/tags          {"source": "...", "language": "Python"}   # the frontend
POST /api/tags/file     the file as the raw request body          # a whole file
```

```
curl -X POST --data-binary @path/to/file.py \
     'http://127.0.0.1:8001/api/tags/file?filename=file.py&language=Python'
```

`language` and `filename` are optional everywhere; when given, the model does
not have to infer the language, which is where it mostly errs on short snippets.
The file travels in the body rather than as multipart so the service does not
need `python-multipart` for one file per request. Interactive docs are at
`/docs`.

The response carries everything the model produced, not only what the service
would use itself — `tags` per category, `ordered_tags` flattened by tier,
`suggested`, and a ready-to-use `query`. #22 lets the user pick tags by hand, so
nothing is thrown away on their behalf.

### `suggested`: the model's own pick

`suggested` holds up to five tags, best first — the model's answer to "which of
these would actually surface a *different* file with the same intent?". It is
always a subset of `tags`, so the picker in #22 can render it as the pre-ticked
boxes and the user changes them from there. It decides nothing on its own.

The model has to make that call, because it is a judgement about how rare a term
is across GitHub, which no cheap heuristic in this repo can answer. The prompt
says so directly: a tag can be perfectly correct and still a bad pick, because
every project of that stack contains it. On the reference file it picks
`defaultdict, uuid4, FastAPI, in-memory repository, lending`, where tier order
alone had produced the five framework imports every FastAPI project shares.

Normalisation keeps it honest: entries the model invented rather than copied
from a category are dropped, spelling is taken from the category so the ids
match, and fewer than five is left as-is rather than padded — the prompt asks it
to stop rather than fill. If nothing usable comes back, it falls back to the
`query` tags so the picker never opens with nothing selected.

Note that `suggested` and `query` optimise for different things and will
disagree. `suggested` answers *same intent* and will happily cross into
`algorithm` and `domain_keywords`; `query` answers *what GitHub can actually
match* and stays on the literal tiers. Feeding `suggested` straight into
`search/code` is not the intended use — it is the starting selection for a human.

### Why the suggested query is short

`query` holds far fewer tags than would fit in 256 characters, and only from
`api_calls` and `data_structures`. That is deliberate, and it is the one thing
worth understanding before changing `TagSet.to_query()`:

- **GitHub ANDs the terms of a query.** A file has to contain every one of them.
  Packing 25 tags into the 256 characters returns zero results, which is the
  opposite of what Stage 3 needs — it only has to cut GitHub down to a handful
  of candidates, and the AST stage (#20) and the embeddings (#21) do the
  narrowing after that.
- **GitHub matches 3-character trigrams over raw file text.** Only a tag another
  developer would write *verbatim* can match. `comprehension`, `sort by value`
  and `book lending` describe the code instead of quoting it, so they stay in
  the `TagSet` — the embedding stage (#18) does use them — but out of `q` unless
  the user puts them there.
- Tags shorter than three characters cannot form a trigram at all, and
  ubiquitous names (`dict`, `list`, `value`, `status`) match everywhere and
  narrow nothing, so both are dropped during normalisation. Categories are
  capped at six tags, because the model overshoots the cap the prompt asks for
  when the file is large.

Callers that want something else pass `max_query_tags`, or build their own query
from `tags` / `ordered_tags`.

### Errors

Every failure comes out as `LlmTagError` and leaves the service as JSON with a
stable `code`, the same shape the proxy uses for `GitHubError`. The provider's
own English text travels in `message` and may change; `code` does not.

| `code` | HTTP | Meaning |
| --- | --- | --- |
| `empty_source` | 422 | Nothing to extract from |
| `source_not_text` | 422 / 413 | Not decodable UTF-8, or past the size ceiling |
| `llm_auth` | 502 | Our key was rejected |
| `llm_quota_exhausted` | 429 | Free-tier quota spent; `Retry-After` is forwarded |
| `llm_unavailable` | 503 | Provider down, overloaded, or unreachable |
| `llm_malformed_response` | 502 | The model answered something unparseable |
| `llm_request_failed` | 502 | Anything else |

Everything except `empty_source` and `source_not_text` also carries
`"fallback": "grep"`: the LLM is a complement, so the pipeline can continue on
the grep tags from #4 with a worse but working query. A snippet problem gets no
such hint, because grep cannot read it either.

A rejected key comes back as **502 and not 401**. A 401 from Gemini means *our*
credential is wrong, and forwarding it would make the frontend think the user is
not signed in. Transient failures (429, 5xx, network) are retried **once** with
exponential backoff, honouring `Retry-After` when the provider sends one;
`401`/`403` are not retried, because a key does not fix itself.

Two attempts rather than more is a quota decision, not a latency one. The free
tier allows a low number of requests per day, so every retry costs a share of
it; one retry absorbs the isolated 503 that actually happens in practice, while
three would let a bad afternoon at the provider spend the whole day's budget.

### Manual smoke

```
uv run python -m code_search_proxy.llm_tags path/to/file.py Python
```

Prints the tags per category, the `q` it would send to `search/code`, and how
many terms that `q` ANDs together. Progress goes to stderr so the result can be
piped on its own.

The test suite never reaches the network: it injects an `httpx.MockTransport`,
so it is deterministic and spends no quota. `tests/test_llm_tags.py` validates
against the dictionary-ranking snippet from #7.

### Merging with #3

This stage lives in its own modules so it does not collide with the proxy while
that is in review. Once both are on `main`:

- `create_tags_app()` in `tags_api.py` goes away, and `create_app()` in `app.py`
  picks up the router instead:

  ```python
  app.include_router(create_tags_router(tag_service))
  app.add_exception_handler(LlmTagError, handle_llm_tag_error)
  ```

  with the service built in the lifespan next to `GitHubClient`.
- `GeminiSettings` folds into `Settings` in `config.py`.
- `backend/.env.example` exists on both branches — this one documents
  `GEMINI_API_KEY`, #3's documents `GITHUB_TOKEN`. Keep both variables in the
  merged file; neither version is a superset of the other.

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

- Run everything: `uv run pytest`
- Run one file: `uv run pytest tests/test_app.py`
- Run one test by name: `uv run pytest tests/test_app.py::test_health_reports_ok`
- Run every test matching a substring: `uv run pytest -k rate_limit`

This is **separate from the frontend's `pnpm test`** (Vitest, run from the repo
root — see `FRONTEND.md`). Neither command runs the other, so a full local check
means running both. Nothing enforces that yet: the repo has no CI.
