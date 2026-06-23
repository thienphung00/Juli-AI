---
name: Juli AI
description: Juli AI design system — warm pink seller dashboard for TikTok Shop (Vietnamese market). Light seller canvas + dark affiliate variant. Sourced from Juli brand guidelines and adapted from Vercel Geist structural conventions.
colors:
  # ─── Surfaces (3-tier, simplified from Material Design 5-tier) ───────────
  surface: '#ffffff'                   # Primary seller canvas, cards, header
  surface-dim: '#fef5f6'              # Secondary panels, sidebar tint, subtle wash
  surface-tint: '#fde8ec'             # Selected / active / highlighted states only
  on-surface: '#0a0a0a'
  on-surface-variant: '#71717a'        # Captions, meta, inactive nav icons (zinc-500)
  inverse-surface: '#050505'           # Affiliate dark canvas
  inverse-on-surface: '#f5f5f5'

  # ─── Neutral Gray Scale (zinc-based, warm-neutral) ────────────────────────
  # Used for table dividers, input tracks, disabled fills — NOT for borders on brand cards
  gray-50: '#fafafa'
  gray-100: '#f4f4f5'
  gray-200: '#e4e4e7'
  gray-300: '#d4d4d8'
  gray-400: '#a1a1aa'
  gray-500: '#71717a'
  gray-600: '#52525b'
  gray-700: '#3f3f46'
  gray-800: '#27272a'
  gray-900: '#18181b'
  gray-alpha-100: '#0000000d'
  gray-alpha-200: '#00000015'
  gray-alpha-400: '#00000024'

  # ─── Pink Brand Ramp ──────────────────────────────────────────────────────
  pink-50: '#fff0f6'
  pink-100: '#fde8ec'
  pink-200: '#ffd5e5'
  pink-300: '#faa5c4'                  # Gradient end, lighter accent
  pink-500: '#f86ba5'                  # Primary brand accent (CTAs, active nav, Juli tab)
  pink-700: '#e85a94'                  # Pressed / darker state
  pink-alpha-10: 'rgba(248,107,165,0.10)'
  pink-alpha-20: 'rgba(248,107,165,0.20)'  # Brand glow, outline-accent

  # ─── Borders / Outlines ───────────────────────────────────────────────────
  # Suggestion: two-tier border system
  # outline        → neutral zinc hairline for table rows, list separators, input outlines
  # outline-accent → pink-tinted border for brand cards and primary containers
  outline: '#e4e4e7'                   # Neutral hairline (zinc-200); tables, inputs, dividers
  outline-accent: '#f8d4dc'            # Pink-tinted; brand cards, section borders

  # ─── Primary (Brand Pink) ─────────────────────────────────────────────────
  primary: '#f86ba5'
  on-primary: '#ffffff'
  primary-container: '#fef5f6'
  on-primary-container: '#171717'
  inverse-primary: '#faa5c4'

  # ─── Info / Juli Insight Blue ─────────────────────────────────────────────
  # Suggestion: removed "tertiary" (was identical to "info: #2563eb") — use info only.
  # Tertiary as a brand color role is misleading; Juli has one brand accent (pink).
  # Blue is strictly semantic: Juli AI suggestion panels only.
  info: '#2563eb'
  on-info: '#ffffff'
  info-container: 'rgba(37,99,235,0.12)'
  on-info-container: '#2563eb'

  # ─── Functional State Colors ──────────────────────────────────────────────
  error: '#e5484d'
  on-error: '#ffffff'
  error-container: 'rgba(229,72,77,0.12)'
  on-error-container: '#e5484d'
  success: '#16a34a'
  on-success: '#ffffff'
  success-container: 'rgba(22,163,74,0.12)'
  on-success-container: '#16a34a'
  warning: '#f59e0b'
  on-warning: '#ffffff'
  warning-container: 'rgba(245,158,11,0.12)'
  on-warning-container: '#b45309'

  # ─── Chart Tokens ─────────────────────────────────────────────────────────
  chart-line: '#f86ba5'               # Sparkline strokes, trend lines
  chart-fill: 'rgba(248,107,165,0.10)'  # Area fill under sparklines
  chart-positive: '#16a34a'
  chart-negative: '#e5484d'
  chart-neutral: '#f86ba5'

  # ─── Surface Tints for Brand Moments ──────────────────────────────────────
  surface-tint-token: '#f86ba5'       # Brand tint reference (aliased from primary)
  brand-gradient-start: '#f86ba5'
  brand-gradient-end: '#faa5c4'
  brand-glow: 'rgba(248,107,165,0.20)'

  # ─── Glass / Overlay Surfaces ─────────────────────────────────────────────
  glass-bg-light: 'rgba(255,255,255,0.92)'
  glass-bg-dark: 'rgba(10,10,10,0.92)'

  # ─── Dark / Affiliate Theme ───────────────────────────────────────────────
  card-dark: '#111111'
  header-dark: '#0a0a0a'

