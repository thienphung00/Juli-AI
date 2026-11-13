# P98 waves — parallel slots with disjoint write paths, one deploy

Plan: `fasttrack/contracts/p98-plan.md`. Decisions: `docs/adr/122-one-shopee-funnel-and-option-results.md`.
Contract (fixed, do not edit): `backend/src/juli_backend/services/shopee_builder/engine/contract.py` and
`apps/demo/src/lib/shopee-decisions/option-result.ts`.

**Base / integration branch:** `fasttrack/p98-combo` in `.worktrees/p97-shopee-data` (the parent merges
each slot after its wave, runs the checks, then starts the next wave). One deploy after wave 3.

## Rules for every slot

1. Work ONLY in your slot's worktree (absolute path below). Start every shell command with
   `cd <worktree> &&`. Never touch the primary checkout or another slot's worktree.
2. Write ONLY inside your owned paths. Read anything. A change you need outside them: stop and say so
   in your report — do not make it.
3. Python: `/Users/macos/Juli-AI-v2/juli/.venv/bin/python`, always `PYTHONPATH=<worktree>/backend/src`
   (bare pytest tests the wrong checkout). `ruff check` + `ruff format`, and mypy
   (`--config-file backend/pyproject.toml`) on your files. No new `# noqa` / `# type: ignore`.
4. Tests: TDD (red → green). Fixtures and doubles from `tests/support/`; synthetic data only — never
   Fujiwa or ORY values. Postgres is not available in this sandbox: write Postgres tests (marked as the
   repo does) but say they were not run.
5. Commit on your slot branch (conventional commits, ending with
   `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`). Never push, tag, stash, rebase,
   `worktree remove` or switch branches.
6. Seller-facing text is Vietnamese, the app's wording (`CONTEXT.md` › Shopee option estimates).
7. Report: what you built, files, tests run (pass / fail counts), anything not done, any contract gap.

## Wave 1 — independent foundations (start together)

