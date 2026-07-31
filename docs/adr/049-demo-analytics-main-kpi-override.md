# ADR-049: Demo Analytics Main KPI override (CDP-backed Option B′)

**Status:** Accepted  
**Date:** 2026-07-30  
**Deciders:** grill-with-docs (Architect)

**Amends:** [ADR-023](023-four-destination-analytics-ownership.md) Main KPI set and selector
behavior for **`apps/demo` Analytics only** (Mock mode, CDP envelope reads).  
**Builds on:** [ADR-011](011-display-grade-analytics-layer.md), [ADR-029](029-phase-2.9-analytics-historical-backfill.md),
[ADR-037](037-phase-2.10-demo-real-data-no-auth.md), [ADR-038](038-phase-2.10-dual-layer-pipeline.md),
[ADR-048](048-cdp-webhook-first-spine-dual-credential.md), [ADR-046](046-cdp-medallion-physical-model.md)
(serving gold envelope contract — Q3).  
**Does not change:** ADR-023 four-destination IA; Analytics as exclusive KPI owner;
authenticated **`apps/dashboard`** Main KPI catalog (still ADR-023 until a future ADR);
Sign-in/OAuth deferral (ADR-048).

## Context

ADR-023 locked six **Main KPIs** for Analytics — SPS, Net Revenue, ROAS, Inventory
Turnover, Fulfillment Accuracy Rate, and CSAT — with honest unavailable states for
missing sources. Phase 2.10 wired Demo Analytics to **CDP precomputed envelopes**
(`analytics_backfill` → transform/compute → Postgres + Redis → public Demo read API).

The reference shop can now back a different, Partner-grounded hero set without
fabricating Shop Status, Ads, or CSAT proxies. Showing ADR-023 cards as visible-but-
unavailable placeholders would waste the Demo's primary evidence surface and mislead
visitors about what Juli measures today.

Alternatives considered:

| Option | Outcome |
|--------|---------|
| A — Keep ADR-023 set; mark most unavailable | Honest but empty Demo; rejects CDP value |
| B — Replace Net Revenue with GMV only | Partial fix; still shows dead SPS/ROAS/CSAT cards |
| **B′ — Demo-only five-KPI override (chosen)** | Five CDP-upgradable KPIs; drop non-envelope cards from selector; catalog locked at five |
| C — Unbounded metric wall | Violates ADR-023 compact selector model |

## Decision

1. **`apps/demo` Analytics** uses the **Demo Main KPI set** (Option B′) — one hero
   plus four selector cards — sourced from CDP envelopes when available. Each KPI is a
   **`metric_id` entry** in `gold.kpi_envelopes.payload.kpis` ([ADR-046](046-cdp-medallion-physical-model.md)
   Q3) — **not** a dedicated Postgres column. Initial catalog (**exactly five KPIs**;
   no sixth card):
   | Order | KPI | Envelope / source | Notes |
   |-------|-----|-------------------|-------|
   | 1 | GMV (TikTok) | A-36 | Default hero candidate |
   | 2 | AOV | A-36 GMV ÷ orders | Derived |
   | 3 | CTOR (click→đơn) | A-34 `click_order_rate`, GMV-weighted | Seller term **CTOR** |
   | 4 | LIVE hours | A-28 `live_hours` | **Not** GMV LIVE; **not** `avg_watch_duration` (unavailable on Partner) |
   | 5 | Cancellation rate | A-7 + webhook #11 | Silver A-7 merge |

   **Removed from B′ (2026-07-30 grill):** **Bestselling** (A-38 / A-39). Marketplace/
   platform bestselling ≠ the merchant's own bestsellers — must not appear as shop KPIs.
   Ops may still stop wasted A-38/A-39 Partner calls ([ADR-048](048-cdp-webhook-first-spine-dual-credential.md));
   that is **not** a Demo KPI or serving-gold initial-key requirement.

2. **Remove from the Demo selector** (do not show as empty placeholders) until
   envelope-backed: SPS, ROAS, CSAT, inventory turnover, fulfillment accuracy,
   **and Bestselling (A-38/A-39)**. Full visual-layer catalog may still exist in
   backend/docs; Demo UI selector is capped to the five above. Future KPI adds require
   an explicit ADR/catalog change — the flexible `payload.kpis` map allows keys without
   schema migration ([ADR-046](046-cdp-medallion-physical-model.md) Q3).

3. **Trust copy** on every Demo Analytics card: insight chain (what changed → risk/
   opportunity → action), seller-language sources (no API names / “fixture” labels),
   relative sync freshness + live indicator from envelope `computed_at`, and one
   consistent demo-data timestamp across Home and Analytics.

4. **`apps/dashboard`** and future authenticated surfaces retain ADR-023 Main KPI
   naming until a product ADR explicitly reconciles the authenticated catalog with
   CDP availability.

## Rationale

Demo exists to prove the **continuous CDP spine** and Decision loop on real masked
commerce patterns. The override is **Demo-scoped**, reversible, and documents why
the public selector diverges from ADR-023 without weakening Analytics ownership or
IA.

## Consequences

- `docs/product/design/Screens/analytics.md` and Demo tests asserting ADR-023 keys
  must update to the Demo Main KPI set (or assert Demo-specific config).
- Dictionary / copy work uses seller terms (GMV, CTOR, LIVE hours) not Partner codes.
- When envelope fields are missing, cards follow honest unavailable rules — never
  fixture values for dropped ADR-023 metrics reintroduced via the selector.
- Promoting a dropped ADR-023 KPI back into Demo requires envelope backing + explicit
  scope (no silent selector expansion).
- Swapping Demo Main KPIs (add/remove/replace B′ entries) updates **`payload.kpis` keys**
  and this ADR's catalog table — **no** `gold.kpi_envelopes` column migration per KPI
  ([ADR-046](046-cdp-medallion-physical-model.md) Q3).
