# backend/src/juli_backend/services/shopee_builder

## Purpose

P92 "Tự tạo phương án" (`fasttrack/contracts/p92-plan.md`, API contract
`fasttrack/contracts/p92-api.md`): the builder's backend. It owns **no formula**. A typed version
(one model per strategy, `specs`) becomes a variant (`translate`), the existing recommendation
machinery builds its card (`shopee_recommendations.manual.build_variant`: evaluators, lift model,
floors, spend check), and `outcome` lays the same block out for every kind (driver metric(s), Δ GMV /
orders / profit as low-P50-high, margin after, cost of the change, break-even as extra orders AND CTOR,
estimate basis, warnings).

## Layers

| Module | Role |
|---|---|
| `specs` | pydantic models, one per kind, hard bounds; `items_of` lists the listings a version names |
| `context` | `BuilderContext` (the 30-day `RecoEnv`, the variation rows, the 90-day view, keyword facts), `SpecRefused` |
| `translate` | `to_variant`: typed version -> `manual` variant; a shadow `estimate` variant for a variation set |
| `outcome` | `shape` / `refused`: the B-3 block, `DRIVERS`, `BASIS_LABELS`, break-even, cost per kind |
| `traffic` | orders / clicks of a scope from the flow tables; the CTOR a break-even takes |
| `variations` | B-2: list / selling price, pack count, price per unit, VAT-aware margin, "chưa tính" |
| `catalogue` | B-1: the product picker (catalogue + order lines, 90-day GMV, has_cost, excluded) |
| `copurchase` | "Sản phẩm hay mua cùng" from order lines |
| `response` | the product's own (then the other products') orders response to a price cut -> `prediction` |
| `keywords` | the keyword table of a product: title seeds, suggestions, competitor phrases, ads report |
| `drafts`, `llm` | LLM drafts (titles, cover overlay concepts, description first lines) behind `LLMClient` |
| `service` | loading, `evaluate_versions`, `choose` (through `manual.create_manual`), draft facts |

## Rules

- A listing without a giá vốn can be built: profit and margin are `None` / `chua_tinh`, never the
  1/3-of-price fallback (B-7.1). GMV and orders are still shown.
- An excluded listing has no builder entry: `manual.build_variant` refuses it (`item_excluded`). Its
  sales stay in every shop total; `excluded_summary` gives the Tổng quan line.
- Breaches (floor, shop spend cap `daily_marketing_cap`) warn and never block; `choose` needs
  `acknowledge_breaches` for the P91 warning dialog.
- Estimate basis: `product_history` (this product's days with / without a cut) > `shop` (the other
  products' median, or the shop's measured calibration) > `prior` > `insufficient` (no volume could be
  predicted: bands are `null`, not 0).
- The LLM writes words only. Cover numbers come from the product's own prices; a title is <= 100
  characters, holds every ticked keyword, has no banned term and no certification / ingredient /
  price / percent the facts do not state. Off (switch, key or consent) = 503 `llm_off` "LLM tắt".

## Must not

- Re-implement an evaluator, a fee or a floor; extend `shopee_recommendations` instead.
- Put a buyer field, an order reference or a voucher code in a payload.
- Call a model outside `llm.GatedLLMClient` (the OpenAI gate), or in a test.
