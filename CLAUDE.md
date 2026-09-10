# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Branch layout — read this first

The repo is split across two branches with almost nothing in common:

- `**main**` — design notes only (`discussion.txt`, reference PDFs, `tests.md`). No code, no tooling.
- `**origin/feature/initial-frontend**` — the actual application: a React + TypeScript + Vite frontend. Not merged into `main`, and it does not contain `tests.md`.

Check which branch you are on before concluding a file doesn't exist. Code work happens on the feature branch; the notes below under "Project: LAB #1" are the design intent that lives on `main`.

Source comments are written in Spanish, prose/UI strings in English. Follow suit; keep identifiers English.

## Team and ownership

Three people, working on this as a research project / hobby. Ownership was agreed at the first meeting and the work is split by *concern*, not by layer:

| Person | Lane |
| --- | --- |
| **pelusa** ("pelu") — `@zmorgado` — programming technician, few years' professional experience | Reducing a pasted snippet to the handful of terms most likely to be distinctive: unique function names, class declarations, rare identifiers |
| **socio** — `@nicocernadas` — recently finished a programming associate's degree | Search options, filters, output review and parsing |
| **cebolla** — `@theonobile01` — studying data science, strong maths background | Embeddings, search improvements, how GitHub does this, research |

Consequences worth keeping in mind when planning work:

- The lanes map onto the V0/V1 staging: pelu owns V0's recall reduction, socio owns everything around the query and its results, cebolla owns the V1 precision stage and the research feeding it.
- A strictly vertical slice tends to cross all three lanes at once. Prefer slicing so that a ticket sits in one lane where possible, and call it out explicitly when a ticket genuinely spans two.
- `discussion.txt` is written by the team to each other and addresses people by name (e.g. the note beginning *"Pelu, fijate que..."*). Read it as meeting notes, not as spec prose.

## Commands (feature/initial-frontend only)

Package manager is **pnpm** (`pnpm-lock.yaml`).

```
pnpm install
pnpm dev      # vite dev server
pnpm build    # tsc -b && vite build — typecheck is part of the build
pnpm lint     # eslint .
pnpm preview
```

There is **no test runner configured** — no test script, no vitest/jest dependency, no test files. `tests.md` on `main` is a captured API response, not a test suite. If asked to run tests, say so rather than inventing a command; adding a runner is a real (unmade) decision.

## Frontend architecture

React 19, Vite 8, Tailwind v4 (via `@tailwindcss/vite`, not a PostCSS config), react-router v8 (`createBrowserRouter` in `src/router/`), axios, Phosphor icons. `@/` is aliased to `src/` in both `vite.config.ts` and the tsconfigs — use it rather than deep relative paths.

The directory names encode a layering that is worth respecting:

- `types/` — domain shapes the UI consumes. `jsons/` — raw GitHub response shapes, kept separate.
- `model/` — no classes; pure query construction (`SearchQuery.ts`) and raw→domain mapping (`Repository.ts` / `toRepository`). The boundary between `jsons/` and `types/` is crossed **here and only here**.
- `services/` — axios calls. `common.ts::getAxiosData` is the single error funnel: it unwraps GitHub's error body (`errors[].message` ?? `message`) and rethrows a plain `Error`, so callers never touch `AxiosError`.
- `utility/` — pure helpers *and* React hooks (`UseDismissable`, `UseFocusWhen`, `UseScrollIntoView`), despite the name.
- `components/`, `pages/`, `layouts/` — presentation. `pages/Search.tsx` holds essentially all search state and orchestration.

`README.md` on that branch is the **stock Vite template readme**, not project documentation.

### The search flow

`Search.tsx` drives everything: `buildQueryString` → client-side guards → `buildSearchQuery` → `searchRepoService.search` → `toSearchResult` → render. Chat state is a `Message` discriminated union (`user` | assistant `loading`/`error`/`done`), and a pending assistant message is swapped in place by id once the request settles — keep that shape when adding states.

Non-obvious constraints already encoded in the code:

