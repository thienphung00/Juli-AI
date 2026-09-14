# Module: theme

## Responsibility

Own Juli's framework-independent semantic design tokens and motion/accessibility
defaults for product apps.

## Public interface

- `@juli/theme/tokens.css` — colors, typography, spacing, radii, elevation,
  focus, touch-target, and reduced-motion tokens.
- `@juli/theme/run-surface-tokens.css` — the scoped token layer for every
  surface carrying `data-juli-surface="run"` (the Optimize Product run view
  and the In-Progress run ledger). ADR-102: the surface sits on the light
  Juli canvas, expressed as **four semantic layers — canvas, panel, raised,
  overlay — each carrying four facets: fill, border, shadow and blur**. The
  blur facets are `0px` today and are consumed anyway, so a liquid-glass
  pass is a token redefinition, not a consumer change.

## Invariants

- Product components consume semantic variables instead of hardcoded theme colors.
- The seller canvas is white; pink is an accent.
- Motion is disabled when `prefers-reduced-motion: reduce` is active.
- This package never imports an app.
- **A future re-theme of the run surface — including a liquid-glass pass —
  changes this file only** (`run-surface-tokens.css`). Consumers reference
  layer tokens; they never declare a literal colour, blur, shadow or
  border-colour. Adding translucency and blur is a change to
  `--juli-run-<layer>-fill` and `--juli-run-<layer>-blur`, nothing else.
  Enforced by `__tests__/run-surface-token-only-theming.test.ts`.
- `--juli-run-live-edge` is reserved for the live edge only (three sanctioned
  rules); `tokens.css` stays byte-identical to its pinned hash.

## Owners

- domain: web
- code: `packages/theme/`
