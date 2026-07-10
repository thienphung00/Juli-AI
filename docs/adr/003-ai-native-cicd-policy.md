# ADR-003: AI-Native CI/CD Policy

**Status:** Accepted
**Date:** 2026-05-27
**Deciders:** Product owner
**Supersedes:** none
**Related:** [ADR-001](001-keep-python-fastapi.md), [ADR-002](002-supabase-backend-service.md)

## Context

**Harness routing (updated 2026):** Agent phases in [`agent-runtime/docs/agent-runtime.md`](../architecture/agent-runtime.md) supersede the workflow skills below. **CI gate ordering is unchanged.**

- The repository is built and operated by AI agents using skills in
  [`.cursor/skills/`](../../.cursor/skills/). Conversations are session-local;
  agents lose context across sessions. We have already accepted that:

- Backend runtime is Python/FastAPI ([ADR-001](001-keep-python-fastapi.md)).
- Persistent state lives in Supabase ([ADR-002](002-supabase-backend-service.md)).
- Modules are tracked in [`docs/architecture/map.md`](../architecture/map.md) with
  per-module `MODULE.md` files.
- _Historical:_ workflow skills `build-feature` / `fix-bug` chained planning and
  implementation; removed Phase 2 in favor of agent phases (see agent-runtime.md).
- Issue concurrency is governed by [`.cursor/rules/issue-workflow.mdc`](../../.cursor/rules/issue-workflow.mdc)
  using the disjoint-modules rule, with cross-session ownership tracked per slice
  in [`EXECUTION.md`](../../EXECUTION.md). _(Historical: a `docs/handoffs/` registry
  previously held this; removed in the seller-money rescope.)_

What is missing is a deterministic CI/CD enforcement layer. Today there are no
GitHub Actions workflows, no validation scripts, and no machine-verifiable
contract for what each skill must produce. Reviews and ship decisions are
conversational; if a session ends mid-feature, the next agent has only
free-form handoff prose to work from.

## Decision

Adopt an **artifact-driven CI/CD policy** with three principles:

1. **Conversation is temporary compute.** Decisions and review findings live in
   repository artifacts, not chat history.
2. **Repository is persistent memory.** Every gate consumes or emits a JSON
   artifact under [`artifacts/`](../../agent-runtime/artifacts/).
3. **CI/CD is the enforcer.** Every rule that can be checked deterministically
   is checked by a Python script in [`agent-runtime/scripts/validate/`](../../agent-runtime/scripts/validate/)
   wired into [`.github/workflows/`](../../.github/workflows/).

The policy is implemented as:

- A new `validate` skill ([`.cursor/skills/standalone/validate/SKILL.md`](../../.cursor/skills/standalone/validate/SKILL.md))
  inserted between `review` and `ship` in the Review Agent phase.
- Three GitHub Actions workflows: `pr.yml`, `release.yml`, `architecture-audit.yml`.
- Python validation and audit scripts under `agent-runtime/scripts/validate/` and `agent-runtime/scripts/ci/`.
- Three artifact directories: `agent-runtime/artifacts/reviews/`, `agent-runtime/artifacts/validation/`, `agent-runtime/artifacts/releases/`.
- A root [`done.md`](../../done.md) checklist consumed by `check_done_md.py`.

The full implementation reference lives in
[`docs/deployment/implementation-guide.md`](../ci/implementation-guide.md), with the
operational cheat sheet in [`docs/deployment/quick-reference.md`](../ci/quick-reference.md)
and failure recovery in [`docs/deployment/troubleshooting.md`](../ci/troubleshooting.md).

## Rationale

| Factor | Why this approach |
|--------|-------------------|
| Stateless agents | Next session reads `artifacts/`, not chat history |
| Existing skills | `review`, `ship`, `focus` already exist; we extend rather than replace |
| Tier-aware modules | Drift checks read [`docs/architecture/map.md`](../architecture/map.md); Tier 3 utilities stay exempt |
| Stack consistency | All gate scripts are Python (matches [ADR-001](001-keep-python-fastapi.md)); no Node tooling at the repo root |
| Issue workflow respect | "Modules touched" is a *warning*, not a hard fail; the disjoint-modules rule in [`issue-workflow.mdc`](../../.cursor/rules/issue-workflow.mdc) is the enforcement source |

## Artifact Schemas

The three JSON artifact schemas are defined in
[`docs/deployment/implementation-guide.md`](../ci/implementation-guide.md). Summary:

