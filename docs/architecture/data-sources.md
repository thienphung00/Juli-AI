# Data Sources

Single, phase-aligned source-of-truth matrix for Juli-AI. `discover`, `focus`, and
`review` must consult this file before proposing work that depends on any external
data. For module layout see [`map.md`](map.md); for phases and gates see
[`../../EXECUTION.md`](../../EXECUTION.md); for pipeline design see
[`../system-design.md`](../system-design.md).

> **Authority:** `EXECUTION.md` > `system-design.md` > this file. This is the **only**
> place that assigns a phase to a data source. Adding a source requires updating this
> table **and** linking the driving EXECUTION.md slice.

## Phase legend

| Phase | Meaning |
|-------|---------|
| **P1** | Phase 1 (Weeks 1–6) — UI + **mock** data |
| **P1.5** | Phase 1.5 (Weeks 6–9) — **backtest** (parquet) / synthetic for ML training |
| **P1.6** | Phase 1.6 (Weeks 9–10) — listing workflow **mock fixtures** + client export |
| **P1.7** | Phase 1.7 (Weeks 10–11) — leakage workflow **mock fixtures** + client mock execute |
| **P2** | Phase 2 (Weeks 11–15) — **live** TikTok API polling + daily inference |
| **Later** | Phase 2.5+ / Phase 3+ — out of the next 15 weeks |
| **Forbidden** | Must never appear in any PR (ToS, privacy, or stability risk) |

## Source matrix (phase-aligned)

| Source | P1 | P1.5 | P2 | Powers | Notes |
|--------|----|------|----|--------|-------|
| **TikTok Orders** | Mock | Backtest (parquet) | Live polling | Returns, refunds, GMV → Revenue Leakage Detection | Bounded order history (~90d); per-(app × shop × endpoint) rate limits; API ref: [`tiktok_api/endpoints.md`](../tiktok_api/endpoints.md) |
| **TikTok Affiliate** | Mock | Backtest | Live polling | Cancellation rates, commission disputes, collab type (Open vs Targeted) → fraud detection / Revenue Leakage | Scope-gated; masked buyer contact only; Targeted rate overrides Open; 30-day grace on seller rate decrease; settlement 3rd/15th day after delivery |
| **TikTok Ads** | Mock | Backtest | Live polling | Spend, CPC, conversions (daily) → Growth Copilot | Daily ad-performance signals |
| **TikTok Shop Account** | Mock | Backtest | Live polling | Shop age, order count, **account health** (VP/AHR if exposed) → seller-stage / New Seller Copilot / Revenue Leakage | **P2-1 gate:** VP/AHR API exposure is **UNKNOWN** until verified in Partner Center API Reference + API Testing Tool. Use `health_data_source: api \| proxy \| unavailable` (see Operational rules). Platform ref: [`tiktok_platform/seller/account-health.md`](../tiktok_platform/seller/account-health.md). API ref: [`tiktok_api/endpoints.md`](../tiktok_api/endpoints.md) → Account Health section. |
| **Supabase Postgres** (`src/shared/utils/data`) | — | — | Live | OLTP persistence, Alembic migrations, shop-scoped repos | Single backend DB; source of truth for persisted state ([ADR-002](../decisions/002-supabase-backend-service.md)) |
| **Ollama** (local inference node) | — | — | Live | Copy layer — summarize + localize structured signals for UI / alerts | Optional optimization path; **rules fallback** if offline or budget exceeded; never blocks ingestion or task execution |
| **Kalodata / Shoplus** | N/A | Optional backtest | — | Return-pattern validation only | **Phase 2.5+**; never user-facing analytics |
| **Leakage workflow fixtures** (`web/src/lib/mock-data/leakage-workflow/`) | Mock | — | — | Revenue Leakage executable workflow (P1.7) | Juli-internal schemas per `canonical-entities.md` § Leakage workflow; no network; masked IDs only |
| **Listing workflow fixtures** (`web/src/lib/mock-data/listing-workflow/`) | Mock | — | — | New Seller listing workflow (P1.6) | Juli-internal; see ADR-020 |

## Operational rules

