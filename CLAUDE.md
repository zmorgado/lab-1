# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo layout — read this first

`main` carries everything: the design sources plus the code, since `feature/initial-frontend` was merged in PR #16. Two codebases sit side by side, with separate toolchains:

- **`frontend/`** — the React + TypeScript + Vite frontend (`src/`, `package.json`, pnpm).
- **`backend/`** — the Python service (`pyproject.toml`, uv). It will hold the whole pipeline: proxy, tag extraction, AST stage and embeddings. So far it has the proxy from #3 (`/health`, `/api/search/code`, `/api/contents`, in `src/code_search_proxy/`) and the UniXcoder embedding stage from #21 (`backend/services/`, a library the app doesn't call yet). Tags, AST and the orchestration are still to come.
- **`docs/research/`** — the design sources: `solution-schematics-v2.md`, `multiple-snippet-sorting-solution.md`, `unixcoder-verificacion.md`, the reference PDFs, `discussion.txt`, `tests.md` and the `generacion-de-tags-query.py` sketch. Committed sources, not generated output — cite them rather than re-deriving.
- **`docs/diagrams/`** — the architecture diagram (`lab-1.architecture.html`, generated from `lab-1.architecture.json`).
- **`docs/agents/`** — how agent skills should use this repo's tracker, labels and domain docs.

`origin/feature/initial-frontend` still exists but is behind `main`; work from `main`.

### Decided restructure, backend half not done yet

Frontend and backend grew into the same repo without a plan, so the layout is getting reshuffled. The frontend half is done: it moved out of the root into **`frontend/`**, so the root only holds `docs/`, `backend/`, `frontend/`, the agent files and `.gitignore`. Decided, still to be done, after #27 merges:

- The Python package **`code_search_proxy` is renamed `snippet_search`**, since it holds the whole pipeline and not just the proxy.
- **`backend/services/` moves into the package.** Stages are flat modules (`github.py`, `llm_tags.py`, ...), and a stage gets a subpackage only when it has several files. The embeddings stage does: the vendored `unixcoder.py` plus the ranking.
- **`backend/tests/` keeps only pytest.** The manual UniXcoder runner and its inputs move to `backend/scripts/`.

Until that lands, don't add new top-level folders or packages. New backend code goes flat into `src/code_search_proxy/`.

Source comments are written in Spanish, prose/UI strings in English. Follow suit; keep identifiers English. Issues are written in English too.

## Where the plan lives

**GitHub issue #1 is the spec.** It holds the pipeline, the decisions, what's out of scope and the ticket map. Read it before planning work — it's more current than any file in the repo.

`docs/research/solution-schematics-v2.md` is the authoritative pipeline description and supersedes the first version. `multiple-snippet-sorting-solution.md` justifies the AST subtree filtering. `discussion.txt` is the original meeting notes: it's historical, written by the team to each other, and addresses people by name (*"Pelu, fijate que..."*). Read it as notes, not as spec prose.

## Team and ownership

Three people, working on this as a research project / hobby. Ownership was agreed at the first meeting and the work is split by *concern*, not by layer:

| Person | Lane |
| --- | --- |
| **pelusa** ("pelu") — `@zmorgado` — programming technician, few years' professional experience | Reducing a pasted snippet to the terms most likely to be distinctive, and the AST work that grew out of it |
| **socio** — `@nicocernadas` — recently finished a programming associate's degree | Search options, filters, output review and parsing |
| **cebolla** — `@theonobile01` — studying data science, strong maths background | Embeddings, search improvements, how GitHub does this, research |

Consequences worth keeping in mind when planning work:

