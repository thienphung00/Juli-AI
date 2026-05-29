# Handoff: focus → tdd — Issue #81

## Issue
- **#81** — Nav redesign 6/8: Operations hub (role-based sub-tabs: Seller vs Affiliate)
- Parent PRD: https://github.com/thienphung00/Juli-AI/issues/75
- Blocker #77: **merged** (nav + redirects live on main)

## Acceptance criteria
- Seller mode shows 4 sub-tabs: Sản phẩm, Creator, Đơn hàng, Hoàn trả.
- Affiliate mode shows 3 sub-tabs: Sản phẩm, Đơn hàng, Hoàn trả (no Creator tab).
- Each sub-tab renders mode-appropriate fields and affordances.
- With `NEXT_PUBLIC_UI_ONLY=1`, operations renders with mock data without API calls.

## Worktree
```bash
cd ../juli-ai-issue-81   # branch feat/issue-81-operations-hub
```

## Context loaded (focus)

### Architecture
- `docs/architecture/map.md` — web tier only; no backend changes
- `docs/features/nav-redesign/PRD.md` — § Mock Data — Operation (Seller/Affiliate), lines ~1148–1320
- `web/MODULE.md` — `/operation` route placeholder → full hub

### Existing patterns (follow #79 Home)
- Route: `web/src/app/operation/page.tsx` → `OperationPage` (placeholder today)
- Component: `web/src/components/OperationPage.tsx` — **replace placeholder**
- Mode: `useWorkspaceMode()` from `@/lib/mode-context`
- Shell: `AuthenticatedShell` (header + bottom nav already wired)
- Service pattern: `web/src/lib/services/home.ts` — branch on `isUiOnly`, mock via `@/lib/mock-data/*`
- Tests: `web/src/__tests__/test_home_control_center.test.tsx` — integration-style, `data-testid`, mock service layer

### MCP / tools
- None required (frontend-only, mock data)

### Implementation approach

**New files**
| File | Purpose |
|------|---------|
| `web/src/lib/mock-data/operation-seller.ts` | Copy shapes from PRD `MOCK_OPERATION_SELLER` |
| `web/src/lib/mock-data/operation-affiliate.ts` | Copy shapes from PRD `MOCK_OPERATION_AFFILIATE` |
| `web/src/lib/services/operation.ts` | `getOperationData(mode)` — `isUiOnly` → mock; else empty/stub |
| `web/src/components/operation/*` | Sub-tab panels (products, creators, orders, returns) — keep flat if small |
| `web/src/__tests__/test_operation_hub.test.tsx` | AC coverage |

**Modified files**
| File | Change |
|------|--------|
| `web/src/components/OperationPage.tsx` | Sub-tab bar + mode-aware tab set + panel routing |
| `web/MODULE.md` | Update `/operation` description |

**Sub-tab behavior**
- Seller: Products (GMV/ROI/stock), Creators (GMV/conversion/actions), Orders (list + status), Returns (processing)
- Affiliate: Products (commission focus, read-only), Orders (status read-only), Returns (impact-only)
- Affiliate must **not** render Creator tab

**UI-only**
- No `@/lib/api-client` imports in components — data via `services/operation.ts` only
- `OperationPage` accepts optional `uiOnly={isUiOnly}` prop for tests (same as HomePage)

### DO NOT touch
- `web/src/components/AiChatPage.tsx`, `web/ai-chat/**` — owned by #82
- `web/src/lib/nav-config.ts`, `NavBar.tsx` — already shipped in #77
- Backend / API routes

### Standards applied
- [x] Maintainability — match HomePage component/service split
- [x] Performance — bounded mock lists; no unbounded renders
- [x] Security — no secrets; mock only in UI-only path

## TDD plan (red → green → refactor)

1. **RED** — `test_operation_hub.test.tsx`:
   - Seller: 4 sub-tab labels visible; affiliate: 3 tabs, no Creator
   - Seller products tab shows GMV/ROI fields from mock
   - Affiliate products tab shows commission fields
   - UI-only: `getOperationData` called, no api-client
2. **GREEN** — mock data + service + OperationPage sub-tabs
3. **REFACTOR** — extract sub-panels if OperationPage > ~200 lines

## Review → ship checklist
- `cd web && npm test -- test_operation_hub`
- `npm run lint` in web/
- PR title: `feat(web): Operations hub with role-based sub-tabs (#81)`
- Parallel: commit locally; hand branch + PR draft to GitHub ops owner (do not push unless ops owner)
