# DVR-A0 — Ephemeral design reference bundles

> **Scope:** Demo Visual Refinement PRD ([#580](https://github.com/thienphung00/Juli-AI/issues/580)), slice **DVR-A0** ([#583](https://github.com/thienphung00/Juli-AI/issues/583)).
>
> **Status:** Ephemeral handoff artifacts — **not** permanent agent-runtime infrastructure and **not registered** in agent-runtime config. Archive or delete after DVR-A2–A5 land. Do **not** register an Airtable-first Meta pipeline in `agent-runtime/config/`.

## Destinations covered

| Bundle | Consumer slices | Demo paths (read-only context) |
|--------|-----------------|--------------------------------|
| [home.md](./home.md) | DVR-A2 (Home icons) | `apps/demo/src/app/page.tsx`, `homeDestinations` |
| [analytics.md](./analytics.md) | DVR-A3 (Analytics polish) | `apps/demo/src/app/analytics/`, KPI/chart components |
| [recommendations.md](./recommendations.md) | DVR-A4, DVR-A5 | Recommendations list + five-stage review |

## ADR-015 adaptation (not 1:1 Mobbin clones)

Mobbin and Open Design references inform **layout rhythm, hierarchy, and interaction patterns only**. Implementation must map to Juli semantic tokens:

| Role | Token | Value | Use in these bundles |
|------|-------|-------|----------------------|
| Brand accent | `var(--primary)` | `#F86BA5` | Card hover rings, primary CTAs, active nav — never full-page wash |
| Canvas | `var(--background)` | `#FFFFFF` | Seller page background (not `--secondary` / `#FEF5F6`) |
| Secondary fill | `var(--secondary)` | `#FEF5F6` | Card tint, subtle section backgrounds |
| Growth | `var(--success)` | `#16A34A` | Positive deltas, approved states |
| Loss / risk | `var(--destructive)` | `#E5484D` | Negative deltas, reject emphasis |
| Caution | `var(--warning)` | `#F59E0B` | Threshold proximity |
| Juli suggestions | `var(--info)` | `#2563EB` | Contextual Juli accordion only — not generic “AI purple” |
| Elevation | `--shadow-sm` / `--shadow-md` | 3-step scale | Cards (`sm`), modals/drawers (`md`) |
| Radius | `--radius` / `--radius-lg` | `16px` / `24px` | Destination cards, hero KPI surfaces |
| Focus | 3px ring | `color-mix(in srgb, var(--primary) 45%, transparent)` | Keyboard targets on launchpad cards |

Typography stays **Inter**, ≤6-size scale per ADR-015. Metric values use `tabular-nums`.

## Copy authority

**Never** treat Mobbin, Open Design, or Airtable extract copy as authoritative Vietnamese.

- Terminology: [`dictionary.md`](../../../dictionary.md) keys only (`nav.*`, `decisions.*`, `analytics.*`).
- Voice/rules: [`docs/product/design/design-context.md`](../../product/design/design-context.md).

Reference screenshots may show English; implementation resolves labels from dictionary keys.

## Reference pipeline (this run)

1. **Open Design MCP** — Juli design system project `ds-juli-is-an-app-design-system` (`DESIGN.md`, linked repo `docs/product/design/`).
2. **Mobbin MCP** — problem-section screen search (web) per destination; links recorded in each bundle.
3. **Airtable layout extract** — *not available in this executor run*; compensated with OD `DESIGN.md` + existing `docs/product/design/README.md` locked IA.

## Product / design sign-off

HITL sign-off is **waived for this Meta-prepared run** (see [dvr-a0-handoff-note.md](../dvr-a0-handoff-note.md)). Bundles are ready for DVR-A2/A3 consumption from a layout-reference standpoint; final visual approval remains with implementers referencing ADR-015 + dictionary.

## Validation checklist

- [x] Bundles exist for Home, Analytics, Recommendations
- [x] Each bundle lists Mobbin screen URLs and Open Design artifact path
- [x] ADR-015 token mapping documented (this README)
- [x] Ephemeral scope documented — no agent-runtime registration
- [x] Unit test: `tests/unit/test_dvr_a0_reference_bundles.py`

```bash
python -m pytest tests/unit/test_dvr_a0_reference_bundles.py -q
```
