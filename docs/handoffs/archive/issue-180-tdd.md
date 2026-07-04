# Handoff: tdd → review — Issue #180

## Branch
`feature/issue-180-reasoning-panel`

## Tests (11 passing)

| Test file | Behavior |
|-----------|----------|
| `test_operations_reasoning.test.ts` | Envelope shape, templates per workflow_id, indicator traceability, no hallucinated metrics in why/impact, catalog guard, Vietnamese + rules chain |
| `test_clarity_card_reasoning.test.tsx` | Collapsed card, expand toggle aria, three reasoning sections visible |

## Implementation

| File | Purpose |
|------|---------|
| `web/src/lib/operations/reasoning.ts` | `WORKFLOW_REASONING_TEMPLATES`, `buildWorkflowReasoning` |
| `web/src/lib/operations/index.ts` | Re-export reasoning public API |
| `web/src/lib/operations/MODULE.md` | P1.8-5 docs |
| `web/src/components/workflows/operations/ClarityCard.tsx` | Card + expand toggle (`reasoning-expand-toggle`) |
| `web/src/components/workflows/operations/ReasoningPanel.tsx` | Why / Impact / Next Steps sections |
| `web/src/components/workflows/operations/index.ts` | Barrel export |

## AC status

- [x] Template functions per validated workflow_id
- [x] Unit: signals-only guard (why + expected_impact)
- [x] Unit: catalog guard
- [x] Component: expand reasoning three sections
- [x] data-testid hooks for expansion analytics

## Fixes during TDD

- Hallucination guard scoped to signal-derived copy (not next_steps cadence literals)
- Removed literal "7 ngày" from why copy (refund spike, product scaling) to avoid false positives

## Next: review
