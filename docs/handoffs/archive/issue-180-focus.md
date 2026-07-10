# Handoff: focus → tdd — Issue #180

## Issue

- **#180** — Rules-only reasoning panel — Why / Expected Impact / Next Steps (P1.8-5)
- **Parent:** #175 · **Blocked by:** #179 (closed)

## Acceptance criteria

- Template functions per validated `workflow_id` producing Why / Impact / Next Steps
- Unit tests: reasoning references only signals present in health results (no hallucinated metrics)
- Unit tests: copy never mentions workflows outside catalog
- Component test: expand reasoning on mock recommendation renders three sections
- `data-testid` hooks for reasoning expansion (analytics: reasoning-expansion clicks)

## Context Plan

### Workflow Phase
- issue implementation: focus → tdd → review → ship

### Load (Required)
- `EXECUTION.md` slice P1.8-5
- `docs/architecture/system-design.md` § LLM reasoning (copy layer)
- `docs/adr/026-operations-system-orchestration.md`
- `web/src/lib/operations/` (classification, health-check, recommendations from #177–#179)
- `web/src/lib/format.ts` (VND/number formatters)
- GitHub issue #180

### Implementation approach

| Layer | Files |
|-------|-------|
| Copy templates | `web/src/lib/operations/reasoning.ts` — `WORKFLOW_REASONING_TEMPLATES`, `buildWorkflowReasoning` |
| UI | `web/src/components/workflows/operations/ClarityCard.tsx`, `ReasoningPanel.tsx` |
| Tests | `test_operations_reasoning.test.ts`, `test_clarity_card_reasoning.test.tsx` |

### Key decisions

- **Rules-only:** `copy_source: "rules"` always; no Ollama
- **Signal guard:** hallucination test scoped to `why` + `expected_impact` only; `next_steps` are fixed operational cadence templates (7/14/30-day guidance)
- **Traceability:** `source_indicator_ids` filtered via `HEALTH_INDICATOR_TRACEABILITY_MAP`
- **Consumable shell:** export `ClarityCard` from `workflows/operations/`; wire into SellerHomeShell deferred to #181

### DO NOT Load
- TikTok API, backend Python, Supabase
- Approval gate (#181), outcome tracking (#182)

## Next: tdd

Branch `feature/issue-180-reasoning-panel` — implement templates + Clarity Card expansion; RED→GREEN per AC.
