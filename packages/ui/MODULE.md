# Module: ui

## Responsibility

Own accessible, app-agnostic React primitives shared across Juli product
deployables.

## Public interface

- `DestinationCard` — complete keyboard-operable launcher link.
- `PrimaryNavigation` — ordered four-destination navigation with text and
  non-color active state.
- `Button` — primary/secondary/ghost action button with a 44×44px minimum
  target, visible focus-visible ring, and disabled/reduced-motion states.
- `Badge` — inline status/label chip; color is always paired with visible
  text, never color-only.
- `RecommendationCard` — presentational, app-state-agnostic Decision
  recommendation card (Phê duyệt/Từ chối/Mở rộng trio, forwardRef'd container
  for scroll/focus targeting).
- `@juli/ui/styles.css` — component styles backed by `@juli/theme` tokens.

## Invariants

- Interactive controls are semantic links or buttons with at least 44×44px targets.
- Focus-visible state is never removed.
- Product apps provide Vietnamese labels and route ownership.
- Components use semantic theme variables and respect reduced motion.
- This package never imports an app.

## Owners

- domain: web
- code: `packages/ui/`
