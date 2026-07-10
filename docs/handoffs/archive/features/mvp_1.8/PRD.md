# PRD: MVP 1.8 — Design System & Interaction Polish (P1.8-8)

> **Phase:** 1.8 (Weeks 11–13) · **Slice:** P1.8-8 · **Authority:** [`EXECUTION.md`](../../../EXECUTION.md) · **Design:** [`docs/architecture/system-design.md`](../../architecture/system-design.md) § Design system & token foundation · **ADR:** [ADR-027](../../adr/027-design-system-token-foundation.md)
>
> **Exit gate (design-system):** Tokens applied (theme swap + states + elevation + motion); Seller (light) and Affiliate (dark) modes verified; no stray theme hex; `web/MODULE.md` invariant updated; screenshots re-baselined.

---

## Problem Statement

Phase 1 shipped three copilot workflows (New Seller, Revenue Leakage, Growth) and Phase 1.6–1.7 added executable modal journeys — but the web UI grew organically from ad-hoc tokens in `globals.css`. There is no single, enforceable design language for the Phase 1.8 operations-system spine: Shop Health hero, ranked recommendation "Clarity Cards", reasoning panel, approval gate, and outcome views.

Sellers and agency operators experience inconsistent visual hierarchy: semantic colors drift from the product strategy (Growth/Loss/New), interaction states are incomplete on some surfaces, elevation is mostly flat, and motion is ad-hoc. The current **Seller = dark / Affiliate = light** mapping conflicts with the approved design direction (**Seller = light** calm canvas, **Affiliate = dark**). Without a token foundation before P1.8 orchestration UI ships, new surfaces will be built on legacy patterns and require expensive retrofit.

Phase 1.8-8 must deliver the **design-system & interaction polish** slice: one token source, theme swap, full interaction states, 3-step elevation, and purposeful motion — all respecting accessibility and Vietnamese locale conventions. No new features, APIs, ML, or backend work.

---

## Solution

Adopt [ADR-027](../../adr/027-design-system-token-foundation.md) as the single design-token foundation for the Juli web app:

1. **Theme swap** — Seller workspace renders on a light canvas (`#FEF5F6`/white, charcoal text); Affiliate workspace renders dark. Invert current `html.dark` semantics.
2. **Typography** — One typeface (Inter), single **≤6-size** type scale; hierarchy from size + weight only (no serif or monospace fonts).
3. **Semantic palette** — Brand Primary `#F86BA5`, Background `#FEF5F6`; Growth `#16A34A`, Loss `#E5484D`, Warning `#F59E0B`, New/Info `#2563EB`, each with low-opacity background tints. Enforce 60/30/10 color distribution (neutral → semantic → pink accent).
4. **Interaction states** — Every interactive surface: Default · Hover (color shift or shadow lift) · Active (darker fill + scale 0.98) · Focus (3px ring + offset) · Disabled (muted, not-allowed) · Loading (inline spinner + disabled).
5. **Elevation** — 3-step shadow scale: `sm` (cards), `md` (modals/popovers), `lg` (toasts).
6. **Motion** — Card entry (fade + scale, staggered), metric counter on value change, approval → success toast, loading shimmer/skeleton, tab/route fade — all gated by `prefers-reduced-motion`.
7. **Migration** — Refactor existing orchestration and copilot surfaces to compose from CSS variables and shared component utilities; eliminate stray theme hex. Re-baseline screenshots and update module invariants.

The Clarity Card pattern (workflow recommendation card: name, plain description, key metric, reasoning sentence, approve + learn CTAs) becomes the reusable recommendation surface styled with these tokens — consumed by P1.8-4/5 ranking and reasoning slices without redefining visuals per slice.

---

## User Stories

### Theme & workspace modes

1. As a **seller**, I want the seller workspace to use a calm light canvas with charcoal text, so that the app feels trustworthy and readable during long operating sessions.
2. As an **affiliate user** (out-of-scope shell), I want the affiliate workspace to use a dark theme, so that mode distinction remains clear when switching workspaces.
3. As a **seller**, I want my persisted workspace mode to load the correct theme immediately without flash of wrong colors, so that the experience feels polished.
4. As a **developer**, I want theme semantics documented in the module invariant (Seller=light, Affiliate=dark), so that future contributors do not reintroduce the old mapping.
5. As a **QA engineer**, I want visual regression or snapshot tests covering both workspace modes on key routes, so that theme swap does not break contrast or layout.

### Design tokens & semantic palette

