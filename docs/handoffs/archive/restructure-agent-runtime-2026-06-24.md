# Restructure Handoff — Agent Runtime Alignment (2026-06-24)

**Session:** Agent Runtime Architecture — codebase alignment, agent existence, harness optimization loop  
**Plan:** `agent_runtime_architecture_6de3e55e.plan.md`  
**Status:** Structural changes complete; no open restructure issues remain.

---

## What was preserved

All existing behaviour is intact:
- All four agent phase skills (`review`, `validate`, `ship`, `focus`) unchanged in logic.
- ADR-003 CI gates (`review → validate → ship`) unchanged.
- All JSON artifact schemas in `docs/schemas/agent-runtime/` unchanged.
- All `scripts/ci/` generator scripts unchanged.
- All domain executor skills unchanged.

---

## Structural changes completed

### 1. Fixed stale domain pattern paths in `focus/SKILL.md`

`RULE_TRIGGERS` in the focus skill referenced pattern files at the wrong path:

| Before | After |
|--------|-------|
| `.cursor/skills/domain/python-patterns.md` | `.cursor/skills/domain/testing-patterns/python-patterns.md` |
| `.cursor/skills/domain/python-testing.md` | `.cursor/skills/domain/testing-patterns/python-testing.md` |
| `.cursor/skills/domain/postgres-patterns.md` | `.cursor/skills/domain/testing-patterns/postgres-patterns.md` |
| `.cursor/skills/domain/swift-patterns.md` | `.cursor/skills/domain/testing-patterns/swift-patterns.md` |

Actual files live at `.cursor/skills/domain/testing-patterns/`.

### 2. Cleaned `context-plan-template.md`

Removed stale "deprecated Phase 2" parentheticals from the Skills checklist. `discover`
and standalone `tdd` are now labelled `removed` (migration completed in Phase 2).

### 3. Extended `agent-runtime.config.yml` — harness optimization loop

Added three new top-level sections to make the harness optimization loop self-contained and
operational without agents needing to look up paths from narrative docs:

**`agents`** — declares all four agent roles (Architect, Meta, Executor, Review) with their
phase, owned skills, consumed/emitted artifacts, and must-not constraints. This is the
machine-readable source of truth for agent boundary enforcement.

**`baseline_metrics`** — maps each of the eight metrics to its source artifact field:
- `execution_time` ← `implementation-artifact.executionDurationMs`
- `token_usage` ← `implementation-artifact.tokenUsage.total`
- `test_pass_rate`, `test_coverage` ← `validation-artifact`
- `review_failure_rate`, `validation_failure_rate`, `retry_count` ← review/validation artifacts
- `tool_invocation_count` ← `implementation-artifact.toolInvocationCount`

**`optimization`** — declares:
- Artifact input/output paths (using `{n}` / `{phaseRunId}` / `{id}` placeholders)
- `auto_apply_eligible_targets` (config, template, focus routing hints, benchmark thresholds)
- `auto_apply_forbidden` (skills, rules, architecture docs, PRDs, ADRs, product scope)
- `root_cause_categories` (ten initial categories)
- `schemas_dir` pointing to `docs/schemas/agent-runtime/`

---

## Codebase state after restructure

| Requirement | State |
|-------------|-------|
| Codebase alignment and cleanliness | ✓ Domain pattern paths corrected; stale language removed |
| Architect Agent exists | ✓ Defined in `docs/architecture/agent-runtime.md` § Agent specifications + `agent-runtime.config.yml` `agents.architect` |
| Review Agent exists | ✓ Defined in `docs/architecture/agent-runtime.md` § Agent specifications + `agent-runtime.config.yml` `agents.review` |
| Harness Optimization can run from real artifacts | ✓ `agent-runtime.config.yml` now declares artifact paths, baseline metric sources, auto-apply rules, and forbidden targets |

---

## Open issues

None from this restructure. All plan todos were either already implemented (Phases 1–5
completed before this session) or addressed here.

**Phase 6 (optimization loop proof)** remains the next milestone: run one complete
agent-phase execution, collect all five artifacts, and apply + measure one harness change
per `agent-runtime-benchmarks.md`.

---

## References

- Canonical runtime: [`docs/architecture/agent-runtime.md`](../architecture/agent-runtime.md)
- Artifact schemas: [`docs/schemas/agent-runtime/`](../schemas/agent-runtime/)
- Harness config: [`agent-runtime.config.yml`](../../agent-runtime.config.yml)
- Benchmark protocol: [`docs/architecture/agent-runtime-benchmarks.md`](../architecture/agent-runtime-benchmarks.md)
- Migration phases: [`docs/architecture/agent-runtime-migration.md`](../architecture/agent-runtime-migration.md)
