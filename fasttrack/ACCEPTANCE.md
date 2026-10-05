# Acceptance criteria

Tick with evidence: `- [x] AC-n … — evidence: <sha / test / query / log>`.

## P0 — setup

- [x] **AC-0.1** Branch `fasttrack/optimize-product` exists on origin, cut from
  `main` after #2079. — evidence: 86795725 pushed to origin
- [x] **AC-0.2** `fasttrack/` contains README, SPEC, ACCEPTANCE, PROGRESS,
  DECISIONS, LOG, DEBT. — evidence: 86795725
- [x] **AC-0.3** `.claude` edit hooks and the executor-cache pre-commit gate are
  disabled on this branch (D4); ruff pre-commit hooks stay. — evidence: 86795725 (owner-applied)
- [x] **AC-0.4** `fasttrack/check.sh` runs, in order: migration check on a
  throwaway Postgres, shop-isolation tests, gitleaks, ruff, pytest on files
  touched since a given ref. Exits non-zero on any failure. — evidence: 596f9d0b; local full run on throwaway PG16: migrations to head, isolation proof 12 passed
- [x] **AC-0.5** A manual (`workflow_dispatch`) deploy workflow for this branch:
  takes a commit SHA; **backs up the production database first and aborts
  before any migration if the backup fails or is empty**; runs `check.sh`;
  then deploys using the existing VPS deploy path. Never triggers on push. — evidence: 596f9d0b; actionlint clean. CAVEAT: dispatch needs the file on the default branch — see LOG OPEN item
- [x] **AC-0.6** Open Dependabot PRs closed with a comment pointing at D3. — evidence: 19 Dependabot PRs closed 2026-10-05

## P1 — data layer

- [ ] **AC-1.1** OAuth callback enqueues `bootstrap_shop(shop_id)` after commit
  on a high-priority queue; an enqueue failure is logged and does not fail the
  callback. Test covers both.
- [ ] **AC-1.2** Fast phase: commerce cold start + last 30 days of analytics
  via date-range detail calls, then scoring + card persistence for that shop.
  Test with a fake TikTok resource shows rows written for 30 distinct days and
  a card persisted.
- [ ] **AC-1.3** History phase runs on a low-priority queue after the fast
  phase, walks back in chunks until no data, records the earliest date, and is
  resumable (re-running doesn't refetch completed chunks). Tested.
- [ ] **AC-1.4** Per-shop bootstrap state + timestamps persisted (migration).
- [ ] **AC-1.5** One beat entry fans out one task per connected shop with a
  usable read credential (production merchant and `SELLER_CONNECT` shops);
  shops without a completed fast phase get `bootstrap_shop`; a per-shop mutex
  prevents overlap. Tested with ≥2 shops.
- [ ] **AC-1.6** Commerce stays incremental every 15 min; analytics runs at
  most once per day per shop and fetches every missing day up to
  `latest_available_date`; a cycle with nothing new makes zero analytics
  detail calls. Tested.
- [ ] **AC-1.7** Product/SKU detail calls run concurrently (bounded) and still
  respect the rate limiter and cycle budget. Tested.
- [x] **AC-1.8** Mapper: product-grain rows carry `impressions`, per-content-type
  breakdown, `ctr`, derived clicks, and `conversion_rate` (from
  `click_order_rate`); fixture built from the contract samples in
  `docs/integrations/tiktok_api/contract-collection.md`. — evidence: 4010fece; tests/unit/test_tiktok_mapping_product_analytics.py 15 passed
- [x] **AC-1.9** `products.price` filled from `tax_exclusive_price`;
  `products.category`/`category_id` filled from the `category_chains` leaf.
  Tested against `docs/integrations/tiktok_api/samples/`. — evidence: 4010fece; same test file (samples products-{search,detail}-response.json)
- [ ] **AC-1.10** Latency events/timestamps exist for connect → bootstrap
  enqueued → fast done → first card → history done.
- [ ] **AC-1.11** All new/changed backend tests pass; `fasttrack/check.sh`
  passes locally (minus the production backup step).
- [ ] **AC-1.12** Shop isolation holds: new per-shop tasks run under the
  correct shop scope (sticky scope where ETL commits mid-cycle, as #1967).
  Tested with two shops.
