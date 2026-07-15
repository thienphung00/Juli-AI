# 8. Xử lý yêu cầu trả hàng

> Execution authority: `execution_layer.md` §8b Request Return.

## Identity and capability

| Key | Value |
|---|---|
| Recommendation identity | `request_return` |
| `workflow_key` | `prevent_return_8b` |
| FBS `tool_name` | `returns.prevent_return` |
| FBT intake key | `prevent_return_8b_fbt` |
| Capability | **FBS executable**; FBT webhook-intake only |

## Eligibility and unresolved trigger

Reverse status update #2 creates intake. Requires an eligible post-shipment request and,
for FBS restock, physical inspection confirming resellable quantity. Production T6 fraud
scoring is deferred by `EXECUTION.md`; any exact fraud threshold or auto-triage policy is
**unresolved** and must not appear as live capability.

## Recommendation card

Show masked return/order ID, reason, eligibility/deadline, RMA state, available rule-based
risk evidence (not a fake ML score), proposed seller decision, inventory consequence,
confidence, and capability.

## Inputs and defaults

No Approve/Reject default. Reject reason comes from Get Reject Reasons. Review notes are
required only for an authoritative escalation case. FBS restock defaults to off until
physical inspection; inspected resellable quantity requires explicit input.

## FBS numbered screen-states

1. **Wait/intake — Reverse status update #2:** record new/changed return.
2. **Action — Search Returns:** load authoritative request.
3. **Action — Get Aftersale Eligibility:** verify window and item rules.
4. **Action — Search RMA:** load physical-return tracking.
5. **Wait — RMA Status Update #65:** wait for required physical stage.
6. **Conditional action — Review Aftersales:** run for authoritative ambiguous/escalated cases.
7. **Action — Get Reject Reasons:** load valid reasons.
8. **Needs input — Seller decision:** Approve or Reject; reason required for Reject.
9. **Branch action — Approve Return:** submit approval.
10. **Branch action — Reject Return:** submit rejection/reason.
11. **Wait — Physical inspection:** for approved FBS return, collect resellable result.
12. **Conditional action — Update Inventory:** restock only inspected resellable FBS quantity.
13. **Action — Get Return Records:** read decision/history record.
14. **Wait — Return status change #12:** confirm terminal state.
15. **Outcome — Returned/rejected/restocked/failed:** distinguish return decision from
    inventory reconciliation.

## Branch rules

Approve and Reject are mutually exclusive. Review Aftersales is conditional. Inventory
write occurs only after approved return plus physical inspection; never auto-restock.
Decision success and restock failure are a partial outcome, not a rolled-back decision.

## Errors and recovery

Ineligible/expired requests become read-only; missing RMA waits visibly; missing reject
reason blocks submission; transient decision writes retry idempotently; inspection keeps
`needs_input`; inventory failure preserves inspected quantity; status timeout refreshes
records without fabricating completion.

## FBT target-state scaffold — intentionally unfilled

`prevent_return_8b_fbt` is intake only. Known future stock wait is FBT inventory update
#24, but TikTok inspection state, executor, request/decision parity, inputs, action states,
outcomes, and recovery are **Unresolved/Unfilled**. Never show seller Update Inventory.
