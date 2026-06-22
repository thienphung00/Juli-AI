# ADR 015: Design system and token foundation

## Status
Accepted

## Context

The web UI required a consistent visual language for Shop Health hero, decision cards,
approval gate, and outcome views before Phase 2 MVP live data surfaces ship.

## Decision

Single design-token foundation for the Juli web app:

- **Theme swap.** Seller = light (calm `#FEF5F6`/white canvas); Affiliate = dark.
- **One typeface (Inter), ≤6-size type scale.** Hierarchy via size + weight.
- **Semantic palette:**
  - Brand Primary `#F86BA5` · Brand Background `#FEF5F6`
  - Growth `#16A34A` · Loss `#E5484D` · Warning `#F59E0B` · Info `#2563EB`
  - Each semantic color ships a low-opacity background tint.
- **Interaction states:** Default, Hover, Active, Focus (3px ring), Disabled, Loading.
- **Elevation:** 3-step shadow scale — sm (cards), md (modals), lg (toasts).
- **Motion:** Card entry, metric counter, approval→toast, loading shimmer, tab fade;
  honor `prefers-reduced-motion`.

We will **not** introduce serif/monospace fonts, decorative gradients, or bounce animations.

## Consequences

- Token source: `globals.css` + `tailwind.config.ts`.
- New Phase 2 MVP surfaces compose from `var(--*)` utilities, not one-off hex.
