# Components / charts.md

> Tokens: `colors_and_type.css`. Library: Recharts. Historical reference:
> `ReportMetricChart.tsx`, `MetricSparkline.tsx`, `RealEstimatedBar.tsx`.

## Sparklines

- Compact trend line inside an Analytics metric card — no axes, no gridlines,
  color from the semantic delta (`--success`/`--destructive`).
- Purely illustrative of direction; the numeric delta badge carries the actual
  value — the sparkline never has to be read precisely.

## Area charts

- Used for KPI drill-down time-series on `Flows/analytics/dashboard.md`.
- Fill uses the metric's semantic color at low opacity (`~12%`), stroke at full
  opacity — never a decorative gradient unrelated to the metric's meaning.

## Line charts

- Used for period-over-period comparison (current vs. previous period as two
  strokes, current period solid, previous period dashed/muted).

## Main KPI hero charts

The hero uses the exact representation owned by `docs/ml/visual_layer.md`:

| Main KPI | Representation |
|---|---|
| SPS | Horizontal health bar |
| Net Revenue | Actual-vs-Forecast line with interval |
| ROAS | Actual-vs-Forecast line |
| Inventory Turnover | Trend line with forecast |
| Fulfillment Accuracy Rate | Gauge |
| CSAT | Gauge |

Unavailable KPIs do not render these representations until their sources are
active. A neutral empty-chart pattern reserves composition without implying a
value.

## Selector preview charts

- Available selector cards use a simplified, low-contrast version of the same
  graph family as their hero.
- Preview marks stay behind a readability-safe foreground layer and use
  semantic CSS variables at low opacity; they never obscure labels.
- Previews have no axes, tooltips, precise-value interaction, or comparison
  overlay. They are `aria-hidden` because the card name, value, and delta are
  the accessible equivalent.
- The global date range updates every available preview. `So sánh kỳ trước`
  remains hero-only.
- Unavailable previews use a neutral dashed baseline/grid motif with no plotted
  series, gauge fill, numeric label, or trend direction.

## Real vs. estimated bar (`RealEstimatedBar`)

- Two segments in one bar: real (solid fill) + estimated/projected (same hue,
  lower opacity + subtle glow pulse, disabled under `prefers-reduced-motion`).
- When a chart supports a recommendation, contextual Juli assistance may link to
  `/decisions?highlight=<workflow_id>`. Assistance remains inside Analytics; it
  does not create a standalone assistance destination.

## Color coding for trends

- Growth/positive → `--success`. Loss/risk/negative → `--destructive`. Caution/
  threshold proximity → `--warning`. Never any other hue for a trend indicator.
- Every color-coded trend pairs with a direction glyph (▲/▼) or explicit sign —
  never color alone.

## Placement

- All KPI, metric, shop-health, comparison, forecast, and reporting charts belong
  to Analytics.
- Home contains no charts; its two launcher cards link to Decisions and Analytics.

## Accessibility

- Any chart that is tappable (sparkline tile, estimated bar segment) must be a
  real interactive element (`button` or `role="button"` with `tabindex="0"`), not
  a bare `<div onClick>` — keyboard users must be able to reach and activate it.
- Expandable chart tiles carry `aria-expanded`.
- Chart containers with meaningful data provide a text-equivalent summary (the
  label + delta badge already serves this — do not rely on the chart pixels
  alone to convey the value).
- Chart SVGs use `focusable="false"` unless the chart exposes a documented
  keyboard interaction.

## Anti-patterns

- Hardcoded chart hex instead of CSS variables.
- A chart that requires precise pixel-reading to understand — the accompanying
  label/delta must always carry the actual number.
- A flat zero series used to represent missing or unavailable data.
- A selector preview with tooltip, comparison series, or focus stops separate
  from its card.
