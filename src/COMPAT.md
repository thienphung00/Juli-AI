# `src/` compatibility shims (issue #252)

Runtime Python code moved to `backend/`. Import paths under `src/` are thin
re-exports so existing deploy entrypoints (e.g. `uvicorn src.apps.api_gateway.api.main:app`)
and Alembic tooling keep working until deploy config is updated in a later slice.

New code and tests should import from `backend.*` only.
