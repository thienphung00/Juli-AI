# Scope Alignment — Issue #301 (child of parent #278)

**Parent issue:** #278 — Phase 2: Contract-first TikTok Shop read sync and sandbox write validation
(constant — `parent-cache-issue-278.json`)
**Status:** valid
**Cache block version:** 1
**Last validated:** 2026-07-11
**Companion artifact:** `agent-runtime/artifacts/grill-cache/grill-cache-issue-301.json`

## Authority chain (this run)

| Rank | Source | Applies because |
|------|--------|---------------|
| 1 | `EXECUTION.md` P2-A1 | Phase/slice law |
| 2 | `parent-cache-issue-278.json` | Epic constant for all children |
| 3 | GitHub issue #301 | **Child** acceptance criteria (unique) |
| 4 | `docs/handoffs/phase-2-tiktok-implementation.md` | Epic handoff, not superseded |
| 5 | `docs/integrations/tiktok_api/contract-collection.md` §14-41 | Verified Layer 0 write contracts (#287, #289, #291) |

## Conflicts resolved

| Topic | Conflicting sources | Decision |
|-------|---------------------|----------|
| Promotion lifecycle write endpoints (#289) | Issue #301 AC says "Matches Layer 0 contracts from #287, #289, #291" · `contract-collection.md` #20-23 mark method/path **TBD from Promotion API Testing Tool** | **Defer** promotion create/update/deactivate activity implementation until a Layer 0 HITL pass verifies the path. Do not invent a path. `SandboxWriteClientFactory`-backed promotion resources are optional for this issue; their absence is not a regression. |
| Product edit body shape (#287, `contract-collection.md` #18) | Method/path stated (`PUT /product/202309/products/{product_id}`) but no captured cURL/response demo; a `202509` full-replace variant is explicitly noted as unconfirmed | **Implement** using the stated `202309` PUT path only. Do not use the `202509` variant. Body fields beyond `product_id` are flexible/minimal until a verified sample exists. |
| Fulfillment body shapes (#291, `contract-collection.md` §32/§40) | Paths stated and already present in `capabilities.SANDBOX_ALLOWED_REQUESTS`; body fields marked **TBD from cURL demo** | **Implement** using the stated paths; keep body construction minimal (identifiers only) until a verified sample exists. |
| Confirm Package Shipment location (#291, `contract-collection.md` #39) | Endpoint **moved from Fulfillment API to Supply Chain API** this pass (`POST /supply_chain/202309/packages/sync`) | **Use the Supply Chain path**, not a `/fulfillment/` path, for shipment confirmation. |

## In scope (this issue)

- Inventory update resource, wired behind `SandboxWriteClientFactory` (Layer 0 #287, `contract-collection.md` #14 — verified)
- Product publish (create) and edit resources, wired behind `SandboxWriteClientFactory` (Layer 0 #287, #17 verified / #18 path-stated)
- Fulfillment package/ship resources: combine, ship (single + batch), uncombine, split, confirm-shipment (supply chain), wired behind `SandboxWriteClientFactory` (Layer 0 #291, #29-#41 paths stated)
- A `SandboxWriteClientFactory.create_resources(config)` entry point (mirrors the existing `ProductionReadClientFactory.create_resources()` convention in `factories.py`) so write resources are reachable only through this factory
- Technical validation evidence (signing, HTTP status, TikTok `code`, response parsing) for every implemented write path — business failures from sparse sandbox data are acceptable and do not block ship

## Out of scope (explicit deferrals)

- Promotion lifecycle write endpoints (#289) — paths TBD, see Conflicts resolved above
- Layer 1 read resources — already shipped (#297)
- ETL normalization / Postgres upserts — already shipped (#299)
- Any change to `ProductionReadClientFactory`, `ProductionReadResources`, or the production-read guard allowlist
- P2-A3 feature aggregates (#300) — separate slice, separate child cache, not loaded here

## DO NOT load (deprecated or sibling-scoped for this run)

- `docs/handoffs/archive/`
- `docs/product/features/`
- `web/`, `ios/`
- `src/modules/ml/`
- `agent-runtime/artifacts/grill-cache/grill-cache-issue-300.json` (sibling child cache — never inherited)
- Any other sibling `grill-cache-issue-<n>.json` under #278

## Open questions

- (empty — the promotion-lifecycle and edit-body ambiguities above are resolved as deferrals/flexibility, not open questions)

## Prompt cache note

The `promptCacheBlock` in `grill-cache-issue-301.json` is the machine-injectable summary
of this file. On cache hit, agents load the JSON block first and skip re-reading full
upstream docs unless fingerprints are stale.
