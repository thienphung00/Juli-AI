# ADR-003: AI-Native CI/CD Policy

**Status:** Accepted
**Date:** 2026-05-27
**Deciders:** Product owner
**Supersedes:** none
**Related:** [ADR-001](001-keep-python-fastapi.md), [ADR-002](002-supabase-backend-service.md)

## Context

The repository is built and operated by AI agents using the skill chain in
[`.cursor/skills/`](../../.cursor/skills/). Conversations are session-local;
agents lose context across sessions. We have already accepted that:

- Backend runtime is Python/FastAPI ([ADR-001](001-keep-python-fastapi.md)).
- Persistent state lives in Supabase ([ADR-002](002-supabase-backend-service.md)).
- Modules are tracked in [`docs/architecture/map.md`](../architecture/map.md) with
  per-module `MODULE.md` files.
- The `build-feature` and `fix-bug` workflow skills chain `discover -> to-prd ->
  to-issues -> focus -> tdd -> review -> validate -> ship` and `qa -> focus -> tdd
  -> review -> validate -> ship` respectively.
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
   artifact under [`artifacts/`](../../artifacts/).
3. **CI/CD is the enforcer.** Every rule that can be checked deterministically
   is checked by a Python script in [`scripts/validate/`](../../scripts/validate/)
   wired into [`.github/workflows/`](../../.github/workflows/).

The policy is implemented as:

- A new `validate` skill ([`.cursor/skills/standalone/validate/SKILL.md`](../../.cursor/skills/standalone/validate/SKILL.md))
  inserted between `review` and `ship` in both workflow chains.
- Three GitHub Actions workflows: `pr.yml`, `release.yml`, `architecture-audit.yml`.
- Python validation and audit scripts under `scripts/validate/` and `scripts/ci/`.
- Three artifact directories: `artifacts/reviews/`, `artifacts/validation/`, `artifacts/releases/`.
- A root [`done.md`](../../done.md) checklist consumed by `check_done_md.py`.

The full implementation reference lives in
[`docs/ci/implementation-guide.md`](../ci/implementation-guide.md), with the
operational cheat sheet in [`docs/ci/quick-reference.md`](../ci/quick-reference.md)
and failure recovery in [`docs/ci/troubleshooting.md`](../ci/troubleshooting.md).

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
[`docs/ci/implementation-guide.md`](../ci/implementation-guide.md). Summary:

| Artifact | Producer | Consumer | Path |
|----------|----------|----------|------|
| Review | `review` skill | `validate` skill, `pr.yml` | `artifacts/reviews/review-issue-<n>.json` |
| Validation | `validate` skill, `pr.yml` | `ship` skill | `artifacts/validation/validation-issue-<n>.json` |
| Release | `ship` skill, `release.yml` | Future agents (rollback/hotfix) | `artifacts/releases/release-<version>.json` |
| Audit (nightly) | `architecture-audit.yml` | Triaged into GitHub issues | `artifacts/validation/audit-<date>.json` |

## Enforcement Rules

CI **must fail** on any of:

- Missing `artifacts/reviews/review-issue-<n>.json` for the PR's issue number.
- Review artifact `status: "FAIL"` or any `criticalFindings[*].severity == "CRITICAL"`.
- Acceptance criteria in the issue body not mapped to a named test (per
  `check_acceptance_mapping.py`).
- `MODULE.md` "Public Interfaces" out of sync with actual public symbols
  (per `check_module_drift.py`) for any Tier 1/2 module touched by the PR.
- Cyclic dependency among modules listed in [`docs/architecture/map.md`](../architecture/map.md).
- ADR required (architectural change) but no new file in `docs/decisions/`.
- Handoff document present (legacy `docs/handoffs/*.md`) but missing required
  sections per `check_handoff.py` (dormant gate; handoffs no longer required).
- Lint, type-check, unit test, integration test, or migration up/down/up failure.

CI **must warn (not fail)** on:

- More than 3 modules touched in a single PR — defer to the disjoint-modules
  rule in [`issue-workflow.mdc`](../../.cursor/rules/issue-workflow.mdc).
- Stale `MODULE.md` (no commits in 30+ days) — surfaced by the nightly audit.

## Consequences

**Skill chain (updated):**

```
build-feature: discover -> to-prd -> to-issues -> focus -> tdd -> review -> validate -> ship
fix-bug:       qa -> focus -> tdd -> review -> validate -> ship
```

**Files added:**

- `.cursor/skills/standalone/validate/SKILL.md`, `checks.md`
- `.github/workflows/pr.yml`, `release.yml`, `architecture-audit.yml`
- `scripts/ci/*.py`, `scripts/validate/*.py`
- `artifacts/{reviews,validation,releases}/.gitkeep`, `artifacts/README.md`
- `done.md`
- `docs/ci/implementation-guide.md`, `quick-reference.md`, `troubleshooting.md`

**Files updated:**

- [`.cursor/skills/standalone/review/SKILL.md`](../../.cursor/skills/standalone/review/SKILL.md) — emits review artifact
- [`.cursor/skills/standalone/ship/SKILL.md`](../../.cursor/skills/standalone/ship/SKILL.md) — consumes validation artifact, emits release artifact
- [`.cursor/skills/standalone/ship/ci-examples.md`](../../.cursor/skills/standalone/ship/ci-examples.md) — replaced with pointer to real workflows
- [`.cursor/skills/workflow/build-feature/SKILL.md`](../../.cursor/skills/workflow/build-feature/SKILL.md) and [`fix-bug/SKILL.md`](../../.cursor/skills/workflow/fix-bug/SKILL.md) — chain updated
- [`.cursor/skills/standalone/focus/routing-rules.md`](../../.cursor/skills/standalone/focus/routing-rules.md) — adds validation-stage routing
- [`.cursor/rules/dev-workflow.mdc`](../../.cursor/rules/dev-workflow.mdc) — CI/CD subsection

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

- Source policy and implementation drafts: `docs/ci/implementation-guide.md`,
  `docs/ci/quick-reference.md`, `docs/ci/troubleshooting.md`
- [`.cursor/rules/dev-workflow.mdc`](../../.cursor/rules/dev-workflow.mdc) — version control + CI/CD rule
- [`.cursor/rules/issue-workflow.mdc`](../../.cursor/rules/issue-workflow.mdc) — disjoint-modules concurrency rule
- [`docs/architecture/map.md`](../architecture/map.md) — authoritative module list
- [`EXECUTION.md`](../../EXECUTION.md) — single source of truth (plan + cross-session ownership)
