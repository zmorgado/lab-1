# Backend

Python service for LAB #1, living in `backend/`. It holds the whole pipeline —
see the stack decision on #3 for why it is Python rather than Node/TS:

- the authenticated GitHub proxy: code search and file fetching (#3)
- query building and execution, moved out of the frontend (#19)
- grep tag extraction (#4) and the LLM tag service (#7)
- the AST stage: parse, isolate subtrees, prune (#20)
- the embedding stage: UniXcoder + cosine ranking (#21, after the #18 spike)
- the result mapper the frontend renders (#8) and error codes (#9)
- the model's explanation of each result (#43)

#3 landed the first two endpoints and the app skeleton (FastAPI + uvicorn). #21
landed the embedding stage as a library. #7 added the LLM tags, and #4 the grep
tags with the general search endpoint. #20 added the AST stage and wired every
stage into one run behind `/api/search`, and #8 turned its output into the ranked
result list. #38 put the frontend on it, with a tag preview the user confirms
before the search runs, and #43 has the model explain each result once the
search is done. Filters (#19) and error codes (#9) are still to come.
Issue #1 is the spec.

## Layout

```
backend/
  src/snippet_search/   the package: the app and every pipeline stage
    embeddings/         the one stage with a subpackage of its own
  tests/                pytest only
  scripts/              manual runners, never collected by pytest
```

Each stage is a flat module (`github.py`, `ast_grep_tags.py`, `llm_tags.py`, ...)
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
| `POST /api/search/preview` | the queries a search would run, each tag with its source; spends no GitHub budget (#38) |
| `POST /api/search` | the full run: tags, queries, the ranked results (#8) and GitHub's raw bodies (see below) |
| `POST /api/search/explain` | per result: what it offers next to the snippet, a suggestion and the lines that matter; one LLM call, no GitHub budget (#43) |

The proxy endpoints are a thin pass-through: they attach the credential and
forward. They do not build queries or reshape results (#8), and GitHub's error
status and body are relayed as-is for #9 to map to stable error codes. Only
`/api/search` and its preview build queries.

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

`/api/search` calls it through `pipeline.unixcoder_rank`, which loads the model
once per process, on the first search that has something to rank. That first
call downloads `microsoft/unixcoder-base` from Hugging Face (about 500 MB).
`torch`, `transformers` and `psutil` are in the dependency list for this stage.

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
endpoint: filters (#19), and the user's edits to the tag list (#22), which reach
it as the confirmed `tags`. The tag preview exists beside it because it is a
step of its own for the user (#38). The result explanations (#43) are the one
exception: not a step, but run apart, after the search, so the results never
wait for the model and a model failure never fails the search.

| Module | Stage |
| --- | --- |
| `ast_grep_tags.py` | 1: `extract_tags(snippet)` → `Tiers`, the candidates in three tiers. Python only |
| `tag_selection.py` | 2: `select(tiers, llm_tags, language)` → the pool the user edits, weighted, with the default selection (#22) |
| `query.py` | 3: `build_query(tags, language)` → `SearchQuery` or `NothingToSearch` |
| `ast_subtrees.py` | 4: `analyze_snippet(snippet)` → `SnippetShape`; `isolate(file, shape, anchors)` → `Isolation` |
| `results.py` | After 5: `merge_files(bodies, limit)` → files by `sha`, no private repos; `to_results(candidates, query_text, max_results)` → `Result`s |
| `pipeline.py` | `preview(source, language, llm=)` → `QueryPlan`, stages 1–2 alone; `search(github, source, language, llm=, rank=, max_results=, tags=)`: the whole run, below |
| `search_api.py` | the request and response models of `/api/search` and its preview, typed in `/openapi.json` |

Tags come in three tiers, APIs (imports and calls), then structures (own
`def`/`class` names and `lambda`), then a few docstring words. Keywords, generic
builtins (`print`, `len`, ...), dunders and names under 3 characters are dropped.
`build_query` fills the query in the order given, up to 6 tags and 256 characters
on the `q` value, so truncation keeps the highest tiers. It takes any tag list and
quotes multi-word tags, so #22 can feed it the merged and edited list.

The run: AST tiers → LLM list (#7, #22) → one `search/code` query per kind of
tag (#19) → files merged → each file through `/repos/{repo}/contents/{path}` at
the commit the search returned → AST → UniXcoder over at most
`MAX_EMBEDDED_SUBTREES` (50, #18's ceiling) → ranked results (#8).

- **Queries.** The LLM gets the AST tiers and returns tags of three kinds:
  `syntactic`, `conceptual` and `paradigm`. Each kind becomes one query through
  `build_query`, so each keeps the 6-tag and 256-character limits. A seed the LLM
  drops, such as an internal module (`ringr_agents`), goes into none. If the LLM
  fails or leaves nothing searchable, there is one query from the tiers (kind
  `tiers`), and a failure's `code` is reported.
- **One at a time.** The queries run serially, as GitHub asks to avoid its
  secondary rate limits. Each search spends one code-search request per query,
  out of 10 per minute. A query that fails is reported in its `error` and the
  rest go on; the search fails only when all of them do.
- **Merge.** `results.merge_files` merges the hits on blob `sha`. Private copies
  never enter: a content with a public copy is fetched and listed from its public
  repos, and one found only in private repos is dropped and counted in
  `private_excluded`. Files found by more queries go first (a query that only saw
  a private copy still counts), then by their best position in GitHub's results,
  and only the first `MAX_CANDIDATE_FILES` (20) are fetched, the same budget as
  one query. The same count orders subtrees for the embedding budget.
- **Results (#8).** `results.to_results` sorts by cosine, breaks ties by repo,
  path and line, numbers the ranks from 1 and cuts at `max_results`. That's a
  request field from 1 to 50 (no more than reach UniXcoder), 10 by default. Each
  result lists every public repo with its content and the queries that found its
  file. Nothing surviving gives an explicit `[]`.

```
POST /api/search   {"source": "...", "language": "python", "max_results": 10}
                   # language and max_results optional
→ {"tiers": {"apis": [...], "structures": [...], "domain": [...]},
   "queries": [{"kind": "syntactic", "tags": [...], "q": "... language:python",
                "error": null}, ...],
   "llm": {"tags": [{"tag", "kind", "source"}] | null, "error": "llm_unavailable" | null},
   "snippet": {"category": "function", "fallback": false, "lines": 4},
   "anchors": [...],
   "results": [{"rank", "score", "sha",
                "locations": [{"repo", "path", "html_url"}],
                "queries": [{"kind", "q"}],
                "name", "node", "parent", "start_line", "end_line", "code"}],
   "rejected": {"A": 0, "C": 0, "B": 0, "length": 0, "budget": 0},
   "skipped": [{"repo", "path", "reason"}],
   "private_excluded": 0,
   "github": {"syntactic": <search/code body, without private items>, ...}}
```

The response is typed: `SearchResponse` (`search_api.py`) shows up in
`/openapi.json`, and the route validates against it. Private repos are never
named, not in `results`, not in `skipped`, and their items are removed from
`github`; `private_excluded` only counts them. The bare proxy
(`GET /api/search/code`) still returns GitHub's body unchanged, private items
included.

Both errors are 422s with a stable `code`, as in #7, and neither reaches GitHub:
`nothing_to_search` (no usable tags) and `unsupported_language`. Filters (owner,
repo, languages) are #19's.

Verify it end to end against the real API, with the server running:

```
jq -Rs '{source: .}' some_snippet.py | curl -s -X POST localhost:8000/api/search \
  -H 'Content-Type: application/json' -d @- \
  | jq '{queries, results: [.results[] | {rank, score, name}], totals: (.github | map_values(.total_count))}'
```

### Tag preview and selected tags (#38, #22)

The page shows the tags before spending any search budget, and lets the user pick
and add them, so stages 1–2 also run alone. `POST /api/search/preview` takes the
same `source` and `language` and runs them exactly as the search does: AST tiers,
then the LLM, then `build_query` per kind. It spends one LLM call and no GitHub
request, and returns:

- `pool`: every tag offered, with its `kind` (the query it feeds), its `source`
  (`seed` from the AST, `llm` from the model) and whether it is `selected` unless
  the user changes it. `tag_selection.select` builds it, below;
- `queries`: per kind, the selected tags that fit the 6-tag and 256-character
  limits, the ones those limits `dropped`, and the `q` it would send (`null` when
  none fit). Nothing is truncated silently.

```
POST /api/search/preview   {"source": "...", "language": "python"}   # language optional
→ {"pool": [{"tag": "sorted", "kind": "syntactic", "source": "seed", "selected": true}, ...],
   "queries": [{"kind": "syntactic", "tags": ["sorted", "items"], "dropped": [],
                "q": "sorted items language:python"}, ...],
   "llm": {"error": null},
   "is_fallback": false}
```

With the model unavailable it still answers 200, with one `tiers` query from the
AST and the LLM's code in `llm.error` (the LLM is a complement, #1).
`is_fallback` says the snippet didn't parse and the regex extracted the AST tags.
Its errors are the search's: `nothing_to_search` and `unsupported_language`.

**The pool (#22).** `select` merges the AST seeds and the model's tags, without
repeats (case-insensitive), into at most `POOL_SIZE` (20) tags, larger than a
query on purpose. A weight orders it, lightest first, so whatever has to be cut
keeps the distinctive tags. The AST tells the kinds of seed apart without
guessing:

| Weight | Seeds | Model tags without a seed |
| --- | --- | --- |
| 1, domain | the snippet's own `def`/`class` names, docstring words | `conceptual` |
| 2, API | calls, `lambda` | `syntactic`, `paradigm` |
| 3, import | imported modules (`Tiers.imports`) | |

- **With the model**, its tags are all selected, each feeding the query of its
  kind. The seeds it dropped fill the rest of the pool unselected, so an internal
  module like `ringr_agents` only goes in if the user picks it. Each seed goes to
  a group: names and calls `syntactic`, docstring words `conceptual`, `lambda` and
  imports `paradigm`.
- **Without it**, or when it leaves nothing searchable, every seed goes to the
  `tiers` query by weight, and the ones that fit it are selected.

The pool is the same whichever path extracted the seeds: `is_fallback` only
records it. The weights are #22's decision, which put imports such as `math`
behind the names and words that actually identify the code.

Both routes take the user's selection in an optional `tags` field, one
`{"tag", "kind"}` per tag, `kind` being `syntactic`, `conceptual`, `paradigm` or
`tiers`. With `tags`:

- **neither calls the LLM**. The preview only rebuilds `queries` from them, with
  an empty `pool` since the client already holds it, so the page can show what
  fits while the user edits. The search runs them, and `llm` comes back as
  `{"tags": null, "error": null}`;
- the queries are one per kind, in that order;
- the anchors are the snippet's AST `apis` and `structures`, recomputed since
  they are deterministic and free, plus every selected tag;
- each tag is checked before GitHub is called. Empty, over 100 characters, an
  unknown kind or a double quote (which would break `q`) is a 422 with
  `code: invalid_tag`, and so is `tiers` mixed with the model's kinds: the `tiers`
  query replaces those three, and together they would spend four code-search
  requests. An empty list is `nothing_to_search`.

`build_query` quotes a bare `AND`, `OR` or `NOT`, so a tag the user types is
searched as a word instead of acting as a GitHub operator. Without `tags`, the
search runs the LLM itself as before, so plain curl usage keeps working.

## AST stage (#20)

`ast_subtrees.py` parses with tree-sitter (`tree-sitter-python`) and cuts each
candidate file down to the subtrees worth embedding.

**The snippet** is dedented and parsed. Its first top-level `def` or `class`
sets the category, `function` or `class`. Loose statements fall back to
`function` with `fallback: true`, since that code would live inside some
function in a candidate.

**Each candidate file** goes through the criteria of
`docs/research/multiple-snippet-sorting-solution.md`, cheapest first. Each one
counts what it drops in `rejected`:

| Criterion | Keeps |
| --- | --- |
| A | Top-level functions and methods of top-level classes (or top-level classes, for a class snippet). Nested definitions are dropped |
| C | Subtrees with a name, parameters and a body that does something. Stubs whose body is only a docstring, `pass`, `...` or `raise NotImplementedError` are dropped |
| B | Subtrees containing at least one anchor |
| length | Between `MIN_LENGTH_RATIO` (0.25) and `MAX_LENGTH_RATIO` (4.0) times the snippet's non-blank lines |

**Anchors** are the grep `apis` and `structures` tiers plus every LLM tag. A tag
matches when all its words appear in the subtree. The subtree's words come from
its identifiers (split on `snake_case` and `camelCase`), its comments, its
docstring and the constructs it uses (`lambda`, `comprehension`, `generator`,
`async`, `decorator`, and `recursion` for a self-call). That last part is what
lets a conceptual tag like `binary search` or `generator` match.

**Output**, one `Subtree` per survivor, the input for #21:

| Field | |
| --- | --- |
| `code` | the subtree's source, dedented, decorators excluded. This is what gets embedded |
| `kind`, `name` | `function_definition` / `class_definition`, and its name |
| `parent` | the enclosing class for a method, else `null` |
| `start_line`, `end_line` | 1-based, inclusive, in the original file |
| `anchors` | the tags criterion B found in it |

A file that survives nothing gives an empty set. A file with syntax errors is
skipped whole, with `syntax error at line N` as the reason. tree-sitter never
raises, so its error nodes are the signal. GitHub indexes Jinja-templated `.py`
files that fail exactly like this. Note that tree-sitter's grammar still accepts
most Python 2 (`print "x"`, `except E, e:`).

`tree-sitter` is pinned below 0.26: 0.26.0 corrupts memory while walking large
trees and segfaults on the standard library's `textwrap.py`.

The tests run on real files in `tests/fixtures/` (CPython's `bisect`,
`textwrap` and `numbers`, and a cookiecutter-django template). The README there
says where each one comes from.

## LLM tag service (#7, #22)

Stage 2: `POST /api/tags` takes a pasted snippet, runs the AST extractor (#4) on
it, and sends the model both the code and those tiers. The model keeps the seeds
worth searching for, adds what they miss, and returns one list, most relevant
first. Each tag has a `kind`, the #19 query it feeds (`syntactic`, `conceptual` or
`paradigm`), and a `source`: `seed` if it was already among the tiers, `llm` if the
model added it. The code sets `source`, not the model. A snippet declared in
another language goes without tiers, because the extractor is Python-only.

It lives in `llm_tags.py` (client, prompt, `TagSet`, `LlmTagError`), `tags_api.py`
(dependency, request/response models, error handler) and the route in `app.py`.
Merging the list with the tags the user edits is #22's.

```
POST /api/tags   {"source": "...", "language": "Python"}   # language optional
→ {"language": "Python",
   "tags": [{"tag": "sorted", "kind": "syntactic", "source": "seed"},
            {"tag": "itemgetter", "kind": "paradigm", "source": "llm"}, ...]}
```

Each kind holds at most 6 tags (`MAX_TAGS_PER_KIND`), one query's worth.

**Provider**: Google Gemini (`gemini-3.8-flash`) over plain REST with `httpx`. The
free tier needs no card, takes a JSON schema for the response. No `thinkingConfig` is sent: `thinkingBudget` is a 400 on the 3.x models. Key at <https://aistudio.google.com/apikey>; limits change, read
<https://ai.google.dev/gemini-api/docs/rate-limits>. Under the free-tier
[terms](https://ai.google.dev/gemini-api/terms) Google may use the content sent to
improve its products: fine for public code pasted into a search engine, not for
anything private.

**Configuration**, read like the GitHub token (environment, then `backend/.env`):

```
GEMINI_API_KEY=          # optional
GEMINI_MODEL=...         # optional, defaults to gemini-3.8-flash
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

## Result explanations (#43)

After a search, `POST /api/search/explain` asks the same model about every
result in one call. For each one it returns what the code offers next to the
snippet, one thing worth bringing into the snippet (empty when there is
nothing), and up to three ranges of its most interesting lines, which the page
underlines. It is stateless: the page sends back the snippet and the results it
already has, so nothing is kept between the two calls.

```
POST /api/search/explain
  {"source": "...",
   "results": [{"rank": 1, "repo": "o/r", "path": "a.py", "name": "top_keys",
                "start_line": 40, "code": "def top_keys(d, n=None): ..."}]}
→ {"explanations": [{"rank": 1,
                     "value": "Sorts keys by score like your snippet, and cuts to the top `n`.",
                     "suggestion": "Accept an optional `n` instead of returning every key.",
                     "highlights": [{"start": 42, "end": 42}]}]}
```

`rank` is the one `/api/search` gave each result, and keys the answer. A result
the model skipped is missing, never filled in. The prompt numbers each result's
lines with its file's line numbers so the model can point at them, and the
cleaning clips every range to the lines it saw. Each result's code is cut at
`MAX_CANDIDATE_CHARS`, on whole lines.

It lives in `result_explanations.py` (prompt, schema, cleaning), the models in
`search_api.py`, and the route in `app.py`. The call goes through the tag
service's `generate()`, so the configuration, the errors and their codes are
the LLM tag service's (above), quota included: each search now spends two model
calls, the tags and this one. A failure here leaves the results untouched.

Measured on `gemini-3.5-flash-lite` with a 15-line snippet and 10 results of
5–59 lines (#43): about 3 s (median of 4 runs), 5.1k tokens in and 0.8k out.
50 results took 8.6 s.

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
