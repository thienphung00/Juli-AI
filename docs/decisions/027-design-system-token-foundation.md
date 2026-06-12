# ADR 027: Design System & Token Foundation (Phase 1.8)

## Status

Accepted

## Context

- Juli's web UI grew organically from `globals.css` tokens with no formalized design
  language. Phase 1.8 ties the three workflows into one operations-system spine, so the
  surfaces (Shop Health hero, ranked recommendation "Clarity Cards", approval gate,
  outcome views) must share a consistent, trustworthy visual language.
- A product design strategy ("Juli AI — Design Strategy & Token System") proposed a
  palette, typography, spacing, interaction states, elevation, and motion. Aligning it
  against the codebase surfaced four divergences that need a decision:
  1. **Theme mapping** — the strategy's light, calm canvas reads as the *affiliate*
     light theme, but the in-scope *seller* surface is currently dark (`#050505`).
  2. **Typography** — strategy proposed serif display + monospace data fonts; the app is
     Inter-only.
  3. **Semantic palette** — strategy hex drifted from implemented tokens
     (Growth `#16A34A` vs `#10b981`, Loss `#E5484D` vs `#ef4444`, New `#2563EB` vs cyan
     `#06b6d4`).
  4. **Elevation & motion** — the UI is mostly flat (borders only) with ad-hoc animation.
- Decision window: before P1.8 orchestration UI polish ships, so the new pipeline surfaces
  are built on the final tokens rather than retrofitted.

## Decision

We will adopt a **single design-token foundation** for the Juli web app, applied as the
Phase 1.8 polish slice (**P1.8-8**):

- **Theme swap.** **Seller = light** (calm `#FEF5F6`/white canvas, charcoal text);
  **Affiliate = dark**. This inverts the current mapping (`html.dark` semantics flip).
- **One typeface (Inter), ≤6-size type scale.** Hierarchy comes from **size + weight**,
  not font mixing. No serif/display or monospace fonts.
- **Semantic palette (with background tints):**
  - Brand Primary `#F86BA5` · Brand Background `#FEF5F6`
  - Growth `#16A34A` · Negative/Loss `#E5484D` · Warning `#F59E0B` · New/Info `#2563EB`
  - Each semantic color ships a low-opacity background tint for badges/cards.
  - 60 / 30 / 10 distribution: neutral structure → semantic growth/loss → pink accent.
- **Interaction states (every interactive surface):** Default (base, full opacity,
  standard border) · Hover (subtle color shift **or** shadow lift) · Active (darker fill,
  scale `0.98`) · Focus (3px visible ring + offset) · Disabled (muted fill, reduced
  contrast, `not-allowed`) · Loading (inline spinner + disabled).
- **Elevation: 3-step shadow scale** — `sm` (cards), `md` (modals/popovers), `lg` (toasts).
- **Motion (respecting `prefers-reduced-motion`):** card entry (fade + scale, staggered),
  metric counter on value change, approval → success toast, loading shimmer/skeleton,
  tab/route transition fade.

We will **not** introduce serif/monospace fonts, additional brand colors, decorative
gradients, or risk-badge bounce animation (deferred).

## Why this architecture (the "because")

- **Speed:** One token source (`globals.css` + `tailwind.config.ts`) means P1.8 pipeline
  surfaces compose from `var(--*)` + `@layer components` utilities instead of one-off hex.
- **Cost:** Single typeface = no extra font payload or fallback complexity; no new runtime deps.
- **Scalability:** Semantic tints + elevation scale let new surfaces (health hero, Clarity
  Card, outcome views) stay on-brand without per-component design.
- **Performance:** Inter-only and CSS-variable theming keep CLS/LCP within the `web/MODULE.md`
  2s budget; motion is opt-out under reduced-motion.
- **Reliability/Operability:** State + a11y contract (focus ring, contrast, 44×44 targets)
  is enforceable in review (`ui-ux-design` skill Stop hook) rather than rediscovered per PR.

## Options considered

- **Option A — Adopt strategy literally (serif + mono, light-only).** Pros: matches mockups
  1:1. Cons: breaks the dual seller/affiliate theme contract, adds font weight, diverges from
  Inter-only system. → Rejected.
- **Option B — Keep current tokens, ignore strategy.** Pros: zero churn. Cons: leaves the
  divergences unresolved; P1.8 surfaces ship inconsistent. → Rejected.
- **Option C (chosen) — Reconcile: swap themes, keep one font, adopt strategy palette +
  states + elevation + motion.** Pros: preserves dual-theme architecture, minimal font cost,
  consistent semantics. Cons: theme swap is a visible change requiring screenshot/UX re-baseline.

## Consequences

- **Positive:** Single coherent language for all P1.8 surfaces; enforceable state/a11y
  contract; semantic colors become meaningful (intentional, not decorative).
- **Negative:** Seller↔affiliate theme inversion invalidates current seller-dark screenshots;
  `web/MODULE.md` dual-theme invariant text and any hardcoded theme assumptions must be
  re-verified. Implemented semantic hex changes (`--success`, `--destructive`, `--info`).
- **Follow-ups:**
  - Implement under **P1.8-8** (tokens, theme swap, state utilities, elevation, motion).
  - Update `web/MODULE.md` dual-theme invariant when the swap ships (code is authority).
  - Re-baseline `screenshots/` after the swap.

## Rollout / Migration plan

1. Update `globals.css` tokens: flip `html.dark` / `html:not(.dark)` semantics so
   Seller=light / Affiliate=dark; set semantic hex (`#16A34A` / `#E5484D` / `#2563EB`) +
   background tints; add elevation scale and state utilities.
2. Land the ≤6-size type scale and state/elevation/motion utilities in `@layer components`.
3. Migrate surfaces to tokens (no stray theme hex); verify both modes.
4. Re-baseline screenshots and update `web/MODULE.md` invariant.
