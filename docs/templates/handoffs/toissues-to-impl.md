# Handoff: to-issues → implementation

## Issue Queue (dependency order)
1. #[N1] — [title] — AFK — blocked by: none
2. #[N2] — [title] — AFK — blocked by: #N1
3. #[N3] — [title] — HITL — blocked by: #N1

## Parent PRD
- GitHub issue: #[prd-number]

## Implementation Order
Process issues top-to-bottom. Skip HITL issues until the user resolves them.
For each AFK issue: run focus → tdd → review → ship.
