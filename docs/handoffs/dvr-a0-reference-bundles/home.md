# Home — launchpad destination cards (DVR-A0)

> **IA law:** [ADR-023](../../adr/023-four-destination-analytics-ownership.md) — sparse launchpad with **exactly two** prominent cards: Decisions and Analytics. No KPIs, charts, or recommendation actions on Home.

## Target implementation (DVR-A2)

- Two large, tappable destination cards (`nav.decisions` → `/decisions`, `nav.analytics` → `/analytics`).
- Icon + eyebrow + one-line benefit copy per card (dictionary-driven).
- Minimum 44×44px touch target; focus ring per ADR-015.
- Current fixture shape: `apps/demo/src/lib/mock-data.ts` → `homeDestinations`.

## Layout patterns to adopt (adapted, not cloned)

### Primary: two-card launchpad (vertical stack, mobile-first)

Borrow **card anatomy** (icon block, title, supporting line, whole-card hit target) from SaaS launchpads, but reduce to **two** cards only — not four-up grids.

| Source | Mobbin URL | What to borrow | What to reject |
|--------|------------|----------------|----------------|
| Wave — Professional invoicing launchpad | [Wave launchpad](https://mobbin.com/screens/2839a4c7-77a2-4075-b84b-2bc20a5a98eb) | Horizontal card row rhythm → **stack two full-width cards** on mobile; icon-in-circle + bold title + muted description | Four-card grid; Wave blue palette; English copy |
| Snowflake — Quick actions | [Snowflake Home quick actions](https://mobbin.com/screens/636eccdf-537b-49eb-888a-02806d43ac73) | Icon + title + short description cell; generous padding (`--radius`, `--shadow-sm`) | Six action tiles; “Create User” patterns; Snowflake blue |
| Remote — Quick actions (secondary) | [Remote dashboard quick actions](https://mobbin.com/screens/eba81069-677a-49c5-8270-9de96a73ed8a) | Compact 2×2 grid spacing reference only — **do not add a third/fourth launcher** | “Things to do” task list (belongs in Decisions, not Home) |

### Secondary: wayfinding clarity

| Source | Mobbin URL | What to borrow | What to reject |
|--------|------------|----------------|----------------|
| Hotjar — Suggested for you carousel | [Hotjar Home](https://mobbin.com/screens/8b7178ae-a961-4727-bb65-52b66e7faedf) | Optional subtle page intro spacing above cards (not a carousel) | Onboarding carousel; live-session sidebar; English strings |

## Open Design reference

| Artifact | Path | What to borrow |
|----------|------|----------------|
| Juli design system | Open Design project `ds-juli-is-an-app-design-system` → `DESIGN.md` | Sparse Home — “one metric grid, one shop-health module” on **dashboard** product; Demo Home stays **cards only** per ADR-023 |
| Layout & composition | `DESIGN.md` §5 | Mobile-first; `.app-container` max-width; seller canvas `var(--background)` white |
| Components | `docs/product/design/README.md` | Locked two-card launchpad; Lucide/Shadcn icons folded into `@juli/ui` (DVR-A2) |

Linked repo authority: [`docs/product/design/README.md`](../../product/design/README.md).

## ADR-015 token mapping

| Element | Token / utility | Notes |
|---------|-----------------|-------|
| Page background | `bg-background` / `var(--background)` | White canvas — not pink wash |
| Card surface | `bg-card`, `border-border`, `--shadow-sm` | Pink-tinted border `#F8D4DC` via `--border` |
| Card hover | `--primary` at low opacity ring | No purple/blue Mobbin accents |
| Icon container | `bg-secondary` (`#FEF5F6`) + `text-primary` icon | Replace Unicode glyphs (current `⌂` `✓` `↗`) |
| Title | `text-foreground`, `font-semibold`, card title scale (0.875rem) | Use `nav.decisions` / `nav.analytics` dictionary labels |
| Description | `text-muted-foreground`, body scale | Benefit-led VI from fixtures until copy slice; never Mobbin English |
| Focus | 3px `var(--primary)` ring | Required for keyboard nav (DVR-A2 AC) |

## Copy keys (authority: dictionary.md + design-context.md)

| UI element | Dictionary key | VI (reference only) |
|------------|----------------|---------------------|
| Decisions card label | `nav.decisions` | Quyết định |
| Analytics card label | `nav.analytics` | Phân tích |
| Decisions eyebrow | *(fixture / future copy slice)* | Pattern: outcome-framed, “bạn” address |
| Analytics eyebrow | *(fixture / future copy slice)* | Pattern: exploration, not dense metrics |

Do **not** import Mobbin card titles (“Create invoices”, “Query data”, etc.).

## Anti-patterns

- Third launcher card (Settings belongs in nav only).
- KPI sparklines or shop health on Home (Analytics ownership per ADR-023).
- Mobbin purple/blue brand colors or generic AI gradients.
- English nav strings hard-coded in components.

## Downstream notes (DVR-A2)

- Export/refine `DestinationCard` (or equivalent) in `packages/ui/src/destination-card.tsx`.
- Preserve e2e Home launcher assertions in `apps/demo/e2e/exit-gate/decisions-journey.spec.ts`.
