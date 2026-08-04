# Components / home-activity-tracker.md

> Introduced by [ADR-053](../../adr/053-demo-home-activity-summary.md). Screen
> spec: `Screens/home.md`. Layout reference reviewed for composition only (not
> color/brand): a circular-ring progress screen. This component deliberately
> does **not** use a ring — see Rationale below.

## Anatomy

One full-width section, three stat tiles in a row (stacks to one column below
`35rem` alongside the rest of Home's mobile layout):

| Tile | Icon (`lucide-react`, see `Assets/README.md`) | Count | Label | Badge/motion reuse |
|---|---|---|---|---|
| Done | `CheckCircle2` | Completed executions | **Hoàn tất** | `Components/badges.md` Success |
| Running | `.badge-live` pulsing dot | Executing or `needs_input` | **Đang thực hiện** | `Components/badges.md` Live |
| Needs attention | `AlertCircle` / `Bell` | Open recommendations | **Đề xuất cần xem xét** | brand accent (pink), not a semantic badge — it's the one tile meant to draw the eye toward Decisions |

Each tile is one keyboard-operable link/button (44×44px minimum target, visible
focus-visible ring) — not three cells in a table and not individually
clickable sub-elements inside one non-interactive card.

## Behavior

- Tapping/activating a tile navigates to `/decisions`: "Needs attention" →
  Recommendations tab; "Done"/"Running" → In Progress tab. No in-place
  expansion, no list, no Approve/Reject — Home only summarizes
  ([ADR-053](../../adr/053-demo-home-activity-summary.md)).
- Counts share the same data Decisions already computes (open recommendations
  count, execution lifecycle counts) — this is a second view of existing
  state, not a second source of truth.
- Copy budget: tile label ≤ 3 words (`design.md#copy-density`).

## States

- **Has activity** — three tiles with real counts.
- **First run / no activity yet** — one calm line replacing all three tiles
  (`Components/empty-states.md` "No data yet" pattern), e.g. "Juli sẽ hiển thị
  tiến độ ở đây khi có đề xuất hoặc việc đang thực hiện." Never render three
  zeros.
- **Loading** — skeleton matching the three-tile shape
  (`Components/loading-indicators.md`), independent of the launcher cards'
  loading state below it.
- **Error** — the tracker fails independently; the two launcher cards below it
  remain fully usable. Show a small inline retry, not a page-level error.

## Rationale — stat tiles, not a ring

The layout reference used for inspiration renders one ratio (a single value
against one goal, e.g. calories consumed/target). Home's three states are
independent counts with no shared denominator — a ring would force an invented
"goal" number that doesn't exist in the product today (confirmed with the
product owner during the design pass; recorded here so a future reader doesn't
re-propose a ring without re-deciding this). Three stat tiles state each count
plainly, matching `soul.md`'s Intentional pillar (no element earns its place
by looking more elaborate than the data behind it).

## Anti-patterns

- A single hero ring/percentage implying one "% complete" across done/running/
  needs-attention.
- A fourth tile, or any tile expanding into a list/card in place — see
  [ADR-053](../../adr/053-demo-home-activity-summary.md)'s cap at three
  summary-only counts.
- Using `--info` blue on the "Needs attention" tile — that hue is reserved for
  Juli-suggestion labels (`Components/badges.md`), not a status color here.