- **It calls `search/repositories`, not `search/code`.** This diverges from the V0 design on `main`, which is about code search. Treat the current frontend as a scaffold over the wrong endpoint unless told otherwise.
- **The user's pasted message is not in the query yet** — `buildQueryString(_message, filters)` ignores its first argument (explicit `TODO`). Searches are driven purely by the owner/repoName/languages filters.
- **Repeated qualifiers act as OR** (`language:Go language:Rust`). The literal word `OR` does not work on qualifiers — GitHub answers "Logical operators only apply to text, not to qualifiers".
- Values containing whitespace must be quoted (`language:"Jupyter Notebook"`); `URLSearchParams` handles the rest of the encoding so `C#`/`C++` don't break the URL.
- `MAX_QUERY_LENGTH` (256) is checked against the `**q` value alone**, before the URL is assembled.
- Only `owner` is validated (`OWNER_PATTERN`), because it goes out as a `user:` qualifier and a bad value yields 422; `repoName` travels as free text with `in:name` and can't break the query.
- Requests are **unauthenticated** — no token is attached, so expect the low anonymous rate limit. `toSearchErrorMessage` maps GitHub's raw English error text to user-facing copy by substring matching (`"cannot be searched"`, `"longer than 256"`, `"rate limit"`); that coupling is brittle and is the place to look when an error renders as a raw API string.

`src/mocks/mockAnswers.ts` is lorem-ipsum placeholder text, not fixtures.

## Project: LAB #1 (design intent, `main`)

A GitHub-backed search engine that, given a pasted snippet, finds where equivalent code already exists. Three stages (`discussion.txt`):

- **V0** — syntax-similarity search using GitHub's own code search, to cheaply reduce the search space.
- **V1** — embedded vector search as a second, fine-tuned filter over V0's reduced space, maximizing functional/conceptual comparison.
- **V2** — interactive web / plugin / MCP tool letting users vectorize their own code to feed V1.

The staging is the core architectural decision: V0 is a **recall** stage whose only job is to cut the corpus down (the notes cite &gt;99.99% reduction from language/stars filtering), and V1 is a **precision** stage that only ever runs on V0's survivors. Cost is what couples them — see open question (a).

### Why V0 alone is insufficient

GitHub code search matches on **3-character trigrams**, strictly textual — it cannot match on functional similarity or semantic concept. So:

- The search bar has a character limit; a pasted snippet cannot be sent whole and must be reduced to distinctive fragments.
- Highest-signal query terms are unique function names, class definitions, and rare variable names.
- Double quotes (`"function computeMatrix(a, b)"`) force exact-phrase matching.

### The V2 pipeline

Parse → embed → compare, as diagrammed in `discussion.txt` and detailed in `Vector-Embeding.pdf`:

1. **Parse** — incremental Tree-sitter parsing, O(N) in code length, to an AST; incremental re-parse of an edited region is O(M).
2. **Chunk** — split along AST scope boundaries (whole functions, class signatures) rather than by character or token count; strip syntactic noise (formatting, local names, comments) while keeping execution logic, control flow, and API/library invocations; enrich each chunk with parent AST metadata (`Class: AuthMiddleware -> Function: ValidateToken`) so a sliced sub-component keeps its context.
3. **Embed** — code-native model (UniXcoder / CodeBERT / `text-embedding-3-small`) to a dense vector (~768–1536 dims), indexed in a vector store (Qdrant is the one named).
4. **Rank** — cosine similarity `A · B / (||A|| ||B||)`, direction only, magnitude ignored; rerank and present equivalent code. Do not sum vectors as a similarity score — that moves a point in the space instead of producing a scalar and lets large-magnitude components distort the result.

AST depth encodes **scope and structural containment, not human meaning** — that is precisely why the embedding step exists.

### Open questions (from `discussion.txt`, unresolved)

a) Pick a critical number of V0 pulls, bounded by embedding cost plus the downstream vector-comparison cost (complexity bounds are in the pushed PDFs).
b) Decide the app/runtime the embedding runs on.
c) AST generation already ranks function importance, flags API calls, and drops insignificant tokens — so **V2's first stage and V0 may be the same process**. Worth resolving before building them separately.

## Querying GitHub code search

The reference invocation and the exact response shape for the **code** endpoint (the one V0 needs, and which the frontend does not yet use) are in `tests.md` on `main`:

```
gh api -X GET search/code -f q='"_analyze_document_payload_sync" language:python'
```

Requires an authenticated `gh` CLI. Two things visible only in that sample output: results include **private** repos the authenticated user can see (`repository.private: true`), and the same blob `sha` recurs across repos — dedupe on `sha` when ranking, and decide deliberately whether private hits should surface.

## Reference PDFs (`main`)

Committed sources, not generated output — cite them rather than re-deriving:

- `Vector-Embeding.pdf` — the full end-to-end embedding architecture (12 pp).
- `Resumen-Vector-Embeding.pdf` — cosine-similarity math and the pipeline map.
- `Resumen- Protocolo-AST.pdf` — AST definition, node structure, and the O(N)/O(M) complexity bounds.


## Agent skills

### Issue tracker

Issues and specs live as GitHub issues in `zmorgado/lab-1`, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, each label string equal to its name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
