# Agent Runtime Migration

**Status:** Published (Agent Runtime Phase 5)  
**Authority:** [`EXECUTION.md`](../../EXECUTION.md) > [`agent-runtime.md`](agent-runtime.md) > this file

Five-phase rollout from workflow-oriented orchestration to agent-oriented runtime with
artifact-driven optimization. Phases 1–5 are documentation and harness alignment;
Phase 6 proves the optimization loop.

---

## Summary

| Phase | Status | Deliverable |
|-------|--------|-------------|
| **1** | Complete | Canonical `agent-runtime.md`; routing alignment |
| **2** | Complete | Legacy skills removed; domain executor skills |
| **3** | Complete | Artifact schemas; persistence policy |
| **4** | Complete | Skills emit/consume artifacts per agent boundaries |
| **5** | Complete | Unified benchmark framework; this migration doc |
| **6** | Pending | Harness change proposed, applied, measured |

---

## Phase 1: Agent-Oriented Documentation Alignment

**Goals:** Establish one canonical Agent Runtime doc and replace workflow-chain language
with agent phases.

**Files affected**

- `docs/architecture/agent-runtime.md`
- `docs/README.md`
- `.cursor/skills/standalone/focus/SKILL.md`
- `docs/handoffs/context-plan-template.md`
- `.cursor/rules/core-orchestration.mdc`

**Risks**

- Accidentally creating another orchestration framework
- Leaving old workflow language active in skills or rules

**Success criteria**

- Docs describe Planning, Implementation, Review + Testing, and Harness Optimization
- `discover` and standalone `tdd` marked for removal

**Rollback**

- Revert doc-only changes
- ADR-003 remains authoritative for validation gates

---

## Phase 2: Skill Restructure

**Goals:** Remove `discover`, remove standalone `tdd`, retire workflow skills, reorganize
retained skills into standalone and domain categories.

**Files affected**

- `.cursor/skills/standalone/discover/` (removed)
- `.cursor/skills/standalone/tdd/` (removed)
- `.cursor/skills/workflow/*` (removed)
- `.cursor/skills/domain/{ui-ux,backend,data-platform,machine-learning,integrations}/`
- `review`, `validate`, `ship`, `focus`, `to-prd`, `to-issues`

**Risks**

- Broken references from existing docs
- Lost TDD guidance
- Unclear replacement for `discover` responsibilities

**Success criteria**

- `discover` removed; TDD lifecycle in Executor Agent specification
- No active path references old workflow chain

**Rollback**

- Restore removed skills from git
- Re-enable prior workflow docs

---

## Phase 3: Artifact Schemas

**Goals:** Define execution feedback schemas and resolve persistence policy.

**Files affected**

- `docs/architecture/agent-runtime-artifacts.md`
- `docs/schemas/agent-runtime/*.schema.json`
- `docs/deployment/implementation-guide.md`
- `artifacts/README.md`
- `.gitignore`

**Risks**

- Duplicating ADR-003 schemas
- Requiring fields that cannot be collected yet

**Success criteria**

- Review/validation artifacts remain ADR-003 compatible
- Harness optimization captures eight baseline metrics
- Product-development optimization routes to Architect backlog

**Rollback**

- Remove new schema docs
- Keep ADR-003 schemas unchanged

---

## Phase 4: Agent Role Implementation

**Goals:** Update skill documentation to emit/consume artifacts per agent ownership.

**Files affected**

- `.cursor/skills/standalone/guardrails/SKILL.md`
- `.cursor/skills/standalone/validate/SKILL.md`
- `.cursor/skills/standalone/ship/SKILL.md`
- `.cursor/skills/domain/*/SKILL.md`
- `.cursor/skills/standalone/focus/SKILL.md` (Meta optimization)
- `docs/templates/handoffs/*.md`
- `scripts/ci/generate_*_artifact.py`, `scripts/ci/common.py`

**Risks**

- Turning agent specs into prompts
- Overlapping responsibilities between agents

**Success criteria**

- Architect plans; Meta routes and optimizes; Executor implements with TDD
- Review tests/validates; Meta consumes evidence and emits optimization artifacts

**Rollback**

- Revert skill doc and generator changes
- Keep ADR-003 gate behavior

---

## Phase 5: Unified Benchmark System

**Goals:** Document one complete agent-runtime benchmark framework; retire per-phase
benchmark concepts.

**Files affected**

- `docs/architecture/agent-runtime-benchmarks.md`
- `docs/architecture/agent-runtime-migration.md` (this file)
- `docs/benchmarks/agent-runtime/*.md`
- `docs/README.md`, `agent-runtime.md` (cross-links)

**Risks**

- Benchmark tasks too broad or subjective
- Duplicate scoring systems outside artifact fields

**Success criteria**

- Task types A–D each define expected artifacts, deterministic checks, baseline metrics
- Single repeated-run protocol for Phase 6 measurement

**Rollback**

- Remove benchmark task specs and `agent-runtime-benchmarks.md`
- Retain artifact schemas for normal issue execution

---

## Phase 6: Optimization Loop (pending)

**Goals:** Prove Meta can improve harness quality, speed, or cost; route occasional
product-development improvements through Architect.

**Files affected**

- `docs/schemas/agent-runtime/harness-optimization-artifact.schema.json` (if extended)
- `docs/schemas/agent-runtime/product-development-optimization-artifact.schema.json`
- Optional `agent-runtime.config.yml`
- `focus` routing tables, benchmark thresholds

**Risks**

- Applying automatic harness changes before metrics are trustworthy

**Success criteria**

- One harness optimization proposed → applied → measured on benchmark rerun
- One product-development optimization proposed and routed to Architect backlog

**Rollback**

- Revert config/doc update
- Keep original artifacts as baseline evidence

**Minimal proof run** (from architecture plan)

1. Select small issue or benchmark fixture (type A–D)
2. Run Planning → Meta routing → Executor → Review + Testing → Meta optimization
3. Produce all runtime artifacts
4. Meta proposes one harness optimization (e.g. reduce context overload)
5. Apply approved change manually to docs/config surface
6. Rerun same benchmark; compare eight baseline metrics
7. Mark `appliedStatus: measured` if no regression per thresholds in
   [`agent-runtime-benchmarks.md`](agent-runtime-benchmarks.md)

---

## Files removed (historical)

| Path | Phase | Replacement |
|------|-------|---------------|
| `.cursor/skills/standalone/discover/` | 2 | Architect Agent + `focus` / `to-prd` / `to-issues` |
| `.cursor/skills/standalone/tdd/` | 2 | Executor built-in TDD + domain skills |
| `.cursor/skills/workflow/build-feature/` | 2 | Agent phases |
| `.cursor/skills/workflow/fix-bug/` | 2 | Agent phases + `qa` |

---

## Governance

- **No new orchestration framework** — agent phases operate over existing skills-first harness
- **ADR-003 unchanged** for CI gate ordering (`review → validate → ship`)
- **Meta must not** auto-edit skills, rules, ADRs, or product scope without Architect approval
- **Benchmark reports** are harness telemetry, not product release artifacts

---

## Related documents

| Document | Owns |
|----------|------|
| [`agent-runtime.md`](agent-runtime.md) | Runtime architecture |
| [`agent-runtime-artifacts.md`](agent-runtime-artifacts.md) | Artifact schemas |
| [`agent-runtime-benchmarks.md`](agent-runtime-benchmarks.md) | Benchmark protocol |
| [ADR-003](../adr/003-ai-native-cicd-policy.md) | CI/CD policy |
