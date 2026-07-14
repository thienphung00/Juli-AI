# Scope alignment — Issue #380 (P2-B7) — Sub-PR 1

**Parent:** #278 · **Slice:** P2-B7 (partial) · **Domain:** backend  
**Branch:** `feat/issue-380-leakage-executors`

## In scope (this PR)

Register Celery tool handlers for **inventory + promotion** leakage workflows:

| workflow_key | tool_name |
|---|---|
| `replenish_inventory_3` | `inventory.replenish` |
| `clear_excess_4` | `inventory.clear_excess` |
| `create_activity_7a` | `promotion.create_activity` |
| `update_activity_7c` | `promotion.update_activity` |
| `delete_activity_7b` | `promotion.delete_activity` |

- Route via existing `tool_routing.py` (#305)
- Orchestrate Product/Promotion API chains through `load_sandbox_write_resources` (#301)
- Derive chain parameters from catalog endpoints + prior steps (inventory search → update; create activity → attach products)
- Unit tests mirroring `test_listing_executors_contract.py` (registration, routing, mocked E2E, API failure path)
- `MODULE.md` documents inventory/promotion executors; **EXECUTION.md P2-B7 stays open** until returns sub-PR

## Out of scope (this PR)

- Returns executors (`returns.prevent_cancellation`, `returns.prevent_return`, `returns.prevent_refund`) — **Sub-PR 2**
- FBT executors and FBT REST endpoints — **Phase 5** (see `CONTEXT.md` **Phase 2 FBS-only fulfillment**)
- Live SANDBOX_VN capture in CI (mocked in tests)
- Action Card auto-approve UI

## FBT — deferred to Phase 5 (do not remove working intake)

Per grill 2026-07-13: keep `webhook_catalog.py` FBT rows and ingestion; sanitize webhook
payloads in `webhook-contract-collection.md` (#21, #24, #58). Missing FBT **REST** paths
(inbound-shipment create, FBT MCF status read, etc.) remain `TBD` in `contract-collection.md`.
Phase 2 implements **workflow 3 (FBS)** via Inventory Search → Update Inventory only.

| Deferred input | Location | Phase |
|---|---|---|
| FBT inbound-shipment create API | `contract-collection.md` | 5 |
| Webhook #21 / #24 / #58 sanitized samples | `webhook-contract-collection.md` | 2 (sanitize) / 5 (executors) |
| `replenish_inventory_3b` tool routing | `tool_routing.py` | 5 |
| `prevent_return_8b_fbt` executor | — | 5 |

## Resolved decisions

| Decision | Choice |
|----------|--------|
| PR split | Sub-PR 1: inventory + promotion (this PR); Sub-PR 2: returns (FBS paths only) |
| Registry location | `runner.py` per #305/#379 correction |
| Parameter derivation | Catalog + prior chain steps; caller supplies only non-derivable inputs (raw targets, overrides) |
| Fulfillment model | Phase 2 FBS-only executors; FBT deferred Phase 5; keep working webhook intake |
| `clear_excess_4` | FBS executor; keep #24 catalog mapping; 6a FBS write + 6b FBT webhook in docs |
| `prevent_return_8b` (Sub-PR 2) | FBS executor: explicit `decision` + optional 7a Update Inventory; 7b FBT deferred |
| Post-sales naming | Display/docs: **Request *** (8a/8b/8c); `prevent_*` workflow_key rename TBD |
