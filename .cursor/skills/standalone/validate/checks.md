# Validate Skill: Per-Check Reference

Each gate is a single Python script under
[`scripts/validate/`](../../../scripts/validate/) that exits 0 on PASS and 1
on FAIL. The validation artifact's `checks[]` array has one entry per gate
listed below, in this order.

## 1. `review_artifact_present`

**Script:** [`scripts/validate/check_review_artifact.py`](../../../scripts/validate/check_review_artifact.py)

**Reads:** `artifacts/reviews/review-issue-<n>.json`

**Passes if:**
- File exists at the canonical path.
- JSON is parseable.
- Required fields present: `id`, `issue`, `status`, `criticalFindings`,
  `modulesTouched`, `testCoverage.acceptance.{total,mapped,mappings}`.
- `status` is one of `PASS`, `PASS_WITH_WARNINGS`, `FAIL`.
- If `status == "FAIL"`, validation immediately fails (do not merge a FAIL review).
- If any `criticalFindings[*].severity == "CRITICAL"`, the artifact's `status`
  must be `FAIL` — mismatches fail this check.
- If any `criticalFindings[*].severity == "WARNING"` (after normalizing legacy
  `warnings[]`), `status` must be `PASS_WITH_WARNINGS`, not `PASS`.
- Legacy top-level `warnings[]` entries must be migrated into `criticalFindings`;
  non-empty `warnings[]` fails this check (regenerate via
  `scripts/ci/generate_review_artifact.py` or `normalize_review_artifacts.py`).
- Structural validity only — blocking CRITICAL findings and `FAIL` status are
  enforced by `critical_findings_resolved`.

## 2. `acceptance_criteria_mapped`

**Script:** [`scripts/validate/check_acceptance_mapping.py`](../../../scripts/validate/check_acceptance_mapping.py)

**Reads:** review artifact's `testCoverage.acceptance`.

**Passes if:**
- `total == mapped`.
- `unmapped` is empty.
- Every entry in `mappings[]` references a `pytest` node id (`path::name`)
  that exists on disk.
- The criterion text overlaps the test name (case-insensitive substring match
  after normalizing underscores and spaces).

## 3. `module_boundaries`

**Script:** [`scripts/validate/check_module_boundaries.py`](../../../scripts/validate/check_module_boundaries.py)

**Reads:**
- [`docs/architecture/map.md`](../../../docs/architecture/map.md) (authoritative module list)
- All `MODULE.md` files (public surface)
- Python AST of every `.py` under `src/`

**Passes if:**
- No imports cross module boundaries except via symbols listed in the
  importee's `MODULE.md` "Public Interfaces".
