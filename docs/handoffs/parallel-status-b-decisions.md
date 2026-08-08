# Parallel status — Head Meta 3.5-B (Continuous CDP Decisions)

**Status: IN PROGRESS** (2026-08-08)
**Parent PRD:** [#599](https://github.com/thienphung00/Juli-AI/issues/599)
**Integration branch:** `feature/b-decisions-wave` (`.worktrees/b-decisions-wave`), cut from `origin/main` @ `9e9e4ad1`
**Head Meta:** owns this file, slice routing registration, ops-lock arbitration, exit gate

## Epic gate — READ FIRST

#599 is **blocked on A1 Speed (#601) exit** per ADR-047. **A1 has not exited:**
[#780](https://github.com/thienphung00/Juli-AI/issues/780) is open — `ctor` and `live_hours`
have no bronze domain, so 3 of the 5 Demo Main KPIs resolve `unavailable` on every reconcile.

**Operator decision (2026-08-08):** build 3.5-B on this wave branch anyway. The gate is a
*sequencing* gate, not a technical one — B-1 extends the already-merged #627 orchestrator,
which does not depend on the missing bronze domains.

**Hard constraint:** `feature/b-decisions-wave` → `main` is **not** authorized until #780
closes and #601 exit is confirmed. Issue PRs merge into the wave only.

## Slice DAG

```
B-1 #713 → B-2 #714 → B-3 #715 ─┬→ B-4 #716 ─┐
                                └→ B-5 #717 ─┴→ B-6 #718
```

Parallelism is available only at **#716 ∥ #717**; the rest is a strict chain.

## Locked decisions

| # | Decision |
|---|----------|
| 1 | PR base = `feature/b-decisions-wave`, never `main` |
| 2 | Head Meta alone edits this file and `agent-runtime/config/slices/B-*.yml` |
| 3 | Executor domain is `backend` for all six slices — never dual-load `data-platform` |
| 4 | Postgres is SoT for candidates + emission state; Redis read-through only (ADR-038/ADR-021) |
| 5 | #716 and #718 are public-surface slices — release-evidence plan required before Executor |
| 6 | Wave → `main` exit gate blocked on #780 / #601 exit (see above) |

## Issue board

| Issue | Slice | Domain | Worktree / branch | Gate | Status |
|-------|-------|--------|-------------------|------|--------|
| [#713](https://github.com/thienphung00/Juli-AI/issues/713) | B-1 | backend | `.worktrees/issue-713` / `feature/issue-713` | readyForExecutor: true | Executor DONE (`2403bdfe`) — Review running |
| [#714](https://github.com/thienphung00/Juli-AI/issues/714) | B-2 | backend | `.worktrees/issue-714` / `feature/issue-714` | readyForExecutor: true | Executor running (pipelined off `feature/issue-713`) |
| [#715](https://github.com/thienphung00/Juli-AI/issues/715) | B-3 | backend | pending | readyForExecutor: true | blocked on #714 |
| [#716](https://github.com/thienphung00/Juli-AI/issues/716) | B-4 | backend | pending | readyForExecutor: true | blocked on #715 |
| [#717](https://github.com/thienphung00/Juli-AI/issues/717) | B-5 | backend | pending | readyForExecutor: true | blocked on #715 |
| [#718](https://github.com/thienphung00/Juli-AI/issues/718) | B-6 | backend | pending | readyForExecutor: true | blocked on #716 + #717 |

## Executor environment — mandatory

`juli_backend` is installed into the ambient python (`/opt/homebrew/anaconda3`) as an
editable install pointing at the **main checkout**. A bare `python -m pytest` inside any
worktree therefore imports the wrong source tree, and the main checkout is parked on an
unrelated stale branch. Every Executor and the Review agent must run:

```bash
PYTHONPATH=$PWD/backend/src python -m pytest <paths> -q
```

Verify with `PYTHONPATH=$PWD/backend/src python -c "import juli_backend;print(juli_backend.__file__)"` —
the path must be inside the worktree. Baseline on this wave with the fix applied:
`test_cdp_speed_shared_compute_orchestrator.py test_scoring.py test_action_cards_contract.py`
= **44 passed**. Full `tests/unit` on the wave base: **2239 passed, 5 skipped** (94s).

## Pipelining

Issue branches chain off their predecessor rather than waiting for the wave merge:
`feature/issue-714` is cut from `feature/issue-713`, not from the wave. Each branch is
rebased onto the wave once its predecessor's PR lands, so the wave history stays linear
and a slice never waits on its predecessor's Review to start.

## Ops lock

**Holder:** Head Meta. Stagger remote ops ≥30s; one PR push/merge at a time. Only #716 and
#717 ever run concurrently — they are path-disjoint (emission budget persistence vs dry-run
execution module).

## Exit gate (wave → main)

- [ ] All six slices merged into `feature/b-decisions-wave`, Review + validate PASS each
- [ ] Release-evidence plans committed for #716 and #718
- [ ] Dry-run isolation test proves no `/v1/executions`, `enqueue_approved_tool`, or `run_tool_async` on the Demo path
- [ ] **#780 closed and #601 A1 exit confirmed** — hard prerequisite, operator sign-off
- [ ] `feature/b-decisions-wave` → `main` PR green
