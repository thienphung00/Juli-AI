# Analytics Main KPI selection and drill-down

> Screen: [`../../Screens/analytics.md`](../../Screens/analytics.md). Routes:
> `/analytics` and `/analytics/[metricKey]`. Analytics owns all KPI reporting.

## Default entry

1. Enter from the Home Analytics launcher, primary navigation, a deep link, or
   supporting evidence in Decisions.
2. `/analytics` resolves to `/analytics/net-revenue`.
3. Render Net Revenue in the hero, the other five Main KPIs in the selector
   grid, and the global range at `30 ngày`.
4. Announce the selected KPI through the page heading, not an intrusive live
   region.

## Select an available Main KPI

1. Focus or tap an available selector card.
2. Activate with pointer, Enter, or Space.
3. Move that KPI into the hero and return the previous hero KPI to the exact
   grid position vacated by the new selection.
4. Push `/analytics/[metricKey]` into browser history.
5. Move focus to the hero heading only when selection was keyboard-initiated;
   pointer activation keeps normal focus behavior.
6. Preserve the global range. Reset hero-only period comparison to off because
   it belongs to the selected KPI's chart state.
7. Render the KPI-specific graph defined in `docs/ml/visual_layer.md`.

Browser back and forward restore the KPI represented by the URL. Invalid keys
show a recoverable state with a `Xem Net Revenue` action; they do not silently
rewrite history.

## Change the global range

1. Choose `7 ngày`, `30 ngày`, or `90 ngày`.
2. Update the hero value, delta, signal, provenance window, and chart together.
3. Update every available selector preview from the same range.
4. Keep unavailable selectors neutral; a range change does not invent data.
5. Keep period comparison hero-only and compare against the immediately
   preceding equivalent window.

## Compare the previous period

1. Toggle `So sánh kỳ trước` inside the hero.
2. Add a dashed, muted previous-period series or equivalent comparison treatment
   appropriate to the KPI graph.
3. Keep the current period visually primary and provide a text legend.
4. Do not add comparison overlays to selector previews.

## Inspect an unavailable Main KPI

SPS, ROAS, and CSAT are visible but non-selectable.

1. The card shows `Chưa khả dụng` and a neutral empty-chart pattern.
2. The seller activates the labelled `Vì sao KPI này chưa khả dụng?` info button.
3. A non-modal popover names the missing source and activation requirement:
   - SPS — official TikTok Shop Account health contract must be verified and connected.
   - ROAS — TikTok Promotion API data ingestion must be connected.
   - CSAT — a legal buyer review/chat source must be available.
4. Escape or outside click closes the popover and returns focus to the trigger.
5. The unavailable card never updates the route or replaces the hero.

## One-line signal and Decision link

The hero states **what changed → risk/opportunity → action** for the active
range. A CTA appears only when the KPI maps to a real open workflow and links to
`/decisions?highlight=<workflow_id>`. Analytics remains advisory; approval and
execution stay in Decisions.

## Data provenance

Show `Nguồn dữ liệu`, `Cập nhật lần cuối`, the active window, and whether data is
fixture, demo, or live. Never label fixture data live. Partial data states name
the incomplete source or period.

## Loading, error, and recovery

- Loading preserves one hero and five-card geometry.
- A range or metric load error preserves the prior successful content,
  selection, and range while offering `Thử lại`.
- An unavailable source uses the unavailable-card pattern, not a network error.
- No state draws zeros, flat lines, or gauges as substitutes for missing data.

## Platform parity

Web, mobile-web, and native preserve the six KPIs, literal swap, route/deep-link
meaning, availability copy, and global-range behavior. Native may use a picker
sheet or popover equivalent while retaining labels, focus order, and dismissal
semantics.
