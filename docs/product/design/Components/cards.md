# Components / cards.md

> Tokens: `colors_and_type.css`. Historical implementation evidence:
> `source_examples/`. Current behavior follows the root design authorities,
> `Screens/`, and `Flows/`.

## Standard card

- `.card` primitive — bordered panel, `--radius: 16px`, `--shadow-sm`.
- Header (title + optional meta), body, optional footer action row.
- Base unit for shop info, empty states, and generic content grouping.

## Interactive card

- Standard card + hover lift (`--shadow-sm` → subtle increase) + `cursor: pointer`.
- Used for the two Home launcher cards and list rows that navigate or expand.
- Must have a visible focus-visible ring — interactive cards are keyboard-reachable.

## Home launcher cards

Home contains exactly two prominent interactive cards:

1. **Quyết định** — opens `/decisions` on the `Đề xuất` sub-tab and summarizes
   whether recommendations need review.
2. **Phân tích** — opens `/analytics` and summarizes the reporting destination
   without rendering KPI values on Home.

The cards are navigation launchers, not miniature dashboards. They may include a
short outcome-oriented description and directional icon, but no charts, metric
grids, shop-health bars, workflow actions, or approval controls.

## RecommendationCard (Decision)

The primary card for a Decision on the Quyết định tab. Structure, top to bottom:

1. **Header row** — Vietnamese workflow name (Đề xuất title), confidence badge
   (`high`/`medium`/`low` via `Components/badges.md`).
2. **Impact line** — `Tác động dự kiến` and `Độ tin cậy`, prominent and formatted.
3. **Reasoning trigger** — an explicit **Mở rộng** control with `aria-expanded`;
   it reveals `Lý do đề xuất`, supporting evidence, and relevant risks inline.
4. **Action row** — **Phê duyệt** (primary), **Từ chối** (secondary/ghost), and
   **Mở rộng** (tertiary). All three are visible on every recommendation card.

Phê duyệt opens the workflow with prefilled but editable inputs; it does not imply
silent execution. Từ chối removes the recommendation after any required
confirmation. Mở rộng never authorizes an action.

After approval, the item appears under `Đang thực hiện` with the existing
`needs_input`, `executing`, and `completed` lifecycle states.

## Execution workflow card

- Appears only in Decisions → `Đang thực hiện`.
- Shows workflow title, current lifecycle status, estimated impact, current
  execution step, and the next valid CTA.
- One card can represent a complete workflow journey: approved/prefilled input →
  execution progress → outcome. Step transitions preserve entered values and
  provide recovery when execution fails.

## Analytics metric cards

- KPI, chart, health, date-range, comparison, and forecast cards belong to
  `/analytics`, never Home.
- Delta badges use semantic tokens and pair color with a direction glyph or sign.

### MainKpiHero

- Displays exactly one selected Main KPI with category icon, canonical name,
  description, formatted value/delta, one-line signal, source, freshness, global
  range, hero-only period comparison, and its authoritative chart.
- Uses `--radius-lg` for the containing hero surface; nested summary and chart
  regions are layout regions, not equal-weight cards.
- Wide layouts place summary and controls left and chart right. Narrow layouts
  stack them in one column.
- Selection is reflected by `/analytics/[metricKey]`; the default is
  `net-revenue` at `30 ngày`.

### MainKpiSelectorCard

- The five non-selected Main KPIs form a responsive grid.
- An available card is a single real `button`; its category icon, name,
  one-line description, and low-contrast preview chart belong to that control.
- Activating it swaps it with the hero and preserves the global range.
- Foreground content sits on an opaque or sufficiently strong semantic surface
  so preview lines never reduce text below WCAG AA contrast.
- Preview charts are supporting texture and `aria-hidden`; the card's labels
  provide the text equivalent.

### Unavailable Main KPI card

- SPS, ROAS, and CSAT remain visible with `Chưa khả dụng`.
- The container is not selectable and never updates the route.
- It uses a neutral empty-chart pattern instead of values, deltas, or fake flat
  series.
- A separate 44×44px labelled info button opens the reusable unavailable
  popover from `Components/popovers.md`.
- Unavailable styling is not conveyed by opacity or color alone.

## Rules

- Card radius is always `--radius` (16px) — never a different radius per card type.
- One accent color moment per card maximum (the confidence badge, or the delta
  badge, not both fighting for attention).
- Cards never nest a card of the same visual weight inside themselves — a
  `ClarityCard`'s expanded reasoning is a lighter-weight panel, not a second card.

## Anti-patterns

- A colored left-border accent as the only differentiator between card types.
- Stacking more than one badge type in the header row without clear hierarchy.
- A legacy two-action recommendation card or any card without the
  Phê duyệt/Từ chối/Mở rộng trio.
- A KPI dashboard, recommendation preview, or execution queue on Home.
- An unavailable Main KPI implemented as a disabled selection button with an
  unreachable nested info control.
- Card text placed directly over a preview without a readability-safe layer.
