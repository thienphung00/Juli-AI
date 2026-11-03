# backend/src/juli_backend/services/shop_inputs

## Purpose

The seller's imported inputs, P90 step 4 (ADR-120 d.12, `fasttrack/contracts/p90-plan.md`
Step 4): the pre-filled `.xlsx` template, parse / validate / diff / apply, versioned writes with
restore, the cost fallback and the recommendations an input change re-runs. No table of its own:
`shop_rules` is the projection every reader uses, `shop_rule_versions` (migration 112) is the
append-only history.

## Public API

- `template`: `build_template(session, shop_id)` -> `TemplateResult` (sheets `SKU`, 12 columns,
  one row per catalogue SKU; `Mục tiêu`, one row per month set).
- `importer`: `preview_import` (writes nothing: rejections with row / SKU / column / value /
  reason / kind, field diffs old -> new, goal warnings) and `apply_import` (reason required;
  valid rows only; one change set; one file hash; `FileMismatch` when the file is not the one
  checked). Kinds: `unknown_sku`, `cost_ge_price`, `cost_missing`, `out_of_range`, `bad_date`,
  `duplicate_sku`, `invalid_value`, `bad_month`.
- `versions`: `write_version(s)`, `write_rule` (the editors' path), `list_versions`,
  `restore_version`, `sku_history` (change sets `v1`.. per SKU), `restore_sku_version`. Flush,
  never commit: history and projection commit or roll back together.
- `fallback`: `cost_fallbacks` lists the SKUs with no imported cost (assumed cost = list price / 3,
  or the shop's `default_gross_margin_pct`); `ShopEconomics.unit_cost_labelled` names the source.
- `affected`: `affected_recommendations` (open `shop_proposals` + active `action_cards` of the
  changed items; shop-wide for a monthly margin / marketing-cap change), `register_recompute_hook`
  / `mark_stale` (the step-8 generator registers; none today).
- `overview`: the screen's read model. `xlsx_io`: stdlib writer and reader, size limits.

## Scope refs

SKU rules use `item_id` (an item without variations) or `item_id:variation_id`
(`catalogue.sku_scope`); monthly rules use `YYYY-MM`. Keys: `sku_cost`, `packaging`,
`max_discount_pct`, `stock`, `restock_date`, `product_group`, `item_status` (per SKU);
`monthly_gmv`, `monthly_orders`, `monthly_aov`, `monthly_margin_pct`, `monthly_marketing_cap`
(per month). Validators live in `services/shop_rules/rules.py`.

## Routes

`/v1/demo/shop-inputs` (the shop's owner, `set_by = seller`) and `/v1/ops/shops/{id}/inputs`
(Xem+ reads, Vận hành writes, `set_by = team`, audited as `inputs_apply` / `inputs_restore`).

## Tests

`tests/unit/test_shop_inputs.py`, `tests/unit/test_shop_inputs_routes.py`,
`tests/integration/test_shop_inputs_db.py` (Postgres, as `juli_app`),
`apps/demo/src/components/__tests__/shop-inputs.test.tsx`.
