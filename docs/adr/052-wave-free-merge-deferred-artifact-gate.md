# ADR-052: Wave free-merge + deferred artifact gate

**Status:** Accepted  
**Date:** 2026-07-31  
**Deciders:** grill-with-docs (Architect)

**Builds on:** [ADR-003](003-ai-native-cicd-policy.md) (artifact-driven CI), [ADR-040](040-pr-safe-tests-lane.md) (PR-safe Tests), three-tier `pr.yml` (#657).  
**Does not change:** ADR-003 principles (conversation temporary, repo persistent, CI enforces); coverage floor on product pytest; live Partner only on `merge_group`; `release.yml` as the only deploy workflow.  
**Out of scope:** Agentic Eval Loop metrics instrumentation (follow-on); GitHub Merge Queue enablement on user-owned repos.

## Context

Parallel agents land path-disjoint issues into `feature/*-wave`, then open one wave → `main` PR. Three-tier CI (#657) already splits **issue** / **wave** / **main**, but:

1. Sibling merges into wave often re-fire issue-tier CI when only the **base** advanced — agents wait/rework for no head change (token + wall-clock cost).
2. ADR-003 artifact jobs (`validate-artifacts`, generate validation JSON, misnamed `ai-review`) still run on **every issue push**, the highest-frequency tier.
3. Wave push forced all path filters `true`, so “integration tier” behaved like a near-full suite instead of domain-matched checks.
4. Dropping CI artifact enforcement entirely (agent-local only) would speed today but remove the merge-time SoT a future autonomous eval loop needs.

## Decision

1. **Free-merge into wave.** No “up to date with base” requirement on `feature/*-wave`. Issue-tier workflow **skips** (or skips heavy jobs) when the PR **head SHA is unchanged** and only the wave base moved.
2. **Issue → wave CI (minimal).** `classify-tier`, `changes`, `gitleaks`, `policy-checks`, plus path-filtered `lint` / `typecheck` / PR-safe `test` / `frontend` / `demo-frontend`. **No** artifact validate/generate jobs on this tier.
3. **Wave push CI (domain-matched).** Path-filter against the push’s **before→after** SHAs. Run integration / architecture / cross-module contracts / dependency checks only for affected domains — **not** the full main suite.
4. **Wave → main CI.** Full / path-aware main-tier gates (regression, E2E, security, deploy readiness, live on `merge_group` when available) plus the **artifact-gate**.
5. **Wave manifest.** Committed file on the wave branch, e.g. `agent-runtime/artifacts/waves/wave-<id>.json` with `{ "issues": [/* ints */] }`. Each issue→wave PR **must** bump the manifest to include its issue number; issue-tier `policy-checks` fails if missing. `docs/handoffs/parallel-status*.md` remains human ops UI — not the CI parser.
6. **Deferred artifact gate (hybrid D).** Agents still produce per-issue review/validation artifacts in git. On wave→main, job **`artifact-gate`** (rename of `ai-review`) reads the manifest and asserts each listed issue’s artifacts exist with `status: PASS` (existence + status — not full `meta_prepare_executor` / `check_*.py` on every issue push).
7. **Rename.** Replace the `ai-review` job id/name with `artifact-gate` so CI is not mistaken for an LLM step.
8. **Eval metrics.** Do not block this ADR on an Agentic Eval Loop schema. Preserve merge-time artifact SoT so a future loop can extend validation JSON / sibling metrics without rebuilding enforcement.

## Consequences

- Parallel issue merges into a wave stop paying base-update CI thrash; wave push cost scales with what just landed.
- ADR-003 enforcement **timing** moves from issue PR to wave→main; artifact **presence** in the repo remains mandatory before main.
- Forgotten manifest bumps fail at issue→wave (`policy-checks`), not only at main.
- Implementers must update `pr.yml`, issue-workflow / topology docs, and classifier/status-check contracts; add unit tests for tier classification, base-skip, and manifest policy.
- Glossary: `CONTEXT.md` § CI / test lanes (`Three-tier CI`, `Free-merge (wave)`, `Wave artifact gate (D)`).
