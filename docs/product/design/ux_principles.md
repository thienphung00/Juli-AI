# UX Principles — Interaction and Information Design

> `soul.md` defines why, `design.md` defines the visual system, and this file
> defines how the seller workspace behaves.

## Core product principles

1. **Mobile-first** — support single-thumb operation and 44×44px targets.
2. **Minimal cognitive load** — each screen answers one primary question.
3. **Recommendation-first** — Decisions is the action hub.
4. **Sparse Home** — a summary-only activity strip (three counts, no lists or
   actions — [ADR-053](../../adr/053-demo-home-activity-summary.md)) above
   exactly two prominent cards that launch Decisions and Analytics; no KPI
   wall or recommendation actions.
5. **Clear ownership** — Analytics owns reporting; Settings owns workflow
   templates and thresholds.
6. **Human approval required** — no autonomous execution.
7. **Explain before action** — impact is visible; reasoning and evidence are
   revealed via Expand. No confidence score anywhere, collapsed or expanded
   ([PRD #600](https://github.com/thienphung00/Juli-AI/issues/600) — verified
   in code, not just UI copy).
8. **Contextual Juli** — assistance follows the active destination and never
   becomes a standalone tab.

## Screen mental models

| Destination | Primary question | Allowed actions | Forbidden |
|---|---|---|---|
| Home | What has Juli done, what's running, what needs me, and where do I go next? | View activity summary counts; open Decisions or Analytics | KPI/chart reporting, per-item lists, approval, workflow configuration |
| Decisions | What should I do, and what is running? | Expand, Approve, Reject, provide workflow inputs, track work | Templates and thresholds |
| Analytics | What is happening in my shop? | Explore metrics, compare periods, inspect forecasts and evidence | Approve or execute |
| Settings | How should recommendations be configured? | Manage workflow templates and thresholds | Active recommendation decisions |

Juli may explain the current screen, item, or setting in context. She cannot
replace any destination's primary task.

## Navigation

Use exactly four primary destinations on every platform:

1. Home / Trang chủ
2. Decisions / Quyết định
3. Analytics / Phân tích
4. Settings / Cài đặt

Juli is not a fifth destination. Responsive layouts may use a bottom bar,
sidebar, or other platform-appropriate shell while preserving these four
destinations and their ownership.

## Home interaction model

Home answers two questions in order: "What has Juli done, and what needs me
now?" then "Where do I want to go?" ([ADR-053](../../adr/053-demo-home-activity-summary.md)).

**Activity summary** (above the launcher cards) — three counts, reusing
existing lifecycle/tab vocabulary, no new terms:

| Tile | Meaning | Label |
|---|---|---|
| Done | Completed executions | Hoàn tất |
| Running | Executing or awaiting input | Đang thực hiện |
| Needs attention | Open recommendations awaiting review | Đề xuất cần xem xét |

Each tile is a count only — tapping it routes into Decisions (Recommendations
tab for "needs attention"; In Progress tab for "done"/"running"). It never
renders a list, a recommendation card, an execution detail, or an Approve/
Reject control in place. First-run/empty state (nothing yet) renders one calm
explanatory line instead of three zero-value tiles.

**Launcher cards** (unchanged) — exactly two prominent clickable cards below
the summary:

- **Decisions** — opens Decisions, defaulting to Recommendations.
- **Analytics** — opens Analytics.

The cards communicate their destination and current relevance concisely.
Beyond the activity summary above, Home still does not render metric tiles,
KPI charts, shop-health dashboards, recommendation preview cards, a full
task/execution list, In Progress lists, or Approve/Reject controls — those
stay owned by Decisions and Analytics.

On mobile the cards stack in one column; wider layouts may place them side by
side. Both cards are keyboard accessible and have a visible focus state.

## Decisions structure

Decisions has exactly two sub-tabs:

| Tab | Content | Empty state |
|---|---|---|
| Recommendations / Đề xuất | Ranked recommendation cards with the human gate | Explain why none are available and what happens next |
| In Progress / Đang thực hiện | Approved workflows using current statuses | Explain that there is no approved work yet |

Workflow Templates is not a Decisions sub-tab. Templates and thresholds live
under Settings.

## Recommendation card human gate

Every recommendation exposes:

- **Approve / Phê duyệt** — opens the workflow with known inputs prefilled and
  missing/editable inputs fillable. Execution does not begin before the
  required review and inputs.
- **Reject / Từ chối** — removes the recommendation from the active list and
  confirms the result. It does not execute, snooze, or silently defer.
- **Expand / Mở rộng** — toggles reasoning and details in place, including
  expected impact, evidence, inputs, and risks. No confidence score,
  collapsed or expanded.

Reasoning is collapsed by default and available in one interaction. Back
navigation from the workflow preserves the Decisions list position.

## Workflow and In Progress behavior

Approve leads into one shared workflow experience whose fields can be
prefilled or completed by the seller. Workflow-specific action, wait, outcome,
error, recovery, and rollback states render within that execution experience.

Preserve the current In Progress statuses:

- `needs_input`
- `executing`
- `completed`

Their names and lifecycle are explicitly deferred. Do not introduce a new
status model in lower-tier design specifications.

## Analytics ownership

Analytics owns all:

- KPIs and shop-health metrics
- charts and time series
- date ranges and period comparisons
- forecasts and estimated trends
- metric drill-down and supporting evidence

Analytics can deep-link to a relevant recommendation in Decisions, but it
cannot expose the approval gate directly.

## Settings ownership

Settings owns workflow templates and thresholds. Configuration is
progressively disclosed and separate from both recommendation review and
active execution. A setting may affect future recommendation eligibility but
must never auto-approve an existing recommendation.

## Contextual Juli assistance

Juli assistance is:

- **Contextual** — grounded in the active destination, metric,
  recommendation, workflow state, or setting.
- **Assistive** — explains evidence, compares values, clarifies platform
  policy, or helps complete an input.
- **Non-authorizing** — cannot Approve, Reject, or execute for the seller.
- **Non-navigational** — not a primary tab or destination.

## Cross-destination journeys

| Direction | Behavior |
|---|---|
| Home → Decisions | Open Recommendations |
| Home → Analytics | Open the Analytics overview |
| Analytics → Decisions | Deep-link to and highlight a related recommendation |
| Decisions → Analytics | Open supporting metric evidence |
| Decisions → Settings | Open relevant template/threshold configuration without changing the active decision |

Deep links preserve useful return context and focus the destination target.

## Vietnamese copy standards

Follow `design-context.md` for voice and copy rules; look up product terms in
repo-root [`dictionary.md`](../../../dictionary.md):

- All user-visible strings use Vietnamese with full diacritics.
- Errors state the problem and recovery step.
- Empty states explain why and what happens next.
- Currency, dates, and numbers use shared formatters.

## Accessibility

| Requirement | Standard |
|---|---|
| Text contrast | WCAG AA 4.5:1 |
| UI component contrast | 3:1 |
| Touch targets | At least 44×44px |
| Forms | Label controls; connect errors with `aria-describedby` |
| Dialogs | Focus trap, `aria-modal`, labelled title |
| Tabs | `role="tablist"`, `role="tab"`, `aria-selected` |
| Expandable cards | Expose `aria-expanded` and controlled content |
| Live feedback | Use `aria-live` for asynchronous state |
| Icon-only controls | Provide an `aria-label` |
| Reduced motion | Disable nonessential glow, pulse, and stagger |

## Loading, empty, and error states

| State | Pattern |
|---|---|
| Initial load | Skeleton placeholders, never a blank screen |
| No data | Explain why and what happens next |
| Demo/preview | Explicit disclosure |
| Restricted surface | Clear out-of-scope message, never a broken shell |
| Failed action | Preserve seller input and offer a recovery step |

## Performance UX

- Primary destinations target under two seconds to useful content.
- Home remains lightweight.
- Heavy reporting loads in Analytics; workflow detail loads in Decisions.
- Animations respect `prefers-reduced-motion`.

## UX anti-patterns

- More or fewer than four primary destinations.
- A standalone Juli or AI-chat tab.
- Dashboard-first or metric-heavy Home (the ADR-053 activity summary is three
  lifecycle counts, not a metrics dashboard).
- Approval or recommendation previews on Home (summary counts route to
  Decisions; they never render recommendation or execution content in place).
- KPI reporting outside Analytics.
- Workflow Templates as a Decisions sub-tab.
- Threshold management outside Settings.
- Approval without a human choice.
- Hiding reasoning behind a second destination.
- Renaming the current In Progress statuses.
- Pipeline-stage labels exposed as user-facing navigation.
- Non-Vietnamese placeholders or inaccessible click-only containers.
