# P90 deploy checklist (branch fasttrack/reco-final, merge 158000a1)

Never pushed or tagged by the integration agent. Owner runs the deploy.

## 1. Migrations 112-115 (all expand-only; downgrade 115 -> 111 and back verified on a clean cluster)

| Rev | Adds | Downgrade |
|---|---|---|
| 112_shopee_profit_and_history | tables platform_item_snapshots, product_image_assets, shopee_order_lines, shop_rule_versions, ad_campaign_purposes, platform_fee_formulas (reference, no shop_id; juli_ops writes, juli_app reads); columns shop_keyword_seeds.role / item_scope; card_events event_type CHECK accepts whatif_adjusted. RLS by app_current_shop_id() | drops tables and columns, CHECK restored NOT VALID. Order lines / snapshots are lost |
| 113_shopee_orders_and_logs | shopee_order_lines extra columns (buyer_shipping_fee, bank_promo, ad_attributed, seller/shopee_subsidy, returned_qty, completed_at, paid_at, sku, variation_sku); new append-only tables shop_health_daily, ads_change_log | drops the two tables and the columns |
| 114_card_verification_events | widens CHECK ck_card_events_event_type with verified / mismatch / not_seen | restores 112 list as NOT VALID; rows with the new names stay |
| 115_shopee_recommendations | shopee_sim_prior_runs, shopee_reco_calibrations (RLS, juli_app SELECT/INSERT/UPDATE) | drops both tables |

Single alembic head = 115_shopee_recommendations. No data change in any of them, so the pre-deploy backup is the only
real safety net for a downgrade that drops tables with data. Run through infra/safe-alembic-upgrade.sh as usual
(the additive gate should pass: only CREATE / ADD COLUMN / widened CHECK).

## 2. New environment variables

Only one new variable was added by P90 (grep of backend/src, scripts, infra, connector diff against base 731b1d20):

| Variable | Purpose | Required |
|---|---|---|
| JULI_ORDER_REF_MASTER_KEY | master secret (>= 16 bytes) from which the per-shop order_ref HMAC key is derived; the Ops order-upload page fetches it via GET /ops/shops/{id}/shopee/orders/ref-key; the loader uses it with --shop-id | Required before the first order upload; without it the ref-key endpoint answers "unavailable" and the page refuses. Rotating it changes every ref (= reload order history). Store in the same secret store as the other backend secrets |
| JULI_ORDER_REF_KEY (script only) | loader fallback key when no master is set | Optional, scripts only, not a service setting |

