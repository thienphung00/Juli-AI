# Decisions — Quyết định

> Dashboard routes: `/decisions`, `/decisions/recommendations/[recommendationId]`,
> and `/decisions/in-progress/[executionId]`. Flow index:
> [`../Flows/decisions/README.md`](../Flows/decisions/README.md).

Decisions answers **What should I do, and what is happening after approval?**

## Exactly two sub-tabs

1. **Recommendations / Đề xuất** (default) — ranked recommendation cards.
2. **In Progress / Đang thực hiện** — approved execution list and detail.

Workflow templates and thresholds are not a Decisions tab. They live in
[`settings.md`](settings.md).

## Recommendations / Đề xuất

Each card shows workflow name, detected signal, expected impact, confidence,
capability status, and concise reasoning. It exposes exactly:

- **Phê duyệt / Approve** — opens the workflow's prefilled, editable review flow.
- **Từ chối / Reject** — records rejection and removes the card from the active list.
- **Mở rộng / Expand** — reveals reasoning, evidence, eligibility, and known limits
  inline without navigation.

Cards are ranked by expected impact. `?highlight=<workflow_key>` scrolls to and
briefly rings a real matching card. Unsupported execution disables Approve and
explains the unresolved contract; it never pretends execution is available.

## Recommendation review

The shared route preserves five review stages: Why, Analytics, Inputs, Preview,
Approve. Analytics links to `/analytics/[metricKey]`; it does not duplicate full
KPI reporting. Approve enqueues the documented `workflow_key`/`tool_name` and moves
the seller to `/decisions/in-progress/[executionId]`.

## In Progress / Đang thực hiện

Use the lifecycle and shared list/detail shell in
[`../Flows/decisions/in-progress/README.md`](../Flows/decisions/in-progress/README.md).
The detail route renders the numbered action/wait/outcome states from the matching
workflow specification; actions are states in one route, not separate pages.

## Empty and error states

- Recommendations empty: explain that no current signal needs review and link to Analytics.
- In Progress empty: explain that approved work will appear here.
- Load error: preserve selected tab and offer retry.
- Unknown workflow/execution: show a recoverable not-found state and return to Decisions.