| Artifact | Producer | Consumer | Path |
|----------|----------|----------|------|
| Review | `review` skill | `validate` skill, `pr.yml`, Meta Agent | `agent-runtime/artifacts/reviews/review-issue-<n>.json` |
| Validation | `validate` skill, `pr.yml` | `ship` skill, Meta Agent | `agent-runtime/artifacts/validation/validation-issue-<n>.json` |
| Release | `ship` skill, `release.yml` | Future agents (rollback/hotfix) | `agent-runtime/artifacts/releases/release-<version>.json` |
| Audit (nightly) | `architecture-audit.yml` | Triaged into GitHub issues | `agent-runtime/artifacts/validation/audit-<date>.json` |
| Implementation | Executor Agent | Review Agent, Meta Agent | `agent-runtime/artifacts/implementations/implementation-issue-<n>.json` |
| Harness optimization | Meta Agent | Harness config | `agent-runtime/artifacts/optimization/harness-issue-<n>-<phaseRunId>.json` |
| Product-development optimization | Meta Agent | Architect Agent backlog | `agent-runtime/artifacts/optimization/product-development-<id>.json` |

Runtime schemas and persistence: [`agent-runtime/docs/agent-runtime-artifacts.md`](../architecture/agent-runtime-artifacts.md).

## Enforcement Rules

CI **must fail** on any of:

- Missing `agent-runtime/artifacts/reviews/review-issue-<n>.json` for the PR's issue number.
- Review artifact `status: "FAIL"`, any `criticalFindings[*].severity == "CRITICAL"`,
  `actionRequired: true` on any finding, legacy non-empty `warnings[]`, or
  `status` inconsistent with findings (e.g. WARNING findings with `status: "PASS"`).
- `PASS_WITH_WARNINGS` without per-finding `acceptanceByReviewer` + `ownerAck` +
  (`fixedInCommit` or `shipAsIsReason`), or without `reviewerSignoff` /
  `ownerSignoff` (per `check_findings_acknowledged.py`, `check_reviewer_signoff.py`,
  `check_owner_signoff.py`).
- Mandatory fail triggers (no override): CRITICAL security, production data
  exposure, test regression (`unit.failed > 0`), missing ML cold-start / promotion
  gate documentation, unresolved `priorReviewBlockers`, incomplete acceptance criteria.
- **Audited hotfix override:** `overriddenMerge` on the review artifact may clear
  *overridable* mandatory fails (test regression, ML gates, acceptance gaps, prior
  blockers) when `timestamp`, `overriddenBy`, `reason`, and `incidentLink` are set.
  CRITICAL security and production data exposure are **never** overridable.
- Acceptance criteria in the issue body not mapped to a named test (per
  `check_acceptance_mapping.py`).
- `MODULE.md` "Public Interfaces" out of sync with actual public symbols
  (per `check_module_drift.py`) for any Tier 1/2 module touched by the PR.
- Cyclic dependency among modules listed in [`docs/architecture/map.md`](../architecture/map.md).
- ADR required (architectural change) but no new file in `docs/adr/`.
- Handoff document present (legacy `docs/handoffs/*.md`) but missing required
  sections per `check_handoff.py` (dormant gate; handoffs no longer required).
- Lint, type-check, unit test, integration test, or migration up/down/up failure.

CI **must warn (not fail)** on:

- More than 3 modules touched in a single PR — defer to the disjoint-modules
  rule in [`issue-workflow.mdc`](../../.cursor/rules/issue-workflow.mdc).
- Stale `MODULE.md` (no commits in 30+ days) — surfaced by the nightly audit.

## Hotfix override policy (`overriddenMerge`)

Production incidents may require merging before every gate is green. Overrides are
**audited, not silent**:

| Field | Required | Purpose |
|-------|----------|---------|
| `timestamp` | Yes | When the override was approved |
| `overriddenBy` | Yes | Approver identity (email/handle) |
| `reason` | Yes | Why P0 impact outweighs the gate |
| `incidentLink` | Yes | Incident id or URL (e.g. `INC-789`) |

**Never overridable:** CRITICAL security findings, production data exposure, any
`severity: CRITICAL` finding, `actionRequired: true`.

**Overridable with audit trail:** test regression, missing ML gate documentation,
incomplete acceptance mapping, unresolved `priorReviewBlockers`.

Review `status` remains `FAIL` when gates fail; validation passes only when
`overriddenMerge` is valid and no non-overridable blockers remain.

## Accepted risk vs planned debt

