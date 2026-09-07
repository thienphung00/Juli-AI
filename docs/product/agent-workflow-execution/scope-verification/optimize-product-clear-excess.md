# Scope verification — Optimize Product (§2) & Clear Excess (§3) v1

## Tool surface today (registered, W1-A)

| Tool | Class / policy | file:line |
|---|---|---|
| `get_product_information` | READ / AUTO | `backend/src/juli_backend/services/agent/tools/product.py:267` |
| `get_seo_keywords` | READ / AUTO | `product.py:354` |
| `check_product_status` | READ / AUTO | `product.py:391` |
| `inspect_product_image` | READ / AUTO | `product.py:489` |
| `upload_product_image` | WRITE / **AUTO** | `product_write.py:161` |
| `update_product_listing` | WRITE / CONFIRM | `product_write.py:337` |
| `update_product_price` | WRITE / CONFIRM | `product_write.py:407` |
| `conclude_without_changes` | READ / AUTO (terminal) | `tools/terminal.py:77` |

`required_steps = ("update_product_listing", "update_product_price")`, `max_iterations=6`, `wall_clock 300s`, `approval_timeout_h=4` — `playbooks/optimize_product.py:66-74`.
`update_product_price` calls `resources.products.update_prices(product_id, {"skus":[{id, price}]})` — **a base-price write** (`product_write.py:389-404`). Spec OP-FR-3 deletes exactly this tool.

Spec adds: diagnosis read, `create_product_discount`, `deactivate_activity`, `search_activities`. **All four ABSENT** from the registry, the playbook, and `PRODUCT_WRITE_TOOL_HANDLERS` (`product_write.py:426-436`).

---

## §2 Optimize Product

| Spec id | What exists (file:line) | Gap | Smallest producer | Blocking |
|---|---|---|---|---|
| OP-FR-1 diagnosis first | Nothing. `grep -i diagnos` over `backend/src` + `docs/integrations/tiktok_api/**` returns **zero** endpoint hits. No `PRODUCT_DIAGNOSES_PATH` in `integrations/tiktok/constants.py` | Both diagnosis endpoints ABSENT: no constant, no resource method, no guard allowlist entry, no contract capture | `constants.py` paths + `ProductsResource.get_diagnoses/diagnose_optimize` + 2 regexes in `capabilities.py:83` + a captured cURL in contract-collection | **YES** |
| OP-FR-2 one lever | Playbook proposes listing **and** price as two independent CONFIRM steps (`optimize_product.py:109-127`); `required_steps` demands *both* | v1 wants exactly one CONFIRM per run | Change `required_steps` to a 1-tuple + drop a step; also `runner/concurrency.py:180` field-lock map | YES |
| OP-FR-3 discount not base price | `PromotionResource.create_activity` exists (`resources/promotion.py:29`) and IS bound to `SandboxWriteResources.promotion` (`factories.py:62,132`) and allowlisted `POST /promotion/\d+/activities` (`capabilities.py:142`) | No agent tool wraps it; `ProductToolContext` is product+sku_ref bound (`product.py:92`), handler dispatch is hard-coded to the two product dicts (`runner/tool_executor.py:276,305`). No `DIRECT_DISCOUNT` body builder anywhere | New `tools/promotion_write.py` + a third handler dict + registry entry; delete `UPDATE_PRODUCT_PRICE_SPEC` | YES (client exists — this is wiring, not integration) |
| OP-FR-4 T9 depth | `ai/recommendations/engine.py:546 get_price_direction_suggestion` — **zero callers**; depth is hardcoded `price*0.95` (`engine.py:611`); fee ratio falls back to `0.30` (`engine.py:524`) and in practice reads `platform_commission`/`shipping_fee` which are **always 0** (ADR-065 unimplemented) | No margin floor: **no per-SKU cost column exists** on `Product` (`models.py:235-262`) or `InventoryItem` (`models.py:265`). `margin_floor`/`discount_depth`/`price_floor` ABSENT from all code | Either a `products.unit_cost` column + a seller-supplied producer, or redefine the floor as fee-adjusted and land ADR-065's `fee_amount` mapping (`mapping.py:357-392`) | **YES** |
| OP-FR-5 lock via rejection | Vendor error surfaces as `TOOL_ERROR_UNRECOVERABLE` (`services/agent/status.py:115`) — no per-code branch | No `price_lever_locked` path; no vendor error-code taxonomy for promotion creates | Map the create-activity rejection code to a new stop reason | YES |
| OP-FR-6 title ≥25 chars | `_build_listing_edit_body` (`product_write.py:242`) — no length check found | Validator ABSENT | 3-line guard in the input model | no |
| OP-FR-8 end states | `StopReason` (`status.py:93-133`) has 15 values; none of `no_diagnosis_codes`, `price_lever_locked`, `scope_unavailable`, `declined` (nearest: `CONFIRMATION_DECLINED`) | 3 new stop reasons; `String(32)` fits | Enum additions | no |
| OP-NFR-1 scope held | **No OAuth scope is requested or recorded anywhere.** `grep -rn scope backend/src/juli_backend/integrations/tiktok/` → zero hits. `seller.product.optimize` appears only in ADR-090 prose | Cannot detect scope presence ⇒ cannot degrade or emit `scope_unavailable` | Persist granted scopes at auth and expose a checker | YES for the degrade branch |
| OP-NFR-3 CTOR at 7/14d | Impact reader lives and works: `workers/impact_reader/pipeline.py`, windows T+7 / T+14 (`services/impact/windows.py:33`), `suppressed` confidence is real (`models.py:879`, `pipeline.py:87`) | **CTOR does not exist.** `METRIC_MAP` has impressions/ctr/conversion_rate/items_sold/gmv/sku_orders/gmv_per_order only (`metric_map.py:142-178`); `grep ctor` in scoring/impact/action_cards → 0. Price maps to `gmv`, not CTOR | Add a `ctor` MetricSpec + the backing daily column on `analytics_performance_intervals` | YES if CTOR is meant literally |

