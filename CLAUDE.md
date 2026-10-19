# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo layout — read this first

`main` carries everything: the design sources plus the code, since `feature/initial-frontend` was merged in PR #16. Two codebases sit side by side, with separate toolchains:

- **`frontend/`** — the React + TypeScript + Vite frontend (`src/`, `package.json`, pnpm).
- **`backend/`** — the Python service (`pyproject.toml`, uv). It will hold the whole pipeline: proxy, tag extraction, AST stage and embeddings. So far, in `src/snippet_search/`: the proxy from #3, the LLM tags from #7, the grep tags, query building and pipeline from #4, the tag pool the user edits from #22 in `tag_selection.py`, the UniXcoder embedding stage from #21 in `embeddings/`, the AST stage from #20 in `ast_subtrees.py`, which also wired every stage into one run behind `POST /api/search`, the ranked result list from #8 in `results.py`, and the model's explanation of each result from #43 in `result_explanations.py`.
- **`docs/research/`** — the design sources: ~~`solution-schematics-v2.md`~~, `multiple-snippet-sorting-solution.md`, `unixcoder-verificacion.md`, the reference PDFs, `discussion.txt`, `tests.md` and the `generacion-de-tags-query.py` sketch. Committed sources, not generated output — cite them rather than re-deriving.
- **`docs/diagrams/`** — the architecture diagram (`lab-1.architecture.html`, generated from `lab-1.architecture.json`).
- **`docs/agents/`** — how agent skills should use this repo's tracker, labels and domain docs.

`origin/feature/initial-frontend` still exists but is behind `main`; work from `main`.

### Where backend code goes

The layout was settled in #30, after frontend and backend grew into one repo without a plan. The package is **`snippet_search`**, because it holds the whole pipeline, not just the proxy:

- **A stage is a flat module** in `src/snippet_search/` (`github.py`, `llm_tags.py`, ...). It gets a subpackage only when it spans several files, as `embeddings/` does: the vendored `unixcoder.py` plus the scoring.
- **`backend/tests/` is pytest only.** Manual runners and their inputs go in `backend/scripts/`, like the UniXcoder `tester.py`.
- **New code goes into the package**, not into a new top-level folder or a second package.

Source comments are written in Spanish, prose/UI strings in English. Follow suit; keep identifiers English. Issues are written in English too.

## Where the plan lives

**GitHub issue #1 is the spec.** It holds the pipeline, the decisions, what's out of scope and the ticket map. Read it before planning work — it's more current than any file in the repo.

~~`docs/research/solution-schematics-v2.md` is the authoritative pipeline description and supersedes the first version.~~ `multiple-snippet-sorting-solution.md` justifies the AST subtree filtering. `discussion.txt` is the original meeting notes: it's historical, written by the team to each other, and addresses people by name (*"Pelu, fijate que..."*). Read it as notes, not as spec prose.

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

**The two test commands are separate and neither runs the other**: `pnpm test` is Vitest over the frontend, `uv run pytest` is pytest over the Python service. See `frontend/FRONTEND.md` and `BACKEND.md` for how to run a single test in each. `docs/research/tests.md` is a captured API response, not a test suite; nothing runs in CI, because there is no CI.

## The pipeline

A GitHub-backed search engine: paste a snippet, get back ranked code on GitHub that does the same thing. Five stages, each matching on something different ~~(`docs/research/solution-schematics-v2.md`)~~:

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

## Frontend architecture

Everything in this section lives under `frontend/`, and the paths below are relative to it.

React 19, Vite 8, Tailwind v4 (via `@tailwindcss/vite`, not a PostCSS config), axios, and `prism-react-renderer` for highlighting. One page, no router. `@/` is aliased to `src/` in both `vite.config.ts` and the tsconfigs — use it rather than deep relative paths.

The page talks only to our backend, at `VITE_API_URL` (default `http://127.0.0.1:8000`, `src/constants/api.ts`), and knows nothing about GitHub's API. #38 built it, #22 added tag editing, #43 the result explanations and #9 the error taxonomy: the backend's stable `code` is what the page turns into copy, never GitHub's prose. Filters (#19) are still to come.

The directory names encode a layering that is worth respecting:

