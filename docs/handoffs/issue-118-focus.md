# Handoff: focus → tdd — Issue #118

## Issue

- **#118** — Seller home shell — routing + persona switcher
- **Status:** Already merged to `main` via PR #129 (`a579502`). This window is **ship verification only** — no new feature work unless a gap is found.

## Acceptance criteria (verify, do not re-implement)

- [x] Post-login seller lands in home shell (not legacy recommendation feed)
- [x] Persona switcher loads mock personas from #114 and re-routes on change
- [x] Stage router (#116) selects workflow; UI shows which workflow is active
- [x] Vietnamese copy, VND formatting, responsive mobile layout
- [x] Integration test: switching persona changes visible workflow/stage
- [x] Integration test: new/leakage/growth personas route to expected workflow entry
- [x] Demo login flow unchanged

## Context loaded

- Architecture: `EXECUTION.md`, `docs/system-design.md`, `docs/architecture/map.md`
- Module docs: `web/MODULE.md`
- Implementation: `web/src/components/seller-home/`, `web/src/lib/seller-workflows.ts`, `web/src/lib/demo-persona-context.tsx`
- Tests: `web/src/__tests__/test_seller_home_shell.test.tsx`
- Review artifact: `artifacts/reviews/review-issue-118.json` (PASS)

## Standards applied

- Reliability, maintainability, security (no PII in fixtures), observability (N/A for this slice)

## Plugin skills & MCP

- `/nextjs`, `/shadcn` — reference only
- No Supabase or API changes

## Implementation approach (verification)

1. Run `cd web && npm test -- --testPathPattern=test_seller_home_shell`
2. Run full web test suite
3. Confirm `artifacts/reviews/review-issue-118.json` status PASS
4. **ship:** Close GitHub issue #118 if still open; confirm EXECUTION slice documented (home shell is prerequisite, not a numbered P1 slice in updated queue — note in PR/issue comment if needed)
5. Hold **GitHub ops lock** for #119/#120 PR pushes (stagger ≥ 30s)

## DO NOT touch

- `web/src/components/workflows/` — owned by #119/#120
- Workflow-specific UI beyond generic `SellerHomeShell` + `TaskQueue`
