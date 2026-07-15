# Components / tables.md

> Tokens: `colors_and_type.css`. Used for list-shaped data in Analytics and
> execution details under Decisions → Đang thực hiện.

## Structure

- Row height ≥ 44px to preserve tap targets on mobile-web.
- `--border` hairline dividers between rows — no zebra striping (would compete
  with status badges for attention).
- First column carries the primary identifier (order ID, SKU, workflow name);
  status/badge lives in a dedicated column, never inline in free text.

## Sorting

- Sortable columns show a direction glyph on the active sort; default sort is
  always the one most useful to the current question (e.g. SLA-risk orders sort
  by time-to-deadline ascending by default, not alphabetically).

## Responsive collapse to cards

- Below the tablet breakpoint, tables collapse into a stacked card list — each row
  becomes a `Components/cards.md` Standard card with the same field labels
  retained (never drop labels just because the layout changed).
- Column headers become inline field labels inside each collapsed card row.

## Rules

- Never truncate a monetary value or a status label to save width — collapse to
  cards before truncating meaningful content.
- Empty table → `Components/empty-states.md`, never a bare "no rows" row.

## Anti-patterns

- Dense data tables on mobile-web that require horizontal scroll — collapse to
  cards instead.
- Status conveyed only by row background color.