---

## §3 Clear Excess Inventory

| Spec id | What exists (file:line) | Gap | Smallest producer | Blocking |
|---|---|---|---|---|
| CE-FR-1 excess formula | `InventoryItem` (`models.py:265-289`) has **only** `quantity`, `warehouse_id`, `velocity`. Forecaster exists (`ai/forecasting/forecaster.py:178 get_forecast`) | (a) `days_of_supply` **ABSENT** from all code (only ADR-091:66 prose). (b) `sell_through` **ABSENT** repo-wide. (c) the "per-SKU daily forecast" is shop-level units split equally: `per_sku_share = 1.0/len(skus)` (`forecaster.py:166-168`) — not a per-SKU forecast. (d) the T1 overlay is hardcoded `{"availability":"unavailable"}` (`analytics_kpi_precompute/unavailable_contract.py:51-53`) | A real per-SKU daily series + a `days_of_supply` callable + a 30-day sell-through computation | **YES — biggest gap** |
| CE-FR-1 data source | ADR-087:89 "`inventory_items` … holds zero rows" — **root cause found**: the writer chain is complete (`sync_inventory` `polling/sync.py:350` → `_PollStep` `polling/orchestrate.py:85` → `run_fujiwa_poll_cycle` → channel `tiktok.inventory.raw` → `transform.py:230` → `InventoryRepo` `repositories/commerce.py:150`) but **`run_fujiwa_poll_cycle` is not in `beat_schedule`** (`workers/celery_app.py:40-92`; its only live caller is manual `services/action_cards/refresh.py:89,123`). Webhook #68 is the other producer | Five readers, one writer no scheduler ever fires. `forecaster.py:181` reads `InventoryItem` and gets nothing | Add the poll cycle to `beat_schedule` (or backfill once) and assert row counts for the reference shop **before** implementation starts | **YES** |
| CE-FR-1 exclusions | `PromotionResource.get_activity(activity_id)` only (`promotion.py:25`) | **No Search/List Activities endpoint exists at TikTok** — `contract-collection.md` A-25 says "Replaces Search Promotion Activity — no list/search endpoint exists"; `endpoints.md:509` repeats it. Campaign-locked / creator-reserved / Thanh lý / Luôn sẵn hàng: **no field anywhere** | Juli must persist its own activity ids at create time and reconcile via webhook #39 | YES (design change, not a capture) |
| CE-FR-2 discount lever | `create_activity` captured only as `activity_type: "FLASHSALE"` (contract-collection B-5 ~line 1185). A-25 read shows `FIXED_PRICE`. **`DIRECT_DISCOUNT` appears nowhere** in code or docs | The one lever v1 depends on is uncaptured — violates the spec's own S-NFR-10 | One sandbox capture of a `DIRECT_DISCOUNT` create | **YES** |
| CE-FR-3 8-rule validator | `services/execution/promotion_leakage.py` is pure passthrough (75 lines, no validation) | Envelope validator ABSENT: no band, no clamp, no margin floor, no collision, no stock-bucket, no ≤300 cap | New validator module | YES |
| CE-FR-4 seller-editable stock goal | `params_sha` binding is real and enforced (`services/agent_runs/confirmations.py:230-231`, `runner/confirmation.py`). But `POST /v1/demo/decisions/{id}/approve` takes **no request body** (`api/routes/demo_execution.py:67-76`), and `_card_snapshot` copies card columns only (`services/agent/approval.py:129-147`) | No path for a seller-supplied value to enter the run or the hash. ADR-055 agent-proposed fields are `apps/demo` UI-only (ADR-055 scope line: "`apps/demo` mobile-web only"); `stock_goal` ABSENT from backend | Approve body + a `seller_inputs` blob in `workflow_runs.state`, re-hashed at CONFIRM | **YES** |
| CE-FR-6 `waiting_external` | `WorkflowRunStatus` has 7 states (`status.py:79-90`); DB CHECK is `status IN ('queued','running','waiting_approval','completed',…)` (`models.py:627`) | `waiting_external` ABSENT — state, CHECK, reaper policy, intervention guard all missing | Migration + enum + reaper branch | YES |
| CE-FR-6 webhooks | #68 `INVENTORY_CHANGED` `confirmed=True`, routed to `clear_excess_4` (`services/tiktok/webhook_catalog.py:179-187`); #27 present but `confirmed=False` (:118); #39 `ACTIVITY_STATUS_CHANGE` present, `confirmed=False` (:134). **#63 ABSENT** from the catalog | #68 lands in bronze/ETL; there is **no `WorkflowWebhookSignal` consumer that resumes a run** — `migrations/011_workflow_webhook_signals.py` is schema only | A webhook→run resume dispatcher | YES |
| CE-NFR-3 measure | `impact_readings` keys on `(tool_execution_id, metric, kind)` (`models.py:843-878`); `classify_mutation_kinds` keys off payload fields `price_update`/`image_uri`/`title`/`description` (`impact_reader/classify.py:57-66`) | No place to record a per-run days-of-supply before/after fact; `impact_readings` has no non-DiD "fact" row shape. A discount write would classify as `[]` and be skipped | Either a `run_facts` JSON on `workflow_runs.state`, or a new `MutationKind.DISCOUNT` + classify branch | YES |
| CE-NFR-3 card KPI | `KPI_WORKFLOW_KEYS` ties `clear_excess_4` to `inventory_turnover` and `dsi` (`services/scoring/kpi_catalog.py:46-47`) — **not AOV** | Spec statement contradicts code | — | — |

