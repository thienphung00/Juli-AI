# UI/UX Reference — Juli web

## Stack

| Layer | Choice |
|-------|--------|
| Framework | Next.js 14 App Router (`web/src/app/`) |
| Language | TypeScript |
| Styling | Tailwind CSS + CSS variables in `globals.css` |
| Components | Custom (`web/src/components/`) — no shadcn `components/ui/` yet |
| Locale | Vietnamese (`vi-VN`), ICT timezone, VND via `@/lib/format` |

## Dual workspace theme

Mode is persisted (`juli_workspace_mode` in `localStorage`) and toggles `dark` on `<html>`:

| Mode | Theme | Typical user |
|------|-------|--------------|
| `seller` | **Light** (`#FEF5F6`/white canvas) | TikTok Shop seller workflows |
| `affiliate` | **Dark** | Out-of-scope shell in Phase 1 |

> **Theme swap ([ADR-027](../../../../docs/decisions/027-design-system-token-foundation.md)):** Seller→light, Affiliate→dark. Theme mapping is implemented in `globals.css` and `applyWorkspaceTheme`.

**Rule:** Use semantic tokens (`var(--background)`, `var(--foreground)`, `var(--muted-foreground)`, `var(--border)`, `var(--primary)`) so both modes work without duplicate components.

## Design tokens

Defined in `web/src/app/globals.css` and mirrored in `tailwind.config.ts` for `primary.*` scales.

| Token | Role |
|-------|------|
| `--background` / `--foreground` | Page surface + text |
| `--card` / `--card-foreground` | Elevated panels |
| `--muted` / `--muted-foreground` | Subtle fills + secondary text |
| `--border` / `--border-accent` | Dividers; pink-tinted accent border |
| `--primary` / `--accent` | Brand pink (`#F86BA5`, `#FAA5C4`) |
| `--pink-background` | Light surface (`#FEF5F6`) |
| `--destructive` / `--success` / `--warning` / `--info` | Status semantics |
| `--radius` | `16px` default corner radius |
| `--brand-gradient` | Primary CTA / wordmark gradient |
| `--glass-bg` / `--glass-border` | Header overlays |

Tailwind extensions: `primary-50`…`primary-900`, `surface.*`, `ink.*`, `rounded-2xl` (16px).

## Component primitives (`@layer components`)

Prefer these before adding new utility soup:

| Class | Use |
|-------|-----|
| `.card` | Bordered panel (`TaskCard`, list items) |
| `.glass` | Blurred sticky overlays |
| `.app-header` | Top bar (`PageHeader`) |
| `.brand-wordmark` / `.brand-wordmark-lg` / `.brand-wordmark-sm` | Logo text |
| `.gradient-primary` / `.gradient-primary-text` | CTA fill / gradient text |
| `.btn-primary` / `.btn-secondary` | Standard actions |
| `.field-input` | Text inputs |
| `.badge` + `.badge-success` etc. | Status chips |
| `.badge-live` | Pulsing live indicator |
| `.spinner` | Loading indicator |
| `.safe-area-top` / `.safe-area-bottom` | iOS notch/home indicator |
| `.text-muted` / `.bg-card` / `.bg-muted` | Utility aliases |

## Layout patterns

```
┌─────────────────────────────┐
│ PageHeader (sticky, max-w-lg)│
├─────────────────────────────┤
│                             │
│   main content              │
│   px-4, max-w-lg, mx-auto   │
│   pb-24 (clear bottom nav)  │
│                             │
├─────────────────────────────┤
│ NavBar (fixed bottom)       │
└─────────────────────────────┘
```

- Content width: `max-w-lg mx-auto px-4`
- Bottom padding: leave room for fixed `NavBar` (`pb-20`–`pb-24`)
- Headers: `PageHeader` with `role="banner"`
- Navigation: `NavBar` with `aria-label="Điều hướng chính"`, `aria-current="page"`

## File organization

```
web/src/
  app/              # routes, layout.tsx, globals.css
  components/       # UI by feature (tasks/, workflows/, seller-home/, …)
  lib/              # format, auth, nav-config, mock-data, hooks
  __tests__/        # component tests (*.test.tsx)
```

- Colocate feature UI under `components/<feature>/`
- Export shared shells from feature `index.ts` when multiple imports exist
- Page files stay thin — compose from `components/`

## Vietnamese copy

- All user-visible strings in Vietnamese with full diacritics
- Error messages: state problem + recovery (`LoginForm`: "Mã OTP không đúng. Vui lòng thử lại.")
- Empty states: explain why empty + what to do (`CollectingDataEmpty`)
- Currency: `formatVND(n)` — never hand-format ₫
- Dates: `formatDate` / `formatDateTime` (ICT)