typography:
  # Headings
  display-brand:
    fontFamily: Inter
    fontSize: 30px
    fontWeight: '800'
    lineHeight: 36px
    letterSpacing: -0.03em
  heading-24:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 32px
    letterSpacing: -0.02em
  heading-18:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '700'
    lineHeight: 28px
    letterSpacing: -0.02em
  heading-16:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.02em
  heading-14:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: '0'
  # Metrics / Stats
  metric-xl:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 32px
    letterSpacing: '0'
    fontVariantNumeric: tabular-nums
  metric-lg:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '700'
    lineHeight: 28px
    letterSpacing: '0'
    fontVariantNumeric: tabular-nums
  # Labels & Body
  label-14:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-14-strong:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
  label-12:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  label-caps:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.05em
    textTransform: uppercase
  nav-label:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 16px
  # Buttons
  button-14:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
  # Copy
  copy-14:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  copy-13:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px

rounded:
  sm: 6px
  md: 12px
  lg: 16px
  xl: 24px
  full: 9999px
  button: 12px
  card: 16px
  card-lg: 24px
  input: 12px
  nav-item: 12px
  pill: 9999px
  juli-tab: 16px

spacing:
  unit: 4px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  section: 32px
  gutter: 16px
  margin-mobile: 16px
  margin-desktop: 16px
  bottom-nav-clearance: 96px
  sidebar-width: 280px
  max-content: 1152px

breakpoints:
  sm: 640px
  md: 768px
  lg: 1024px
  xl: 1280px
  2xl: 1536px
---

# Design System: Juli AI

**Project ID:** juli-ai-tiktok-shop  
**Sources:** Juli brand guidelines, `web/src/app/globals.css`, `web/tailwind.config.ts`, adapted structural conventions from Vercel Geist.

---

## 1. Visual Theme & Atmosphere

Juli AI is a TikTok Shop management copilot aimed at Vietnamese sellers. The visual language is **warm, modern, and personal** — a white seller canvas with soft pink accents that feel approachable rather than corporate. The interface prioritizes clarity over decoration: a seller opens Home and sees today's report metrics, shop health bars, and tappable paths into Decisions — not dense pipeline jargon.

The atmosphere reads as a **friendly financial dashboard**. Pure white (`#FFFFFF`) grounds the seller workspace; pink is reserved for brand moments — gradient CTAs, the Juli AI tab, health progress, and subtle pink-tinted card borders. Semantic greens, reds, ambers, and blues carry meaning (growth, loss, caution, Juli suggestions) and are never used as decorative gradients. Motion is purposeful: cards fade in, metric charts slide up, and journey highlights pulse with a pink ring — all respecting `prefers-reduced-motion`.

Structurally the shell borrows the **sidebar + fluid main** discipline of precision dashboards: a fixed 280px sidebar on desktop (≥1024px) anchors navigation while the main canvas stays open for metrics, sparklines, and decision cards. Surfaces separate through tonal layering (`surface` → `surface-dim` → `surface-tint`) and neutral `gray-alpha` hairlines rather than heavy shadows — a warm instrument panel, not an enterprise ERP.

A secondary **affiliate dark theme** (`html.dark`) inverts the canvas to near-black (`#050505`) with charcoal cards (`#111111`), stronger shadows, and the same pink brand accent. Seller mode is the primary design target; affiliate shares tokens.

**60 / 30 / 10 rule:** ~60% white/neutral canvas, ~30% content cards and text, ~10% pink accent and semantic color. Pink is accent-only — not a page wash.

---

## 2. Color Palette & Roles

### Primary Foundation

