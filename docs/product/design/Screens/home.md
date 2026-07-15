# Home — sparse launcher

> Dashboard route: `/`. First-run flow: [`../Flows/home/onboarding.md`](../Flows/home/onboarding.md).
> Source target: `apps/dashboard`. Home answers only: **Where do I want to go?**

## Layout

After the compact shop header and optional connection/collection notice, render exactly
two equal-priority launcher cards:

1. **Quyết định / Decisions** — short copy about reviewing recommendations and tracking
   approved work; opens `/decisions`.
2. **Phân tích / Analytics** — short copy about shop KPIs, trends, comparisons, and
   forecasts; opens `/analytics`.

Desktop uses a two-column card row in a centered container. Mobile stacks the cards.
Each entire card is one keyboard-operable link with a visible focus state and a
44×44px minimum target.

## Content rules

- Show a title, one sentence, and a directional affordance per card.
- A small count such as open recommendations may appear on the Decisions card only
  when backed by current data; it is not a KPI.
- Juli may provide contextual help in the header, but is not a third launcher.
- Loading affects only the optional count/connection notice; both destination links
  remain available.

## Forbidden on Home

No KPI values, metric tiles, charts, health bars, forecasts, recommendation previews,
approval actions, execution queues, workflow templates, or thresholds. KPI and metric
reporting belongs exclusively to [`analytics.md`](analytics.md); recommendation and
execution work belongs to [`decisions.md`](decisions.md).

## States

1. **Connected** — two launcher cards.
2. **Collecting data** — truthful notice above the same two cards; Analytics explains
   unavailable metrics after navigation.
3. **Connection required** — connection CTA above the same two cards.
4. **Connection error** — state the problem and recovery action; never replace the
   launcher with a dead end.
