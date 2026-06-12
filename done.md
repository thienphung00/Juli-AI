# Definition of Done — Issue #191

Checklist for `scripts/validate/check_done_md.py`. White seller canvas + 3-tab nav + /decisions shell (P1.8-9).

## Required

- [x] Issue acceptance criteria each have a named test mapping in `artifacts/reviews/review-issue-191.json`
- [x] `artifacts/reviews/review-issue-191.json` written; review `status` is `PASS`
- [x] Frontend: `npm test -- --testPathPattern="test_issue191|test_nav_header|test_legacy_creator|test_design_token"` passes
- [x] Frontend: `npx tsc --noEmit` clean
- [x] Backend: N/A — web-only change
- [x] Migrations: N/A — no migration changes
- [x] `artifacts/validation/validation-issue-191.json` exists with `status: "PASS"`
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| `web/` MODULE.md | Updated with `/decisions` route and bottom-nav contract |
| Handoff | `docs/handoffs/issue-191-review.md` |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-191.json` |
| Validation | `artifacts/validation/validation-issue-191.json` |
