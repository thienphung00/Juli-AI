# Agent Runtime JSON Schemas

**Status:** Published (Agent Runtime Phase 5+)  
**Authority:** [`agent-runtime-artifacts.md`](../agent-runtime-artifacts.md) for paths and CI gates; this file indexes schema files only.

Draft 2020-12 JSON Schemas for runtime artifacts, workflow caches, and harness config.
Validate with your preferred JSON Schema tool or the gate scripts that embed subset validators
(e.g. `release_evidence_plan.py`, `implementation_schema.py`).

---

## Execution artifacts (committed on feature branches)

| Schema | `artifactType` | Primary path pattern |
|--------|----------------|----------------------|
| [`implementation-artifact.schema.json`](implementation-artifact.schema.json) | `implementation` | `agent-runtime/artifacts/implementations/implementation-issue-<n>.json` |
| [`intent-review-artifact.schema.json`](intent-review-artifact.schema.json) | `intent_review` | `agent-runtime/artifacts/intent-reviews/intent-review-issue-<n>.json` |
| [`review-artifact.schema.json`](review-artifact.schema.json) | `review` | `agent-runtime/artifacts/reviews/review-issue-<n>.json` |
| [`validation-artifact.schema.json`](validation-artifact.schema.json) | `validation` | `agent-runtime/artifacts/validation/validation-issue-<n>.json` |
| [`harness-optimization-artifact.schema.json`](harness-optimization-artifact.schema.json) | `harness_optimization` | `agent-runtime/artifacts/optimization/harness-issue-<n>-<phaseRunId>.json` |
| [`product-development-optimization-artifact.schema.json`](product-development-optimization-artifact.schema.json) | `product_development_optimization` | `agent-runtime/artifacts/optimization/product-development-<id>.json` |
| [`promotion-candidate-artifact.schema.json`](promotion-candidate-artifact.schema.json) | `harness_promotion_candidate` | Meta promotion proposals (Phase 6+) |

---

## Workflow prompt caches (gitignored; schema-validated at Meta entry)

| Schema | `artifactType` | Path pattern |
|--------|----------------|--------------|
| [`parent-cache-artifact.schema.json`](parent-cache-artifact.schema.json) | `parent_cache` | `agent-runtime/artifacts/workflow-cache/parent-cache-issue-<parent>.json` |
| [`issue-context-cache-artifact.schema.json`](issue-context-cache-artifact.schema.json) | `issue_context_cache` | `agent-runtime/artifacts/workflow-cache/issue-context-cache-<n>.json` |

**Public release (#500 / ADR-035)** — fields on the child cache:

| Field | Schema location | Notes |
|-------|-----------------|-------|
| `publicRelease` | `issue-context-cache-artifact.schema.json` | Set by `ensure_workflow_cache`; checked by Meta gate `public_release_classification` (#513) |
| `publicReleaseReasons` | same | Classifier reason codes |
| `issueLoadProfile.releaseEvidencePlan` | same | Required when `publicRelease: true`; validated against [`release-evidence-plan.schema.json`](release-evidence-plan.schema.json) via Meta gate `public_release_evidence_plan` (#513) |

Meta emits `injectionPlan.releaseEvidencePlan` / `releaseEvidencePlanId` and `tddContract` when
`readyForExecutor: true` ([`meta_prepare_executor.py`](../../scripts/meta_prepare_executor.py)).

---

## Embedded contracts (not standalone artifact files)

| Schema | Used by |
|--------|---------|
| [`release-evidence-plan.schema.json`](release-evidence-plan.schema.json) | Child cache `issueLoadProfile.releaseEvidencePlan`; optional `releaseEvidencePlanId` on implementation / validation artifacts |

---

## Harness config

| Schema | Used by |
|--------|---------|
| [`harness-config.schema.json`](harness-config.schema.json) | [`agent-runtime.config.yml`](../../config/agent-runtime.config.yml) — tunable Meta routing, workflow cache policy, executor domains |

---

## Related

| Document | Owns |
|----------|------|
| [`agent-runtime.md`](../agent-runtime.md) | Meta Agent Must list, prepare gates, injection contract |
| [`agent-runtime-artifacts.md`](../agent-runtime-artifacts.md) | Persistence, Validate `CHECKS`, META slice ownership (#513–#516) |
| [ADR-035](../../../docs/adr/035-public-release-evidence-and-automatic-rollback.md) | Public release evidence product contract |
