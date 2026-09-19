# Backend

Python service for LAB #1, living in `backend/`. It holds the whole pipeline —
see the stack decision on #3 for why it is Python rather than Node/TS:

- the authenticated GitHub proxy: code search and file fetching (#3)
- query building and execution, moved out of the frontend (#19)
- grep tag extraction (#4) and the LLM tag service (#7)
- the AST stage: parse, isolate subtrees, prune (#20)
- the embedding stage: UniXcoder + cosine ranking (#21, after the #18 spike)
- the result mapper the frontend renders (#8) and error codes (#9)

Right now it is scaffolding only: `src/code_search_proxy/` has no endpoints yet.
#3 is the first one and brings the app skeleton with it. Issue #1 is the spec.

## Commands

Package manager and task runner is **uv** (`backend/uv.lock`). Run everything
from `backend/`; `uv run` creates and syncs `.venv` on its own, so there is no
separate activate step, and `.python-version` pins the interpreter (3.12) so the
lockfile resolves the same way for everyone.

```
uv sync                 # install deps into backend/.venv
uv run pytest           # run the test suite — exits non-zero on failure
```

## Tests

`pytest` is the test runner, configured in `pyproject.toml` under
`[tool.pytest.ini_options]` rather than a separate `pytest.ini`. It is the runner
FastAPI's own docs are written against, so `TestClient` and app-config fixtures
work as documented once #3 lands the app.

The package uses a **src layout** (`src/code_search_proxy/`), and `uv sync`
installs it editable, so tests import `code_search_proxy` as an installed package
— no `sys.path` juggling and no `conftest.py` needed for imports. Tests live in
`backend/tests/`, mirroring the module they cover, not colocated (that differs
from the frontend, where Vitest tests sit next to the source).

- Run everything: `uv run pytest`
- Run one file: `uv run pytest tests/test_package.py`
- Run one test by name: `uv run pytest tests/test_package.py::test_package_is_importable`
- Run every test matching a substring: `uv run pytest -k importable`

This is **separate from the frontend's `pnpm test`** (Vitest, run from the repo
root — see `FRONTEND.md`). Neither command runs the other, so a full local check
means running both. Nothing enforces that yet: the repo has no CI.
