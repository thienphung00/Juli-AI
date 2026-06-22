---
name: ui-ux-design
description: >-
  Builds production-grade Next.js UI for the Juli web app with strong UX,
  accessibility, and brand consistency. Use when creating or refining components,
  pages, dashboards, forms, modals, or layouts under web/, or when the user asks
  to improve how something looks or feels.
catalog:
  pluginIndex: skill-catalog
  loadWhen:
    - web/ next.js component page layout form modal dashboard
    - ui ux visual polish accessibility vietnamese
  companionSkills:
    - nextjs
    - react-best-practices
    - shadcn
hooks:
  Stop:
    - hooks:
        - type: prompt
          prompt: >-
            Check if the UI/UX task is complete. Advice-only tasks: respond
            {"ok": true}. Code was written: verify (only what applies) —
            Vietnamese copy with diacritics; CSS vars from globals.css (not
            hardcoded theme colors); interactive states; semantic HTML; visible
            focus; form labels; data-testid on key elements; seller (dark) and
            affiliate (light) if theme-sensitive; empty/loading/error states.
            Respond {"ok": true} or {"ok": false, "reason": "specific gap"}.
---

# UI/UX Design (Juli web)

Working code in `web/` — not mockups. Follow existing patterns before inventing new ones.

## When to invoke

| Signal | Action |
|--------|--------|
| New/changed component, page, modal, form | Load this skill + `web/MODULE.md` |
| "Make this look better" / screenshot pasted | Assess gap vs brand; patch in place |
| Figma → code | Also load `figma-use` + Figma MCP |
| Adding shadcn registry component | Also load `shadcn` plugin skill |

**Out of scope:** `ios/` (use `swift-patterns`), Python API, TikTok integration internals.

## Workflow

### 1. Read repo context

Before editing:

1. [`web/MODULE.md`](../../../../web/MODULE.md) — routes, invariants, locale
2. Nearest existing component (grep `web/src/components/` for similar UI)
3. [REFERENCE.md](REFERENCE.md) — tokens, primitives, layout, copy

Load plugin skills when Focus selects them: `nextjs`, `react-best-practices`; `shadcn` only when introducing registry components (no `components/ui/` yet — prefer existing `.card`, `.btn-*` classes first).

### 2. Design within brand

Juli has an established identity — **extend it, don't replace it**:

- Pink accent (`--primary` / `#F86BA5`), background `#FEF5F6`, Inter, glass + gradient wordmark
- **Theme ([ADR-015](../../../../docs/decisions/015-design-system-token-foundation.md), P1.8-8 target): Seller = light; Affiliate = dark** — inverts the prior mapping; use semantic tokens so both modes work
- One typeface (Inter), single **≤6-size** type scale (hierarchy from size + weight)
- Semantic palette: Growth `#16A34A`, Loss `#E5484D`, Warning `#F59E0B`, New/Info `#2563EB` (+ background tints); 60/30/10 distribution
- 3-step elevation (`sm`/`md`/`lg`); motion gated by `prefers-reduced-motion`
- Mobile-first (`max-w-lg`, bottom nav, sticky header, `safe-area-*`)

Vary **layout, density, motion, and hierarchy** — not the core palette or typeface unless the issue explicitly rescopes brand.

### 3. Implement

| Requirement | Standard |
|-------------|----------|
| Copy | Vietnamese with proper diacritics |
| Money/dates | `formatVND`, `formatDate`, `formatDateTime` from `@/lib/format` |
| Theming | `var(--*)` and `@layer components` utilities in `globals.css` |
| Structure | Semantic HTML (`header`, `nav`, `main`, `article`, `button`) |
| States | default · hover (color shift/shadow lift) · active (scale 0.98) · focus-visible (3px ring + offset) · disabled (muted, not-allowed) · loading (inline spinner) · error/empty |
| A11y | 4.5:1 text contrast; 44×44px touch targets; `aria-*` + labels on forms |
| Motion | Respect `prefers-reduced-motion` for non-essential animation |
| Tests | `data-testid` on interactive/empty-state elements (match existing pages) |
| Client boundary | `"use client"` only when hooks/events/browser APIs needed |

### 4. Verify

```
- [ ] web/MODULE.md invariants respected (API auth, locale, dual theme)
- [ ] Tokens from globals.css — no stray hex for theme surfaces
- [ ] Vietnamese copy; VND/date formatting via @/lib/format
- [ ] Interactive + empty/loading/error states
- [ ] Focus visible; inputs labeled
- [ ] data-testid on key elements
- [ ] Responsive at mobile width (375px)
```

## Anti-patterns

- New purple/blue-on-white gradients or random fonts (conflicts with Juli brand)
- Hardcoded `#fafafa` / `#111` instead of CSS variables (breaks affiliate/seller switch)
- `div` buttons, icon-only actions without `aria-label`
- Removed focus outlines
- English UI strings in user-facing copy
- Direct Supabase calls from browser components

## Recovery

| Issue | Action |
|-------|--------|
| Looks off-brand | Re-read REFERENCE tokens; copy patterns from `TaskCard`, `LoginForm`, `PageHeader` |
| Too generic | Strengthen hierarchy, spacing rhythm, or micro-interactions — stay on-brand |
| a11y gap | Contrast check, `focus-visible:ring-*`, associate labels |
| Missing states | Walk checklist; mirror `LoginForm` error/loading pattern |

## See also

- [`.cursor/rules/ui-ux-design.mdc`](../../../rules/ui-ux-design.mdc) — Ramp-inspired product patterns on Juli brand (Focus Tier 2)
- [REFERENCE.md](REFERENCE.md) — tokens, primitives, file layout, examples
- [`web/src/app/globals.css`](../../../../web/src/app/globals.css) — source of truth for design tokens
