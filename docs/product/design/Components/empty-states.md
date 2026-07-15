# Components / empty-states.md

> Historical reference: `CollectingDataEmpty.tsx`. Current copy follows the
> root context authority.

## Principle

Every empty state explains **why it's empty** and **what happens next** — never a
bare "Không có dữ liệu" with nothing else. This is a trust behavior, not just a
content nicety.

## Variants

### No data yet (collecting)
- Used when Juli hasn't finished the minimum evaluation window for a signal.
- Copy pattern: "Juli đang thu thập dữ liệu shop của bạn. Đề xuất đầu tiên sẽ xuất
  hiện trong vòng [khung thời gian]." — always includes a concrete-as-possible
  timeframe, never an open-ended "soon."

### No results (filtered view)
- Used when a filter/sub-tab genuinely has nothing to show right now (e.g. In
  Progress with zero active decisions).
- Copy explains the filter is working correctly, not broken: "Chưa có quyết định
  nào đang thực hiện."

### Error
- Used when a fetch/load failed. States the problem, offers a retry action.
- Never silently retries in a loop without telling the seller.

### Permission denied
- Used for the affiliate out-of-scope shell and any gated surface.
- States what the surface is for and, where applicable, what unlocks it.

### Main KPI unavailable

- Used when a Main KPI's required source is not connected, verified, or legally
  available.
- Keep the KPI card visible so category coverage remains understandable.
- Show `Chưa khả dụng`, a neutral empty-chart pattern, and a labelled info
  control. The explanation lives in the reusable popover contract in
  `Components/popovers.md`.
- Copy names both why and what activates it:
  - SPS: official TikTok Shop Account health contract verification + connection.
  - ROAS: TikTok Promotion API ingestion connection.
  - CSAT: a legal buyer review/chat source.
- This is not a zero, error, loading, or disabled-product state. Do not render a
  value, delta, trend direction, gauge fill, or fake series.

## Layout

- Illustration/icon area (simple, on-brand — never a generic AI robot or
  hand-drawn scene per `soul.md` anti-patterns) + one-line explanation + optional
  next-action button.
- Fits within the card/section it replaces — never forces extra scroll height
  compared to the populated state.

## Anti-patterns

- A blank screen or blank card with no explanation.
- Empty-state copy that just restates the section title ("Không có báo cáo" under
  a "Báo cáo" heading) without saying why or what's next.
- "0", "0%", or a flat line used as the value for a missing KPI source.
