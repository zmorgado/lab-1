# Frontend

Paths here are relative to `frontend/`. Running it, the commands and the tests are in `FRONTEND.md`.

React 19, Vite 8, Tailwind v4 (via `@tailwindcss/vite`, not a PostCSS config), axios, and `prism-react-renderer` for highlighting. One page, no router. `@/` is aliased to `src/` in both `vite.config.ts` and the tsconfigs — use it rather than deep relative paths.

The page talks only to our backend, at `VITE_API_URL` (default `http://127.0.0.1:8000`, `src/constants/api.ts`), and knows nothing about GitHub's API. The backend's stable `code` is what the page turns into copy, never GitHub's prose. There are no filters yet.

The directory names encode a layering that is worth respecting:

- `jsons/` — raw backend shapes, mirroring `/openapi.json` with only the fields read. `types/` — domain shapes the UI consumes.
- `model/` — no classes; `model/Search.ts` is the raw→domain mapping, and the boundary between `jsons/` and `types/` is crossed **here and only here**. Grouping results by repository happens here too.
- `services/` — axios calls. `common.ts::getAxiosData` is the single error funnel: every failed call becomes an `ApiError` carrying the backend's stable `code` (if any) and the status, or `null` for no response. Callers never touch `AxiosError`.
- `utility/` — pure helpers. `TagEdits.ts` toggles and adds tags on the domain shape. `ErrorCopy.ts` keys the user-facing copy by `code`, and also how each failure is printed: a `Severity` per code (`correctable` → the user changes the snippet or the tags, `transient` → nobody, wait, `setup` → whoever runs the service fixes a credential), a short type label and a one-line note per family. Neither the backend's `message` nor GitHub's text is ever shown. The model's failures on the results step have their own copy there, since the search itself didn't fail.
- `components/`, `pages/` — presentation. `pages/Search.tsx` holds the step state and the two calls. `components/StatusLine.tsx` prints a failure as a typed line — tone, type and stable code, then the copy — and `components/ErrorDialog.tsx` opens the type's family in a native `<dialog>` when that label is clicked.

## The three steps

`Search.tsx` keeps the snippet in its own state and everything else in one `Step` union (`types/Step.ts`): editing → loadingTags → confirming → searching → done, or failed (which step, and the error). Keep that shape when adding states.

1. **Snippet.** Pasted, or a `.py` file read into the same box. It is sent **untrimmed**: trimming strips the first line's indentation and breaks a pasted method.
2. **Tags.** `POST /api/search/preview` returns a pool of tags by kind, each marked AST or model and selected or not; the page notes when the model was unavailable and when the snippet didn't parse. The user toggles tags and adds their own, one input per group, so a tag's kind is its group (#22). After each edit the page sends the selection back to the preview, which rebuilds the queries without the model and says which tags won't fit; only the latest answer counts. Confirming sends exactly the selected tags in `/api/search`'s `tags` field, so the LLM isn't called twice.
3. **Results.** Each result is a subtree that may live in several repos (same blob). `toSearchOutcome` places it once, under the first of its `locations`, and lists the rest as "also in". Each file says which queries found it, the full `q` behind a collapsed line. Repos order by their best cosine, files and subtrees within them by cosine, ties by name. Then `/api/search/explain` fills in a note under each subtree, keyed by the `rank` the backend gave it; a late answer only lands if the page still shows the same outcome.

Both waits count elapsed seconds and lock the controls. Nothing found is a plain sentence, never the error style.

## Visual system

The token layer at the top of `src/index.css` is the portfolio's (`zmorgado/portfolio`, `app/globals.css`), copied verbatim; its ADR 0005 owns the palette. Change it there, then copy the block down. Tailwind sees the tokens through `@theme`, with its own palette and font stacks reset to `initial`, so `text-pencil` exists and `text-slate-600` doesn't. The Python code display adds the Om Theme's syntax inks as separate tokens (`--code-*`), shared through `src/utility/CodeTheme.ts` and used only there and in `SnippetForm`, never as UI colours. No raw hex outside that file (the favicon carries literals, with a comment saying why).

- Spectral for prose, IBM Plex Mono for data only: code, tags, paths, line ranges, scores, seconds.
- `--signal` for links, the system acting (including the lines the model underlines) and a correctable failure; `--pencil` for secondary text and a transient failure; `--alert` for a setup failure — a credential, the service, or the model key — whether it stops the step or only drops the model's tags, and at most one shows at a time. A failure always prints its type and stable code next to the tone, so colour is never the only signal (WCAG 1.4.1).
- No shadows, no filled cards, radius at most 2px. Colour transitions only; nothing loops. The page follows the system theme.
- Code highlighting reads the tokens too, but draws its inks from the Om Theme (`--code-*`): comments and docstrings in `--code-comment`, keywords and operators in `--code-keyword`, strings, functions, classes and constants in their own. The result blocks and the snippet paste box both use it. The paste box is a transparent `<textarea>` over a `Highlight` layer with the same type, so the code is coloured while you type and the textarea keeps the text, caret and scroll; both sit on the page colour, matching the site's background.
