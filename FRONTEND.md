# Frontend

React + TypeScript + Vite frontend for LAB #1. `@` is aliased to `src/` (`vite.config.ts`, both tsconfigs).

## Commands

```
pnpm install
pnpm dev      # vite dev server
pnpm build    # tsc -b && vite build — typecheck is part of the build
pnpm lint     # eslint .
pnpm preview
pnpm test     # vitest run — single pass, exits non-zero on failure
```

## Tests

Vitest is the test runner (native to the Vite build tool, so `vitest.config.ts` merges `vite.config.ts` instead of restating the `@` alias or plugins). Tests are colocated `*.test.ts` files next to the module they cover; import `describe`/`it`/`expect` explicitly from `'vitest'` rather than enabling `globals: true`, so test files typecheck under the existing `tsconfig.app.json` with no extra global types.

- Run everything: `pnpm test`
- Run one file: `pnpm test src/utility/ToggleArrayItem.test.ts`
- Run by test name: `pnpm test -t "<name>"` (no extra `--` before `-t`, or the flag doesn't reach Vitest through pnpm)
