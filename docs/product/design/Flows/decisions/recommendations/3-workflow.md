# 3. Nhập thêm hàng

> Execution authority: `execution_layer.md` §3 Replenish Inventory.

## Identity and capability

| Key | Value |
|---|---|
| Recommendation identity | `replenish_inventory` |
| `workflow_key` | `replenish_inventory_3` |
| FBS `tool_name` | `inventory.replenish` |
| FBT intake key | `replenish_inventory_3b` |
| Capability | **FBS TikTok inventory executable**; supplier/ERP and FBT creation contracts unresolved |

## Eligibility and unresolved trigger

Requires an authorized SKU, FBS warehouse, current inventory read, and an approved reorder
quantity. T1/T10 may provide advisory risk and quantity, but Phase 2 is rules-based and the
exact stockout trigger, forecast window, supplier contract, ERP contract, and purchase-order
contract are **unresolved**.

## Recommendation card

Show SKU, current stock, days-of-inventory/risk only when sourced, recommended quantity,
fulfillment model, unresolved external dependency, confidence, and expected stockout days
avoided only when backed by a real forecast.

## Inputs and defaults

Reorder quantity defaults to a documented ROP/EOQ result when available; otherwise no
default. Supplier/ERP path has no default until connected. FBS warehouse is read-only from
the SKU. Direct TikTok inventory update requires confirmed received quantity.

## FBS numbered screen-states

1. **Action — Inventory Search:** load current SKU/warehouse quantity.
2. **Outcome — Replenishment eligibility:** validate FBS ownership and quantity.
3. **Needs input — External path:** seller selects Supplier or ERP; show **Unresolved**
   if no authoritative integration contract exists.
4. **Unresolved action — Create Purchase Order / Purchase Request:** no API behavior invented.
5. **Wait — Supplier delivery:** external tracking contract unresolved; allow seller-confirmed
   receipt only when product policy authorizes that fallback.
6. **Outcome — Inbound receipt confirmed:** show received quantity and discrepancy before write.
7. **Action — Update Inventory:** write confirmed quantity to the FBS warehouse.
8. **Wait — Inventory reconciliation:** listen for Inventory status change #27 and Inventory
   changed #68.
9. **Outcome — Sellable stock reconciled / discrepancy:** show final observed quantity.

## Branch rules

Supplier and ERP branches converge only after confirmed receipt. Approval cannot skip the
real-world delivery wait. A mismatch requires correction before Update Inventory. No
purchase-order cancellation/rollback is promised without a contract.

## Errors and recovery

Stale inventory triggers a re-search; unavailable Supplier/ERP keeps `needs_input`;
invalid quantity returns to inputs; update failure preserves receipt evidence and retries
idempotently; webhook timeout shows last observed quantity and manual refresh, not success.

## FBT target-state scaffold — intentionally unfilled

`replenish_inventory_3b` is webhook-intake only. Create Inbound Shipment API, fulfillment
center selection, shipment labels, inputs, write executor, and recovery are **Unresolved**.
Known future wait: Inbound FBT order status #21, then FBT inventory update #24. These waits
must not be rendered as an executable FBT flow until the creation contract exists.