---

## Ranked top-8 "discovered during implementation" gaps

1. **The run's subject is not the card's subject.** `ActionCard` has no product/SKU column (`models.py:890-930`), and approval derives the bound product as *the shop's highest-revenue product* (`services/agent/approval.py:13-16, 226-238`). Every OP/CE requirement that says "this listing" / "this SKU" has no producer. ADR-087 subject-scoping is unimplemented.
2. **`inventory_items` is empty because its poll cycle is unscheduled** (`celery_app.py:40-92` has no `run_fujiwa_poll_cycle` entry). Everything CE reads bottoms out here. Also `inventory_items.velocity` is its own consumer-without-producer: `transform.py:245` writes the literal `"low"` for every row (`normalize_inventory` never emits `velocity`) and nothing reads it.
3. **Days of supply and sell-through do not exist**, and the "per-SKU" series is a shop total divided by SKU count (`forecaster.py:166-168`). `get_forecast` (`forecaster.py:178`) persists nothing — all four forecaster entrypoints return in-memory dataclasses. The named T1 forecaster is a permanent `{"availability":"unavailable"}` stub (`analytics_kpi_precompute/unavailable_contract.py:37,52`).
4. **No margin floor input.** No per-SKU cost column exists at all, and the fee proxy is structurally 0 (ADR-065 unimplemented). Worse, the T9 rule's *tests* pass only because they hand-build `platform_commission=35000`/`shipping_fee=25000` fixtures (`tests/unit/test_recommendations.py:744-756, 766`) — the fee floor is green in CI and inert in production. OP-FR-4 / CE-FR-3 are unimplementable as written.
5. **Diagnosis endpoints are not merely uncaptured — they have no constant, resource, guard entry or doc row.** OP-FR-1 is a from-scratch integration slice, and OP-NFR-1's scope check has nothing to check (no scope is stored anywhere).
6. **`DIRECT_DISCOUNT` is uncaptured** (only `FLASHSALE`/`FIXED_PRICE` appear), so both workflows' single lever violates S-NFR-10 on day one.
7. **No seller-supplied-value path.** Approve takes no body; `params_sha` hashes only model-supplied tool arguments. CE-FR-4's editable goal (and RI-FR-4's attested report) need a new consent kind before either workflow ships.
8. **`committed_quantity` is dropped at every layer.** The vendor returns it (contract-collection A-8 `total_committed_quantity` + per-warehouse `committed_quantity`; webhook deltas in `webhook-contract-collection.md:500-519`), but `expand_inventory_search` (`mapping.py:396-433`) keeps only `available_quantity`, `normalize_inventory` (`mapping.py:437-465`) synthesises only `available_quantity`, and `_transform_inventory` (`transform.py:235-248`) collapses it into the single `quantity` column. `committed_quantity` is read **nowhere** in `backend/src`. S-FR-6's "never below a committed quantity" has no data — and no per-warehouse breakdown is persisted at all.

