# Design — Visual System

> Category: Custom
> Surface: web, mobile-web, and native (mobile-first, platform parity)
> Implementation: `apps/dashboard` (Next.js)

This is the visual authority for Juli's color, typography, spacing, layout,
motion, voice, and component schemas. `colors_and_type.css` implements the
reusable token contract. Add missing values here first; lower-tier examples
and historical source evidence never define new design rules.

## Product posture

Juli is a Vietnamese-language shop-operations app that transforms shop data
into clear opportunities, risks, and ranked, explainable recommendations.
She shows expected impact, confidence, and reasoning before action and waits
for the seller's decision.

**Warm · Modern · Simplistic · Personal · Interactive**

| Quality | Expression |
|---|---|
| Warm | Soft pink-tinted borders and direct, supportive Vietnamese copy |
| Modern | White seller canvas, Inter type, clean responsive composition |
| Simplistic | Sparse Home with two destination cards and no metric clutter |
| Personal | Contextual Juli assistance tied to the active surface |
| Interactive | Expandable reasoning, guided workflows, and clear feedback |

Every choice serves the three pillars in `soul.md`: Intentional, Trusted, and
Personality. Avoid generic dashboard styling, jargon, autonomous-action
claims, and cliché purple AI gradients.

## Information architecture and composition

- Four primary destinations: **Home, Decisions, Analytics, Settings**.
- Juli is contextual assistance, not a standalone navigation destination.
- Home contains exactly two prominent clickable cards: Decisions and
  Analytics.
- Analytics owns all metrics, KPIs, forecasts, comparisons, charts, and
  reporting.
- Decisions owns recommendation review and execution tracking.
- Settings owns workflow templates and thresholds.
- Recommendation cards expose **Approve**, **Reject**, and **Expand**.
  Approve opens a prefilled/fillable workflow; Reject removes the
  recommendation; Expand reveals reasoning and details.
- In Progress preserves `needs_input`, `executing`, and `completed`.

## Workspace themes

Mode is persisted with `juli_workspace_mode` and toggles `dark` on `<html>`.

| Mode | Theme | Canvas |
|---|---|---|
| `seller` | Light | White `#FFFFFF` page, header, and muted surfaces |
| `affiliate` | Dark | `#050505` background and `#111111` cards |

- Use semantic CSS variables, never hardcoded theme colors in components.
- Seller white is the page canvas; `#FEF5F6` is a secondary surface only.
- Brand pink is accent-only, never a full-page wash.

## Color

### Brand

| Token | Value | Role |
|---|---|---|
| `--pink-main` / `--primary` | `#F86BA5` | Brand accent and primary actions |
| `--pink-light` / `--accent` | `#FAA5C4` | Lighter accent and gradients |
| `--pink-dark` | `#E85A94` | Pressed or darker accent |
| `--pink-background` | `#FEF5F6` | Secondary fill |
| `--brand-gradient` | `135deg #F86BA5 → #FAA5C4` | CTA fills and wordmark |

### Semantic

| Token | Value | Use |
|---|---|---|
| `--success` | `#16A34A` | Growth and positive delta |
| `--destructive` | `#E5484D` | Loss, risk, and negative delta |
| `--warning` | `#F59E0B` | Caution and threshold proximity |
| `--info` | `#2563EB` | Contextual Juli assistance only |

Status is never color-only; pair it with text, an icon, or a badge.

### Seller neutrals and overlays

| Token | Value |
|---|---|
| `--background` | `#FFFFFF` |
| `--foreground` | `#0A0A0A` |
| `--card` | `#FFFFFF` |
| `--muted-foreground` | `#71717A` |
| `--border` | `#F8D4DC` |
| `--border-accent` | `rgba(248, 107, 165, 0.2)` |
| `--header-background` | `#FFFFFF` seller / `#0A0A0A` affiliate |
| `--glass-bg` | `rgba(255,255,255,0.92)` seller / `rgba(10,10,10,0.92)` affiliate |

## Typography

- Inter only, weights 400–800, loaded from Google Fonts.
- No serif, display, or monospace typefaces.
- Use no more than six sizes; headings use weight 700 and `-0.02em`
  letter-spacing.

| Role | Typical classes |
|---|---|
| Page title | `text-lg` / `text-xl font-bold` |
| Section heading | `text-base font-semibold` |
| Card title | `text-sm font-semibold` |
| Body | `text-sm` |
| Caption / meta | `text-xs`, `.text-muted` |
| Metric value | `text-lg`–`text-2xl font-bold tabular-nums` |

## Spacing, layout, and elevation

| Pattern | Value |
|---|---|
| Default radius | `--radius: 16px`; 24px for hero surfaces |
| Content container | `.app-container`; mobile-first and centered when wide |
| Navigation clearance | Shell padding clears fixed navigation and safe areas |
| Touch target | Minimum 44×44px |
| `--shadow-sm` | Cards and list items |
| `--shadow-md` | Modals and popovers |
| `--shadow-lg` | Toasts and elevated overlays |

Home's two cards stack on narrow screens and may sit side by side on wider
screens. Analytics may use denser responsive grids; Home must not inherit
dashboard density.

## Motion

All motion respects `prefers-reduced-motion`.

| Pattern | Treatment |
|---|---|
| Card entry | Fade and subtle slide/scale |
| Approval feedback | Toast and visible transition to In Progress |
| Loading | Skeleton shimmer or spinner |
| Route change | Short fade |
| Button press | `scale(0.98)` and brightness shift |
| Focus-visible | 3px semantic focus ring with offset |

Motion communicates hierarchy or state. Decorative risk-badge bounce remains
deferred.

## Interactive state contract

Every interactive surface implements default, hover, pressed, focus-visible,
disabled, loading, error, and empty states. Errors preserve input and state a
recovery step; empty states explain why and what happens next.

## Component primitives

Prefer `colors_and_type.css` and `Components/` before inventing utility
combinations:

- `.card`, `.glass`, `.app-header`
- `.brand-wordmark`, `.gradient-primary`, `.gradient-primary-text`
- `.btn-primary`, `.btn-secondary`, `.field-input`
- `.badge` and semantic badge variants
- `.spinner`, `.skeleton`
- `.text-muted`, `.bg-card`, `.bg-muted`

Key product components include recommendation cards, two-segment
real-versus-estimated progress, In Progress workflow cards, and contextual
Juli assistance. Historical components in `source_examples/` are evidence.

## Charts and formatting

- Charts belong to Analytics, not Home.
- Series colors use CSS variables.
- Interactive charts support keyboard access.
- Currency uses `formatVND`; dates use `formatDate` or `formatDateTime` in
  ICT; impact values use `formatNumber`.

## Source provenance

Token evidence was extracted from `apps/dashboard/src/app/globals.css` and
`apps/dashboard/tailwind.config.ts`. Notes and snapshots under `context/`,
and examples under `source_examples/`, `preview/`, and `ui_kits/`, are
supporting evidence only. Root authorities win every conflict.

## Anti-patterns

- Hardcoded semantic colors or tokens introduced outside this authority.
- Purple decorative AI gradients.
- English UI strings or missing Vietnamese diacritics.
- Pink tint as the seller page background.
- Color-only status indicators.
- A standalone Juli/AI navigation tab.
- Metrics or KPI reporting on Home.
- Workflow templates or thresholds under Decisions.
- Autonomous-action messaging or execution without approval.

## Governance

Change a token or visual rule here first, then update
`colors_and_type.css`, relevant specifications, and `apps/dashboard` in the
same product change. This consolidation does not alter application code.
