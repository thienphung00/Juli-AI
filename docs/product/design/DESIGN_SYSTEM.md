# Juli AI — Design System

> Token foundation and visual language for the Juli web app. Implemented in
> `web/src/app/globals.css` and `web/tailwind.config.ts`. Governed by
> [ADR-007](../adr/015-design-system-token-foundation.md); white seller canvas per
> [ADR-007](../adr/014-decision-copilot-app-structure-and-journey.md).

## Brand feel

**Warm · Modern · Simplistic · Personal · Interactive**

| Emotion | Expression |
|---------|------------|
| Warm | Soft pink-tinted borders, brand pink accent used sparingly, smooth chart entry |
| Modern | White seller canvas, Inter type, clean dashboard grid on desktop |
| Simplistic | Minimal copy on Home — chart + label + delta; no pipeline stage labels |
| Personal | Interactive metric tiles, Juli suggestion on tap (blue info affordance) |
| Interactive | Tappable charts, two-step metric → Decisions flow, Recharts sparklines |

## Dual workspace themes

Mode is persisted (`juli_workspace_mode` in `localStorage`) and toggles `dark` on `<html>`:

| Mode | Theme | Canvas |
|------|-------|--------|
| `seller` | Light (`html:not(.dark)`) | **White** `#FFFFFF` page, header, muted surfaces |
| `affiliate` | Dark (`html.dark`) | `#050505` background, `#111111` cards |

**Rules:**

- Always use semantic CSS variables (`var(--background)`, `var(--primary)`, etc.) — never
  hardcoded theme hex in components.
- Seller white canvas is **not** the pink tint `#FEF5F6`; pink tint is secondary surface
  (`--secondary`, `--pink-background`) only.
- Brand pink `#F86BA5` is **accent-only** — health progress, primary CTAs, Juli tab
  highlight — not full-page wash.

## Color palette

### Brand

| Token | Hex | Role |
|-------|-----|------|
| `--pink-main` / `--primary` | `#F86BA5` | Brand accent, primary actions |
| `--pink-light` / `--accent` | `#FAA5C4` | Lighter accent, gradients |
| `--pink-dark` | `#E85A94` | Pressed / darker accent |
| `--pink-background` | `#FEF5F6` | Secondary fill (not page background on seller) |
| `--brand-gradient` | `135deg #F86BA5 → #FAA5C4` | CTA fills, wordmark |

### Semantic (60 / 30 / 10 distribution)

| Token | Hex | Tint variable | Use |
|-------|-----|---------------|-----|
| `--success` | `#16A34A` | `--success-tint` (`#16A34A20`) | Growth, positive delta |
| `--destructive` | `#E5484D` | `--destructive-tint` | Loss, risk, negative delta |
| `--warning` | `#F59E0B` | `--warning-tint` | Caution, threshold proximity |
| `--info` | `#2563EB` | `--info-tint` | **Juli suggestion only** — not generic AI purple |

**Color accessibility rule:** never status by color alone — pair with text, icon, or badge
class (`.badge-success`, `.badge-destructive`, etc.).

### Neutrals (seller light)

| Token | Value |
|-------|-------|
| `--background` | `#FFFFFF` |
| `--foreground` | `#0A0A0A` |
| `--card` | `#FFFFFF` |
| `--muted-foreground` | `#71717A` |
| `--border` | `#F8D4DC` (pink-tinted divider) |
| `--border-accent` | `rgba(248, 107, 165, 0.2)` |

### Glass & header

| Token | Seller | Affiliate |
|-------|--------|-----------|
| `--header-background` | `#FFFFFF` | `#0A0A0A` |
| `--glass-bg` | `rgba(255,255,255,0.92)` | `rgba(10,10,10,0.92)` |
| `--glass-border` | pink 10% opacity | pink 12% opacity |

## Typography

- **Single typeface:** Inter (400–800), loaded from Google Fonts in `globals.css`.
- **No serif, display, or monospace** fonts — hierarchy from size + weight only.
- **≤6-size scale** (ADR-007); headings use `font-weight: 700`, `letter-spacing: -0.02em`.

| Role | Typical classes |
|------|-----------------|
| Page title | `text-lg` / `text-xl font-bold` in `PageHeader` |
| Section heading | `text-base font-semibold` (e.g. Báo cáo hôm nay) |
| Card title | `text-sm font-semibold` |
| Body | `text-sm` |
| Caption / meta | `text-xs`, `text-muted` / `var(--muted-foreground)` |
| Metric value | `text-lg`–`text-2xl font-bold tabular-nums` |

## Spacing & layout