| Descriptive Name | Hex | Role |
|---|---|---|
| **Pure Seller White** | `#FFFFFF` (`surface`) | Page canvas, cards, header — the one true background |
| **Blush Panel** | `#FEF5F6` (`surface-dim`) | Secondary surfaces, sidebar tint — never full-page wash |
| **Pink Highlight** | `#FDE8EC` (`surface-tint`) | Active/selected row tint, completed action backgrounds |
| **Soft Charcoal** | `#0A0A0A` (`on-surface`) | Primary body text, metric values, headings |
| **Mid Zinc Muted** | `#71717A` (`on-surface-variant`, `gray-500`) | Captions, meta labels, inactive nav icons |
| **Deep Void Black** | `#050505` (`inverse-surface`) | Affiliate dark canvas |
| **Charcoal Card Dark** | `#111111` (`card-dark`) | Affiliate card surfaces |

#### ✦ Color Role Decisions — Borders

> **Recommendation: two-tier border system** (adapted from Vercel's neutral/alpha pattern).
>
> The previous design used a single pink-tinted border (`#F8D4DC`) for everything — brand cards *and* data tables. This creates visual noise in metric-dense views where rows also carry green/red semantic colors. The two-tier split resolves this:

| Descriptive Name | Hex | Role |
|---|---|---|
| **Neutral Hairline** | `#E4E4E7` (`outline`, zinc-200) | Table row dividers, list separators, input outlines — structural, not branded |
| **Pink Card Border** | `#F8D4DC` (`outline-accent`) | Brand cards, section containers — warm, intentional brand touch |

#### ✦ Color Role Decisions — Surface Containers

> **Recommendation: 3-tier surfaces** instead of Material Design's 5-tier system.
>
> The previous design had `surface-container-lowest`, `-low`, `-container`, `-high`, `-highest` — all `#FFFFFF` or `#FEF5F6` variants. For a 2-layer seller dashboard, only 3 tiers are needed and distinguishable.

| Tier | Token | Hex | Use |
|---|---|---|---|
| Base | `surface` | `#FFFFFF` | Page, cards, header |
| Secondary | `surface-dim` | `#FEF5F6` | Sidebar, secondary panels |
| Highlighted | `surface-tint` | `#FDE8EC` | Active rows, selected states |

### Pink Brand Ramp

| Token | Hex | Descriptive Name | Role |
|---|---|---|---|
| `pink-50` | `#FFF0F6` | **Blossom Whisper** | Hover tints on white, lightest wash |
| `pink-100` | `#FDE8EC` | **Rose Mist** | Surface tint, selected backgrounds |
| `pink-200` | `#FFD5E5` | **Soft Petal** | Chart fills, progress track |
| `pink-300` | `#FAA5C4` | **Soft Rose Light** | Gradient end, lighter accent |
| `pink-500` | `#F86BA5` | **Vibrant Brand Pink** | Primary accent, CTAs, active nav, Juli tab |
| `pink-700` | `#E85A94` | **Pressed Rose Dark** | Pressed state, darker interactive fill |
| `pink-alpha-10` | `rgba(248,107,165,0.10)` | **Pink Wash** | Chart area fill under sparklines |
| `pink-alpha-20` | `rgba(248,107,165,0.20)` | **Pink Glow Halo** | Juli tab shadow, brand rings |

### Accent & Interactive

| Descriptive Name | Hex | Role |
|---|---|---|
| **Vibrant Brand Pink** | `#F86BA5` (`primary`, `pink-500`) | Primary buttons, active nav items, Juli tab, health progress |
| **Soft Rose Light** | `#FAA5C4` (`pink-300`) | Gradient end, inverse-primary, lighter brand moments |
| **Pressed Rose Dark** | `#E85A94` (`pink-700`) | Pressed/active state on primary elements |
| **Brand Gradient** | `135deg #F86BA5 → #FAA5C4` | Primary button fills, brand wordmark text |
| **Pink Glow Halo** | `rgba(248,107,165,0.20)` (`brand-glow`) | Juli tab shadow, highlight rings |
| **Glass Overlay Light** | `rgba(255,255,255,0.92)` (`glass-bg-light`) | Sticky blurred headers on seller canvas |
| **Glass Overlay Dark** | `rgba(10,10,10,0.92)` (`glass-bg-dark`) | Affiliate glass overlays |

### Typography & Text Hierarchy

| Descriptive Name | Hex | Role |
|---|---|---|
| **Soft Charcoal** | `#0A0A0A` | Headings, metric values, primary labels |
| **Mid Zinc Muted** | `#71717A` | Section subtitles, card meta, secondary links |
| **Vibrant Brand Pink** | `#F86BA5` | KPI highlights, active tab labels, brand metric deltas |
| **White on Pink** | `#FFFFFF` | Text on gradient buttons and active Juli icon |

### Functional States

| Descriptive Name | Hex | Tint | Role |
|---|---|---|---|
| **Growth Green** | `#16A34A` (`success`) | `rgba(22,163,74,0.12)` | Positive delta, approved status, upward trends |
| **Loss Coral Red** | `#E5484D` (`error`) | `rgba(229,72,77,0.12)` | Negative delta, errors, live badges, rejection |
| **Caution Amber** | `#F59E0B` (`warning`) | `rgba(245,158,11,0.12)` | Threshold warnings, mid-range scores |
| **Juli Insight Blue** | `#2563EB` (`info`) | `rgba(37,99,235,0.12)` | **Juli suggestion panels only** — not generic AI purple |

#### ✦ Color Role Decision — Tertiary removed

> **Recommendation: remove `tertiary` role.**
>
> The previous design had `tertiary: '#2563eb'` and `info: '#2563eb'` — identical values with different names. "Tertiary" in Material Design 3 denotes a third *brand* color, but Juli has one brand accent (pink). The blue is purely semantic (Juli AI insight). Using `info` for both the semantic state and the container tokens (`info-container`, `on-info-container`) is cleaner and communicates intent at a glance.

**Accessibility:** Never communicate status by color alone. Pair with text, icons, or badge classes (`.badge-success`, `.badge-danger`, `.badge-info`).

---

## 3. Typography Rules

**Single typeface: Inter** (weights 400–800), loaded from Google Fonts or bundled via `next/font`. No serif or display variants — hierarchy comes from size and weight only.

### Hierarchy & Weights

| Token | Size / Weight | Usage |
|---|---|---|
| `display-brand` | 30px / 800 | Brand wordmark on login, gradient-clipped text |
| `heading-24` | 24px / 700 | Modal titles, major section headers |
| `heading-18` | 18px / 700 | `PageHeader` h1, page title |
| `heading-16` | 16px / 600 | "Báo cáo hôm nay", card section titles |
| `heading-14` | 14px / 600 | Card titles, metric labels, table column headers |
| `metric-xl` | 24px / 700 + `tabular-nums` | Large KPI values, VND totals |
| `metric-lg` | 20px / 700 + `tabular-nums` | Secondary KPI values, shop health scores |
| `label-14` | 14px / 400 | Nav labels, form fields, body prose |
| `label-14-strong` | 14px / 600 | Project names, filter labels, strong body |
| `label-12` | 12px / 400 | Badge text, timestamps, chart axis labels |
| `label-caps` | 12px / 500 + uppercase + `+0.05em` | Section tags: "ƯU TIÊN #", "VẤN ĐỀ", "TÁC ĐỘNG" |
| `nav-label` | 11px / 600 | Bottom tab bar labels |
| `button-14` | 14px / 600 | Button labels — CTAs and secondary actions |
| `copy-14` | 14px / 400 | Rationale text, modal descriptions |
| `copy-13` | 13px / 400 | Helper text, sublabels |

### Spacing Principles

- **≤6-size type scale** — no ad-hoc font sizes outside the token set above.
- Headings use negative letter-spacing (`-0.02em` to `-0.03em`) for a compressed, warm voice.
- Metric numbers always use `tabular-nums` (`font-variant-numeric: tabular-nums`) for aligned VND columns.
- Uppercase labels (`label-caps`) always pair with `on-surface-variant` (`#71717A`) for hierarchy — uppercase at full ink weight is too heavy.
- Body line-height stays compact (1.43–1.5) for dashboard density.
- Title Case for buttons, tabs, card titles; Sentence case for descriptions and helper text; ALL CAPS only for `label-caps` section tags.

> **Note on monospace:** No dedicated mono font is loaded. VND and numeric alignment is handled via `tabular-nums` on Inter. If commit hashes or deployment URLs ever appear, add Geist Mono or JetBrains Mono at that point — do not pre-load for anticipated use.

---

## 4. Component Stylings

### Buttons

**Primary (`.btn-primary`):**
- Fill: brand gradient (`135deg #F86BA5 → #FAA5C4`)
- Text: white, `button-14` (14px / 600)
- Radius: 12px (`rounded-xl`)
- Height: 40px standard; 48px hero CTAs (login, full-width)
- Hover: `brightness(1.05)` + `shadow-sm`
- Active: `scale(0.98)`, `brightness(0.95)`
- Focus: 3px pink focus ring with 2px offset
- Disabled: 50% opacity
- Loading: inline spinner overlay (`.btn-loading`)

**Secondary (`.btn-secondary`):**
- Transparent fill, 1px `outline-accent` border (`#F8D4DC`)
- Same radius, height, and padding as primary
- Hover: `surface-dim` background + `shadow-sm` lift
- Active: `scale(0.98)`

**Ghost / Tertiary:**
- Transparent fill, no border; ink text
- Hover: `gray-alpha-100` tint
- Used for inline actions, expand toggles

Hover steps fill from `gray-50` → `gray-100` → `gray-200` on neutral surfaces. Disabled: `gray-100` fill, `gray-500` text.

### Cards & Domain-Specific Containers

**Standard card (`.card`):**
- Background: `surface` (`#FFFFFF`)
- Border: 1px `outline-accent` (`#F8D4DC`)
- Radius: 16px (`card`)
- Padding: 16px standard (`p-4`); 24px on auth forms (`p-6`)
- No box-shadow unless elevated (modals, popovers use `0 4px 16px rgba(0,0,0,0.08)`)

**Interactive card (`.card-interactive`):**
- Hover: border tightens to `pink-300`, `shadow-sm`
- Active: `scale(0.98)`
- Focus-visible: 3px pink ring

**ClarityCard** — decision recommendation card with uppercase muted section labels (`label-caps`), rationale in `copy-14`, expandable reasoning panel, and full-width approve/reject action row. Primary action uses `btn-primary`; reject uses `btn-secondary`.

**ReportMetricChart** — tappable metric tile with `heading-14` label, `metric-lg` tabular value, green/red delta badge, optional sparkline (pink stroke `#F86BA5`, pink-alpha-10 fill), expandable Juli suggestion panel (blue `info-container` tint), and `RealEstimatedBar` progress segment.

**RealEstimatedBar** — domain-specific progress bar. Track: `pink-alpha-10`. Real segment: trend color (`success`/`error`). Estimated extension: 40% opacity + optional glow pulse animation. Disabled when `prefers-reduced-motion`.

### Navigation

**Bottom tab bar (`NavBar`):**
- Fixed bottom, full width, `surface` background, top border `outline` (neutral hairline)
- 5 tabs with 44×44px minimum touch targets
- Active tab: pink icon + label, `pink-alpha-10` background pill behind icon
- **Juli tab** (`/ai-chat`): elevated 40×40px `juli-tab`-radius button — gradient fill when active with `brand-glow` shadow; muted bordered square when inactive; pulsing `primary` dot badge
- Labels: `nav-label` (11px / 600)
- Safe area padding via `.safe-area-bottom`

**Top header (`PageHeader` / `.app-header`):**
- Sticky, `glass-bg-light` background with `backdrop-blur-sm`, `outline-accent` bottom border
- Title left (`heading-18`), `ModeSwitcher` + `AlertBell` right
- Shop info inline on mobile, sidebar on desktop (≥1024px)

**Fixed sidebar (desktop ≥1024px):**
- 280px (`sidebar-width`), `surface-dim` fill, full viewport height
- Structure: shop selector → search input → primary nav → secondary nav → bottom: settings + profile
- Active nav item: `pink-alpha-10` rounded pill background (`nav-item` radius), pink icon + label
- Inactive: `on-surface-variant` icon and label

**ModeSwitcher:** pill button, `gray-100` fill, `outline` border, `label-12` semibold toggling "Người bán" / "Affiliate".

### Inputs & Forms

**Field input (`.field-input`):**
- Background: `surface`
- Border: 1px `outline` (neutral, `#E4E4E7`)
- Radius: 12px (`rounded-xl`)
- Focus: `outline-accent` border color + 3px `pink-alpha-20` focus ring
- Disabled: 55% opacity
- Height: 40px

**OTP segmented input:** 6 boxes, 48×40px, `rounded-xl`, `metric-lg` centered digits, pink focus ring.

**Error messages:** `error-container` background, `error` text, `rounded-xl`, `role="alert"`.

### Domain-Specific Components

**Status badges (`.badge-*`):**
- Pill shape (`border-radius: 100px`), `label-12` (12px / 500)
- Variants: `success`, `warning`, `error`, `info`, `pink` — each with 12% opacity tint background and full-opacity text
- `.badge-live`: pulsing red dot + "LIVE" in `label-caps`

**Sparkline / area chart:**
- Pink stroke (`chart-line: #F86BA5`), pink gradient fill (`chart-fill: rgba(248,107,165,0.10)`)
- Green stroke (`chart-positive`) for positive-trend dedicated charts
- Axis labels in `label-12`; values in `metric-lg` above

**Core metric panel:**
- Label in `heading-14`, value in `metric-xl` with `tabular-nums`
- Delta badge: `badge-success` (green up) / `badge-error` (red down) / `badge-pink` (pink neutral)
- Expandable Juli insight panel: `info-container` tint background, `info` text, Juli wordmark icon

**Brand wordmark (`.brand-wordmark`):**
- Gradient-clipped text, `display-brand` (30px / 800), tight tracking
- Sizes: 30px for login, 18px for compact contexts

**Glass overlay (`.glass`):**
- `glass-bg-light` with `backdrop-blur-sm` + 1px `outline-accent` glass border
- Used for sticky blurred headers and modal overlays

**Skeleton / Spinner:**
- Skeleton: shimmer between `gray-100` and `gray-200`, `card` radius
- Spinner: 32px circle, `primary` top border, 0.7s linear spin

---

## 5. Layout Principles

### Grid & Structure

| Pattern | Value |
|---|---|
| Content container | `max-w-sm` (384px) login → `max-w-3xl` (768px) tablet → `max-w-6xl` (`max-content`: 1152px) desktop |
| Horizontal gutter | 16px (`px-4`) |
| Seller home grid (≥1024px) | 280px sidebar (`sidebar-width`) + fluid main, 20px gap |
| Today's report metrics (≥768px) | 2-column grid, 12px gap |
| Affiliate home KPIs | 2-column grid, 12px gap |
| Login form | centered, `max-w-sm` (384px) |

Dashboard uses a **sidebar + fluid main** shell at desktop. Mobile uses a **bottom nav + single column** shell. Main content centers at 1152px max with 16px side gutter.

### Whitespace Strategy

Base unit: **4px**. Rhythm: 8px inside component groups, 12px between grouped items, 16px between major sections, 32px between full sections. Card internal padding: 16px standard, 24px on auth surfaces. Bottom nav clearance: `pb-24` (96px) on authenticated shell. Sticky chat footer: `bottom-[4.5rem]`.

### Alignment & Visual Balance

- Page titles and body copy: left-aligned
- Login hero: center-aligned wordmark + subtitle
- Bottom nav: evenly distributed icons with centered labels
- Metric tiles: label/value left, sparkline right
- Approve/reject actions: side-by-side equal-width buttons
- Numbers: right-aligned in tables, left-aligned in metric tiles

### Responsive Behavior & Touch

- **Mobile-first** — single column default; grids at `md` (768px) / `lg` (1024px)
- **Minimum touch targets:** 44×44px on nav items; `min-h-11` (44px) on metric expand buttons
- **Safe areas:** `.safe-area-top` / `.safe-area-bottom` for iOS notch and home indicator
- **Reduced motion:** all animations and transitions disabled when `prefers-reduced-motion: reduce`
- **Locale:** Vietnamese UI (`lang="vi"`), VND currency (`Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' })`), ICT dates (UTC+7)

---

## 6. Design System Notes for Stitch Generation

### Language to Use

When generating Juli AI screens, describe the mood as:

> "A warm, clean TikTok Shop seller dashboard with a pure white canvas, soft pink brand accents used sparingly, and Inter typography. Feels personal and modern — like a friendly copilot, not an enterprise ERP. Vietnamese labels. Data-dense but breathable; brand cards have subtle pink borders, data tables use neutral hairlines. Pink only on CTAs, the Juli tab, and health progress."

For affiliate/dark variant:

> "Same pink brand accent on a near-black canvas (`#050505`). Cards are charcoal (`#111111`) with stronger shadows. Identical component shapes and typography."

### Color References

Core palette for prompts:

- **Pure Seller White** `#FFFFFF` — page background
- **Vibrant Brand Pink** `#F86BA5` — CTAs, active states, Juli tab
- **Soft Rose Light** `#FAA5C4` — gradient end
- **Blush Panel** `#FEF5F6` — secondary surfaces only
- **Pink Card Border** `#F8D4DC` — brand card borders only
- **Neutral Hairline** `#E4E4E7` — table dividers, input outlines
- **Soft Charcoal** `#0A0A0A` — primary text
- **Mid Zinc Muted** `#71717A` — secondary text
- **Growth Green** `#16A34A` — positive metrics
- **Loss Coral Red** `#E5484D` — negative metrics, errors
- **Caution Amber** `#F59E0B` — threshold warnings
- **Juli Insight Blue** `#2563EB` — AI suggestion panels only

### Component Prompts

1. **Seller Home — Today's Report:**
   > "White mobile dashboard titled 'Báo cáo hôm nay'. 2-column metric tile grid, 12px gap. Each tile: `heading-14` label top-left, `metric-xl` tabular VND number, green/red delta badge, mini pink sparkline right, horizontal progress bar with pink track. 16px rounded corners, pink `#F8D4DC` 1px border, 16px padding."

2. **Bottom Navigation with Juli Tab:**
   > "Fixed bottom nav on white background with neutral top hairline `#E4E4E7`. Five tabs; center 'Juli' tab is a raised 40px pink gradient square (`#F86BA5 → #FAA5C4`) with white icon and pulsing pink dot. Active tabs show pink icon and 10% pink background pill. 11px semibold Vietnamese labels."

3. **Clarity Decision Card:**
   > "White card, pink `#F8D4DC` 1px border, 16px radius. Uppercase muted section tags (`label-caps`) in zinc `#71717A`. 16px semibold title. Expandable reasoning panel. Bottom row: full-width pink gradient 'Phê duyệt' button and outlined 'Từ chối' secondary button side by side."

4. **Juli Insight Panel:**
   > "Expanded panel below a metric tile. Blue `rgba(37,99,235,0.12)` background, blue `#2563EB` left border accent, Juli wordmark icon top-left. `copy-14` rationale text in soft charcoal. 'Xem thêm' link in info blue. Never use pink in this panel."

5. **Desktop Sidebar + Main:**
   > "Fixed 280px left sidebar with blush `#FEF5F6` fill. Juli wordmark top-left. Active nav item: pink icon, pink `label-14` text, 10% pink background pill `12px` radius. Main: white fluid canvas, 20px gap from sidebar. Top header: glass blur with pink-tinted bottom border."

### Incremental Iteration

- Start with seller white canvas + one card + bottom nav — verify pink accent restraint before adding semantic colors.
- Lock `outline-accent` (`#F8D4DC`) to brand cards only; use `outline` (`#E4E4E7`) for table rows and input outlines.
- Add Juli insight panel (blue tint) only on expandable metric tiles — never use blue as a general accent.
- Test at 375px mobile width first; expand to 1024px for sidebar grid.
- Keep `#FEF5F6` off full-page backgrounds — it is secondary fill only.
- Pair every colored metric delta with a text label (e.g., "+12,5%") — never color alone.
- Layer state colors last (green deltas, red badges, amber warnings) — verify they read over both white and pink-tinted backgrounds.
- After first pass, compare against `docs/design/DESIGN_SYSTEM.md` for CSS variable compliance and Vietnamese copy completeness.

---

**Source files:** `web/src/app/globals.css`, `web/tailwind.config.ts`, `web/src/app/layout.tsx`, component primitives in `web/src/components/`.  
**Human-maintained reference:** `docs/design/DESIGN_SYSTEM.md`.  
**Adapted structural conventions from:** `Vercel/DESIGN.md` (gray scale pattern, token naming, two-tier border system, layout discipline).
