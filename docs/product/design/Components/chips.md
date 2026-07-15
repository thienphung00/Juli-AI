# Components / chips.md

> Historical reference: `DecisionsSubTabs.tsx`. Current placement follows the
> root IA and matching screen/flow specifications.

## Status chips (non-interactive)

- Same visual family as `Components/badges.md` but sized for inline placement
  next to a title rather than in a dedicated badge slot (e.g. a small
  "Đang chờ" status next to a list row title).

## Filter chips (toggleable)

- Used for Analytics filters and exactly two Decisions sub-tabs:
  **Đề xuất** and **Đang thực hiện**.
- Pill shape, `--radius` full; active state = filled `--pink-main` background +
  white text; inactive = outline only.
- Horizontal scroll on mobile when chips overflow the viewport — never wrap to a
  second line, which would push content down unpredictably.
- `role="tablist"` / `role="tab"` / `aria-selected` are required.

## Input chips (closeable)

- Used inside filter/input surfaces where a seller has selected multiple discrete
  values (e.g. multiple SKUs in a workflow's Decision detail Inputs step).
- Closeable via a small ✕ target that still meets the 44px hit-area minimum
  (visual chip may be smaller; padded tap area compensates).

## Rules

- Filter chips always show the currently active selection with a persistent
  visual state — never rely on chip order alone to indicate "selected."
- Chip text is short (1–3 words); anything longer belongs in a full label/badge
  layout instead.

## Anti-patterns

- Chips used as the primary submit action — chips filter/tag, they never replace
  a `Components/buttons.md` Primary button for committing a decision.
- A third Decisions sub-tab for workflow templates or thresholds; those controls
  belong to Cài đặt.