- No cycles in the module-level dependency graph (Tarjan's SCC).

**Warns (does not fail) if:**
- More than 3 modules touched in the diff. Defers to
  [`.cursor/rules/issue-workflow.mdc`](../../../.cursor/rules/issue-workflow.mdc).

## 4. `module_md_sync`

**Script:** [`scripts/validate/check_module_drift.py`](../../../scripts/validate/check_module_drift.py)

**Reads:** Each touched module's `MODULE.md` vs Python AST of public symbols.

**Passes if (per touched Tier 1/2 module):**
- Every public symbol in code is listed in `MODULE.md` "Public Interfaces".
- Every symbol listed in `MODULE.md` exists in code (no orphans).

**Skipped if:**
- The module is Tier 3 utility (no `MODULE.md` per
  [`docs/architecture/map.md`](../../../docs/architecture/map.md)).

## 5. `handoff_structure`

**Script:** [`scripts/validate/check_handoff.py`](../../../scripts/validate/check_handoff.py)

**Reads:** Any legacy `docs/handoffs/<topic>-NN.md` referenced by the PR or branch.

> The `docs/handoffs/` registry was removed in the seller-money rescope;
> cross-session continuity now lives in the driving slice in
> [`EXECUTION.md`](../../../EXECUTION.md). This is now a **dormant** gate.

**Passes if (when a handoff exists):**
- Filename matches `<topic>-NN.md`.
- Required sections present: `Status`, `Modules`, `Bootstrap prompts`.
- Module references exist in [`docs/architecture/map.md`](../../../docs/architecture/map.md).

**Skipped if:**
- No handoff is present (the normal case) — track continuity in `EXECUTION.md` instead.

## 6. `adr_requirement`

**Script:** [`scripts/validate/check_adr.py`](../../../scripts/validate/check_adr.py)

**Reads:** review artifact's `criticalFindings[]` and `interfaceChanges[]`,
plus `docs/decisions/`.

**Passes if:**
- No architectural change detected, OR
- An architectural change is detected AND a new file matching `NNN-slug.md`
  exists in `docs/decisions/` on the branch.

**Architectural change detection:**
- New module added to [`docs/architecture/map.md`](../../../docs/architecture/map.md), OR
- `interfaceChanges[*].breaking == true`, OR
- `criticalFindings[*].type == "interface_change"`.

**Filename convention:** `NNN-slug.md` — three-digit zero-padded number,
hyphen-separated lowercase slug. The `adr-NNN.md` form is rejected.

## 7. `done_md_completion`

**Script:** [`scripts/validate/check_done_md.py`](../../../scripts/validate/check_done_md.py)

**Reads:** Root [`done.md`](../../../done.md).

**Passes if:**
- All checklist items in the "Required" sections are checked off.
- `done.md` exists.

**Conditional items** (e.g. "MODULE.md updated if interfaces changed") are
checked only when their precondition is true (see [`done.md`](../../../done.md)
for the conditional table).

## 8. `critical_findings_resolved`

**Script:** [`scripts/validate/check_critical_findings_resolved.py`](../../../scripts/validate/check_critical_findings_resolved.py)

**Reads:** review artifact `status`, `criticalFindings`, `testCoverage`, `mlGates`,
`priorReviewBlockers`.

**Passes if:**
- No effective mandatory fail triggers after applying a valid `overriddenMerge`
  (see merge gating summary).
- Mandatory triggers: CRITICAL security, production data exposure, test regression,
  incomplete acceptance criteria, unresolved prior blockers, missing ML gates when
  ML modules touched.
- Any `severity == "CRITICAL"` or `actionRequired: true` finding forces
  `status: "FAIL"` (never overridable).
- `status: "FAIL"` blocks merge unless `overriddenMerge` clears all overridable
  mandatory fails and no CRITICAL/actionRequired findings remain.

**`overriddenMerge` (hotfix):** requires `timestamp`, `overriddenBy`, `reason`,
`incidentLink`. Clears overridable mandatory fails only; CRITICAL security and
production data exposure are never cleared.

## 9. `findings_acknowledged`

**Script:** [`scripts/validate/check_findings_acknowledged.py`](../../../scripts/validate/check_findings_acknowledged.py)

**Passes if (when `status == "PASS_WITH_WARNINGS"`):**
- **Every** WARNING finding has `acceptanceByReviewer: true`, `ownerAck: true`, and
  either `fixedInCommit` or `shipAsIsReason`.

**Per-finding dual signoff (blocks entire review):** There is no partial merge.
If one WARNING lacks reviewer acceptance, the whole review blocks — even when
other findings are fully acknowledged and global signoffs are present.

| Finding #1 | Finding #2 | Merge? |
|--------------|------------|--------|
| ack'd | ack'd | Yes (if global signoffs present) |
| ack'd | `acceptanceByReviewer: false` | **No** — blocks on #2 |
| ack'd | missing `ownerAck` | **No** |

`shipAsIsReason` documents accepted risk; `targetFixDate` tracks planned debt.
Post-deploy, link incidents via `productionOutcome.incidents[].linkedFinding`.

**Skipped when:** review is `PASS` (no gating warnings).

## 10. `reviewer_signoff_present`

**Script:** [`scripts/validate/check_reviewer_signoff.py`](../../../scripts/validate/check_reviewer_signoff.py)

**Passes if (when `status == "PASS_WITH_WARNINGS"`):**
- `reviewerSignoff.statement`, `reviewerSignoff.timestamp`, and
  `reviewerSignoff.acceptedRisks: true` are present.

## 11. `owner_signoff_present`

**Script:** [`scripts/validate/check_owner_signoff.py`](../../../scripts/validate/check_owner_signoff.py)

**Passes if (when `status == "PASS_WITH_WARNINGS"`):**
- `ownerSignoff.statement`, `ownerSignoff.timestamp`, and
  `ownerSignoff.acknowledged: true` are present.

## 12. `ml_gates_enforced`

**Script:** [`scripts/validate/check_ml_gates.py`](../../../scripts/validate/check_ml_gates.py)

**Passes if (when any `modulesTouched` path is under `src/modules/ml/`):**
- `mlGates.coldStartThresholdDocumented: true`
- `mlGates.promotionGateDocumented: true`
- Source scan: cold-start constants exist in `thresholds.py` for touched inference
  modules (`ad_performance`, `anomaly`, `seller_stage`).
- Source scan: promotion constants exist in `artifacts/thresholds.py` when trainer
  modules are touched.
- When `mlGates.thresholds` is declared, values must match source constants.

**Skipped when:** no ML modules touched.

## Merge gating summary

| Review status | Blocks merge? |
|---------------|---------------|
| `PASS` | No (when all 12 checks pass) |
| `PASS_WITH_WARNINGS` | Yes until **every** WARNING has per-finding ack + global signoffs |
| `FAIL` | Yes — unless valid `overriddenMerge` clears overridable mandatory fails |

**Per-finding rule:** All WARNING findings must pass `finding_is_acknowledged()`
individually; one unacked finding blocks the entire review (no partial merge).

**Override rule:** `overriddenMerge` is audited hotfix metadata. Never overrides
CRITICAL security, production data exposure, CRITICAL findings, or
`actionRequired` items.