| Slot | Worktree / branch | Owns (write) | Delivers | Model |
|---|---|---|---|---|
| **W1-A data** | `.worktrees/p97-t1-connector` · `fasttrack/p98-w1-data` | `backend/src/juli_backend/database/migrations/versions/126_shopee_source_funnel.py`; `models/shopee_metrics.py`; `models/__init__.py`; `database/tenant_scoped_tables.py`; `services/shopee_analytics/materialize.py`; new `services/shopee_analytics/funnel_check.py`; `scripts/backfill_shopee_metrics.py`; their tests | S1 + the daily check (d.11.3): table `shopee_source_metrics_daily` (shop_id, day, item_id NULL = shop row, source ∈ contract `SOURCES`, views, clicks, orders, gmv, profit, ads_views, ads_clicks, ads_orders, ads_gmv, ads_spend, scaled_to_totals, built_at; unique (shop_id, day, item_id, source); RLS tenant-direct + `juli_app` SELECT/INSERT/UPDATE like 123); orders / gmv per source allocated to ShopMetrics with `metrics.allocate` so sources sum to the day's totals exactly, residual `chenh_lech_nguon`; rebuilt in `after_ingest` and by the backfill script; `funnel_check.check_day(...)` returns gaps > 1 % or a broken identity and logs `shopee_funnel_mismatch` (no correction) | opus (migration) |
| **W1-B engine** | `.worktrees/p97-t2-metrics` · `fasttrack/p98-w1-engine` | `services/shopee_builder/engine/` except `contract.py` / `__init__.py` (new `engine.py`, `wire.py`, …); `tests/unit/test_funnel_engine*.py` | S3 core: `run(base: FunnelBase, option: OptionInput, seed: int = 0, n: int = 4000) -> OptionResult` — scale base to the duration (`duration_days or 30`, horizon label); draw each driver from its `Band` (fit through P10/P50/P90), two drivers in the same scenario; propagate per source: views → clicks (CTR) → orders (CTOR) → GMV (AOV) → profit (orders × profit per order + ΔAOV × orders × contribution_rate − offers − fixed); `AddedTraffic` orders = views × ctr × ctor × extra_share; offers = min(orders × use_share, cap) × per_use; rank by Δ profit, P10 / P50 / P90 whole columns; build-up (≤ 3 parts), break-even orders and AOV, `not_estimable` → cost + break-even only; `wire.result_json` exactly per `WIRE_KEYS` / `option-result.ts`; `compare(results)` sorts by per-30-day Δ profit. Property tests (d.11.1): identity in every column for random inputs, sources sum, build-up sums, same seed = same result | sonnet |
| **W1-C combo options** | `.worktrees/p97-t3-fill` · `fasttrack/p98-w1-combo-options` | new `services/shopee_builder/combo_options/`; `tests/unit/test_combo_options*.py` | S7 pure core: `generate(products, picks, packs, rules) -> list[ComboOption]` (multi-pack of one product and bundles of several; rules: same variation per pack, only variations sold in 30 days, at most N; count before building; Shopee per-listing limits as config constants marked "confirm at recon"); `price(options, rule, economics, floor)` with rules discount ladder (default), target margin, price per box; rounding to a clean price; per row: price, price per box, saving vs buying separately, margin %, profit per order ("chưa tính" without giá vốn), floor flag; names (Shopee name length limit as config), SKU pattern, suggested stock = member stock ÷ pack ("không tự đồng bộ"). Input is `shopee_builder.variations` economics rows (read only) | sonnet |
| **W1-D connector + drift** | `.worktrees/p97-t4-builder` · `fasttrack/p98-w1-connector` | `apps/connector/**`; `backend/src/juli_backend/services/ingest/status.py`; their tests | (1) `status.dataset_status`: a dataset is "drift" only when `drift_source_version == last_source_version` (a newer version's successful post makes an older flag "ok"); (2) Connector: keep the hook's `detail` in each reader outcome (`lastRun.outcomes` value `status:detail`, trimmed); (3) `readOrders`: when a page ≥ 2 replay fails, still post the page's own answers already collected (status `done` with a `partial` note) instead of dropping them; bump to 0.3.14 (manifest, package.json, PRIVACY / LOG notes as the repo does) | sonnet |

## Wave 2 — on the merged wave 1

| Slot | Worktree / branch | Owns (write) | Delivers | Model |
|---|---|---|---|---|
| **W2-E read model** | `.worktrees/p97-t5-combo-fill` · `fasttrack/p98-w2-funnel` | new `services/shopee_analytics/funnel.py`; `services/shopee_analytics/{overview,matrix,rankings,queries,product,shared,service,metrics,compute,loaders}.py`; `services/shopee_recommendations/plan_base.py`; `apps/demo/src/components/shopee-analytics/product-page.tsx`; `apps/demo/src/components/shopee-decisions/builder-p92/variations.tsx`; their tests | S2 + ADR-122 d.12 on the product page (both margins labelled chắc chắn / ước tính, Đơn = orders, pack-key SKU chip, no 1/3 footer): `load_funnel_base(session, shop_id, *, item_ids, window) -> FunnelBase` from `shopee_source_metrics_daily` (window sums; CTR / CTOR from sums; `source_detail="all_sources"` when product × source rows are missing; `contribution_rate` from the profit rules); every Shopee screen's Lượt xem / CTR / CTOR reads it (CTOR = ShopMetrics đơn ÷ lượt nhấp, the one-line note "CTOR = đơn (theo Tổng quan) ÷ lượt nhấp"); Kế hoạch base too | opus (cross-domain) |
| **W2-F families** | `.worktrees/p92-builder` · `fasttrack/p98-w2-families` | new `services/shopee_builder/engine_families/`; `tests/unit/test_engine_families*.py` | S4: one function per family returning `OptionInput` from a builder version + `RecoEnv` (+ evaluator outputs for costs / profit per order): voucher (d.6), combo khuyến mãi + new combo listing (d.7, pack evidence from matching variations), price / listing / basket / gift (d.10 table, product history > shop > tagged prior), ads new campaign (d.8: measured CPM, ROAS spend, ad CTR / CTOR / AOV, extra share from on / off days else `not_estimable` "chưa ước tính được — cần chạy thử"), affiliate (d.9 per KOL, cashback classification by name list in config) | sonnet |
| **W2-G builder inputs** | `.worktrees/p92-market` · `fasttrack/p98-w2-builders` | new `services/shopee_builder/specs_p98.py`, `combo_builder.py`, `kol_builder.py`, `ads_builder.py`; new `api/routes/demo_shopee_builder_p98.py` (+ one include line in `api/app.py`); `services/shopee_builder/variations.py`; `services/shopee_builder/combo_options/pricing.py`; their tests | ADR-122 d.12: Biên cuối per variation in `variations.py` (served next to Biên ở giá bán) and combo pricing / floor on Biên cuối. S7–S9 backend: request models and services — combo builder (generate / price via `combo_options`, returns rows + per-option `OptionInput` inputs), KOL builder (KOLs from the KOL report, products, commission %, samples: product, qty, shipping), ads builder (new Hiển thị Sản phẩm nhóm / đơn setups: products, budget, ROAS target or Shopee-optimised, dates); read-only endpoints that evaluate (no writes) | sonnet |

## Wave 3 — integration and UI

| Slot | Worktree / branch | Owns (write) | Delivers | Model |
|---|---|---|---|---|
| **W3-H backend integration** | `.worktrees/reco-fixes` · `fasttrack/p98-w3-integrate` | `services/shopee_builder/{service,outcome,before_after,translate,specs}.py`; `services/shopee_builder/MODULE.md`; `docs/security/surface_inventory.json`; `tests/unit/test_threat_model_inventory.py`; `tests/unit/test_reviewer_no_write.py`; existing builder tests that change | Every builder evaluation returns `result` (= `OptionResult.json()`) from base → family → engine; `before_after` and the money layer stop producing results; ads-edit kinds hidden from the builder menu; p98 routes registered in the inventory / allowlists; old builder tests updated to the new numbers | opus (integration) |
| **W3-I card + compare UI** | `.worktrees/reco-versions` · `fasttrack/p98-w3-card` | `apps/demo/src/components/shopee-decisions/builder-p92/{compare,results,shared}.tsx`; new `apps/demo/src/components/shopee-decisions/option-card/`; `apps/demo/src/lib/shopee-decisions/builder-api.ts`; their tests | d.5: the card (Δ Lợi nhuận money · % + range + build-up; Δ GMV; Δ Đơn + note; Tác động %; Chi phí + hoà vốn; Sau N ngày), Chi tiết (seven metrics, scenarios, sources, basis), the "ước tính chung" tag, the comparison table sorted per 30 days — from `option-result.ts` only | sonnet |
| **W3-J builders UI** | `.worktrees/view-fixes` · `fasttrack/p98-w3-builders-ui` | new `apps/demo/src/components/shopee-decisions/{combo-builder,kol-builder,ads-builder}/`; new `apps/demo/src/lib/shopee-decisions/builder-p98-api.ts`; `builder-p92/index.tsx` (entry points only); their tests | Combo builder (pick products / variations / packs, rules, count, pricing rule, editable table, copy), KOL builder (pick KOLs from the table, products, commission, samples), Ads builder (setups) — each row's result rendered with W3-I's card component by import (`option-card/`), not re-implemented | sonnet |
| **W3-K checks + Ops** | `.worktrees/release-1105` · `fasttrack/p98-w3-checks` | new `tests/integration/test_shopee_funnel_cross_screen_db.py`; new `api/routes/ops_shopee_funnel.py` (+ include line in `api/app.py` — coordinate: W2-G's line merges first); new `apps/demo/src/components/ops/shopee/ops-shopee-funnel.tsx`; their tests | d.11.2 cross-screen test; d.11.3 Ops "lệch số liệu" list from `funnel_check`; d.11.4 coverage of frozen predictions (ADR-121 scoring) in Ops | sonnet |

## After wave 3 (parent)

Merge all slots into `fasttrack/p98-combo`; regenerate `surface_inventory.json` and fixtures on the final
tree; full unit suite + demo lint / tsc / vitest; `fasttrack/contracts/p98-deploy-checklist.md`
(migration 126, backfill, Connector 0.3.14 reload); fast-forward `fasttrack/optimize-product`, push,
one `fasttrack-deploy-*` tag.