6. As a **product designer**, I want all brand and semantic colors defined once in the token layer, so that Growth/Loss/Warning/New colors are consistent everywhere.
7. As a **seller**, I want growth metrics to use green (`#16A34A`) only when reporting positive change, so that color earns meaning and reduces noise.
8. As a **seller**, I want loss/risk indicators to use red (`#E5484D`) only when there is something to report, so that urgent items stand out without alarm fatigue.
9. As a **seller**, I want warning and informational badges to use amber and blue respectively with readable background tints, so that I can scan status at a glance.
10. As a **seller**, I want primary pink (`#F86BA5`) reserved for health bars, shop score progress, and key engagement CTAs (5–10% of screen), so that accent color feels intentional not decorative.
11. As a **developer**, I want semantic background tints available as CSS variables for badges and tinted cards, so that I do not hand-roll rgba values per component.
12. As a **accessibility reviewer**, I want text contrast to meet WCAG AA on all semantic pairings in both themes, so that color is never the only signal.

### Typography (single font, ≤6 sizes)

13. As a **seller**, I want page titles and hero metrics to use larger Inter sizes with appropriate weight, so that hierarchy is clear without switching fonts.
14. As a **seller**, I want body text, labels, and chat messages at readable 16px default with 14px secondary and 12px captions minimum, so that mobile text stays legible.
15. As a **developer**, I want a documented type scale (≤6 sizes) mapped to Tailwind/CSS utilities, so that new surfaces do not invent arbitrary font sizes.
16. As a **product owner**, I want metric numbers to use the same Inter family with semibold weight rather than a separate mono font, so that we avoid extra font payload and stay on-brand.

### Spacing, radius, and touch targets

17. As a **seller on mobile**, I want touch targets at least 44×44px on buttons, nav items, and icon actions, so that I can operate one-handed.
18. As a **seller**, I want consistent 8px-baseline spacing between sections and 16px card padding, so that layouts feel rhythmically consistent.
19. As a **developer**, I want border radius aligned to the design system (12px buttons/inputs, 16px cards per existing `--radius`), so that corners match across surfaces.

### Interaction states — buttons

20. As a **seller**, I want primary buttons to show a subtle hover state (color shift or shadow lift), so that I know the control is interactive.
21. As a **seller**, I want pressed buttons to feel tactile (slightly darker + scale 0.98), so that tap feedback confirms my action.
22. As a **seller using keyboard**, I want a visible 3px focus ring with offset on all buttons, so that I can navigate without losing context.
23. As a **seller**, I want disabled buttons to look clearly inactive (muted fill, reduced contrast, not-allowed cursor), so that I do not attempt invalid actions.
24. As a **seller**, I want loading buttons to show an inline spinner and stay disabled with label text (e.g. "Đang xử lý…"), so that I know work is in progress.

### Interaction states — cards, inputs, links

25. As a **seller**, I want workflow recommendation cards to lift subtly on hover (border deepen or shadow), so that scannable cards feel interactive before I approve.
26. As a **seller**, I want form inputs to mirror the login form pattern: focus ring, inline error below field, disabled while submitting, so that forms behave predictably.
27. As a **seller**, I want tertiary text links to underline on hover with muted default color, so that secondary actions are discoverable but de-emphasized.

### Elevation (3-step shadow scale)

28. As a **seller**, I want resting cards to use light elevation (`sm`) or border-first styling, so that the UI stays calm.
29. As a **seller**, I want modals and popovers to use medium elevation (`md`), so that layered UI reads above the page.
30. As a **seller**, I want success toasts to use large elevation (`lg`) and slide in from the bottom, so that confirmations are noticeable without blocking the whole screen.

### Motion & micro-interactions

31. As a **seller**, I want homepage metric cards to fade and scale in with a short stagger on first load, so that content appears intentionally not abruptly.
32. As a **seller**, I want GMV and shop score numbers to animate when values change, so that updates feel real and rewarding.
33. As a **seller**, I want workflow approval to show button feedback then a success toast that auto-dismisses, so that I get clear closure on my action.
34. As a **seller**, I want data-loading regions to show skeleton shimmer rather than blank space, so that waiting feels calm not broken.
35. As a **seller**, I want tab/route transitions to fade smoothly (~300ms), so that navigation feels cohesive.
36. As a **seller with reduced-motion preference**, I want all non-essential animations disabled instantly, so that the app respects my system settings.
37. As a **product owner**, I want risk-badge bounce animation deferred (not in P1.8-8), so that motion stays purposeful not distracting.

### Clarity Card & orchestration surfaces (visual contract)

38. As a **seller**, I want each workflow recommendation presented as a scannable Clarity Card (name, plain description, key metric, one-sentence reasoning, approve + learn CTAs), so that I can decide quickly with trust.
39. As a **seller**, I want the Shop Health hero to show shop performance score with pink progress accent on neutral structure, so that health feels central without color overload.
40. As a **seller**, I want semantic green/red on metric cards only when there is growth or risk to report, so that the 60/30/10 color rule holds on the homepage.
41. As a **developer**, I want shared card/button/badge utilities that P1.8-4/5 orchestration slices consume, so that ranking and reasoning panels do not duplicate styling.

