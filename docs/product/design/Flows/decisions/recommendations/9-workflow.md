# 9. Xử lý yêu cầu hoàn tiền

> Execution authority: `execution_layer.md` §8c Request Refund.

## Identity and capability

| Key | Value |
|---|---|
| Recommendation identity | `request_refund` |
| `workflow_key` | `prevent_refund_8c` |
| FBS `tool_name` | `returns.prevent_refund` |
| Capability | **FBS executable**; intake #64 and completion #67 supported |

## Eligibility and unresolved trigger

Aftersales Request Status Update #64 is the cataloged intake. Requires an actionable
aftersales request and successful refund calculation. The exact auto-triage/escalation
policy and recommendation threshold are **unresolved**.

## Recommendation card

Show masked request/order ID, request reason, calculated amount when available, partial/full
type, whether a physical return is linked, decision deadline, confidence, and capability.
Never estimate the refund amount.

## Inputs and defaults

No Approve/Reject default. Calculated amount is read-only. Reject reason must come from Get
Reject Reasons. If refund calculation is unavailable, Approve stays disabled and the card
explains the wait/recovery.

## FBS numbered screen-states

1. **Wait/intake — Aftersales Request Status Update #64:** create/update request.
2. **Action — Search Aftersales Request:** load authoritative request.
3. **Action — Calculate Refund:** fetch partial/full amount preview.
4. **Outcome — Calculation ready / unavailable:** only a valid calculation continues.
5. **Action — Get Reject Reasons:** load authoritative reasons.
6. **Needs input — Seller decision:** choose Approve or Reject; reason required for Reject.
7. **Branch action — Approve Refund:** submit the calculated refund.
8. **Branch action — Reject Refund:** submit rejection/reason.
9. **Wait — Refund Success #67:** wait for terminal completion after approval; rejected
   requests wait for their authoritative request state.
10. **Outcome — Refunded / rejected / failed:** show exact amount and status.

## Branch rules

Approve and Reject are mutually exclusive. The seller cannot freely edit calculated
amount. No inventory action exists; a linked physical return is owned by workflow 8.
No rollback is promised after successful refund.

## Errors and recovery

Stale request re-runs search; calculation failure blocks approval and retries; missing
reject reason returns to inputs; transient writes retry idempotently; terminal business
error displays TikTok reason; webhook timeout refreshes the request and never claims money
moved before confirmation.

## FBT target-state scaffold — intentionally unfilled

The execution authority defines no fulfillment-model branch for refund. A distinct FBT key,
inputs, actions, waits, outcomes, and recovery are **Unfilled/not defined**. Do not invent
inventory or fulfillment behavior in this flow.