No new settings fields. Connector build uses the existing API base (default https://api.app-juli.com).

## 3. New beat job

| Name | Task | Schedule (UTC) | Queue |
|---|---|---|---|
| card-change-verification | juli_backend.card_change_verification | 01:17, 07:17, 13:17, 19:17 | default |

Compares Connector readings with each `executed` card change and writes verified / mismatch / not_seen (48 h deadline)
to card_events. DB only, idempotent. Make sure the beat and the default-queue worker are restarted so the new task is
registered. The calibration "learning" has no beat job: it is run by hand from Ops (POST .../learning/run and
.../learning/backfill) or by the acceptance script. Flag it for the owner if a schedule is wanted.

## 4. New routes

- Demo (seller, shop-scoped): /demo/shop-inputs (GET, template, preview, apply, versions, restore); /demo/shopee (overview, matrix,
  critical, ranking, products/{item_id}); /demo/shopee/recommendations (list, {card}, whatif, approve, request-change, dismiss,
  executed).
- Ops (operator role, masked routes): /ops/shops/{id}/inputs (+template, preview, apply, versions, restore); Shopee analytics
  (overview, matrix, critical, ranking, products/{item_id}); /ops/shops/{id}/shopee/orders/ref-key (GET) and /upload (POST);
  Ops recommendations: list, {card}, learning, sim-priors (GET and POST), generate, publish, rerun-stale, whatif, withdraw,
  executed, learning/run, learning/backfill.
- Demo web app: Shopee screens (Tong quan, Xep hang, San pham, Phan tich, Quyet dinh) and Ops analytics tab; build is a normal
  `next build`, needs the usual NEXT_PUBLIC_SUPABASE_URL / ANON_KEY.

## 5. Connector 0.3.1

Build: `cd apps/connector && pnpm install --frozen-lockfile && node scripts/build.mjs` -> apps/connector/dist (manifest version 0.3.1,
host permissions banhang.shopee.vn and api.app-juli.com). Pilot gate: PILOT_SHOP_IDS in src/config.ts is ORY's Juli shop id only
(d73a240b-a00a-4306-9b3e-9fdf75d72aaf); every reader and the tab scheduler are off for any other shop. Do not widen to "*" until
ORY's first live run is confirmed (request bodies, money units). Install: Unlisted pilot build (STORE_LISTING.md) or, for a first
check, chrome://extensions -> Developer mode -> Load unpacked -> dist/ on the ORY operator's Chrome profile.

## 6. Order of operations

1. Backup (the deploy workflow does it) and confirm CI/check.sh green on the deploy ref.
2. Deploy backend (API, worker, beat) from the merged branch.
3. Set JULI_ORDER_REF_MASTER_KEY in the backend environment (before or with the deploy; restart api).
4. Run migrations 112-115 (safe-alembic-upgrade); confirm `alembic current` = 115_shopee_recommendations.
5. Smoke: GET /health; as Ops open the ORY shop -> Tong quan loads (empty is fine before the loader); GET .../orders/ref-key returns a key
   with Cache-Control no-store; beat log shows card-change-verification registered.
6. Load ORY history if not yet in production: loader per folder with --shop-id and the master key (counts reported below
   came from a local run), then order exports last.
7. Build and install connector 0.3.1 on the ORY seller's Chrome.
8. Pair: in Juli press "Tao ma ket noi" (Tạo mã kết nối), enter the code in the Connector popup.
9. First-run checks (next day's alarm or trigger manually): three prices read (item_snapshot), 114 products in item_catalog,
   yesterday's ads (ads_campaign / ads_change_log), item_traffic_sources rows, voucher_settings, shop_health_daily. Watch for
   money-unit and request-body surprises in the first posts.
10. Only then consider widening PILOT_SHOP_IDS.

## 7. Rollback

- Backend: redeploy the previous release; the new tables are unused by old code, so migrations can stay applied (preferred).
- Migrations: downgrade to 111_shopee_keywords only if required; it drops order lines, snapshots, health/ads log, sim and calibration
  tables (data loss) - restore from the pre-deploy backup instead where the data matters.
- Connector: remove/disable the extension, or ship a build with PILOT_SHOP_IDS = [] (all readers off). It never writes to Seller Centre.
- Order_ref master rotation = reload of order history; do not rotate casually.

## 8. Known limits and test status

- Local full suites on the merged tree: all green except pre-existing failures (see report). tests/integration/test_migrations.py::
  test_no_public_table_holds_update_beyond_its_call_site fails on base 731b1d20 with 23 unjustified UPDATE grants; P90 adds 3 more
  (shopee_order_lines, shopee_sim_prior_runs, shopee_reco_calibrations) following the same pattern as the other platform_* tables. Needs
  an owner decision: register those tables' call sites in GRANT_REQUIRED (and the 23 older ones) or tighten grants.
- Nine other integration tests fail identically on base (restore_drill x3, safe_alembic_upgrade_local, change_attribution x2, p61e
  journey, agent registry sanitizer, demo cohort impact reading) - environment/ordering related, not P90.
- ruff in this machine is 0.15.22 while backend pins >=0.16.2; `ruff format --check` lists 30 files, none touched by P90.
- Real-data run: no real cost prices (cost coverage 100 % assumed), 0 KOL / affiliate-linked orders in October, ads_budget natural
  experiments unusable (changes made by the Shopee optimiser), review_voucher calibration has 7 usable points and is out of range,
  matrix shows Thẻ sản phẩm children 0, 5 datasets more than 3 days behind the window end.
- Recommendation cards are ranked by dGMV P25 per month; no simulation priors are imported until a juli-sim file is passed with --sim-file.
- Assisted execution only: nothing writes to Seller Centre; the seller applies each change and presses "Da lam".
- Not run here: Playwright mobile beyond the shopee specs, gitleaks CI binary version (local gitleaks 93 commits: no leaks), live Seller Centre.