- **Phase gating:** No real TikTok API calls before Phase 2. Phase 1 is mock JSON;
  Phase 1.5 is offline backtest/synthetic only.
- **Rate limits (P2):** Never sync all shops in the same second; respect
  per-(app × shop × endpoint) buckets; reuse the existing `RateLimiter`.
- **Daily inference (P2):** Models score live seller data at **08:00 UTC**.
- **Settlements (updated Jun 9, 2026 four-tier framework):** Hold money values as
  `pending` per the seller's settlement tier before treating as final:
  Express = 1 day (Mall + Store Rating ≥ 4.5 or Star Shop+);
  Accelerated = 3 days (established shops past adjustment period);
  Standard = 8 days (new shops in adjustment period — **default for unknown shops**);
  Extended = 15 days (risk/violation cases, up to 30 days maximum).
  Source: [docs/tiktok_platform/seller/operational-limits.md](../tiktok_platform/seller/operational-limits.md)
- **ML gates:** Backtest precision/recall targets recorded in
  [`../system-design.md`](../system-design.md) before promoting a model to Phase 2.
- **Ollama (P2):** Copy-layer only — not used for ML scoring or decision logic.
  Rules fallback must pass CI/integration tests with Ollama unreachable.
- **New Shop Adjustment Period:** New sellers progress through 4 tiers (Beginner →
  Standard → Premium → Pro). Juli must not gate affiliate features as available until
  Store Rating ≥ 3 AND SFRR is within category thresholds. Default settlement = Standard
  (8 days) until adjustment period is complete.
  Source: [docs/tiktok_platform/seller/operational-limits.md](../tiktok_platform/seller/operational-limits.md)
- **Affiliate Collaboration gates (P2):** Only surface affiliate recommendations for
  shops that meet: Store Rating ≥ 3 + no counterfeit VP + SFRR within category thresholds
  (Electronics < 3%, Lifestyle/Fashion < 2.8%, FMCG < 2.5%) + no service-related NRR
  violations. Check per-product SFRR for product-level affiliate eligibility.
  Source: [docs/tiktok_platform/seller/programs-and-eligibility.md](../tiktok_platform/seller/programs-and-eligibility.md)
- **Creator commission timing:** Creator commissions are payable only after seller
  settlement period completes. Apply seller settlement tier delay for any creator
  commission estimation (cross-cutting with Phase 3+ matching).
  Source: [docs/tiktok_platform/cross-cutting.md](../tiktok_platform/cross-cutting.md)
- **Account health polling (P2):** Account health is a **three-tier** contract until Partner API exposure is verified:
  - **Tier 1 (`health_data_source=api`)**: If VP/AHR/withholding/violation fields exist in official Partner API, poll daily and apply exact thresholds.
  - **Tier 2 (`health_data_source=proxy`)**: If not exposed, compute **proxies** from Orders/Products/Affiliate polling (never fabricate VP/AHR numbers).
  - **Tier 3 (`health_data_source=unavailable`)**: If neither is possible, surface “health score unavailable” in UI and avoid false certainty.
  During VP → AHR transition (May–July 2026), `health_check_mode: vp | dual | ahr` applies **only if** the corresponding API fields exist; otherwise stay in proxy/unavailable.
  Milestone hits must surface alerts when provable — not silent degradation ([ADR-008](../decisions/008-alert-vp-ahr-milestones.md)).
  Sources: platform policy ([`seller/account-health.md`](../tiktok_platform/seller/account-health.md)) + API verification gate ([`tiktok_api/endpoints.md`](../tiktok_api/endpoints.md)).
  Source: [docs/tiktok_platform/seller/account-health.md](../tiktok_platform/seller/account-health.md)
- **Appeal window (P2):** First appeal ≤ 30 days from violation notification; second
  ≤ 15 days from first rejection. Alert when window has ≤ 7 days remaining.
  Source: [docs/tiktok_platform/seller/account-health.md](../tiktok_platform/seller/account-health.md) §6
