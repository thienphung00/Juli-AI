# 6. Quản lý chương trình khuyến mãi

> Execution authority: `execution_layer.md` §7a/7b/7c Promotion.

## Identity and capability

Recommendation identity: `manage_promotion_activity`.

| Branch | `workflow_key` | FBS `tool_name` | Capability |
|---|---|---|---|
| Create | `create_activity_7a` | `promotion.create_activity` | FBS executable |
| Update | `update_activity_7c` | `promotion.update_activity` | FBS executable |
| End | `delete_activity_7b` | `promotion.delete_activity` | FBS executable |

## Eligibility and unresolved trigger

Requires an authorized shop, known SKUs/prices, promotion eligibility, and for update/end
a known `activity_id`. Search Promotion Activity is unavailable; never offer arbitrary
search. Growth/performance/goal thresholds that create these recommendations are
**unresolved**.

## Recommendation card

Show branch (Create/Update/End), activity or proposed activity, affected SKUs, observed
signal, window, expected impact only when sourced, confidence, eligibility, and capability.

## Inputs and defaults

Create/update inputs: authoritative activity type, SKUs, discount/prices, and dates. No
discount or impact number is invented. End has no configurable payload beyond confirmation.
Known `activity_id` is read-only.

## FBS numbered screen-states

### Create branch

1. **Outcome — Create eligibility:** show SKU/price/window constraints.
2. **Action — Create Activity:** submit approved activity.
3. **Action — Update Activity Product:** attach approved SKUs/prices.
4. **Wait — Activity live:** Activity status change #39 confirms live/failed.
5. **Outcome — Active / partial / rejected:** show activity and product-level result.

### Update branch

6. **Outcome — Known activity loaded:** identify by tracked `activity_id`; no search.
7. **Action — Update Activity Product/configuration:** submit approved activity/product
   changes using the cataloged update operation.
8. **Wait — Activity changed:** wait for #39 lifecycle and/or #63 configuration event.
9. **Outcome — Updated / partial / rejected:** show authoritative status.

### End branch

10. **Action — Get Activity:** refresh known `activity_id`.
11. **Outcome — End eligibility:** already inactive ends as a no-op outcome.
12. **Action — Deactivate Activity:** submit explicit seller approval.
13. **Wait — Deactivation:** Activity status change #39 confirms effect.
14. **Outcome — Inactive / still active / failed:** show recovery.

## Branch rules

Exactly one execution key is dispatched per recommendation. Create must attach products
before reporting live. Update/end require a known ID. Activity change #63 is cataloged for
configuration edits but support must be shown as unresolved if not subscribed/available in
the current environment.

## Errors and recovery

Eligibility errors return to inputs; create success plus product-attach failure is partial,
not total failure; update rejection names field/SKU; missing ID blocks update/end; webhook
timeout offers Get Activity refresh where authoritative; deactivation failure keeps the
activity visibly active and allows retry.

## FBT target-state scaffold — intentionally unfilled

Promotion behavior for FBT-held SKUs, FBT eligibility, keys, inputs, actions, waits,
outcomes, and recovery are **Unresolved/Unfilled**. Do not infer parity from FBS.
