# ADR-007: North-star ML models + vendor feature ingestion

> **SUPERSEDED (historical).** Tied to the creator↔shop matching scope of ADR-006,
> which was rescoped to **seller-money** workflows. The current ML plan (seller
> stage classifier, anomaly/fraud detector, ad performance analyzer) lives in
> [`docs/system-design.md`](../system-design.md); phasing in
> [`EXECUTION.md`](../../EXECUTION.md). Kept as history.

**Status:** Superseded by the seller-money rescope (see `EXECUTION.md`)
**Date:** 2026-06-03
**Deciders:** Engineering / Product
**Related:** [ADR-006](006-matching-pivot.md), [`data-sources.md`](../architecture/data-sources.md)

## Context

Phase 1 north-star KPIs (closed matches, repeat collaborations, revenue attributed,
recommendation accuracy, graph coverage) require **predictive models** fed by
TikTok Official API signals, internal platform data, and cross-shop vendor feeds
(Kalodata, Shoplus, FastMoss). The PRD initially listed scraping as forbidden for
Phase 1 **analytics surfaces**; ML feature ingestion from vendor sites is a distinct
use case already scoped as v1.5 in data-sources #10.

Prior art in-repo: gradient boosting / logistic patterns in
`docs/tiktok_api/ai-analytics.md`; Scrapy planned under `src/jobs/scraping/` in
nav-redesign and migration docs; no production spiders yet.

## Decision

**We will** implement five metric-aligned models under `matching/models/`:

| North-star KPI | Model | Algorithm |
|----------------|-------|-----------|
| Closed matches | `closed_matches` | Logistic regression |
| Repeat collaborations | `repeat_collab` | Survival analysis (Cox PH) |
| Revenue attributed | `revenue_attributed` | XGBoost regressor |
| Recommendation accuracy | `calibration` | Calibration metrics (monitoring) |
| Graph coverage | `graph_coverage` | Network metrics (operational) |

**We will** materialize features via:

- TikTok Shop Partner API extractors (MVP/v1.5)
- Internal DB lookups (real-time)
- Scrapy spiders for Kalodata, Shoplus, FastMoss (v1.5 only; `src/jobs/scraping/`)
- **Not** Seller Center scraping (remains forbidden #9)

**We will not:**

- Expose vendor data as analytics dashboards (competing with Kalodata class)
- Block `GET /v1/recommendations` on ML or scrape failure (graceful degradation)
- Introduce a separate graph DB or feature store service in v1.5

Full feature matrix: superseded (creator-shop-matching feature docs removed in the rescope).

## Why this architecture

- **Speed:** One model per KPI → clear ownership, testable gates, traceable metrics.
- **Cost:** Postgres feature tables + weekly train; XGBoost/logistic run on CPU local node.
- **Scalability:** Feature job / train job / inference job separation keeps the runner swappable.
- **Performance:** Daily batch inference sufficient for Phase 1; real-time features limited to internal lookups.
- **Reliability:** Missing vendor rows reduce confidence; rules fallback for copy; stale features labeled with `computed_at`.

## Options considered

- **A — Single multi-task neural model.** Rejected: opaque, data-hungry, hard to debug for ops.
- **B — Rules-only scoring (no ML).** Rejected: cannot hit accuracy/coverage KPIs or improve from outcomes.
- **C — Vendor APIs via paid contracts.** Deferred: Scrapy v1.5 path already approved in #10; revisit if ToS risk materializes.
- **D (chosen) — Five specialized models + Postgres feature store + staggered Scrapy.** Best interpretability / ship speed trade-off.

## Consequences

- **Positive:** Metric-to-model traceability; eval plan per KPI; reuses planned Scrapy location.
- **Negative:** Spider maintenance burden; vendor layout changes can break parsers.
- **Follow-ups:** Implement `matching/features/`, `src/jobs/scraping/` spiders, golden ML fixtures, wire calibration to P2-3.

## Rollout

1. v1.5: TikTok + internal features only → train revenue + closed-match models.
2. v1.5 +2w: Enable Kalodata/Shoplus/FastMoss spiders one vendor at a time.
3. v1.5 +4w: Enable survival + calibration + graph coverage jobs.
4. v2.0: Near-realtime feature refresh for hot paths; optional Redis feature cache.
