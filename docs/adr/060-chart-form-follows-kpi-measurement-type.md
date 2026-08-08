# ADR-060: Chart form follows KPI measurement type (apps/demo Analytics)

**Status:** Proposed
**Date:** 2026-08-08
**Deciders:** grill-with-docs (Architect)

**Builds on:** [ADR-054](054-brand-pink-role-separation.md) (`--chart-neutral` for
non-directional series), [ADR-049](049-demo-analytics-main-kpi-override.md) (the five Demo
Main KPIs)

## Context

Every Demo Analytics KPI renders as effectively the same line, so a seller cannot tell
from a chart's shape what kind of quantity they are looking at. The cause is not a
missing taxonomy — one exists — but a taxonomy that never took effect:

- `ChartKind` declares four kinds; only two render. `health-bar` is declared by no KPI
  and has no render branch. `gauge` is declared by Cancellation rate but the envelope
  mapper hardcodes its value to `undefined`, so **Cancellation rate renders no chart at
  all on live data**.
- The two surviving kinds differ only by an area fill, which is applied without regard
  to whether the measure accumulates. CTOR is a rate rendered with an area fill, which
  reads as a running total of something that cannot be totalled.
- `chartKind` is hand-assigned per KPI, so GMV (a sum) and AOV (an average) were both
  tagged `forecast-line` and render identically despite opposite arithmetic.

A second defect compounds it. Semantic tone is derived from the sign of the delta alone
(`pct > 0 ? "positive" : ...`), and no KPI declares a goal direction. Cancellation rate
rising is therefore classed `positive`, painted with the success colour, and shown with
an upward arrow — more cancelled orders presented as good news. The same inversion will
hit any lower-is-better KPI added later.

The surface is mobile-web, so the conventional hover layer does not exist. At 30 points
across a phone-width plot each point occupies roughly 17px, below a reliable touch target.

## Decision

**1. A KPI's chart form is derived from a declared measurement type, never chosen by hand
and never derived from its business category.**

| Measurement type | Form | Example |
|---|---|---|
| `flow` (sum-able quantity) | line with gradient fill | GMV |
| `average` | line, **no fill** | AOV |
| `rate` | line, **no fill**, percentage axis | CTOR |
| `count` (discrete per period) | bars | LIVE hours |
| `bounded-ratio` | threshold band with target line | Cancellation rate |

Business category (`Doanh thu`, `LIVE Shopping`) groups KPIs for navigation and never
selects a mark. Two revenue KPIs may legitimately need different marks; that is precisely
how GMV and AOV came to be indistinguishable.

**2. The `ChartKind` union is retired.** `health-bar` is removed as a chart kind. `gauge`
is replaced by `bounded-ratio`, and the envelope mapper must populate its value — without
that, no form renders for Cancellation rate. The `HealthBar` component in `packages/ui`
is **not** deleted: it is a meter primitive (segmented fill, target tick, severity tones),
distinct from a chart form, and is retained for current-state use.

**3. Cancellation rate renders as a banded trend, not a meter.** A meter answers "what is
it now"; the seller's question is "is this getting worse". 4% steady and 4% doubled this
week require different responses and a meter cannot distinguish them. The band keeps the
time axis while showing tolerance.

**4. KPIs declare a goal direction, and semantic tone is a function of delta sign *and*
goal direction** — never the sign alone.

**5. Trend marks wear a stable hue tied to the metric.** Identity must not flicker between
periods or ranges. Direction is carried by the delta chip, which pairs tone with an arrow
and a number, so status never travels by colour alone. The status palette is reserved for
genuine goal breaches, principally the `bounded-ratio` tolerance band, so that a breach has
colour left to shout with. `--chart-neutral` from ADR-054 is the non-directional series hue.

**6. Touch inspection is a scrub, and its readout replaces the hero value** above the chart
rather than floating over the plot. At phone width a tooltip occludes the data it explains.
Below roughly ten points the per-point dots suffice and no scrub is required.

## Consequences

- Every KPI definition gains two required fields (`measurementType`, `goalDirection`).
  Adding a KPI becomes slightly more ceremonious; that ceremony is what prevents mis-tagging.
- Chart primitives grow from two to four forms (filled line, plain line, bars, banded line).
- The envelope mapper must supply a value for `bounded-ratio` and a goal direction per KPI;
  until it does, Cancellation rate stays blank as it is today.
- Existing tests asserting a single chart kind per KPI, or tone derived from delta sign,
  will need updating.
- `envelope-mapper.ts` already carries a second, independent inversion for cancellation
  rate (`INVERTED_IMPACT_METRICS` / `impactSentiment`, landed with ADR-055's plan-review
  impact block). The goal-direction resolver must **absorb** it, not sit beside it —
  otherwise two rules decide the same question and can drift apart.
- Charts stop being interchangeable, so a future KPI cannot be added without deciding what
  it measures — which is the point.

## Options considered

1. **Keep hand-assigned `chartKind`, fix the two dead branches.** Cheapest, but leaves the
   mis-tagging that made GMV and AOV identical, and leaves tone inverted.
2. **Derive form from business category.** Rejected: two revenue KPIs can need different
   marks, so category cannot carry the information.
3. **Derive form from measurement type (chosen).** Deterministic, prevents mis-tagging, and
   makes the AOV/GMV distinction structural rather than a matter of who wrote the definition.
