# Data Sources

> **Tier 1 — data phase gates.** Read [`EXECUTION.md`](../../EXECUTION.md) first.  
> **Owns:** which external sources are allowed in which phase; forbidden sources; operational polling rules.  
> **Does not own:** entity schemas (`data-models/`), ingestion field maps (`tiktok_api/endpoints.md`), subsystem envelopes (`system-design.md`).

**Authority:** `EXECUTION.md` > `system-design.md` > this file.  
This is the **only** file that assigns a phase to a data source.

## Phase legend

| Phase | Meaning |
|-------|---------|
| **P2** | Phase 2 MVP Milestone B — live polling + inference |
| **P2-A** | Phase 2 MVP Milestone A — backtest / synthetic only |
| **P3** | Phase 3.0 — polyglot, real-time, LIVE API |
| **Completed** | Pre-MVP mock — [`phase-1-completed.md`](../phases/phase-1-completed.md) |
| **Forbidden** | Never in any PR |

## Source matrix

| Source | P2-A | P2 | P3 | Powers | Notes |
|--------|------|----|----|--------|-------|
| **TikTok Orders** | Backtest | Live polling | — | Loss-prevention workflows | ~90d history; [`endpoints.md`](../tiktok_api/endpoints.md) |
| **TikTok Products** | Backtest | Live polling | — | NPL, Product Scaling | [`endpoints.md`](../tiktok_api/endpoints.md) |
| **TikTok Affiliate** | Backtest | Live polling | — | Policy alerts (not T6 ML) | ADR-008 |
| **TikTok Ads** | Backtest | Live polling | — | T2 ads regressor | Daily signals |
| **TikTok Shop Account** | Backtest | Live polling | — | T8 router, T3 policy | `health_data_source` gate (P2-B1) |
| **Supabase Postgres** | — | Live | Live | OLTP + OLAP | ADR-002 |
| **Redis** | — | Live | Live | Action cards, view cache, sessions | [`phase-2-mvp.md`](../phases/phase-2-mvp.md) |
| **Claude Haiku 3.5** | — | Live | Live | Copy layer | ADR-012 |
| **Kalodata / Shoplus** | Optional | — | Optional | Validation only | Never user-facing |
| **TikTok Inventory (scoped)** | — | Live | — | Stockout Prevention | Signals only — ADR-013 |
| **ClickHouse / S3 / SQS** | — | — | Live | Polyglot plane | Phase 3 — ADR-012 |

## Operational rules

- No real TikTok API before Milestone B; Milestone A is offline only.
- Datum → workflow traceability required (ADR-013).
- Display-grade inference at **08:00 UTC** in P2.
- Haiku is copy-layer only; rules fallback must pass CI when unreachable.
- ML promotion thresholds: `system-design.md` §3 + `thresholds.py`.
- VP/AHR dual-read May–July 2026 (ADR-005, ADR-006).

## Forbidden (permanent)

Seller Center scraping · buyer PII · unofficial livestream websockets · buyer chat/review text in MVP.
