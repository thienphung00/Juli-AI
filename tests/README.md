# tests/

`unit/` exercises one module through its public surface on an in-memory SQLite
engine; `integration/` crosses module boundaries and may need Postgres
(`tests.support.postgres.requires_postgres`). `support/` is the shared
infrastructure: builders, the authenticated API client stack, fakes, the
Postgres gate and a stepping clock.

Conventions and exemplars: `.cursor/skills/domain/testing-patterns/python-testing.md`.

Run from a worktree with the package path pinned, or the tests import whatever
`juli_backend` happens to be installed:

```bash
PYTHONPATH=backend/src python -m pytest tests/unit -q
```
