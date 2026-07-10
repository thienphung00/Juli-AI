# Handoff: focus → tdd — Issue #155

## Issue

- **#155** — E2E listing workflow UI — dual-path state machine from approved list_products
- **EXECUTION slice:** P1.6-2
- **Parent:** #152 · **Blocked by:** #153 (shipped), #154 (shipped)

## Acceptance criteria

- Approving `list_products` in New Seller Copilot opens listing workflow (route or modal)
- Path A flow: form → distributor pick → draft review step mounts
- Path B flow: constraints → opportunity browse → distributor pick → draft review step mounts
- State machine exposes current step; back navigation preserves session data
- Other task types (`shop_setup`, `enable_affiliate`, etc.) still show Phase 1 no-op feedback
- Integration test: approve `list_products` → listing workflow UI visible (`data-testid` marker)
- Integration test: Path A reaches draft review with generated draft from rules engine
- Integration test: Path B opportunity filter with fixed constraints returns deterministic card set
- Workflow works in UI-only mode without backend calls
- `map.md` planned module row updated when code lands

## Context loaded

| Area | Files |
|------|-------|
| Architecture | `EXECUTION.md` (P1.6-2), `docs/architecture/system-design.md` §7, `docs/architecture/map.md` |
| Decisions | `docs/adr/020-new-seller-listing-workflow-scope.md` |
| Fixtures | `web/src/lib/mock-data/listing-workflow/` (#153) |
| Rules engine | `web/src/lib/workflows/new-seller/listing/` (#154) — `generateProductDraft` |
| Task executor | `web/src/lib/task-executor/use-task-executor.ts`, `TaskQueue.tsx` |
| Copilot shell | `NewSellerCopilotPanel.tsx`, `test_new_seller_copilot.test.tsx` |
| Prior art | `docs/handoffs/issue-153-ship.md`, `docs/handoffs/issue-154-ship.md` |

## Standards applied

- Reliability — session-scoped state; deterministic opportunity filter; no API calls
- Maintainability — pure state-machine reducer; hook wraps session; UI reads step from state
- Security — no external fetch; fixture IDs only

## Plugin skills & MCP

- `/nextjs`, `/shadcn` for React workflow UI
- None required for MCP

## Implementation approach

**Dependency order:** state machine → opportunity filter → hook → extend task executor → UI panel → wire TaskQueue → tests → map.md

### New files

| File | Purpose |
|------|---------|
| `web/src/lib/workflows/new-seller/listing/state-machine.ts` | Step enum, reducer, back/next navigation for Path A/B |
| `web/src/lib/workflows/new-seller/listing/filter-opportunities.ts` | Deterministic filter on mock catalog |
| `web/src/lib/workflows/new-seller/listing/use-listing-workflow.ts` | Session hook wrapping reducer + draft generation |
| `web/src/components/workflows/new-seller/listing/ListingWorkflowPanel.tsx` | Modal workflow UI with Vietnamese labels |
| `web/src/components/workflows/new-seller/listing/index.ts` | Barrel export |
| `web/src/__tests__/test_listing_workflow_ui.test.tsx` | Integration tests per AC |

### Modified files

| File | Change |
|------|--------|
| `web/src/lib/task-executor/use-task-executor.ts` | `list_products` approve opens workflow + launch feedback; other types unchanged |
| `web/src/components/tasks/TaskQueue.tsx` | Render `ListingWorkflowPanel` when workflow open |
| `web/src/lib/workflows/new-seller/listing/index.ts` | Re-export state machine + filter |
| `docs/architecture/map.md` | Move UI row from planned → deployed |

### Key patterns

- **Entry:** Only `type === "list_products"` triggers workflow; feedback copy changes to launch confirmation
- **UI shell:** Inline modal overlay (`data-testid="listing-workflow"`) from TaskQueue — no new route
- **Draft review:** Call `generateProductDraft` on entering draft step — Path A `manual_form`, Path B `opportunity_card`
- **Filter test constraints:** `{ category: "Mỹ phẩm", maxCapitalVnd: 20_000_000, dropshipOnly: true }` → stable opportunity IDs
- **Session:** In-memory + sessionStorage for back/forward within workflow session
- **Export step:** Placeholder only (#156 owns export execution)

### Tests (TDD)

1. RED: approve `list_products` → `listing-workflow` visible
2. RED: Path A end-to-end → `listing-draft-review` with draft product name
3. RED: Path B filter → deterministic opportunity cards
4. RED: `shop_setup` approve → Phase 1 no-op feedback (not workflow)
5. GREEN: implement state machine + UI + executor extension

## DO NOT touch

- Export service (#156), shop progress widget (#157)
- Backend / Postgres / TikTok API
- Rules engine logic (#154) except imports
