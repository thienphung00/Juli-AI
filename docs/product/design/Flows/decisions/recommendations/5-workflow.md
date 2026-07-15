# 5. Xử lý đơn hàng có rủi ro trễ hạn

> Execution authority: `execution_layer.md` §5 Process Order. Handle Split Package
> (§6) is a conditional FBS subflow here, not a separate recommendation.

## Identity and capability

| Key | Value |
|---|---|
| Recommendation identity | `process_order_sla_risk` |
| `workflow_key` | `process_order_5` |
| FBS `tool_name` | `fulfillment.process_order` |
| FBT intake key | `process_order_5b` |
| Capability | **FBS executable**; FBT read/intake only |

## Eligibility and unresolved trigger

Requires an authorized FBS order, complete address, `AWAITING_SHIPMENT` status, shippable
line items, and required carrier/pickup data. T5 ranks SLA risk, but the exact time
threshold and card-generation trigger are **unresolved**.

## Recommendation card

Show order count, nearest deadline, ranked queue, fulfillment/shipping type, address-change
warning, expected SLA-risk reduction as a count (not invented money), confidence, and
capability. Never expose buyer PII beyond the minimum masked fulfillment context.

## Inputs and defaults

Order priority defaults to T5 rank and is read-only. Shipping type defaults from the order.
Ship by TikTok requires document type/pickup inputs supported by contract. Ship by Seller
requires seller-entered tracking number and provider ID. Split/combine is off by default
and appears only when packing constraints require it.

## FBS numbered screen-states

1. **Action — Get Order List:** load candidate orders.
2. **Action — Get Order Detail:** load current status, fulfillment/shipping type, masked address.
3. **Wait — Recipient address stability:** if webhook #3 fires, return to state 2.
4. **Wait — AWAITING_SHIPMENT:** webhook #1 must move `ON_HOLD` to `AWAITING_SHIPMENT`.
5. **Outcome — Ready to pack:** show validated line items and shipping branch.
6. **Conditional subflow — Handle Split Package:** run states 6.1–6.7 below when required.
7. **Action — Create Packages:** group approved line items and retain `package_id`.
8. **Ship-by-TikTok action — Get Package Shipping Document:** fetch pick list/label.
9. **Ship-by-Seller outcome — Own-carrier details ready:** skip TikTok document; require
   tracking number and shipping provider ID.
10. **Ship-by-TikTok action — Ship Package:** ship one package, or use Batch Ship Packages
    for an approved multi-package batch.
11. **Ship-by-Seller action — Batch Ship Packages:** send `self_shipment` tracking/provider.
12. **Action — Confirm Package Shipment:** sync through Supply Chain API.
13. **Action — Get Package Detail:** read final package/shipment state.
14. **Outcome — Shipped / partial / failed:** show per-package result and next recovery.

### Conditional FBS subflow 6 — Handle Split Package

6.1. **Action — Get Order Split Attributes:** load permitted grouping constraints.  
6.2. **Branch outcome — Split/combine/uncombine/not needed:** require seller confirmation.  
6.3. **Conditional action — Split Orders:** create seller-approved package groups.  
6.4. **Conditional action — Search Combinable Packages:** list only authoritative matches.  
6.5. **Conditional action — Combine Package:** combine selected compatible packages.  
6.6. **Conditional action — Uncombine Packages:** reverse a selected combination.  
6.7. **Wait/outcome — Package update:** webhook #4 confirms the mutation before state 7.

## Branch rules

Never create/ship while `ON_HOLD`. An address update invalidates the prior detail snapshot.
Ship by TikTok and Ship by Seller are mutually exclusive per package. Split Package runs
before final package creation/shipping and only for FBS. No shipped package rollback exists.

## Errors and recovery

Stale order/address re-fetches detail; status wait offers refresh without bypass; package
mutation waits for #4; document failure retries the named package; tracking validation
returns to inputs; partial batch success shows per-package results; confirm/detail failure
does not claim shipment reversal and retries idempotently.

## FBT target-state scaffold — intentionally unfilled

`process_order_5b` is intake/read only. Known reads/waits are Get Order List, Get Order
Detail, Get FBT MCF Order Status, and webhook #58. FBT API path/schema, executor, inputs,
screen actions, terminal outcomes, and recovery are **Unresolved/Unfilled**. Never show
Create Packages, labels, ship, split, or confirm controls for FBT.
