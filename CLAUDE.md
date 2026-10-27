# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo layout — read this first

`main` carries everything: the design sources plus the code. Two codebases sit side by side, with separate toolchains:

- **`frontend/`** — the React + TypeScript + Vite frontend (`src/`, `package.json`, pnpm).
- **`backend/`** — the Python service (`pyproject.toml`, uv). It will hold the whole pipeline: proxy, tag extraction, AST stage and embeddings. So far, in `src/snippet_search/`: the proxy from #3, the LLM tags from #7, the grep tags, query building and pipeline from #4, the tag pool the user edits from #22 in `tag_selection.py`, the UniXcoder embedding stage from #21 in `embeddings/`, the AST stage from #20 in `ast_subtrees.py`, which also wired every stage into one run behind `POST /api/search`, the ranked result list from #8 in `results.py`, and the model's explanation of each result from #43 in `result_explanations.py`.
- **`docs/research/`** — the design sources: `multiple-snippet-sorting-solution.md`, `unixcoder-verificacion.md`, the reference PDFs (described in `docs/research/README.md`), `discussion.txt`, `tests.md` and the `generacion-de-tags-query.py` sketch. Committed sources, not generated output — cite them rather than re-deriving.
- **`docs/diagrams/`** — the architecture diagram (`lab-1.architecture.html`, generated from `lab-1.architecture.json`).
- **`docs/agents/`** — how agent skills should use this repo's tracker, labels and domain docs.

### Where backend code goes

The layout was settled in #30, after frontend and backend grew into one repo without a plan. The package is **`snippet_search`**, because it holds the whole pipeline, not just the proxy:

- **A stage is a flat module** in `src/snippet_search/` (`github.py`, `llm_tags.py`, ...). It gets a subpackage only when it spans several files, as `embeddings/` does: the vendored `unixcoder.py` plus the scoring.
- **`backend/tests/` is pytest only.** Manual runners and their inputs go in `backend/scripts/`, like the UniXcoder `tester.py`.
- **New code goes into the package**, not into a new top-level folder or a second package.

Source comments are written in Spanish, prose/UI strings in English. Follow suit; keep identifiers English. Issues are written in English too.

## Where the plan lives

**GitHub issue #1 is the spec.** It holds the pipeline, the decisions, what's out of scope and the ticket map. Read it before planning work — it's more current than any file in the repo.

`multiple-snippet-sorting-solution.md` justifies the AST subtree filtering. `discussion.txt` is the original meeting notes: it's historical, written by the team to each other, and addresses people by name (*"Pelu, fijate que..."*). Read it as notes, not as spec prose.

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
uv run snippet-search   # the service on 127.0.0.1:8000; needs a GitHub token (BACKEND.md)
uv run pytest
```

`ModuleNotFoundError: No module named 'snippet_search'` from `uv run`: a macOS flag on `.venv`, fixed under "Commands" in `BACKEND.md`.

**The two test commands are separate and neither runs the other**: `pnpm test` is Vitest over the frontend, `uv run pytest` is pytest over the Python service. See `frontend/FRONTEND.md` and `BACKEND.md` for how to run a single test in each. `docs/research/tests.md` is a captured API response, not a test suite; nothing runs in CI, because there is no CI.

## The pipeline

A GitHub-backed search engine: paste a snippet, get back ranked code on GitHub that does the same thing. Five stages, each matching on something different:

1. **Tags** (#4, #7) — the GREP service pulls APIs, structures and domain words out of the snippet with regex. An LLM service names what the code *is*: algorithm, data structures, paradigm, calls. Grep is the baseline and works alone; the LLM is a complement.
2. **Tag selection** (#22) — both tag sources merge into one weighted pool of up to 20 (`tag_selection.py`: own names and docstring and comment words, then calls, then imports), and the user picks tags and adds their own before searching.
3. **Code search** (#3, #19) — the tags become a `search/code` query, run server-side through an authenticated proxy. Cheap and imprecise on purpose: it just cuts GitHub down to a handful of candidates.
4. **AST** (#20) — the same GREP service parses the candidates, isolates subtrees by construct category, tag anchors and completeness, and prunes by length. It also produces the AST of the pasted snippet.
5. **Embeddings** (#18, #21) — UniXcoder embeds the snippet and the surviving candidates; cosine similarity ranks them. This is where "different text, same function" gets caught.

Then results (#8, #38): one ranked, deduplicated list with repo, path, the matching snippet, scores and the query that found it. Once they're on screen, the LLM explains each one (#43): what it offers next to the snippet, a suggestion for the snippet, and the lines to underline.

**Endpoints follow the user's steps, not the stages.** Each stage is a plain backend module, and `pipeline.py` chains them behind `POST /api/search`. A new stage plugs into `pipeline.search()`; a new endpoint is only for a new user step, like the tag preview (`POST /api/search/preview`, #38) the user confirms before searching. The confirmed tags go back in `/api/search`'s `tags` field, and the LLM isn't called twice. The one exception is `POST /api/search/explain` (#43): it isn't a step, but it runs apart so the results never wait for the model and a model failure never fails the search. It spends the same Gemini quota as the tags.

The diagram is `docs/diagrams/lab-1.architecture.html`, generated from the JSON beside it with the `archify` skill.

### Non-obvious constraints

- **GitHub code search matches 3-character trigrams**, strictly textual. It can't match on functional similarity — that's the entire reason the embedding stage exists.
- **The search bar has a character limit**, so a pasted snippet can't be sent whole and has to be reduced to distinctive fragments. Highest-signal terms are unique function names, class definitions and rare identifiers. Double quotes force exact-phrase matching.
- **Cosine similarity only**: `A·B / (‖A‖‖B‖)`, direction, magnitude ignored. Never sum vectors as a similarity score — that moves a point in the space instead of producing a scalar, and lets large-magnitude components distort the result.
- **AST depth encodes scope and structural containment, not human meaning.** Again, that's why the embedding step exists.
- **No vector store.** Candidates are embedded on demand and thrown away. Qdrant and anything like it are explicitly out of scope in #1.

## Frontend

**Frontend** work (the page, its state, styling): read `frontend/CLAUDE.md` first — the layering, the three steps and the visual system. Claude Code also loads it on its own once a file under `frontend/` is read.

## Querying GitHub code search

The reference invocation and the exact response shape for the **code** endpoint are in `docs/research/tests.md`:

```
gh api -X GET search/code -f q='"_analyze_document_payload_sync" language:python'
```

Requires an authenticated `gh` CLI. Two things visible only in that sample output: results include **private** repos the authenticated user can see (`repository.private: true`), and the same blob `sha` recurs across repos — dedupe on `sha` when ranking, and private hits are excluded (#8).

`search/code` returns repo, path and sha, **not the file's contents**. The AST stage needs the actual code, so #3 also fetches files.

## Agent skills

### Issue tracker

Issues and specs live as GitHub issues in `zmorgado/lab-1`, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, each label string equal to its name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. Neither exists yet. See `docs/agents/domain.md`.
