# Analytics — Main KPI reporting

> Routes: `/analytics` and `/analytics/[metricKey]`. Flow:
> [`../Flows/analytics/dashboard.md`](../Flows/analytics/dashboard.md). Analytics
> exclusively owns KPI, chart, comparison, forecast, provenance, and reporting
> experiences.

## Primary question

**Điều gì đang xảy ra trong shop của tôi?**

The first view is a six-Main-KPI selector, not a generic metric wall. It gives
one KPI enough space for interpretation while keeping the other categories
visible.

## Main KPI set

| Stable `metricKey` | Category | KPI | Availability | Hero chart from `docs/ml/visual_layer.md` |
|---|---|---|---|---|
| `sps` | Shop Status | SPS | Unavailable | Horizontal health bar |
| `net-revenue` | Revenue | Net Revenue | Available; default | Actual-vs-Forecast line + interval |
| `roas` | Ads | ROAS | Unavailable | Actual-vs-Forecast line |
| `inventory-turnover` | Inventory | Inventory Turnover | Available | Trend line + forecast |
| `fulfillment-accuracy-rate` | Operations | Fulfillment Accuracy Rate | Available | Gauge |
| `csat` | Customer Service | CSAT | Unavailable | Gauge |

`SPS`, `ROAS`, and `CSAT` remain visible but non-selectable until their required
sources are connected. They never render fixture values or zeroed charts.

## Layout

```
┌────────────────────────────────────────────────────────────┐
│ Phân tích                         7 ngày · 30 ngày · 90 ngày│
├───────────────────────────────┬────────────────────────────┤
│ Hero summary                  │ KPI-specific hero chart    │
│ KPI name + formatted value    │ from visual_layer.md       │
│ what changed → risk → action  │ comparison overlay optional│
│ source + freshness            │                            │
└───────────────────────────────┴────────────────────────────┘
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ Main KPI card    │ │ Main KPI card    │ │ Main KPI card    │
│ preview / empty  │ │ preview / empty  │ │ preview / empty  │
└──────────────────┘ └──────────────────┘ └──────────────────┘
```

- Default selection: **Net Revenue** at `/analytics/net-revenue`.
- Default global range: **30 ngày**.
- Wide view: the hero has summary, signal, provenance, and controls on the left;
  chart on the right. Narrow view: both hero columns and the card grid collapse
  to one column.
- The five non-selected Main KPIs appear in a responsive selector grid.
- Selecting an available card moves it into the hero and returns the previously
  selected KPI to the grid. This is a literal swap; there are always one hero
  and five cards.
- Selection updates `/analytics/[metricKey]` and browser history. Back/forward
  navigation restores the selected KPI without resetting the global range.

## Hero contract

The selected Main KPI hero contains:

1. Category icon, KPI name, one-line description, formatted value, and delta.
2. One-line signal: **what changed → risk/opportunity → action**.
3. `Nguồn dữ liệu` and `Cập nhật lần cuối`; fixture/demo/live status is explicit.
4. Global range controls: `7 ngày`, `30 ngày`, `90 ngày`; custom range may follow.
5. Hero-only `So sánh kỳ trước` toggle.
6. The exact graph type defined above and in `docs/ml/visual_layer.md`.
7. A related Decision link only when a real `workflow_id` exists.

The range changes the hero summary, signal, chart, and every available card
preview as one transaction. Period comparison affects the hero chart only.

## Main KPI selector card contract

Each card contains:

- category icon;
- canonical KPI name;
- one-line Vietnamese description;
- low-contrast preview chart behind a readability-safe foreground layer;
- visible availability label when unavailable.

Available cards are real buttons with 44×44px minimum targets and visible
focus. Their preview is supporting texture; text and numeric labels remain the
accessible data equivalent.

Unavailable cards:

- show `Chưa khả dụng`;
- are not selection controls and cannot become the hero;
- use a neutral empty-chart pattern, never fake data;
- expose a labelled info button and accessible popover explaining the missing
  source and activation requirement.

## Components used

| Region | Contract |
|---|---|
| Hero and selectors | [`../Components/cards.md`](../Components/cards.md) |
| Hero and preview charts | [`../Components/charts.md`](../Components/charts.md) |
| Range presets | [`../Components/chips.md`](../Components/chips.md) |
| Unavailable explanation | [`../Components/empty-states.md`](../Components/empty-states.md) + [`../Components/popovers.md`](../Components/popovers.md) |
| Related Decision | [`../Components/buttons.md`](../Components/buttons.md), `/decisions?highlight=<workflow_id>` |

## Screen states

1. **Loaded** — one available hero plus five selector cards.
2. **Loading** — stable hero and five-card skeletons; no layout jump.
3. **Unavailable card** — neutral empty chart, status label, and explanation.
4. **Partial data** — available window renders with incomplete source/window label.
5. **Error** — preserve selected KPI and range; state the problem and offer retry.
6. **Invalid deep link** — keep the URL understandable, explain the missing KPI,
   and offer Net Revenue; do not silently select a different metric.

## Acceptance checklist

- Exactly six Main KPIs, one hero, and five cards.
- Net Revenue and 30 days are the defaults.
- SPS, ROAS, and CSAT are visibly unavailable and non-selectable.
- Available selection swaps literally and updates browser history.
- Global range updates hero and previews; comparison remains hero-only.
- Every chart matches `visual_layer.md`; no fabricated data appears.
- Popovers have labelled triggers, managed focus, Escape dismissal, and
  outside-click dismissal.
- Text remains readable over previews; the layout is one column on narrow screens.
- Home contains no KPI, chart, health summary, comparison, or forecast.
