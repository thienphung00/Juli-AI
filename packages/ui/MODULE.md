# Module: ui

## Responsibility

Own accessible, app-agnostic React primitives shared across Juli product
deployables.

## Public interface

- `DestinationCard` — complete keyboard-operable launcher link.
- `PrimaryNavigation` — ordered four-destination navigation with text and
  non-color active state.
- `Button` — primary/secondary/ghost actions with size/loading variants, a
  44×44px minimum target, visible focus-visible ring, and reduced-motion states.
- `Badge` / `ConfidenceBadge` — inline status labels (Decision + semantic
  variants); color is always paired with visible text, never color-only.
- `StatusChip` / `FilterChip` / `InputChip` — inline status, tab filters, and
  closeable input tags.
- `ProgressBar` / `RealEstimatedProgressBar` — standard and real/estimated fill
  indicators.
- `HealthBar` — five-segment shop health visualization with threshold ticks.
- `RecommendationCard` — presentational, app-state-agnostic Decision
  recommendation card (Phê duyệt/Từ chối/Mở rộng trio, forwardRef'd container
  for scroll/focus targeting).
- `Card` / `InteractiveCard` — Standard and interactive surface cards with
  header/body/footer regions.
- `Dialog` / `ConfirmDialog` — modal overlays with focus trap, Escape dismissal,
  and backdrop click-to-close.
- `Popover` / `UnavailableKpiPopover` — anchored overlays with keyboard
  dismissal and Vietnamese copy.
- `Form` / `TextField` / `PasswordField` / `OtpField` — labelled, keyboard-
  navigable form compositions built on shared `Button` submit actions.
- `Table` — keyboard-navigable data table with sortable headers, empty state,
  and responsive card collapse.
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
