# Handoff: review → ship — Issue #210

## Issue

- **#210** — Align AI Chat and Reports copy with seller vocabulary system

## PR

- #212 — `feature/issue-210-vocabulary-alignment` → `main`

## Status

- Critical findings: 0
- Warnings: 0
- Info: Copy-only change; confidence remains internal in data models

## Modules

| Module | Change |
|--------|--------|
| `chat-context` | đề xuất prompts/replies; no confidence in seller copy |
| `ai-chat` service | Decision-aware replies omit confidence field |
| `reasoning` | expected_impact without độ tin cậy |
| `detail-content` | Canonical SPS label; no confidence trend |
| `HomeAiRecommendationCard` | Removed confidence badge; title → Đề xuất |
| `DecisionDetailFlow` | Hỏi Juli link copy aligned |

## Bootstrap

Branch `feature/issue-210-vocabulary-alignment` from `fix/home-decisions-ux-polish` base.

## Review artifact

- `artifacts/reviews/review-issue-210.json` — PASS, 3/3 AC mapped

## Test Results

- Issue tests: `test_issue210_vocabulary_alignment` (6)
- Regression: `test_issue199_chat_decision_context`, `test_operations_reasoning`, `test_ai_chat_tab`
- Full web suite: 466 passing

## Ready for ship

All acceptance criteria mapped. No migrations. Rollback = revert PR.