## Type scale, color, elevation, motion ([ADR-027](../../../../docs/decisions/027-design-system-token-foundation.md))

- **Type:** one typeface (Inter), single **≤6-size** scale; hierarchy from size + weight only. No serif/display or monospace fonts.
- **Color (60/30/10):** neutral (60%) → Growth `#16A34A` / Loss `#E5484D` (30%) → pink `#F86BA5` (5–10%); Warning `#F59E0B`, New/Info `#2563EB`. Each semantic ships a low-opacity background tint (badges/cards). Never color-only — pair with text/icon.
- **Elevation:** 3-step shadow scale — `sm` (cards) · `md` (modals/popovers) · `lg` (toasts).
- **Motion (respect `prefers-reduced-motion`):** card entry (fade + scale, staggered), metric counter on value change, approval → success toast, loading shimmer/skeleton, tab/route fade. No risk-badge bounce (deferred).

## Interactive states

Every interactive surface needs all states below; mirror existing components:

| State | Treatment |
|-------|-----------|
| Default | Base color, full opacity, standard border |
| Hover | Subtle color shift **or** shadow lift |
| Active / pressed | Darker fill + scale `0.98` |
| Focus-visible | 3px visible ring + offset |
| Disabled | Muted fill, reduced contrast, `cursor-not-allowed` |
| Loading | Inline spinner + disabled (label stays) |
| Error / empty | Inline error (`aria-describedby`) / empty = why + what to do |


```tsx
// Primary CTA — gradient + disabled opacity
<button
  type="button"
  className="btn-primary w-full disabled:opacity-50"
  disabled={loading}
  data-testid="submit"
>

// Focus — add visible ring (extend globals if missing)
className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"

// Reduced motion
@media (prefers-reduced-motion: reduce) {
  .badge-live::before { animation: none; }
}
```

## Accessibility checklist

| Check | Target |
|-------|--------|
| Text contrast | WCAG AA 4.5:1 |
| UI component contrast | 3:1 |
| Touch targets | ≥ 44×44px |
| Forms | `<label htmlFor>` or `aria-label`; errors linked with `aria-describedby` |
| Modals | focus trap, `aria-modal`, labelled title |
| Live regions | `aria-live` for async feedback |
| Icons alone | `aria-label` on control |

## `data-testid` conventions

Follow existing pages — stable, kebab-case, role-oriented:

- `task-card`, `task-approve`, `task-dismiss`
- `recommendations-empty`
- `login-phone-input`, `login-submit`

Add testids for: primary actions, empty states, modals, form fields under test.

## Aesthetic directions (within brand)

Juli is **clean light-commerce** (seller) and **refined dark-marketplace** (affiliate) — see ADR-027 theme swap. When expanding UI, pick an emphasis — don't drift to generic SaaS:

| Emphasis | How (on-brand) |
|----------|----------------|
| Data-dense dashboard | Tighter spacing, tabular numbers, badge severity colors |
| Copilot / AI panel | Glass header, gradient accents, conversational cards |
| Workflow modal | Step progress, clear primary/dismiss actions (`TaskDismissModal`) |
| Marketing moment | `brand-wordmark`, hero gradient, generous whitespace |

**Do not** introduce alternate brand colors or fonts to "be different" — differentiate through layout, iconography, and motion.

## Generic AI slop (avoid)

- Unrelated purple/blue gradients (Juli pink is intentional)
- Replacing Inter without explicit brand request
- Cookie-cutter three-column card grids with identical shadows
- Color-only status (pair with text/badge class)
- Lorem ipsum or English placeholders in shipping UI

## Companion tooling

| Need | Load |
|------|------|
| App Router patterns | `nextjs` plugin skill |
| TSX quality pass | `react-best-practices` (after multi-file edits) |
| New registry primitive | `shadcn` + MCP `shadcn` |
| Visual verification | `cursor-ide-browser` or `playwright` MCP |
| Figma source | `figma-use` before `use_figma` |

## Canonical examples

| Pattern | File |
|---------|------|
| Form + error/loading | `web/src/components/LoginForm.tsx` |
| Card + actions + testids | `web/src/components/tasks/TaskCard.tsx` |
| Sticky header shell | `web/src/components/PageHeader.tsx` |
| Bottom navigation | `web/src/components/NavBar.tsx` |
| Empty state | `web/src/components/recommendations/CollectingDataEmpty.tsx` |
| Modal workflow | `web/src/components/tasks/TaskDismissModal.tsx` |
| Workflow panel | `web/src/components/workflows/leakage/LeakageWorkflowPanel.tsx` |
