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

Home contains exactly two prominent interactive cards, rendered below the
activity summary ([ADR-053](../../adr/053-demo-home-activity-summary.md),
`Components/home-activity-tracker.md`):

1. **Quyết định** — opens `/decisions` on the `Đề xuất` sub-tab and summarizes
   whether recommendations need review.
2. **Phân tích** — opens `/analytics` and summarizes the reporting destination
   without rendering KPI values on Home.

The cards are navigation launchers, not miniature dashboards. They may include a
short outcome-oriented description and directional icon, but no charts, metric
grids, shop-health bars, workflow actions, or approval controls.

## RecommendationCard (Decision)

The primary card for a Decision on the Quyết định tab. Structure, top to bottom:

1. **Header row** — Vietnamese workflow name (Đề xuất title) only. **No
   confidence badge** — [PRD #600](https://github.com/thienphung00/Juli-AI/issues/600)
   removes confidence/`Độ tin cậy` from every seller card and approve surface;
   the old `high`/`medium`/`low` confidence badge below is retired.
2. **Impact line** — `Tác động dự kiến` only (no confidence pairing).
3. **Reasoning trigger** — an explicit **Mở rộng** control with `aria-expanded`;
   it reveals `Lý do đề xuất`, supporting evidence, and relevant risks inline.
   No confidence score anywhere in this card, collapsed or expanded — verified
   in code: nothing under `apps/demo/src`/`packages/ui/src`/`packages/contracts/src`
   renders confidence; the fixture `confidenceLabel`/`confidenceLevel` fields
   exist only as negative test oracles.
4. **Action row** — **Phê duyệt** (primary), **Từ chối** (secondary/ghost), and
   **Mở rộng** (tertiary). All three are visible on every recommendation card.

Phê duyệt opens the workflow with prefilled but editable inputs; prefilled
fields carry the suggestion glow + **Gợi ý bởi Juli** label
(`Components/forms.md` Suggestion glow, `Components/badges.md` Info variant) —
never silent prefill, never a confidence score. Từ chối removes the
recommendation after any required confirmation. Mở rộng never authorizes an
action.

After approval, the item appears under `Đang thực hiện` as a progress card (see
Execution progress card below) with the existing `needs_input`, `executing`,
and `completed` lifecycle states, and a **Juli-handles-all** confirm message —
not a you-vs-Juli split checklist.

## Execution progress card (Đang thực hiện)

Replaces a raw status table with one ChatGPT-style card per execution
([PRD #600](https://github.com/thienphung00/Juli-AI/issues/600)):

1. **Mode strip** — a single top-of-card strip that reads as either
   **Xác nhận** (confirm — approved, execution not yet started/needs input) or
   **Đang chạy** (running — actively executing). Exactly one mode is active per
   card; it is the first thing the eye reads, not a column in a table.
2. **Header** — workflow title + lifecycle badge (`Components/badges.md`
   Success/Warning/Live variant per `needs_input`/`executing`/`completed`).
3. **Narrative step line** — the current step in one sentence
   (`Bước {n}: {title}`), not a stepper table; expected duration
   **5–10 phút** shown once execution starts.
4. **Next action** — the single next valid thing the seller can do or expect
   (recovery text if the step needs input), plus **cancel/rollback** — always
   visible, never hidden behind a menu.
5. **Policy line** — **Đã kiểm tra chính sách TikTok Shop** badge/line, present
   on every card once approved.

One card represents a complete workflow journey: approved/prefilled input →
execution progress → outcome. Step transitions preserve entered values and
provide recovery when execution fails. Cards are grouped/sorted with running
executions first, so an active dry-run is never buried below completed ones.

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
- One accent color moment per card maximum (e.g. the delta badge) — never
  multiple badges competing for attention.
- Cards never nest a card of the same visual weight inside themselves — a
  `ClarityCard`'s expanded reasoning is a lighter-weight panel, not a second card.

## Anti-patterns

- A colored left-border accent as the only differentiator between card types.
- Stacking more than one badge type in the header row without clear hierarchy.
- A legacy two-action recommendation card or any card without the
  Phê duyệt/Từ chối/Mở rộng trio.
- A confidence score, `Độ tin cậy` label, or confidence badge anywhere on a
  seller card or approve surface — retired by PRD #600.
- `Đang thực hiện` rendered as a raw data table/columns instead of the
  execution progress card + mode strip above.
- A you-vs-Juli split task checklist after approval instead of the
  Juli-handles-all confirm message.
- A KPI dashboard, per-item execution/recommendation list, or approval action
  on Home — the ADR-053 activity summary is counts only
  (`Components/home-activity-tracker.md`).
- An unavailable Main KPI implemented as a disabled selection button with an
  unreachable nested info control.
- Card text placed directly over a preview without a readability-safe layer.
