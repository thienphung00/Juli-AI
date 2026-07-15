# Module: theme

## Responsibility

Own Juli's framework-independent semantic design tokens and motion/accessibility
defaults for product apps.

## Public interface

- `@juli/theme/tokens.css` — colors, typography, spacing, radii, elevation,
  focus, touch-target, and reduced-motion tokens.

## Invariants

- Product components consume semantic variables instead of hardcoded theme colors.
- The seller canvas is white; pink is an accent.
- Motion is disabled when `prefers-reduced-motion: reduce` is active.
- This package never imports an app.

## Owners

- domain: web
- code: `packages/theme/`
