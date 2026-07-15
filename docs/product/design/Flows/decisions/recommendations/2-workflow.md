# 2. Tối ưu sản phẩm

> Execution authority: `execution_layer.md` §2 Optimize Product.

## Identity and capability

| Key | Value |
|---|---|
| Display name | Tối ưu sản phẩm |
| Recommendation identity | `optimize_product` |
| `workflow_key` | `optimize_product_2` |
| FBS `tool_name` | `listing.optimize_product` |
| Capability | **FBS executable**; Product status change webhook #5 supports review wait |

## Eligibility and unresolved trigger

Requires an authorized, editable listing, enough actual performance data to explain the
change, valid category fields, and price above the shop margin floor. Revenue-by-SKU or
category-conversion deterioration may motivate the card, but the exact recommendation
threshold/evaluation window is **unresolved**.

## Recommendation card

Show product/SKU, observed underperformance, proposed fields, price delta and margin-floor
guard, expected impact range only when evidence exists, confidence, and capability.

## Inputs and defaults

Current product values come from Get Product. SEO title/description defaults come from
TikTok suggestions. Image/file replacement is off by default. Price defaults to the T9
deterministic advisory bounded by the configured margin floor. Every changed field remains
editable before approval.

## FBS numbered screen-states

1. **Action — Get Product:** load current title, description, images, price, attributes.
2. **Outcome — Editable listing:** block and explain if status/category forbids edits.
3. **Action — Get Products SEO Words:** load supported keywords.
4. **Action — Get Recommended Product Title and Description:** create editable defaults.
5. **Conditional action — Upload Product Image:** run only for approved replacements/additions.
6. **Conditional action — Upload Product File:** run only for category-required document changes.
7. **Outcome — Before/after preview:** show changed fields, price delta, floor, and risks.
8. **Action — Edit Product (partial):** submit approved partial fields; never use full replace.
9. **Action — Update Price:** submit approved price when changed.
10. **Wait — Product re-review:** listen for Product status change #5.
11. **Outcome — Live / changes required / rejected:** show final status and measured-next-step link.

## Branch rules

Skip states 5–6 when assets are unchanged. Skip state 9 when price is unchanged. At least
one approved field must change. Content and price failures are reported separately; a
successful partial edit must not be described as fully failed because price failed.

## Errors and recovery

Unknown product or non-editable status returns to selection; rejected fields return to the
preview with exact errors; below-floor price blocks approval; upload retry targets one
asset; transient failures preserve the approved snapshot/idempotency key; review rejection
never auto-rolls back or resubmits.

## FBT target-state scaffold — intentionally unfilled

Fulfillment-specific optimization behavior, FBT keys, inputs, actions, waits, outcomes,
and recovery are **Unresolved/Unfilled**. Do not infer that the FBS warehouse/price path
is valid for FBT enrollment.
