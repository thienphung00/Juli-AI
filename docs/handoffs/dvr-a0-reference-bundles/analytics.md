# Analytics — KPI and chart chrome (DVR-A0)

> **IA law:** [ADR-023](../../adr/023-four-destination-analytics-ownership.md) — Analytics owns **all** metrics, KPIs, charts, comparisons, forecasts. Demo retains **six Main KPI** keys, hero/selector layout, and existing data contracts (DVR-A3). Polish only — no new metrics.

## Target implementation (DVR-A3)

- Six Main KPI categories with one `(main)` representative each: SPS, Net Revenue, ROAS, Inventory Turnover, Fulfillment Accuracy Rate, CSAT.
- Hero metric surface + selector/tabs + chart chrome on detail routes.
- Improved spacing, hierarchy, empty/loading states — mock and live (#534) paths.
- Primary paths: `apps/demo/src/app/analytics/`, `analytics-kpi-card.tsx`, `analytics-charts.tsx`.

## Layout patterns to adopt (adapted, not cloned)

### KPI card grid + hero

| Source | Mobbin URL | What to borrow | What to reject |
|--------|------------|----------------|----------------|
| Google Analytics — Home overview | [GA4 Home](https://mobbin.com/screens/f4f2cebe-5496-4959-9fbb-fe37fe2a5dd6) | Top row: headline metric cluster + secondary realtime card proportions; “View reports →” link pattern → Juli deep-link to metric detail | GA branding; English metric names; extra destinations in sidebar |
| Navattic — Analytics KPI grid | [Navattic Analytics](https://mobbin.com/screens/a5be5a57-9c24-49a2-9ce5-ccd5edc17a1b) | 3×2 metric card grid with mini area sparkline, period comparison line (“vs last period”), filter bar above grid | Upsell hero banner; English labels; Navattic blue as primary |
| Whop — Stats dashboard | [Whop Stats](https://mobbin.com/screens/0bb8b25f-0c3d-47c3-b20a-1447e7dbab9e) | Date-range + comparison controls in a single toolbar row; delta badges (`+` green) mapped to `var(--success)` / `var(--destructive)` | Revenue-specific metrics; dark sidebar duplication |
| Fresha — Occupancy KPI card | [Fresha Analytics](https://mobbin.com/screens/39b5ad91-5928-4e9b-b97f-2de8c9edb879) | Single KPI module: large `tabular-nums` value, comparison badge, line chart, footer sub-metrics row | Purple Fresha accent; salon-specific copy |

### Chart detail chrome

| Source | Mobbin URL | What to borrow | What to reject |
|--------|------------|----------------|----------------|
| Mixpanel — Report editor | [Mixpanel report](https://mobbin.com/screens/e312babc-b969-4cda-96cf-7de2b5b1d0e1) | Chart toolbar: date range, granularity, compare toggle; chart + table split below | Query builder sidebar; Mixpanel purple; multi-metric query UI beyond Juli scope |

## Open Design reference

| Artifact | Path | What to borrow |
|----------|------|----------------|
| ReportMetricChart | `DESIGN.md` §6 (Open Design `ds-juli-is-an-app-design-system`) | Expandable metric tile with sparkline + Juli suggestion accordion (`var(--info)`) |
| RealEstimatedBar | Same | Two-segment impact bar — real vs estimated — never collapsed single number |
| Typography | `DESIGN.md` §3 | Metric value 1.125–1.5rem bold `tabular-nums`; captions 0.75rem muted |
| Read vs act | `docs/product/design/ux_principles.md` (via design package) | Analytics is **read-only exploration** — primary CTAs stay in Decisions |

## ADR-015 token mapping

| Element | Token / utility | Notes |
|---------|-----------------|-------|
| KPI value | `font-bold tabular-nums`, foreground | Canonical KPI names unchanged (SPS, ROAS, …) |
| Positive delta | `text-success`, success tint background | Not Mobbin green hex literally — use `var(--success)` |
| Negative delta | `text-destructive` | Pair with icon or label — never color-only |
| Unavailable KPI | `analytics.unavailable` dictionary copy | Muted surface; not “0” |
| Chart line primary | `var(--primary)` or neutral foreground | Avoid multi-hue Mobbin rainbow; max 2–3 series |
| Chart grid | `border-border` at low opacity | Lighter than Mobbin dense grids |
| Juli evidence accordion | `var(--info)` border/background tint | Only for Juli contextual suggestions |
| Card chrome | `--shadow-sm`, `--radius` | Consistent with Home destination cards |
| Loading | `.skeleton` shimmer | Honor `prefers-reduced-motion` |
| Empty state | `phrases.empty.*` keys | Problem + next step per design-context.md |

## Copy keys (authority: dictionary.md + design-context.md)

| UI element | Dictionary key | Notes |
|------------|----------------|-------|
| Destination nav | `nav.analytics` | Phân tích |
| Main KPI role | `analytics.main_kpi` | Set label, not replacement for SPS/ROAS names |
| Unavailable state | `analytics.unavailable` | Chưa khả dụng |
| Data provenance | `analytics.data_source` | When showing source attribution |

Format currency via formatter (₫); dates via ICT formatter — never raw ISO in UI.

## Data contract guardrails (DVR-A3 AC)

- Do not rename or remap GMV → Net Revenue silently.
- Preserve six Main KPI keys in `apps/demo/src/lib/analytics/main-kpis.ts`.
- Focus order and aria labels must survive visual polish.

## Anti-patterns

- New KPIs or Analytics IA changes.
- Dense “wall of charts” on landing — keep hero + selector clarity.
- Mobbin English metric titles as seller copy.
- Purple AI gradient fills on chart areas.

## Downstream notes (DVR-A3)

- Touch `analytics-dashboard.test.tsx` when chrome changes affect roles/labels.
- Live envelope path (#534) and mock fixtures must receive the same visual treatment.
