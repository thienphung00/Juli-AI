# Decisions — Quyết định

> Dashboard routes: `/decisions`, `/decisions/recommendations/[recommendationId]`,
> and `/decisions/in-progress/[executionId]`. Flow index:
> [`../Flows/decisions/README.md`](../Flows/decisions/README.md).

Decisions answers **What should I do, and what is happening after approval?**

## Layout density

Reviewed against a tab-composition reference (layout only, not color/brand):
tab header, a "current focus" summary card, a stat row, and one primary CTA —
denser than a kicker/title/intro stack alone. Applied here without adding any
new IA:

- Header: kicker + title trimmed to budget (`design.md#copy-density`) —
  drop the standalone intro paragraph in favor of the stat row below carrying
  the "what's going on" information instead of prose.
- Stat row directly under the header: total open recommendations count and
  total in-progress count, both already-computed values (no new data), giving
  the tab an at-a-glance summary before the list — same density principle as
  the Home activity tracker (`Components/home-activity-tracker.md`), scoped
  here to Decisions' own two counts.
- The two sub-tabs (below) remain the only navigation; the stat row is
  read-only context, not a third tab or a filter control.

## Exactly two sub-tabs

1. **Recommendations / Đề xuất** (default) — ranked recommendation cards.
2. **In Progress / Đang thực hiện** — approved execution list and detail.

Workflow templates and thresholds are not a Decisions tab. They live in
[`settings.md`](settings.md).

## Recommendations / Đề xuất

Each card shows workflow name, detected signal, expected impact, capability
status, and concise reasoning — **no confidence score anywhere, collapsed or
expanded** ([PRD #600](https://github.com/thienphung00/Juli-AI/issues/600)). It exposes
exactly:

- **Phê duyệt / Approve** — opens the workflow's prefilled, editable review flow.
- **Từ chối / Reject** — records rejection and removes the card from the active list.
- **Mở rộng / Expand** — reveals reasoning, evidence, eligibility, and known
  limits inline without navigation. No confidence score, collapsed or expanded.

Cards are ranked by expected impact. `?highlight=<workflow_key>` scrolls to and
briefly rings a real matching card. Unsupported execution disables Approve and
explains the unresolved contract; it never pretends execution is available.

## Recommendation review

The shared route preserves five review stages: Why, Analytics, Inputs, Preview,
Approve. Analytics links to `/analytics/[metricKey]`; it does not duplicate full
KPI reporting. Approve enqueues the documented `workflow_key`/`tool_name` and moves
the seller to `/decisions/in-progress/[executionId]`.

**Inputs stage layout** — reviewed against a form-composition reference (layout
only): grouped labeled fields with a preview panel and a bottom-anchored
primary CTA, denser than an unlabeled single-column stack. Applied here:

- Prefilled fields use the suggestion glow + **Gợi ý bởi Juli** label
  (`Components/forms.md` Suggestion glow) — every prefilled value, no
  exceptions, no confidence score alongside it.
- Group related fields under a short section label instead of one flat list,
  when a workflow has more than ~4 fields.
- The **Preview** stage is the "preview panel" equivalent: it summarizes what
  will be sent before Approve, already specced above — no new stage is added.

## In Progress / Đang thực hiện

Use the lifecycle and shared list/detail shell in
[`../Flows/decisions/in-progress/README.md`](../Flows/decisions/in-progress/README.md).
The detail route renders the numbered action/wait/outcome states from the matching
workflow specification; actions are states in one route, not separate pages.

**List composition:** one execution progress card per item
(`Components/cards.md` Execution progress card) — mode strip (Xác nhận /
Đang chạy) + narrative step line + next action + cancel/rollback + policy
line. Not a status table with columns.

## Empty and error states

- Recommendations empty: explain that no current signal needs review and link to Analytics.
- In Progress empty: explain that approved work will appear here.
- Load error: preserve selected tab and offer retry.
- Unknown workflow/execution: show a recoverable not-found state and return to Decisions.
