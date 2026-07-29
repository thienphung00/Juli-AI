## Summary

<!-- What changed and why (1–3 sentences). Link issue(s): Fixes # -->

## Test plan

<!-- How you verified the change. Include commands or manual steps. -->

- [ ] Unit / integration / E2E tests added or updated as applicable
- [ ] Relevant test commands run locally (paste below)

```
<!-- e.g. PYTHONPATH=backend/src python -m pytest tests/unit/... -q -->
```

## Modular monolith review (required)

Every PR must answer the four questions from
[`docs/product/phases/modular-monolith-upgrade/PRD.md`](../docs/product/phases/modular-monolith-upgrade/PRD.md)
(§ PR review). Check each box only when true for this change.

- [ ] **Does it work?** — Tests (unit / integration / E2E as applicable).
- [ ] **Does it belong in this module?** — Ownership (routes, models, services, tables, tasks, Redis keys, integrations).
- [ ] **Did it create forbidden dependencies?** — Import-linter + cycle check.
- [ ] **Can this module still be extracted later?** — Architecture (deep module / facade discipline; no new god-file or cross-module internal reach-through).

> A green “tests only” PR that fails any of questions 2–4 is not merge-ready.
