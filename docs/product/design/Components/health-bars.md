# Components / health-bars.md

> Reference: `HealthMetricBar.tsx`, `ShopHealthCard.tsx`, `ShopHealthHero.tsx`.

## Shop health visualization

- 5-segment bar, pink ramp (light → `--pink-main` → `--pink-dark` across
  segments as the score increases) representing SPS/AHR-style health scores.
- Threshold ticks mark the boundaries sellers care about (e.g. "at risk" /
  "healthy" / "excellent") — ticks are a consistent visual language shared with
  `Components/progress-bars.md` step indicators.

## Multi-segment color coding

- Segments below the "at risk" threshold shift to `--warning` or `--destructive`
  tinting rather than staying on the pink ramp — health bars are the one place a
  semantic-color override of the brand ramp is correct, because health status is
  more urgent information than brand consistency.
- Always pair the color shift with a text label (e.g. "Cần chú ý") — never rely on
  the ramp color shift alone.

## Layout

- `ShopHealthCard` — Analytics container with a title, the bar(s) for SPS and AHR,
  and a one-line status summary per indicator.
- `ShopHealthHero` — larger Analytics drill-down variant.

## Rules

- Estimated/mock health data (Phase 2 pre-live-source) still renders through this
  same component — never a visually different "fake data" treatment; if data
  provenance needs disclosure, do it via copy, not a different chart style.
- Health bars are read-only and live in Analytics. Home is only the two-card
  launcher and must not render health status.

## Anti-patterns

- Using the brand pink ramp with no threshold ticks — an unlabeled gradient bar
  gives no actionable information.
- Adding approval controls directly on a health bar; any related recommendation
  is reviewed in Decisions.
