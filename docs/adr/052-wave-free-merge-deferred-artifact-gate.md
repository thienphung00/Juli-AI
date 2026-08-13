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

## Superseded mechanism (2026-08)

**Maintainer-approved (#670 P1 Option A).** Point 6 above (deferred artifact gate) is amended in
**mechanism only** — the merge-time source-of-truth intent is unchanged. The artifact-volume cost
driver identified by the codebase-cleanliness audit (~820 committed verbose bodies / 3.4 MB,
growing per issue) is reconciled as follows:

- **What stays committed**: a compact per-issue record at `agent-runtime/artifacts/status/issue-<N>.json`
  (~15 lines) — `review.status`, `validation.status`, `sha256` of each verbose body, `artifactRef`,
  acceptance/finding metrics, `gateVersion`. Schema: `agent-runtime/docs/schemas/status-record.schema.json`.
- **What moves off git**: the verbose bodies previously committed under `agent-runtime/artifacts/{reviews,
  implementations,intent-reviews,validation,optimization}/`. They are still written to the working tree
  during the agent loop (Executor/Review/Validate read/write them unchanged via
  `agent-runtime/scripts/ci/common.py`) and are CI-artifact-retained on the issue-tier run; `.gitignore`
  now excludes their `*.json` bodies (recursively) from commits while `status/` remains tracked.
  Permanent object-storage archival of the retained bodies is a follow-up, not required for the gate.
- **Gate read-path change**: `wave_manifest.py`'s `validate_wave_artifacts()` (`--check-artifacts`) now
  reads `status/issue-<N>.json` per manifest issue and fails closed on a missing record or a non-PASS
  `review`/`validation` status, optionally sha256-verifying a body still present on disk
  (`--verify-integrity`). `.github/workflows/pr.yml`'s `artifact-gate` job invocation is unchanged —
  only the script's internal read path moved.
- **Migration**: `agent-runtime/scripts/ci/generate_status_records.py` is an idempotent one-shot that
  built the compact record for every existing review+validation pair (144 issues, including #660) from
  the verbose bodies before they were `git rm`'d.
- History purge (`git-filter-repo`) for the already-committed verbose bodies remains the separate
  maintenance cutover named in point 6 above — still deferred, still not gated inside this amendment.

## Narrow issue-tier exception (2026-08, #1064)

The "CI-artifact-retained on the issue-tier run" clause above (and the deferred-gate framing) was
found not implementable as written: `pr.yml` has no `upload-artifact` step for the five gitignored
body directories and cannot have one, since those bodies never reach the pushed branch (see #1064's
"Design correction before implementation" comment). Point 6's deferred-gate intent otherwise stands
unchanged; this note narrowly amends the *issue tier only*, not the mechanism described above.

**What changed:** an issue-tier PR whose head branch resolves to issue `<N>` now also fails when
`agent-runtime/artifacts/status/issue-<N>.json` is absent, or present but not `PASS` — job
`artifact-retention-guard` in `pr.yml`, backed by
`agent-runtime/scripts/ci/check_artifact_retention_guard.py`.

**Why this is not the re-run this ADR deferred:** the new job is an **existence + status read of
one already-committed JSON file** — the same read `wave_manifest.py`'s `--check-artifacts` performs
at wave→main, just reused at the point where a slice with no status record can still be cheaply
fixed. It does **not** re-run `meta_prepare_executor.py` or the `check_*.py` suite per issue push;
that cost driver (reason 2 in this ADR's Context) is untouched. The wave→main `artifact-gate` job is
unchanged and remains the authoritative merge-time gate.

**Why now:** ADR-079 (Wave 2 artifact disposition) named the gap this closes: *"A gate failing an
issue-tier PR whose branch matches `issue-<N>` when no implementation artifact was uploaded to CI
retention would have caught every one of [four artifact waivers]."* #1064 implements that gate
against the corrected, implementable target (the committed status record, not a nonexistent upload).