### Chat & copy presentation

42. As a **seller**, I want Juli chat bubbles on neutral backgrounds with clear sender labeling, so that conversation matches the rest of the calm UI.
43. As a **seller**, I want success and warning chat variants to use green/amber left-border tints, so that message severity is visible beyond color alone.
44. As a **seller**, I want all user-visible strings to remain Vietnamese with proper diacritics and VND formatting via shared formatters, so that locale consistency is preserved after the visual refresh.

### Accessibility & responsive

45. As a **seller using a screen reader**, I want icons paired with text or `aria-label`, so that controls are understandable without sight.
46. As a **seller**, I want focus order and modal focus traps unchanged or improved after styling migration, so that workflow modals remain accessible.
47. As a **seller on tablet**, I want workflow cards to use two-column layout where space allows without adding new content, so that larger screens use space efficiently.
48. As a **seller on mobile (375px)**, I want the design system to remain mobile-first with bottom nav clearance, so that touch layouts are not broken by the refresh.

### Developer experience & governance

49. As a **developer**, I want all theme surfaces to use `var(--*)` tokens — no hardcoded `#fafafa` / `#111` / legacy semantic hex — so that both workspace modes work from one codebase.
50. As a **reviewer**, I want the ui-ux-design rule and REFERENCE doc aligned to ADR-027, so that PR review can enforce the contract.
51. As a **product owner**, I want EXECUTION.md P1.8-8 slice traceable to implementation issues, so that governance stays intact.
52. As a **QA engineer**, I want `data-testid` preserved on primary actions through the migration, so that existing integration tests keep working.
53. As a **designer**, I want screenshots under `screenshots/` re-baselined after theme swap, so that UX review reflects the new seller-light experience.

### Cross-cutting

54. As a **seller**, I want Ramp-inspired UX discipline (one primary CTA per band, impact-first hierarchy) preserved while adopting the new tokens, so that product patterns stay consistent with prior Phase 1 learnings.
55. As a **developer**, I want no new npm dependencies for animation or fonts in P1.8-8, so that bundle size and LCP stay within module invariants.
56. As a **security reviewer**, I want the design-system work to touch presentation only — no auth, API, or data-layer changes — so that blast radius stays UI-scoped.

---

## Implementation Decisions

### Modules to build/modify (by responsibility)

| Module | Responsibility | Public interface |
|--------|----------------|------------------|
| **Design token layer** | Centralize brand, semantic, elevation, and tint variables; flip seller/affiliate theme mapping | CSS custom properties + Tailwind theme extensions |
| **Type scale utilities** | ≤6-size Inter scale as documented utilities | Typography utility classes / token map |
| **Component state utilities** | Shared hover/active/focus/disabled/loading treatments for buttons, cards, inputs | `.btn-*`, `.card`, `.field-input` extensions in component layer |
| **Elevation utilities** | `sm` / `md` / `lg` shadow tokens | Elevation utility classes |
| **Motion utilities** | Card entry, metric counter, toast, shimmer, route fade + reduced-motion guards | CSS keyframes + optional small React hooks for counters/toasts |
| **Theme bootstrap** | Workspace mode → correct theme class on `<html>` without FOUC | Existing workspace mode persistence, updated mapping |
| **Surface migration** | Refactor copilot home, task cards, workflow modals, chat, headers/nav to tokens | Visual-only changes to existing components |
| **Documentation & baselines** | Module invariant, screenshot refresh, ADR cross-links | Docs + image assets |

### Architectural decisions

- **ADR-027 is authoritative** for P1.8-8; ui-ux-design rule/skill/REFERENCE already updated to match target state.
- **Theme swap inverts prior mapping:** Seller → light (`html:not(.dark)` or equivalent after flip); Affiliate → dark. Implementation must update workspace mode → theme class wiring and both token blocks in globals.
- **One font only:** Inter; no Merriweather/Lora/IBM Plex Mono despite original design strategy mockups.
- **Semantic hex migration:** Update `--success`, `--destructive`, `--info` (and badge classes) to `#16A34A`, `#E5484D`, `#2563EB` respectively; add tint variables.
- **No shadcn registry introduction** in this slice — extend existing `@layer components` primitives first.
- **Clarity Card** is a composition pattern (structure + copy slots), not a net-new product workflow; styling lands in P1.8-8, content/ranking in P1.8-4/5.
- **Deferred:** serif fonts, mono data font, risk-badge bounce, decorative gradients, Figma library sync (optional follow-up).

### Schema & API contracts

