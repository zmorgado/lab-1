# Backend

Python service for LAB #1, living in `backend/`. It will hold the authenticated
GitHub code-search proxy (#3) and, later, V1's embedding stage — Python because
the embedding tooling (UniXcoder/CodeBERT-style) is Python-native regardless, so
one runtime beats a TS proxy plus a Python embedding service.

Right now it is scaffolding only: `src/code_search_proxy/` has no endpoints yet.

## Commands

Package manager and task runner is **uv** (`backend/uv.lock`). Run everything
from `backend/`; `uv run` creates and syncs `.venv` on its own, so there is no
separate activate step.

```
uv sync                 # install deps into backend/.venv
uv run pytest           # run the test suite — exits non-zero on failure
```

## Tests

`pytest` is the test runner, configured in `pyproject.toml` under
`[tool.pytest.ini_options]` rather than a separate `pytest.ini`. It is the runner
FastAPI's own docs are written against, so `TestClient` and app-config fixtures
work as documented once #3 lands the app.

The package uses a **src layout** (`src/code_search_proxy/`), and `uv run`
installs it editable, so tests import `code_search_proxy` as an installed package
— no `sys.path` juggling and no `conftest.py` needed for imports. Tests live in
`backend/tests/`, mirroring the module they cover, not colocated (that differs
from the frontend, where Vitest tests sit next to the source).

- Run everything: `uv run pytest`
- Run one file: `uv run pytest tests/test_package.py`
- Run one test by name: `uv run pytest tests/test_package.py::test_package_is_importable`
- Run every test matching a substring: `uv run pytest -k importable`

This is **separate from the frontend's `pnpm test`** (Vitest, run from the repo
root — see `FRONTEND.md`). Neither command runs the other; CI and local checks
need both.
