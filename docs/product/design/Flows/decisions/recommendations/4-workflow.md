# 4. Xả hàng tồn

> Execution authority: `execution_layer.md` §4 Clear Excess Inventory.

## Identity and capability

| Key | Value |
|---|---|
| Recommendation identity | `clear_excess_inventory` |
| `workflow_key` | `clear_excess_4` |
| FBS `tool_name` | `inventory.clear_excess` |
| Capability | **FBS executable**; activity wait #39 and inventory waits #27/#68 |

## Eligibility and unresolved trigger

Requires an authorized FBS SKU, current inventory, editable price, promotion eligibility,
and seller-approved clearance terms. The exact sell-through/days-of-inventory threshold
and evaluation window are **unresolved**. Never fabricate a Flash Sale eligibility result.

## Recommendation card

Show affected SKUs, observed age/turnover data, baseline markdown, proposed promotion
lever, expected clearance range only when sourced, confidence, and eligibility status.

## Inputs and defaults

SKUs default to those supported by the signal; seller may remove them. Markdown and
activity type have no invented numeric default. Promotion window requires explicit dates.
Seller Flash Sale is selectable only after a real eligibility check. Zero-floor-stock is
shown as a later irreversible step, not silently pre-approved.

## FBS numbered screen-states

1. **Action — Inventory Search:** confirm quantities and aging SKUs.
2. **Action — Get Activity:** load a known activity when updating/avoiding overlap.
3. **Outcome — Clearance eligibility:** show SKU, price, and promotion constraints.
4. **Action — Update Price:** apply the approved baseline markdown.
5. **Conditional action — Create Activity:** create the selected eligible promotion.
6. **Conditional action — Update Activity Product:** attach approved SKUs/prices.
7. **Wait — Activity status:** listen for Activity status change #39 until live/failed.
8. **Outcome — Clearance active:** show active window and observed inventory.
9. **Action — Update Inventory:** after the clearance goal/physical count is confirmed,
   zero remaining FBS floor stock.
10. **Wait — Inventory reconciliation:** listen for #27 and #68.
11. **Action — Deactivate Activity:** close the activity when cleared or expired.
12. **Outcome — Cleared / partial / failed:** show final stock and activity status.

## Branch rules

Price-only clearance skips states 5–7 and still requires explicit approval. Activity
creation requires eligibility. State 9 cannot run merely because a timer expired; require
confirmed physical/business outcome. Deactivation uses the known `activity_id`.

## Errors and recovery

Stale stock re-runs search; price rejection returns to inputs; ineligible Flash Sale falls
back to price-only with seller confirmation; activity failure does not misreport price
rollback; reconciliation timeout shows current observed stock; deactivation failure offers
retry and keeps the activity visibly active.

## FBT target-state scaffold — intentionally unfilled

FBT key, direct-write behavior, activity/stock coordination, inputs, actions, waits,
outcomes, and recovery are **Unresolved/Unfilled**. Known observation is FBT inventory
update #24; no seller-side Update Inventory may be inferred.
