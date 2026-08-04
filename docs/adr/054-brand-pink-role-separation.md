# ADR-054: Brand pink role separation — accessible text and non-directional chart tokens

**Status:** Accepted  
**Date:** 2026-08-04  
**Deciders:** grill-with-docs (Architect)

**Builds on:** [ADR-015](015-design-system-token-foundation.md) brand palette and semantic color
table; [ADR-043](043-frontend-design-skill-wiring.md) design-reference wiring.  
**Amends:** [`docs/product/design/design.md`](../product/design/design.md) Color section —
adds two tokens and one usage rule.  
**Does not change:** Inter-only typography; the `16px` / `24px` radius tokens; ADR-023's
four-destination IA or Home's two-card launcher; the existing brand hues
(`#F86BA5` / `#FAA5C4` / `#E85A94` / `#FEF5F6`) or the semantic color values.

## Context

`design.md` already declares two anti-patterns that the current implementation violates:
**"Brand pink is accent-only, never a full-page wash"** and **"Status is never
color-only."** In practice `--juli-primary` and `--juli-primary-strong` had absorbed
every job in `apps/demo` — nav active-pill, card hover glow, focus ring, links, kicker
text, and the chart *neutral* trend line — so nothing in the interface signalled
relative importance.

Two concrete defects follow from that, and both are measurable rather than matters of
taste:

1. **Chart neutral series is brand pink.** `packages/ui/src/chart.tsx` mapped
   `neutral: "var(--juli-primary)"`. A non-directional series (period-over-period
   comparison, or a metric with no growth/loss framing such as LIVE hours) therefore
   rendered in the same color as navigation and primary actions. The semantic colors
   from ADR-015 (`--success` growth, `--destructive` loss, `--warning`, `--info`)
   deliberately do not cover the non-directional case, so there was no correct token to
   reach for.

2. **Pink text fails WCAG AA.** `--juli-primary-strong` (`#E85A94`) computes to
   **3.32:1** on white — below the 4.5:1 AA threshold for normal text — yet was used as
   a `color` in 17 places (8 in `apps/demo/src/app/globals.css`, 9 in
   `packages/ui/styles.css`), including small uppercase kickers. Separately, `design.md`
   defines `--pink-dark` `#E85A94` as **"Pressed or darker accent"** — an interaction
   state. Using it as body text was already off-spec against the authority's own table,
   so this is a conformance fix, not a palette override.

`colors_and_type.css` already ships a full pink ramp, which made inventing a new hue
unnecessary — the ramp was measured instead:

| Ramp step | Value | Contrast on white | AA normal text |
|---|---|---|---|
| `--primary-600` | `#E85A94` | 3.32:1 | ✗ |
| `--primary-700` | `#D44983` | 4.13:1 | ✗ |
| **`--primary-800`** | **`#B0386A`** | **5.80:1** | ✓ |
| `--primary-900` | `#8C2D54` | — | ✓ |

Alternatives considered:

| Option | Outcome |
|--------|---------|
| Reuse `--muted-foreground` directly for chart series | Zero new tokens, but conflates "de-emphasized text" with "chart series"; a later text-contrast tweak would silently move every chart line |
| Darken `--juli-primary-strong` itself to an AA value | One-line fix for all 17 sites, but darkens every pressed state and the `--juli-focus-ring` derivation, and contradicts `design.md`'s own "pressed or darker accent" definition |
| Keep `#E85A94`, restrict to large text (3:1 threshold) | No token change, but forces kicker/link typography to ≥24px — `demo-kicker` is small uppercase by design |
| **Two new role-specific tokens (chosen)** | Each token has exactly one job; pressed states and the brand hues are untouched; no new hue enters the palette |

## Decision

1. **Add `--chart-neutral` (`#71717A`)** — reserved for **non-directional chart series
   only**. Derived from the `--muted-foreground` family rather than introducing a new
   hue, but declared as its own token so chart color and text color can diverge later
   without one dragging the other. It renders at 4.83:1 on white, ample for a 2px
   stroke. It must never be used for nav, buttons, links, or focus rings.

2. **Add `--pink-text` (`#B0386A`, exposed as `--juli-primary-text`)** — the only
   sanctioned token for **pink text on a light surface**, at 5.80:1. It reuses the
   existing `--primary-800` ramp step, so the palette gains a role, not a color.

3. **`--pink-dark` / `--juli-primary-strong` (`#E85A94`) reverts to its documented
   role** — pressed and darker accent states. It is no longer permitted as a `color`
   value.

4. **Brand pink is banned from charts entirely.** Directional series keep ADR-015's
   semantic colors; non-directional series use `--chart-neutral`.

## Consequences

- 17 `color: var(--juli-primary-strong)` declarations migrate to
  `var(--juli-primary-text)`. Pink text darkens visibly — this is the intended
  correction, not a regression.
- `CHART_SERIES_COLORS.neutral` changes from pink to gray; the guard assertions in
  `packages/ui/src/__tests__/chart.test.tsx` and `destination-card.test.tsx` are updated
  in the same change.
- After the migration `--juli-primary-strong` has **no consumers left**. It is kept
  declared rather than deleted: it is the authority's named pressed-state token, and
  removing a published token from `packages/theme` is a breaking change beyond this
  scope. Note that `--juli-pink-dark` carries the same `#E85A94` and *is* consumed (two
  pressed backgrounds in `packages/ui/styles.css`), and `--juli-focus-ring` hardcodes
  `rgba(232, 90, 148, 0.58)` rather than deriving from either. Collapsing that
  three-way duplication is worthwhile follow-up work, deliberately not done here.
- `apps/dashboard` consumes neither token today, so `design.md`'s governance requirement
  to update it in the same product change is satisfied with no edits there. Any future
  dashboard pink text must use `--juli-primary-text`.
- Dark/affiliate surfaces are out of scope: `apps/demo` is seller/light-only, and
  `packages/theme/tokens.css` declares no dark block. A dark-mode counterpart for
  `--pink-text` (a *lighter* pink on dark) must be defined before either token is used
  on an affiliate surface.
- This ADR covers token hygiene only. The broader `apps/demo` visual and copy revamp —
  chart gridlines and ticks, layout density, and Vietnamese copy (which per ADR-028 must
  resolve from `dictionary.md` keys) — remains separate, unstarted work.

## Notes

`.cursor/rules` cites "ADR-027" as the design-authority precedent; that number now
belongs to an unrelated ADR. The live precedent is **ADR-015**. Tracked as a docs bug
outside this change.
