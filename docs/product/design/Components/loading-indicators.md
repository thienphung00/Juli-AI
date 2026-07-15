# Components / loading-indicators.md

> Code: `.spinner`, `.skeleton` in `apps/dashboard/src/app/globals.css`.

## Spinner

- 32px, single rotation loop at **0.7s** per cycle, `--pink-main` stroke on
  transparent track.
- Used inline inside buttons (smaller inline variant, still 0.7s loop) and for
  short async actions (form submit, approve action).
- Respects `prefers-reduced-motion` — reduces to a static pulsing opacity instead
  of a spin when motion is reduced.

## Skeleton screens

- Used for initial page/section load (`SellerHomeSkeleton`, `DecisionsSkeleton`)
  — never a blank screen while data loads.
- Shape-matches the content it's replacing (metric tile skeleton is tile-shaped,
  card skeleton is card-shaped) so layout doesn't jump when real content arrives.

## Shimmer animation

- Subtle left-to-right gradient sweep over the skeleton shape, `~1.5s` loop,
  disabled under `prefers-reduced-motion` (falls back to a static muted fill).

## Rules

- Skeleton screens are the default for **initial** load; inline spinners are for
  **action-triggered** load (button press, form submit) — don't swap these two
  patterns for each other.
- Loading never blocks the rest of the screen unless the action truly requires
  it (e.g. full-page auth check) — prefer scoped loading over full-page overlays.

## Anti-patterns

- A full-screen spinner for a small in-card action.
- Skeleton shapes that don't match the eventual content's dimensions, causing a
  layout jump when data arrives.
