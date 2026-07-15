# Decisions flows

> Screen: [`../../Screens/decisions.md`](../../Screens/decisions.md). Action-sequence
> authority: [`../../../execution_layer.md`](../../../execution_layer.md). Runtime keys
> mirror `apps/dashboard` requests and backend `WORKFLOW_TOOL_CATALOG`.

Decisions has exactly **Recommendations / Đề xuất** and **In Progress / Đang thực hiện**.
Settings owns workflow templates and thresholds.

## Recommendation lifecycle

1. A supported signal creates a ranked recommendation.
2. The card exposes Approve, Reject, and Expand.
3. Approve opens prefilled inputs and an explicit preview.
4. Final approval dispatches the documented execution key.
5. The recommendation becomes an In Progress execution using the shared
   [`in-progress/README.md`](in-progress/README.md) shell.
6. The detail route renders every numbered action, wait, and outcome state from the
   matching workflow file. Steps never create separate routes.

## Workflow index

| # | Recommendation spec | `workflow_key` | FBS tool(s) |
|---|---|---|---|
| 1 | [`recommendations/1-workflow.md`](recommendations/1-workflow.md) | `create_hero_product_1` | `listing.create_hero_product` |
| 2 | [`recommendations/2-workflow.md`](recommendations/2-workflow.md) | `optimize_product_2` | `listing.optimize_product` |
| 3 | [`recommendations/3-workflow.md`](recommendations/3-workflow.md) | `replenish_inventory_3` | `inventory.replenish` |
| 4 | [`recommendations/4-workflow.md`](recommendations/4-workflow.md) | `clear_excess_4` | `inventory.clear_excess` |
| 5 | [`recommendations/5-workflow.md`](recommendations/5-workflow.md) | `process_order_5` | `fulfillment.process_order` |
| 6 | [`recommendations/6-workflow.md`](recommendations/6-workflow.md) | `create_activity_7a`, `update_activity_7c`, `delete_activity_7b` | `promotion.create_activity`, `promotion.update_activity`, `promotion.delete_activity` |
| 7 | [`recommendations/7-workflow.md`](recommendations/7-workflow.md) | `prevent_cancellation_8a` | `returns.prevent_cancellation` |
| 8 | [`recommendations/8-workflow.md`](recommendations/8-workflow.md) | `prevent_return_8b` | `returns.prevent_return` |
| 9 | [`recommendations/9-workflow.md`](recommendations/9-workflow.md) | `prevent_refund_8c` | `returns.prevent_refund` |

## Capability vocabulary

- **FBS executable** — registered Phase 2 handler exists.
- **Read/wait supported** — authoritative read or webhook exists, but no write occurs.
- **Unresolved** — trigger, third-party contract, or API contract is absent; never invent it.
- **FBT scaffold only** — target-state section intentionally unfilled. FBT executors are
  deferred; `replenish_inventory_3b`, `process_order_5b`, and
  `prevent_return_8b_fbt` are intake-only keys.

Profile targeting is recommendation policy, not execution eligibility. Unless a workflow
file cites a confirmed rule, profile-based suppression is marked unresolved.
