# Parallel status — Phase 2.6 exit gate (#407)

**Started:** 2026-07-23 · **Parent PRD:** [#395](https://github.com/thienphung00/Juli-AI/issues/395) · Meta prepares; Executor → Review

## Locked decisions

| # | Decision |
|---|----------|
| 1 | **Isolate** — single exit-gate issue; Playwright + CI wiring only |
| 2 | Blockers #401–#403 and #406 merged on `origin/main`; proceed on fresh worktree |
| 3 | Analytics (#404) and Settings (#405) are **non-blocking** per ADR-026 — no hard dependency in exit-gate suite |
| 4 | Open individual PR + CI green; sync-before-merge before merge |
| 5 | Review agent may push/PR |
| 6 | **No** `packages/contracts`, backend, or deploy-script behavior changes unless required to green Playwright |

## Current run

| Issue | Title | Modules (exclusive) | Status | Branch | Worktree | GitHub ops |
|-------|-------|---------------------|--------|--------|----------|------------|
| #407 | Demo E2E / responsive / a11y / deploy smoke | `apps/demo/e2e/**`, `apps/demo/playwright.config.ts`, `tests/unit/test_phase_2_6_demo_exit_gate.py`, `.github/workflows/pr.yml` (demo-e2e job) | **PR open — CI green** | `feature/issue-407-demo-exit-gate` | `.worktrees/issue-407` | Review holds |

Base SHA: `fc571251` (`origin/main`).

## Module ownership

| Path family | Owner |
|-------------|-------|
| `apps/demo/e2e/exit-gate/*.spec.ts` + helpers/fixtures | #407 |
| `apps/demo/playwright.config.ts`, `apps/demo/package.json` (`test:e2e`) | #407 |
| `apps/demo/src/components/decisions-page-client.tsx` (`?load=error` test hook) | #407 |
| `tests/unit/test_phase_2_6_demo_exit_gate.py` | #407 |
| `.github/workflows/pr.yml` `demo-e2e` job | #407 |
| `apps/demo` product UI (fix only if Playwright red) | #407 (minimal) |
| `infra/scripts/smoke-test-demo.sh` | **Read-only** (#406) |
| Analytics (#404) / Settings (#405) depth | **Optional** — conditional specs only |

## Meta caches

| Artifact | Path |
|----------|------|
| Parent | `agent-runtime/artifacts/workflow-cache/parent-cache-issue-395.json` |
| Child | `agent-runtime/artifacts/workflow-cache/issue-context-cache-407.json` |
| Scope alignment | `agent-runtime/artifacts/workflow-cache/scope-alignment-issue-407.md` |
| Gate dump | `agent-runtime/artifacts/meta-prepare-issue-407.json` — `readyForExecutor: true` |

Slice: `P2-6` · executorDomain: `ui-ux`

## Executor TDD entry

1. Worktree: `.worktrees/issue-407` on `feature/issue-407-demo-exit-gate`
2. Install: `pnpm install --filter @juli/demo... && pnpm --filter @juli/demo test:e2e:install`
3. Red → green loop: `pnpm --filter @juli/demo test:e2e` (desktop + mobile-web projects)
4. Contract gate: `python -m pytest tests/unit/test_phase_2_6_demo_exit_gate.py -q`
5. Full demo check: `pnpm check:demo`

### Playwright suite map (Meta scaffold)

| Spec | AC coverage |
|------|-------------|
| `e2e/exit-gate/decisions-journey.spec.ts` | Home → Decisions, priority WF1, all cards, approve → In Progress |
| `e2e/exit-gate/manual-refresh.spec.ts` | Manual Refresh from mutated state |
| `e2e/exit-gate/responsive-parity.spec.ts` | Desktop (960px) vs mobile-web (390px) IA parity |
| `e2e/exit-gate/accessibility.spec.ts` | axe, 44×44, keyboard, chart sr-only, reduced motion |
| `e2e/exit-gate/locale-and-assistance.spec.ts` | VI diacritics, truthful states, assistance regression |

**Expected Executor work:** green all Playwright specs; fix any app/a11y gaps surfaced; optionally add conditional Analytics deep-link spec if #404 behavior is present; do not block on Settings #405.

## GitHub ops

| Field | Value |
|-------|-------|
| **Owner** | Review holds ops lock (#407) |
| **PR** | https://github.com/thienphung00/Juli-AI/pull/488 |
| **Merge** | Individual PR; **sync-before-merge** onto current `origin/main` |
| **AFK** | Yes — Playwright + contract pytest, no live VPS |

### Remote op log

| Time (UTC) | Agent | Command | Issue |
|------------|-------|---------|-------|
| 2026-07-23T07:45Z | Meta | `git worktree add` + `meta_prepare_executor.py --issue 407 --force` → ready | #407 |
| 2026-07-23T08:35Z | Review | `git push` + `gh pr create` → https://github.com/thienphung00/Juli-AI/pull/488 | #407 |
| 2026-07-23T09:00Z | Review | fix import/build/e2e selectors + ADR-003 artifacts; push babysit CI | #407 |
| 2026-07-23T09:45Z | Review | CI all green on PR #488 (50 Playwright + artifact gates) | #407 |

## References

- Topology: [`worktree-branch-topology.md`](worktree-branch-topology.md)
- PRD exit gate: [`docs/product/phases/phase-2.6/PRD.md`](../product/phases/phase-2.6/PRD.md)
- ADR-026: [`docs/adr/026-phase-2.6-analytics-optional-exit-gate.md`](../adr/026-phase-2.6-analytics-optional-exit-gate.md)
- Public smoke: [`infra/scripts/smoke-test-demo.sh`](../../infra/scripts/smoke-test-demo.sh)