## Spec statements that are wrong about the code

- **"Search Activities (uncaptured)"** (OP Deferred, CE-NFR-2, CE Deferred) — it is not uncaptured, **it does not exist**: `contract-collection.md` A-25 and `endpoints.md:509` both record that TikTok has no list/search activity endpoint. Deferring it to v2 defers something unbuildable; collision detection must be Juli-side permanently.
- **OP-NFR-3 "the tied KPI (CTOR)"** — CTOR exists nowhere in the codebase; `optimize_product_2`'s KPIs are net_revenue/aov/revenue_by_sku/conversion_rate/repeat_purchase (`kpi_catalog.py:38-42`) and the price mutation's impact metric is `gmv` (`metric_map.py:166`).
- **CE-NFR-3 "card KPI unchanged (AOV)"** — `clear_excess_4`'s KPIs are `inventory_turnover` and `dsi` (`kpi_catalog.py:46-47`). AOV is tied to `create_hero_product_1`/`optimize_product_2`.
- **CE-NFR-1 "the intervention guard landed as shared code"** — nothing named or shaped like it exists; `waiting_external` is not a state.
- **§6.1 "`workflow_key` on runs"** is listed as shared work, but note `workflow_runs` also has a hard `product_id` FK (`models.py:577`) and a `uq_workflow_runs_active_shop_product` unique index — polymorphic subject means changing an existing NOT NULL FK and a uniqueness invariant, not just adding a column.
- **OP-FR-3 "No base-price write exists in the tool set"** — one does today (`update_product_price`); removing it also touches `required_steps` (`optimize_product.py:72`), the field-lock map `runner/concurrency.py:180`, and `impact_reader/queries.py`'s measurable-tool derivation.