- **None.** Presentation-layer only; no Postgres, API, or fixture schema changes.

### Integration points

- **Workspace mode context → `<html>` theme class** — must remain compatible with seller/affiliate shell and `AuthenticatedShell`.
- **Existing components** — `TaskCard`, `LoginForm`, `PageHeader`, `NavBar`, workflow panels, `AiChatPage` — migrate to tokens; preserve behavioral contracts (executor, dismiss modal, focus trap).
- **Downstream P1.8 slices** — P1.8-3 health hero, P1.8-4/5 Clarity Cards, P1.8-6 approval gate consume token utilities; coordinate landing order (tokens first, then orchestration surfaces).

### Assumptions

- P1.8-8 can land in parallel with other P1.8 slices if token utilities merge first; orchestration UI should build on merged tokens to avoid double work.
- Seller-light theme swap will invalidate existing seller-dark screenshots — re-baseline is expected, not optional.
- Vietnamese copy and `formatVND` / date formatters unchanged; only visual layer updates.
- Affiliate out-of-scope shell still needs dark theme verification even though seller is primary for exit gate.
- Product lead engagement bar for Phase 1.8 exit gate includes design-system verification item added to EXECUTION.md.

---

## Testing Decisions

### What makes a good test

- Test **visible behavior and accessibility contracts**, not CSS implementation details — e.g. focus ring present, disabled prevents click, reduced-motion disables animation class.
- One behavior per test; use stable `data-testid` selectors already on primary actions.
- Visual/theme: component tests asserting semantic token classes or computed styles on representative surfaces in both workspace modes where feasible.
- Match prior art: `LoginForm` loading/disabled tests, `TaskCard` approve/dismiss tests, existing copilot integration tests.

### Modules to test

| Module | Test style |
|--------|------------|
| Theme bootstrap | Unit/integration: seller mode → light tokens; affiliate → dark |
| Button states | Component: disabled blocks interaction; loading shows spinner + disabled |
| Focus | Component: focus-visible ring on primary interactive elements |
| Reduced motion | Component/CSS: animation none when `prefers-reduced-motion: reduce` |
| Token migration | Spot integration tests on home, task card, one workflow modal, chat — no regression on testids |
| Contrast | Manual or automated spot-check on semantic badge pairings (document in PR) |

### Prior art

- `web/src/__tests__/test_task_card_executor.test.tsx`
- `web/src/__tests__/test_new_seller_copilot.test.tsx`
- `LoginForm` error/loading patterns
- Existing ui-ux-design skill Stop hook checklist

---

## Out of Scope

- Phase 1.8 orchestration **logic** slices P1.8-1 through P1.8-7 (classification, fixtures, health check, ranking, reasoning copy templates, approval routing, outcome metrics) — separate PRDs/issues; this PRD covers **P1.8-8 visual foundation only**.
- Figma component library creation or design-to-code sync (optional later).
- Serif/display fonts, monospace data fonts, new brand colors.
- Risk-badge bounce animation.
- Backend, TikTok API, ML inference, Ollama, Postgres.
- iOS parity, nav redesign, seller-OS retired routes.
- shadcn/ui registry bootstrap (unless explicitly requested in a follow-up issue).

---

## Further Notes

### Risks

- **Visible regression:** Seller-light swap may surprise stakeholders accustomed to dark seller UI — communicate in release notes; re-baseline screenshots before UX validation sessions.
- **Hardcoded hex debt:** Grep and eliminate stray theme colors during migration; affiliate/seller switch is a common break point.
- **Parallel P1.8 work:** If orchestration slices ship before tokens merge, expect rework — prefer merging P1.8-8 token PR early.

### Rollout

1. Land token layer + theme flip + state/elevation/motion utilities.
2. Migrate high-traffic surfaces (home shell, task cards, nav, headers).
3. Migrate workflow modals and chat.
4. Update module invariant + screenshots.
5. Verify Phase 1.8 exit-gate design-system checkbox.

### Observability

- No new analytics events required; existing UX instrumentation (`trackTaskApproved`, etc.) must remain functional after DOM/class changes.

### Follow-ups

- Optional: Figma token sync via figma-generate-library skill.
- P1.8-4/5 issues should reference Clarity Card structure consuming P1.8-8 utilities.

---

## Assumptions (for issue filing)

- Discover session aligned design strategy with codebase; Product lead chose Seller=light / Affiliate=dark, Inter-only ≤6 sizes, ADR-027 semantic palette, full state table, 3-step elevation, five motion behaviors.
- Code in `globals.css` still reflects **old** theme mapping until P1.8-8 implementation merges — docs/rules describe **target** state.
- Parent Phase 1.8 orchestration PRD (P1.8-1…7) may be filed separately; this PRD scopes **P1.8-8 only**.