- **Joint seller–creator penalties:** Linked creator violations can trigger seller
  enforcement and vice versa. Flag affiliated shops when linked creators breach policy.
  Source: [docs/tiktok_platform/seller/account-health.md](../tiktok_platform/seller/account-health.md) §2.3,
  [docs/tiktok_platform/cross-cutting.md](../tiktok_platform/cross-cutting.md) §1.3
- **Affiliate enrollment gate (seller, P2):** Block affiliate recruitment recommendations
  when VP ≥ 12 (or AHR unhealthy post-July 2026). Open Collaboration (~10–15% fixed)
  vs Targeted Collaboration (~18–50% negotiable); Targeted rate overrides Open.
  Source: [docs/tiktok_platform/seller/feature-guide.md](../tiktok_platform/seller/feature-guide.md),
  [docs/tiktok_platform/seller/implementation-hooks.md](../tiktok_platform/seller/implementation-hooks.md)
- **Creator tiers (affiliate context, P2):** Link-Share Only (0 followers, no video/LIVE
  commission) vs Affiliate Creator (≥ 1,000 followers, full commission). Free samples
  and video/LIVE attribution require Affiliate Creator tier. CHR / creator matching
  filters are Phase 3+.
  Source: [docs/tiktok_platform/creator/programs-and-eligibility.md](../tiktok_platform/creator/programs-and-eligibility.md)
- **Balance withholding (enforcement):** Treat withheld seller balance as `frozen` (not
  `pending`); distinct from normal settlement hold. Duration: up to 180 days from
  enforcement notification. Source: [docs/tiktok_platform/seller/account-health.md](../tiktok_platform/seller/account-health.md) §5
- **Creator KYC / tax code (VN):** Treat VN creators without completed CCCD + tax code
  as KYC-incomplete; cannot withdraw commissions. Alert when linked affiliate creators
  are KYC-incomplete (blocks commission payout). REGION-VARIANT: VN only (since Jul 1, 2025).
  Source: [docs/tiktok_platform/creator/programs-and-eligibility.md](../tiktok_platform/creator/programs-and-eligibility.md) §3
  ([ADR-010](../decisions/010-vn-regional-platform-config.md))
- **Creator commission disputes:** Commissions on disputed/refunded orders held in `pending`
  state until dispute resolution; flag as Revenue Leakage signal.
  Source: [docs/tiktok_platform/creator/feature-guide.md](../tiktok_platform/creator/feature-guide.md) §7

## Forbidden — always, non-negotiable

| # | Source | Why |
|---|--------|-----|
| 8 | Realtime in-stream websockets / unofficial streams | ToS risk; breaks on TikTok updates |
| 9 | Seller Center browser scraping | Account suspension risk — official API only |
| 17 | Buyer PII / DM / private chat storage | Privacy — use masked `buyer_id` only |

- **Leakage workflow (P1.7):** Mock execute only — no Products API writes, no support-case
  submission, no shop-settings API. Placeholder screenshots only; no buyer content.
  `affiliate_fraud` task type removed from leakage persona — affiliate signals are P2
  policy alerts ([ADR-011](../decisions/011-buyer-behavior-anomaly-scope.md)).
- **Skip-with-reason (P1.7):** Dismiss on **all workflows** requires reason enum +
  optional note; stored in session + UX analytics (no PII).

## Out of the next 15 weeks (Later)

- Vendor scraper **training** (Kalodata / Shoplus / FastMoss) — Phase 2.5+
- Creator ↔ Shop matching data graph — Phase 3+
- Redis / Celery near-realtime, Kafka streams — Phase 3+ ([ADR-004](../decisions/004-etl-kafka-consumer.md))
- Shopee / Lazada / other marketplaces; non-TikTok wallets

## PR checklist (review / focus)

Before merging integration or ML work:

- [ ] Data source row + phase cited in PR / issue description and linked to an EXECUTION.md slice
- [ ] No forbidden (#8, #9, #17) dependencies introduced
- [ ] No real TikTok API calls before Phase 2
- [ ] Shop-scoped access enforced in `src/shared/utils/data` and `src/apps/api_gateway/api`
- [ ] Secrets and PII not logged (see `.cursor/rules/observability.mdc`)
