# Home — activity summary + launcher

> Route: `/` (`apps/demo`; the IA model here is ADR-023-shared, but this spec's current
> layout targets `apps/demo` — see [ADR-053](../../adr/053-demo-home-activity-summary.md)).
> First-run flow: [`../Flows/home/onboarding.md`](../Flows/home/onboarding.md).
> `apps/dashboard`'s authenticated Home (`SellerHomeShell`/`HomeSummaryShell`) is a
> separate, already-richer experience; it is a known divergence from this spec, not
> touched by this update, and pending its own future reconciliation ADR.
> Home answers, in order: **What has Juli done, what's running, what needs me now?**
> then **Where do I want to go?**

## Layout

Top to bottom:

1. **Activity summary** (new — [ADR-053](../../adr/053-demo-home-activity-summary.md)) —
   three stat tiles in a row: Done, Running, Needs attention (see Content rules). Summary
   only — no list, no card content, no actions.
2. Optional connection/collection notice, if applicable.
3. Exactly two equal-priority launcher cards:
   - **Quyết định / Decisions** — short copy about reviewing recommendations and tracking
     approved work; opens `/decisions`.
   - **Phân tích / Analytics** — short copy about shop KPIs, trends, comparisons, and
     forecasts; opens `/analytics`.

Desktop uses a two-column card row in a centered container; the activity summary spans
the full width above it. Mobile stacks everything in one column. Each launcher card is
one keyboard-operable link with a visible focus state and a 44×44px minimum target; each
activity tile is a keyboard-operable link/button with the same target minimum.

## Content rules — activity summary

- Exactly three tiles, in this order, reusing existing lifecycle/tab vocabulary (no new
  terms coined):
  | Tile | Label | Meaning | Routes to |
  |---|---|---|---|
  | Done | Hoàn tất | Completed executions | `/decisions` (In Progress tab) |
  | Running | Đang thực hiện | Executing or awaiting input | `/decisions` (In Progress tab) |
  | Needs attention | Đề xuất cần xem xét | Open recommendations awaiting review | `/decisions` (Recommendations tab) |
- Each tile shows a count and its label only — no timestamps, no per-item preview, no
  Approve/Reject control, no execution/recommendation detail.
- First-run/empty state (no executions and no recommendations yet): render one calm
  explanatory line in place of the three tiles — do not show three zeros.
- Copy budget ([`design.md`](../design.md#copy-density)): tile label ≤ 3 words.

## Content rules — launcher cards

- Show a title, one sentence, and a directional affordance per card.
- A small count such as open recommendations may appear on the Decisions card only
  when backed by current data; it is not a KPI.
- Juli may provide contextual help in the header, but is not a third launcher.
- Loading affects only the optional count/connection notice; both destination links
  remain available.

## Forbidden on Home

No KPI values, metric tiles, charts, health bars, forecasts, recommendation preview
cards, per-item execution/recommendation lists, Approve/Reject controls, execution
queues, workflow templates, or thresholds. The ADR-053 activity summary is three
lifecycle **counts** — it is the one exception to "no counts beyond the Decisions card
count," not an exception to "no lists/actions." KPI and metric reporting belongs
exclusively to [`analytics.md`](analytics.md); recommendation and execution work
(and their approval gate) belongs to [`decisions.md`](decisions.md).

## States

1. **Connected, has activity** — activity summary (real counts) + two launcher cards.
2. **Connected, no activity yet** — activity summary empty state + two launcher cards.
3. **Collecting data** — truthful notice above the same layout; Analytics explains
   unavailable metrics after navigation.
4. **Connection required** — connection CTA above the same layout.
5. **Connection error** — state the problem and recovery action; never replace the
   launcher with a dead end. Activity summary fails independently of the launcher
   cards (a summary load error does not block opening Decisions/Analytics).
