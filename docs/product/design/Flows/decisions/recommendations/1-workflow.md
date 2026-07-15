# 1. Tạo sản phẩm nổi bật

> Execution authority: `execution_layer.md` §1 Create Hero Product.

## Identity and capability

| Key | Value |
|---|---|
| Display name | Tạo sản phẩm nổi bật |
| Recommendation identity | `create_hero_product` |
| `workflow_key` | `create_hero_product_1` |
| FBS `tool_name` | `listing.create_hero_product` |
| Detail route | `/decisions/in-progress/[executionId]` |
| Capability | **FBS executable**; product review waits supported by webhooks #5/#37 |

## Eligibility and unresolved trigger

The seller must have an authorized shop, writable product capability, a resolvable
category, required attributes/brand/assets, and an FBS warehouse assignment. The T9
deterministic price advisory may prefill price. The exact category-demand-gap
recommendation trigger and threshold are **unresolved**; do not invent them.

## Recommendation card

Show proposed product/category, why it may fill a catalog gap, expected impact only
when backed by comparable data, confidence, capability, and missing prerequisites.
Actions: Approve, Reject, Expand.

## Inputs and defaults

- Category and attributes: prefill only from catalog reads; never guess required values.
- Brand: prefill a confirmed match; otherwise require selection.
- Images: no default asset; seller supplies or confirms uploaded assets.
- Supporting file: off by default; required only when category prerequisites say so.
- SEO title/description: prefill from TikTok suggestions and keep editable.
- Price: prefill T9 advisory within configured margin floor.
- Inventory/warehouse: require a confirmed FBS `warehouse_id`.

## FBS numbered screen-states

1. **Action — Get Category:** resolve `category_id`.
2. **Action — Check Listing Prerequisites:** load seller/category eligibility.
3. **Outcome — Eligibility:** continue, or move to `needs_input` with exact missing prerequisite.
4. **Action — Get Attributes:** load required/optional category fields.
5. **Action — Get Brands:** resolve required `brand_id`; allow documented no-brand path only.
6. **Action — Upload Product Image:** upload each approved image and retain returned URI.
7. **Conditional action — Upload Product File:** run only for category-required documents.
8. **Action — Get Products SEO Words:** load supported keywords.
9. **Action — Get Recommended Product Title and Description:** prefill editable copy.
10. **Outcome — Review ready:** show complete listing, FBS warehouse, price, and validation.
11. **Action — Create Product:** submit the approved single/multi-SKU payload.
12. **Wait — Product review/audit:** listen for Product status change #5 and Product audit
    status change #37; show no fabricated ETA.
13. **Action — Search Product:** confirm post-review listing status.
14. **Outcome — Listed / changes required / rejected:** show TikTok status and recovery.

## Branch rules

Supporting-file upload is conditional on category prerequisites. Brand selection follows
the category contract. Create Product cannot run until every required attribute and FBS
warehouse assignment is valid. Webhook review precedes the final Search Product check.

## Errors and recovery

Category/prerequisite failure returns to states 1–3; missing attributes/brand return to
4–5; upload failure retries only the named asset; validation failure preserves inputs;
transient API errors retry idempotently; audit rejection shows TikTok's reason and opens
the editable review without auto-resubmitting.

## FBT target-state scaffold — intentionally unfilled

- FBT workflow/execution key: **Unresolved**
- TikTok fulfillment-center enrollment/warehouse contract: **Unresolved**
- FBT input defaults, actions, waits, outcomes, and recovery: **Unfilled**
- UI rule: do not offer FBT approval until authoritative contracts and an executor exist.
