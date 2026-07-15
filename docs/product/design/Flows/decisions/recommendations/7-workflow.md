# 7. Xử lý yêu cầu huỷ đơn

> Execution authority: `execution_layer.md` §8a Request Cancellation.

## Identity and capability

| Key | Value |
|---|---|
| Recommendation identity | `request_cancellation` |
| `workflow_key` | `prevent_cancellation_8a` |
| FBS `tool_name` | `returns.prevent_cancellation` |
| Capability | **FBS executable**; intake #2 and terminal wait #11 supported |

## Eligibility and unresolved trigger

Applies pre-shipment while the seller decision window remains open. Reverse status update
#2 is the intake trigger. Exact auto-approve/auto-reject policy thresholds are
**unresolved**; ambiguous cases require seller approval and the UI must not claim automated
triage occurred without a persisted decision record.

## Recommendation card

Show masked order/request ID, buyer-stated reason, deadline, eligibility, proposed approve
or reject decision with rationale, stock-hold consequence, confidence, and capability.

## Inputs and defaults

No decision default: seller must choose Approve or Reject. Reject reason has no guessed
default and must come from Get Reject Reasons. Request/order identifiers and eligibility
are read-only.

## FBS numbered screen-states

1. **Wait/intake — Reverse status update #2:** create/update the request record.
2. **Action — Search Cancellations:** load authoritative request state.
3. **Action — Get Decision Eligibility:** verify the open decision window.
4. **Outcome — Eligible / expired / already decided:** only eligible continues.
5. **Action — Get Reject Reasons:** load authoritative SEA reasons.
6. **Needs input — Seller decision:** choose Approve or Reject; require reason for Reject.
7. **Branch action — Approve Cancellation:** submit approved choice.
8. **Branch action — Reject Cancellation:** submit rejection and selected reason.
9. **Wait — Cancellation status:** webhook #11 confirms terminal state.
10. **Outcome — Approved / rejected / expired / failed:** show stock hold releases
    automatically; never call Update Inventory.

## Branch rules

States 7 and 8 are mutually exclusive. Expired/already-decided requests are read-only.
No inventory write or rollback exists. Automated clean-case behavior remains unavailable
to the UI until its exact policy and audit contract are authoritative.

## Errors and recovery

Stale request re-runs search; expired eligibility disables actions; missing reject reason
returns to state 5/6; transient write retries idempotently; webhook timeout refreshes the
request without claiming success; terminal rejection cannot be undone in this flow.

## FBT target-state scaffold — intentionally unfilled

The execution authority says fulfillment model does not branch pre-shipment cancellation.
A separate FBT key, actions, waits, inputs, and outcomes are therefore **Unfilled/not
defined**, not inferred. Use the shared cancellation contract only when backend eligibility
confirms it applies.
