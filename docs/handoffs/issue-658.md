# PRD #658 — Wave free-merge CI

## Goal

Reduce parallel-agent token, wall-clock, and CI cost without weakening the
merge-time quality record:

- issue → wave: minimal path-filtered checks; skip base-only updates;
- wave push: before→after, domain-matched integration checks;
- wave → main: main-tier checks plus a deterministic artifact gate.

## Decisions

- Path-disjoint sibling issues free-merge into `feature/*-wave`; wave branches
  do not require “up to date with base”.
- Every issue PR adds itself to a committed
  `agent-runtime/artifacts/waves/wave-<id>.json` manifest.
- Per-issue review and validation artifacts remain in git.
- CI enforces artifact existence and PASS status only on wave → main.
- Rename `ai-review` to `artifact-gate`; the job is deterministic, not an LLM
  call.
- Preserve gitleaks and ADR-040 live-test policy.

## Slices

1. **CI-WAVE-1 / #659:** manifest contract and deterministic validator.
2. **CI-WAVE-2 / #660:** issue free-merge, manifest policy, deferred artifact
   gate.
3. **CI-WAVE-3 / #661:** before→after domain-matched wave checks.
4. **CI-WAVE-4 / #662:** ADR/docs alignment and rollout verification.

## Out of scope

- Agentic Eval Loop metrics schema or dashboards.
- GitHub Merge Queue enablement.
- Production deployment behavior.
- Product application changes.

## Release evidence

CI changes affect merge eligibility and release workflow configuration, so each
child must preserve a candidate-verification plan, workflow/static checks,
schema compatibility assertion, rollback behavior, and implementation/review/
validation artifacts. `release.yml` remains the only deploy workflow.
