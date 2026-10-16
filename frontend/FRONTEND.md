# Frontend

React + TypeScript + Vite frontend for LAB #1. `@` is aliased to `src/` (`vite.config.ts`, both tsconfigs).

One page in three steps (#38): paste or attach a Python snippet, confirm the tags
the search will use, read the results grouped by repository. It talks only to
the backend and knows nothing about GitHub's API. See `CLAUDE.md` at the repo
root for the layering and the visual system, and issue #1 for the pipeline.

## Running it

The page needs the backend (`uv run snippet-search` from `backend/`, see
`BACKEND.md`). It calls `VITE_API_URL`, `http://127.0.0.1:8000` by default; to
point it elsewhere, set it in `frontend/.env.local`:

```
VITE_API_URL=http://127.0.0.1:8001
```

The backend's CORS allows the Vite dev server on port 5173 only, so run
`pnpm dev` there.

| Backend route | Step |
| --- | --- |
| `POST /api/search/preview` | 2: the pool of tags by query kind, each from the AST or the model; with `tags`, which of the user's selection fit each query |
| `POST /api/search` | 3: the search, run with the confirmed `tags` |

A preview spends one LLM call and no GitHub budget, and rebuilding it while the
user edits spends neither. A search spends up to three
code-search requests out of 10 per minute, shared by everyone, and the first one
after a backend restart also loads UniXcoder.

## Commands

Run from `frontend/`, not from the repo root.

```
pnpm install
pnpm dev      # vite dev server
pnpm build    # tsc -b && vite build — typecheck is part of the build
pnpm lint     # eslint .
pnpm preview
pnpm test     # vitest run — single pass, exits non-zero on failure
```

## Tests

Vitest is the test runner (native to the Vite build tool, so `vitest.config.ts` merges `vite.config.ts` instead of restating the `@` alias or plugins). Tests are colocated `*.test.ts(x)` files next to the module they cover; import `describe`/`it`/`expect` explicitly from `'vitest'` rather than enabling `globals: true`, so test files typecheck under the existing `tsconfig.app.json` with no extra global types. Without globals, Testing Library doesn't clean up on its own: call `cleanup()` in an `afterEach`.

The page is the seam. `src/pages/Search.test.tsx` renders it in jsdom with
Testing Library, stubs both backend routes at the HTTP boundary with MSW, and
drives the steps the way a user does: paste or attach, read the tags, confirm,
read the results. Assertions are on what the page shows and what it sends,
never on component internals. To check a wait, hold the MSW response until the
test releases it, and move the clock with Vitest's fake timers.

- Run everything: `pnpm test`
- Run one file: `pnpm test src/pages/Search.test.tsx`
- Run by test name: `pnpm test -t "<name>"` (no extra `--` before `-t`, or the flag doesn't reach Vitest through pnpm)

`pnpm test` covers the frontend only. The Python service in `backend/` has its own runner (`uv run pytest`, from `backend/`) — see `BACKEND.md` at the repo root.

Test at the boundary of a unit: its input and its output. Don't assert internals
(regex patterns, intermediate arrays, prompt wording) — those are exactly what
gets tuned.