| Pattern | Value |
|---------|-------|
| Default radius | `--radius: 16px` (`rounded-2xl`) |
| Content container | `.app-container` — `max-w-lg mx-auto px-4` (mobile); Home grid breaks wider |
| Bottom nav clearance | `pb-24` on shell, fixed `NavBar` |
| Safe areas | `.safe-area-top`, `.safe-area-bottom` for iOS notch/home indicator |
| Seller Home desktop | `.seller-home-grid` — sidebar (shop info) + main (report + health) |

## Elevation

Three-step shadow scale via CSS variables:

| Token | Use |
|-------|-----|
| `--shadow-sm` | Cards, list items |
| `--shadow-md` | Modals, popovers |
| `--shadow-lg` | Toasts, elevated overlays |

Prefer borders + subtle shadow on seller; affiliate uses stronger shadow opacity.

## Motion

All motion respects `prefers-reduced-motion` (hook: `usePrefersReducedMotion`).

| Pattern | Treatment |
|---------|-----------|
| Card entry | Fade + scale, staggered |
| Metric value change | Counter animation |
| Approval success | Toast feedback |
| Loading | `.skeleton` shimmer / spinner |
| Tab/route change | Fade transition |
| Estimated bar segment | Subtle glow pulse on Home (disabled when reduced motion) |
| Journey highlight | 2s ring/pulse on linked metric or `ClarityCard` |

**Deferred:** risk-badge bounce animation.

## Interactive states

Every interactive surface implements the full state contract:

| State | Treatment |
|-------|-----------|
| Default | Base color, full opacity, standard border |
| Hover | Subtle color shift or `--shadow-sm` lift |
| Active / pressed | Darker fill + `scale(0.98)` |
| Focus-visible | `--focus-ring-width: 3px` ring + offset (`--focus-ring-color`) |
| Disabled | Muted fill, reduced contrast, `cursor: not-allowed` |
| Loading | Inline `.spinner` + disabled control |
| Error | Inline message via `aria-describedby` |
| Empty | Explain why empty + what to do |

## Component primitives (`@layer components` in `globals.css`)

Use these before inventing new utility combinations:

| Class | Purpose |
|-------|---------|
| `.card` | Bordered panel |
| `.glass` | Blurred sticky overlays |
| `.app-header` | Top bar |
| `.brand-wordmark` / `-lg` / `-sm` | Logo text with gradient |
| `.gradient-primary` / `.gradient-primary-text` | CTA fill / gradient text |
| `.btn-primary` / `.btn-secondary` | Primary and secondary actions |
| `.field-input` | Text inputs |
| `.badge` + `.badge-success` / `.badge-destructive` / etc. | Status chips |
| `.badge-live` | Pulsing live indicator |
| `.spinner` | Loading indicator |
| `.skeleton` | Loading placeholder |
| `.text-muted` / `.bg-card` / `.bg-muted` | Semantic aliases |

## Tailwind extensions

`tailwind.config.ts` mirrors tokens:

- `primary.50`–`primary.900` pink scale
- `success`, `destructive`, `warning`, `info` semantic colors
- `rounded-2xl` (16px), `rounded-3xl` (24px)
- `animate-fade-in`, `animate-slide-up`, `animate-pulse-slow`

## Charts (Recharts)

- Series colors from CSS variables — no hardcoded chart hex.
- Home uses sparklines, real/estimated bar segments (`RealEstimatedBar`), and domain-specific
  chart types per [`docs/ml/visual_layer.md`](../ml/visual_layer.md) target.
- Chart containers need keyboard support when clickable; pair with `aria-expanded` on
  expandable metric tiles.

## Formatting

| Type | Utility |
|------|---------|
| Currency | `formatVND(n)` from `@/lib/format` |
| Dates | `formatDate`, `formatDateTime` (ICT) |
| Numbers | `formatNumber` for impact values |

## Anti-patterns

- Hardcoded `#F86BA5` or semantic hex in TSX instead of `var(--*)`
- Purple/blue decorative AI gradients (`--info` is Juli suggestion only)
- English UI strings or missing Vietnamese diacritics
- Pink tint `#FEF5F6` as seller page background
- Color-only status indicators
- Serif/monospace font introduction without ADR change

## File map

| File | Contents |
|------|----------|
| `web/src/app/globals.css` | Tokens, themes, `@layer components` |
| `web/tailwind.config.ts` | Tailwind color/radius/animation extensions |
| `.cursor/skills/standalone/ui-ux-design/REFERENCE.md` | Implementation reference for agents |

## OpenDesign polish targets

1. Audit all surfaces for token compliance (zero stray hex).
2. Verify seller white canvas on every authenticated seller route.
3. Normalize interactive states on metric tiles, tabs, and `ClarityCard` actions.
4. Align chart palette with semantic growth/loss colors.
5. Re-baseline screenshots after token or IA changes (`screenshots/`).