| Field | When to use |
|-------|-------------|
| `shipAsIsReason` | Risk accepted at current scale; ship without fixing |
| `targetFixDate` | Known debt with a planned fix date |
| `fixedInCommit` | Finding resolved in this PR |

## Post-deployment feedback (`productionOutcome`)

After ship, link production incidents back to the finding that was accepted:

```json
"productionOutcome": {
  "incidents": [{
    "incidentId": "INC-456",
    "linkedFinding": "find-140-threshold",
    "shipAsIsReason": "acceptable at current scale",
    "actualOutcome": "False positive rate spiked; was NOT acceptable",
    "timestamp": "2026-07-15T09:00:00Z"
  }]
}
```

The nightly architecture audit surfaces `productionOutcome` mismatches (accepted
risk that failed in production) for harness tuning. This field does not block merge.

## ML gate verification

`mlGates.coldStartThresholdDocumented` and `promotionGateDocumented` are necessary
but not sufficient. `check_ml_gates.py` also scans source:

- **Cold-start:** `thresholds.py` in touched inference modules (`ad_performance`,
  `anomaly`, `seller_stage`) must define required constants (e.g.
  `SPARSE_HISTORY_MIN_IMPRESSIONS`).
- **Promotion:** `src/modules/ml/artifacts/thresholds.py` must define promotion
  constants when any trainer module is touched.
- **Optional cross-check:** `mlGates.thresholds` values are verified against source
  when declared.

## Consequences

**Skill chain (harness — see agent-runtime.md):**

```
Planning:       focus -> to-prd -> to-issues
Implementation: focus (Meta) -> Executor (built-in TDD)
Review:         review -> validate -> ship
Bug filing:     qa -> focus -> Executor -> review -> validate -> ship
```

**Files added:**

- `.cursor/skills/standalone/validate/SKILL.md`, `checks.md`
- `.github/workflows/pr.yml`, `release.yml`, `architecture-audit.yml`
- `agent-runtime/scripts/ci/*.py`, `agent-runtime/scripts/validate/*.py`
- `artifacts/{reviews,validation,releases}/.gitkeep`, `artifacts/README.md`
- `done.md`
- `docs/deployment/implementation-guide.md`, `quick-reference.md`, `troubleshooting.md`

**Files updated:**

- [`.cursor/skills/standalone/review/SKILL.md`](../../.cursor/skills/standalone/review/SKILL.md) — emits review artifact
- [`.cursor/skills/standalone/ship/SKILL.md`](../../.cursor/skills/standalone/ship/SKILL.md) — consumes validation artifact, emits release artifact
- [`.cursor/skills/standalone/ship/ci-examples.md`](../../.cursor/skills/standalone/ship/ci-examples.md) — replaced with pointer to real workflows
- [`agent-runtime/docs/agent-runtime.md`](../architecture/agent-runtime.md) — agent phase harness (Phase 2)
- [`.cursor/skills/standalone/focus/routing-rules.md`](../../.cursor/skills/standalone/focus/routing-rules.md) — adds validation-stage routing
- [`.cursor/rules/git-baseline.mdc`](../../.cursor/rules/git-baseline.mdc) — CI/CD subsection

**Operational impact:**

- Every PR now requires a review artifact in the branch before CI passes.
- Releases automatically generate rollback metadata.
- The nightly audit can autonomously open architecture-debt issues.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Keep CI conversational (chat-driven review) | Sessions are stateless; loses memory at every handoff |
| Adopt the policy verbatim with Node tooling | Conflicts with [ADR-001](001-keep-python-fastapi.md); introduces a parallel runtime |
| Add `validate` logic into `review` skill | Mixes generation (artifacts) with assertion (gates); harder to debug failures in CI |
| Use `adr-NNN.md` filenames as proposed in the source policy | Breaks the existing `NNN-slug.md` convention used by ADR-001/002 |

## References

- Source policy and implementation drafts: `docs/deployment/implementation-guide.md`,
  `docs/deployment/quick-reference.md`, `docs/deployment/troubleshooting.md`
- [`.cursor/rules/git-baseline.mdc`](../../.cursor/rules/git-baseline.mdc) — version control + CI/CD rule
- [`.cursor/rules/issue-workflow.mdc`](../../.cursor/rules/issue-workflow.mdc) — disjoint-modules concurrency rule
- [`docs/architecture/map.md`](../architecture/map.md) — authoritative module list
- [`EXECUTION.md`](../../EXECUTION.md) — single source of truth (plan + cross-session ownership)