- A strictly vertical slice tends to cross all three lanes at once. Prefer slicing so that a ticket sits in one lane where possible, and call it out explicitly when a ticket genuinely spans two (#22 does, and says so).
- The lanes are a guide, not the tracker. **Who owns what is whatever the issue's assignee says**, and the team changes those by hand. Don't reassign to match this table.

## Commands

Frontend, from `frontend/`. Package manager is **pnpm** (`frontend/pnpm-lock.yaml`).

```
pnpm install
pnpm dev      # vite dev server
pnpm build    # tsc -b && vite build — typecheck is part of the build
pnpm lint     # eslint .
pnpm preview
pnpm test     # vitest run
```

Backend, from `backend/`. Package manager and task runner is **uv** (`backend/uv.lock`).

```
uv sync
uv run code-search-proxy   # the service on 127.0.0.1:8000; needs a GitHub token (BACKEND.md)
uv run pytest
```

**The two test commands are separate and neither runs the other**: `pnpm test` is Vitest over the frontend, `uv run pytest` is pytest over the Python service. See `frontend/FRONTEND.md` and `BACKEND.md` for how to run a single test in each. `docs/research/tests.md` is a captured API response, not a test suite; nothing runs in CI, because there is no CI.

## The pipeline

A GitHub-backed search engine: paste a snippet, get back ranked code on GitHub that does the same thing. Five stages, each matching on something different (`docs/research/solution-schematics-v2.md`):

1. **Tags** (#4, #7) — the GREP service pulls APIs, structures and domain words out of the snippet with regex. An LLM service names what the code *is*: algorithm, data structures, paradigm, calls. Grep is the baseline and works alone; the LLM is a complement.
2. **Tag selection** (#22) — both tag sources merge into one tier-ordered list, and the user can drop tags or add their own before searching.
3. **Code search** (#3, #19) — the tags become a `search/code` query, run server-side through an authenticated proxy. Cheap and imprecise on purpose: it just cuts GitHub down to a handful of candidates.
4. **AST** (#20) — the same GREP service parses the candidates, isolates subtrees by construct category, tag anchors and completeness, and prunes by length. It also produces the AST of the pasted snippet.
5. **Embeddings** (#18, #21) — UniXcoder embeds the snippet and the surviving candidates; cosine similarity ranks them. This is where "different text, same function" gets caught.

Then results (#8, #23): one ranked, deduplicated list with repo, path, the matching snippet, scores and the query that found it.

The diagram is `docs/diagrams/lab-1.architecture.html`, generated from the JSON beside it with the `archify` skill.

### Non-obvious constraints

- **GitHub code search matches 3-character trigrams**, strictly textual. It can't match on functional similarity — that's the entire reason the embedding stage exists.
- **The search bar has a character limit**, so a pasted snippet can't be sent whole and has to be reduced to distinctive fragments. Highest-signal terms are unique function names, class definitions and rare identifiers. Double quotes force exact-phrase matching.
- **Cosine similarity only**: `A·B / (‖A‖‖B‖)`, direction, magnitude ignored. Never sum vectors as a similarity score — that moves a point in the space instead of producing a scalar, and lets large-magnitude components distort the result.
- **AST depth encodes scope and structural containment, not human meaning.** Again, that's why the embedding step exists.
- **No vector store.** Candidates are embedded on demand and thrown away. Qdrant and anything like it are explicitly out of scope in #1.

## Frontend architecture

Everything in this section lives under `frontend/`, and the paths below are relative to it.

React 19, Vite 8, Tailwind v4 (via `@tailwindcss/vite`, not a PostCSS config), react-router v8 (`createBrowserRouter` in `src/router/`), axios, Phosphor icons. `@/` is aliased to `src/` in both `vite.config.ts` and the tsconfigs — use it rather than deep relative paths.

The directory names encode a layering that is worth respecting:

- `types/` — domain shapes the UI consumes. `jsons/` — raw GitHub response shapes, kept separate.
- `model/` — no classes; pure query construction (`SearchQuery.ts`) and raw→domain mapping (`Repository.ts` / `toRepository`). The boundary between `jsons/` and `types/` is crossed **here and only here**.
- `services/` — axios calls. `common.ts::getAxiosData` is the single error funnel: it unwraps GitHub's error body (`errors[].message` ?? `message`) and rethrows a plain `Error`, so callers never touch `AxiosError`.
- `utility/` — pure helpers *and* React hooks (`UseDismissable`, `UseFocusWhen`, `UseScrollIntoView`), despite the name.
- `components/`, `pages/`, `layouts/` — presentation. `pages/Search.tsx` holds essentially all search state and orchestration.

There is no `README.md`: #2 renamed the stock Vite template readme to `FRONTEND.md` (now `frontend/FRONTEND.md`) and replaced it with real frontend docs.

### The search flow, and why most of it is leaving

`Search.tsx` drives everything today: `buildQueryString` → client-side guards → `buildSearchQuery` → `searchRepoService.search` → `toSearchResult` → render. Chat state is a `Message` discriminated union (`user` | assistant `loading`/`error`/`done`), and a pending assistant message is swapped in place by id once the request settles — keep that shape when adding states.

**#19 moves the query building and the GitHub call to the backend.** The frontend keeps the chat state and the rendering, and stops knowing GitHub's URL. So treat everything below as a description of current code, not as a design to extend:

- **It calls `search/repositories`, not `search/code`.** The pipeline is about code search; this is the wrong endpoint.
- **The user's pasted message is not in the query yet** — `buildQueryString(_message, filters)` ignores its first argument (explicit `TODO`). Searches are driven purely by the owner/repoName/languages filters.
- **Repeated qualifiers act as OR** (`language:Go language:Rust`). The literal word `OR` does not work on qualifiers — GitHub answers "Logical operators only apply to text, not to qualifiers".
- Values containing whitespace must be quoted (`language:"Jupyter Notebook"`); `URLSearchParams` handles the rest of the encoding so `C#`/`C++` don't break the URL.
- `MAX_QUERY_LENGTH` (256) is checked against the **`q` value alone**, before the URL is assembled.
- Only `owner` is validated (`OWNER_PATTERN`), because it goes out as a `user:` qualifier and a bad value yields 422; `repoName` travels as free text with `in:name` and can't break the query.
- Requests are **unauthenticated** — no token is attached, so expect the low anonymous rate limit. `toSearchErrorMessage` maps GitHub's raw English error text to user-facing copy by substring matching (`"cannot be searched"`, `"longer than 256"`, `"rate limit"`); that coupling is brittle and #9 replaces it with error codes from the backend.

## Querying GitHub code search

The reference invocation and the exact response shape for the **code** endpoint are in `docs/research/tests.md`:

```
gh api -X GET search/code -f q='"_analyze_document_payload_sync" language:python'
```

Requires an authenticated `gh` CLI. Two things visible only in that sample output: results include **private** repos the authenticated user can see (`repository.private: true`), and the same blob `sha` recurs across repos — dedupe on `sha` when ranking, and private hits are excluded (#8).

`search/code` returns repo, path and sha, **not the file's contents**. The AST stage needs the actual code, so #3 also fetches files.

## Reference PDFs (`docs/research/`)

- `Vector-Embeding.pdf` — the full end-to-end embedding architecture (12 pp).
- `Resumen-Vector-Embeding.pdf` — cosine-similarity math and the pipeline map.
- `Resumen- Protocolo-AST.pdf` — AST definition, node structure, and the O(N)/O(M) complexity bounds.

## Agent skills

### Issue tracker

Issues and specs live as GitHub issues in `zmorgado/lab-1`, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, each label string equal to its name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. Neither exists yet. See `docs/agents/domain.md`.

## Unexplored: other code hosts

Idea from the team, not investigated yet: [gitee.com/explore/all](https://gitee.com/explore/all) and [gitcode.com](https://gitcode.com) as additional corpora to search. Both are in Chinese — translate the page. Nothing in the pipeline targets them; GitHub is the only host with a ticket.
