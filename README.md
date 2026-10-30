# LAB #1 — Functional code snippet search on GitHub

Paste a Python snippet and get back ranked, functionally similar code from public GitHub repositories.

The pipeline reduces the snippet to searchable tags, runs those tags through GitHub's code search one query at a time, isolates the matching functions and classes, and ranks them with UniXcoder embeddings and cosine similarity. The LLM is a complement: it expands the tags and explains the results, but the search still works without it.

## Objective

The project's objective is to break the circular correction dynamic that appears when a developer and a coding agent iterate only on the model's own output. A design is generated, reviewed, corrected and regenerated, but the next turn still starts from the model's assumptions and training distribution, so the loop tends to reproduce the same kind of mistake.

LAB #1 interrupts that loop by putting external code in front of the agent user: code that differs in implementation but solves a similar problem, retrieved from public repositories instead of generated. The user can paste the snippet under discussion, confirm the tags, and bring the ranked references back into the conversation as concrete comparisons for the scenario at hand — a data structure, an API pattern, a parsing routine, a concurrency model, and so on. The references are evidence from code that already exists, not another model proposal.

Today this is a manual step: the page returns the references and the user decides what to bring back into the agent's context. There is no plugin, MCP server or agent skill in this version.

## Quick start

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/) for the backend, and Node.js with [pnpm](https://pnpm.io/) for the frontend.

### Backend

The service **will not start without a GitHub token**, because `search/code` rejects anonymous requests. The token can come from `GITHUB_TOKEN`, `backend/.env`, or an authenticated `gh` CLI, in that order.

```sh
cd backend

# Option A: export the token for this shell
export GITHUB_TOKEN=$(gh auth token)

# Option B: keep it in backend/.env (gitignored)
cp .env.example .env   # then fill in GITHUB_TOKEN

uv sync
uv run snippet-search  # http://127.0.0.1:8000
```

`GEMINI_API_KEY` is optional. With it, the model expands the tags and briefly notes the value and addable feature each result might containt in respects to the users snippet; without it, the backend starts normally, the search uses AST tags only, and the explanation step is unavailable. See [`backend/.env.example`](backend/.env.example).

### Frontend

```sh
cd frontend
pnpm install
pnpm dev               # http://localhost:5173
```

The page calls the backend at `VITE_API_URL` (`http://127.0.0.1:8000` by default; override it in `frontend/.env.local`). The backend's CORS allows the Vite dev server on port 5173.

### Tests

The commands are separate and neither runs the other. Neither needs a token or a network connection.

```sh
cd backend && uv run pytest    # Python service
cd frontend && pnpm test       # Vitest
```

## How the pipeline works

1. **Tags.** The snippet is parsed with Python's `ast` (with a regex fallback when it doesn't parse) and reduced to three tiers: APIs (imports and calls), structures (its own `def`/`class` names and lambdas) and domain words (docstrings and comments). If the model is configured, it adds `syntactic`, `conceptual` and `paradigm` tags. The tags merge into one weighted pool that the user can edit before searching.
2. **Queries.** Each tag kind becomes one `search/code` query, capped at 6 tags and 256 characters. The queries run **one after another**, not in parallel, because GitHub asks for serial requests to avoid secondary rate limits. Without the model — or when it returns nothing searchable — there is a single `tiers` query built from the AST tags.
3. **Code search.** GitHub returns repo, path and blob `sha`, but not the file contents. Candidate files are deduplicated by `sha`, private repositories are excluded, and the first 20 files are fetched through the authenticated proxy.
4. **AST isolation.** Each candidate file is cut down to top-level functions and methods (or top-level classes for a class snippet), keeping only subtrees that have a name, a real body, at least one matching anchor, and a length close to the snippet's. This is the stage that removes imports, headers and unrelated boilerplate.
5. **Embeddings.** The snippet and the surviving subtrees are embedded with `microsoft/unixcoder-base` into 768-dimensional vectors. Cosine similarity ranks them, which is what catches code that does the same thing with different text.
6. **Results.** The top results (10 by default, up to 50) are returned with rank, score, repo, path, line range and source. A public blob found in several repos is shown once. After the search, the model can explain what each result offers next to the snippet.

```
Pasted snippet
      │
      ▼
AST tags (APIs / structures / domain words) ──► optional LLM tags
      │                                              │
      └──────────────► tag pool, edited by the user ◄┘
                              │
                              ▼
       syntactic / conceptual / paradigm queries
       (one `tiers` query when the model is unavailable)
                              │
                              ▼  serial requests
                    GitHub code search
                              │
                              ▼
             dedupe by sha, drop private repos
                              │
                              ▼
        tree-sitter subtree isolation and pruning
                              │
                              ▼
        UniXcoder embeddings ──► cosine ranking
                              │
                              ▼
                  ranked code references
                              │
                              ▼
           optional LLM explanation per result
```

## Why retrieval

GitHub's code search matches 3-character trigrams, so it finds files that share *words* with the snippet, not files that *do the same thing*. `lambda t: t[1]` and `operator.itemgetter(1)` are the same function to us and different text to the index.

The embedding stage exists to close that gap. AST structure and search tags cut the candidate space down cheaply and imprecisely; UniXcoder and cosine similarity then compare the snippet and each surviving subtree by meaning. The result is a reference grounded in code that already exists publicly, rather than one generated from the model's training distribution.

There is no vector store: candidates are embedded on demand and discarded after the search.

## Repository layout

```
backend/   FastAPI service and every pipeline stage (uv)
frontend/  React + TypeScript + Vite page (pnpm)
docs/      research notes, diagrams and agent documentation
```

## Documentation

- [`BACKEND.md`](BACKEND.md) — endpoints, pipeline stages, configuration, error codes and backend commands.
- [`frontend/FRONTEND.md`](frontend/FRONTEND.md) — the three-step UI, frontend commands and frontend tests.
- [`docs/research/`](docs/research/) — the design sources: AST subtree sorting, UniXcoder verification and the reference PDFs.
- [`docs/diagrams/lab-1.architecture.html`](docs/diagrams/lab-1.architecture.html) — the architecture diagram, generated from the JSON beside it.
- [Issue #1](https://github.com/zmorgado/lab-1/issues/1) — the project's spec and ticket map.

This README is an overview. `BACKEND.md`, `FRONTEND.md` and `docs/research/` are the source of truth for the technical detail.
