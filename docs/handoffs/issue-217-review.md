# Handoff: review → ship — Issue #217

## Issue

- **#217** — Home Reward charts — sparklines, deltas, and CTAs to Decisions (P1.8-10)

## PR

- #223 — `feature/issue-217-home-reward-charts` → `main`

## Status

- Critical findings: 0
- Warnings: 0
- Info: Depends on #216 journey link registry (merged in #222)

## Modules

| Module | Change |
|--------|--------|
| `ReportMetricChart.tsx` | SVG sparkline + delta + CTA row |
| `TodaysReportDomainCard.tsx` | Chart rows replace number-only metric tiles |
| `DecisionPreviewCard.tsx` | Link wrapper for full-card tap target |
| `todays-report.ts` | `metricKey`, `series`, `deriveSparklineSeries` |
| `journey-loop.ts` | `resolveJourneyLinkForMetric` reverse lookup |

## Bootstrap

Branch `feature/issue-217-home-reward-charts` from `main` (includes #216 via merge).

## Review artifact

- `artifacts/reviews/review-issue-217.json` — PASS, 5/5 AC mapped

## Test Results

- Issue tests: `test_issue217_home_reward_charts` (7)
- Full web suite: 497 tests passing
- Type-check: clean

## Ready for ship

All acceptance criteria mapped. No migrations. Rollback = revert PR.