- `jsons/` — raw backend shapes, mirroring `/openapi.json` with only the fields read. `types/` — domain shapes the UI consumes.
- `model/` — no classes; `model/Search.ts` is the raw→domain mapping, and the boundary between `jsons/` and `types/` is crossed **here and only here**. Grouping results by repository happens here too.
- `services/` — axios calls. `common.ts::getAxiosData` is the single error funnel: every failed call becomes an `ApiError` carrying the backend's stable `code` (if any) and the status, or `null` for no response. Callers never touch `AxiosError`.
- `utility/` — pure helpers. `TagEdits.ts` toggles and adds tags on the domain shape. `ErrorCopy.ts` keys the user-facing copy by `code`, and also how each failure is printed: a `Severity` per code (`correctable` → the user changes the snippet or the tags, `transient` → nobody, wait, `setup` → whoever runs the service fixes a credential), a short type label and a one-line note per family. Neither the backend's `message` nor GitHub's text is ever shown. The model's failures on the results step have their own copy there, since the search itself didn't fail.
- `components/`, `pages/` — presentation. `pages/Search.tsx` holds the step state and the two calls. `components/StatusLine.tsx` prints a failure as a typed line — tone, type and stable code, then the copy — and `components/ErrorDialog.tsx` opens the type's family in a native `<dialog>` when that label is clicked.

There is no `README.md`: #2 renamed the stock Vite template readme to `FRONTEND.md` (now `frontend/FRONTEND.md`) and replaced it with real frontend docs.

### The three steps

`Search.tsx` keeps the snippet in its own state and everything else in one `Step` union (`types/Step.ts`): editing → loadingTags → confirming → searching → done, or failed (which step, and the error). Keep that shape when adding states.

1. **Snippet.** Pasted, or a `.py` file read into the same box. It is sent **untrimmed**: trimming strips the first line's indentation and breaks a pasted method.
2. **Tags.** `POST /api/search/preview` returns a pool of tags by kind, each marked AST or model and selected or not; the page notes when the model was unavailable and when the snippet didn't parse. The user toggles tags and adds their own, one input per group, so a tag's kind is its group (#22). After each edit the page sends the selection back to the preview, which rebuilds the queries without the model and says which tags won't fit; only the latest answer counts. Confirming sends exactly the selected tags in `/api/search`'s `tags` field, so the LLM isn't called twice.
3. **Results.** Each result is a subtree that may live in several repos (same blob). `toSearchOutcome` places it once, under the first of its `locations`, and lists the rest as "also in". Repos order by their best cosine, files and subtrees within them by cosine, ties by name. Then `/api/search/explain` fills in a note under each subtree, keyed by the `rank` the backend gave it; a late answer only lands if the page still shows the same outcome.

Both waits count elapsed seconds and lock the controls. Nothing found is a plain sentence, never the error style.

### Visual system

The token layer at the top of `src/index.css` is the portfolio's (`zmorgado/portfolio`, `app/globals.css`), copied verbatim; its ADR 0005 owns the palette. Change it there, then copy the block down. Tailwind sees the tokens through `@theme`, with its own palette and font stacks reset to `initial`, so `text-pencil` exists and `text-slate-600` doesn't. The Python code display adds the Om Theme's syntax inks as separate tokens (`--code-*`), shared through `src/utility/CodeTheme.ts` and used only there and in `SnippetForm`, never as UI colours. No raw hex outside that file (the favicon carries literals, with a comment saying why).

- Spectral for prose, IBM Plex Mono for data only: code, tags, paths, line ranges, scores, seconds.
- `--signal` for links, the system acting (including the lines the model underlines) and a correctable failure; `--pencil` for secondary text and a transient failure; `--alert` for a setup failure — a credential, the service, or the model key — whether it stops the step or only drops the model's tags, and at most one shows at a time. A failure always prints its type and stable code next to the tone, so colour is never the only signal (WCAG 1.4.1).
- No shadows, no filled cards, radius at most 2px. Colour transitions only; nothing loops. The page follows the system theme.
- Code highlighting reads the tokens too, but draws its inks from the Om Theme (`--code-*`): comments and docstrings in `--code-comment`, keywords and operators in `--code-keyword`, strings, functions, classes and constants in their own. The result blocks and the snippet paste box both use it. The paste box is a transparent `<textarea>` over a `Highlight` layer with the same type, so the code is coloured while you type and the textarea keeps the text, caret and scroll; both sit on the page colour, matching the site's background.

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
