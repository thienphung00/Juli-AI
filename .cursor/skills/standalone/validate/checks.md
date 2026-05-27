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

**Reads:** Any `docs/handoffs/<topic>-NN.md` referenced by the PR or branch.

**Passes if (when a handoff exists):**
- Filename matches `<topic>-NN.md`.
- Required sections present per
  [`docs/handoffs/_bootstrap.md`](../../../docs/handoffs/_bootstrap.md): `Status`,
  `Modules`, `Bootstrap prompts`.
- Module references exist in [`docs/architecture/map.md`](../../../docs/architecture/map.md).

**Skipped if:**
- No handoff is present and the PR fits in a single session.

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
