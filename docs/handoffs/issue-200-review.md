# Handoff: review → ship — Issue #200

## Issue

- **#200** — P1.8-9 integration tests, MODULE.md, and screenshot re-baseline

## Manual test plan (Product lead UX review)

### Home — read-only white canvas

1. Log in as seller (UI-only demo); confirm background is white (`#FFFFFF`), not pink tint
2. On `/`, verify Shop Status hero, Today's Report, top-3 decision preview, Recent Progress
3. Confirm no approve/reject buttons or approval toolbar on Home
4. Tap **"Xem tất cả quyết định"** → `/decisions`

### Decisions — action workspace

5. On `/decisions` Recommended tab: full ranked list + approval toolbar
6. **NEW_SHOP** (`Người bán mới`): approve NPL → listing workflow modal
7. **MID_LARGE_SHOP** (`Rò rỉ doanh thu`): approve refund spike → leakage workflow modal
8. Expand card → detail → 5-step flow → step 5 approve routes to executor (or no-op toast)

### Navigation & legacy

9. Bottom nav: Trang chủ, Quyết định, Juli (3 tabs only)
10. `/recommendations` → redirects to `/decisions`

## Modules

| Module | Change |
|--------|--------|
| `HomeSummaryShell` | Top-3 decision preview on Home |
| `test_issue200_p18_9_exit_gate` | Exit-gate integration tests |
| `web/MODULE.md` | Decision object + white canvas docs |

## Bootstrap

No parallel agents; single-issue branch on `feature/issue-200-p18-9-exit-gate`.

## Review status

- Critical findings: 0
- All acceptance criteria mapped in `artifacts/reviews/review-issue-200.json`
- Web tests: 471 passed (includes 11 exit-gate tests)
