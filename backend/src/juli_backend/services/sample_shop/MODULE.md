# Module: services/sample_shop

## Responsibility
The synthetic Shopee sample shop ("Dữ liệu mẫu", P100 Session 2) shared by the loader
(`scripts/sample_shop`, which imports this package; the backend never imports `scripts/`) and the
API. Contract: `fasttrack/contracts/p100-s2-demo.md`.

## Public Interface
- `catalog` — the six synthetic products (`PRODUCTS`), the reserved Seller Centre id range
  (`SAMPLE_SHOPEE_SHOP_ID_MIN..MAX`, `in_reserved_range`), the decision seeds' constants
  (voucher, title change, keywords). `scripts/sample_shop/catalog.py` re-exports it.
- `seed` — `plan_for(end_date)` → `SeedPlan` (plain values); the steps that make the Quyết định
  cards through the app's own services (`seed_keywords`, `seed_history`, `read_back`, `propose`,
  `approve_cover`), each on the caller's session, no commit; `seed_all` runs them in one
  transaction for a shop whose data rows are already in place.

## Rules
- No LLM, no network, no platform call: arithmetic and fixed strings only.
- Writes only the shop it is handed; the callers guarantee it is a sample shop (the loader's
  `check_target`).
