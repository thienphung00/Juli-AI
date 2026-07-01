# Data Sources

> **Tier 1 — data phase gates.** Read [`EXECUTION.md`](../../EXECUTION.md) first.  
> **Owns:** which external sources are allowed in which phase; forbidden sources; operational polling rules.  
> **Does not own:** entity schemas (`data-models/`), ingestion field maps (`tiktok_api/endpoints.md`), subsystem envelopes (`system-design.md`).

**Authority:** `EXECUTION.md` > `system-design.md` > this file.  
This is the **only** file that assigns a phase to a data source.

## Phase legend

| Phase | Meaning |
|-------|---------|
| **P2** | Phase 2 Pipeline Validation — live polling + **rules-based** scoring (internal only) |
| **P2-ML** | Pre-Phase 2 historical ML backtest — **not required** for Phase 2 exit; trained models in Phase 4 |
| **P2.5** | Phase 2.5 Deployment Architecture — no new data sources |
| **P3** | Phase 3 Landing + Demo — mock data only in public apps |
| **P3.5** | Phase 3.5 Full Web App — real backend integration |
| **P4** | Phase 4 ML + LLM — cloud LLM copy layer live |
| **P4.5** | Phase 4.5 Real-Time — webhooks, polyglot, event streams |
| **Completed** | Pre-MVP mock — [`phase-1-completed.md`](../phases/phase-1-completed.md) |
| **Forbidden** | Never in any PR |

## Source matrix

| Source | P2-ML | P2 | P3 (demo) | P3.5 | P4 | P4.5 | Powers | Notes |
|--------|-------|----|-----------|------|----|------|--------|-------|
| **TikTok Orders** | Backtest only | Live polling | — | Live | Live | Live | Loss-prevention workflows | ~90d history |
| **TikTok Products (incl. inventory)** | Backtest only | Live polling | — | Live | Live | Live | NPL, Product Scaling, Stockout | Products API |
| **TikTok Affiliate** | Backtest only | Live polling | — | Live | Live | Live | Policy alerts (rules in P2) | ADR-008 |
| **TikTok Promotion API (Shop Ads)** | Backtest only | Live polling | — | Live | Live | Live | ROAS threshold rules in P2; T2 regressor in P4 | Promotion API |
| **TikTok Shop Account** | Backtest only | Live polling | — | Live | Live | Live | Policy rules in P2; T8 router in P4 | `health_data_source` gate |
| **Supabase Postgres** | — | Live | — | Live | Live | Live | OLTP + OLAP | ADR-002 |
| **Redis** | — | Live | — | Live | Live | Live | Action cards, view cache, sessions | [`phase-2-mvp.md`](../phases/phase-2-mvp.md) |
| **Claude Haiku 3.5** | — | — | — | — | Live | Live | Copy layer | Deferred from P2; rules-only in P2 |
| **Kalodata / Shoplus** | Optional | — | — | — | Optional | Optional | Validation only | Never user-facing |
| **ClickHouse / S3 / SQS** | — | — | — | — | — | Live | Polyglot plane | Phase 4.5 — ADR-004 |
| **Demo mock fixtures** | — | — | Live | — | — | — | `apps/demo` storytelling | Hardcoded; no API calls |

## Operational rules

- No real TikTok API before Milestone A (live data pipeline); pre-Phase 2 ML backtest is historical only.
- Phase 2 uses **rules-based scoring** — no trained model inference at 08:00 UTC.
- Phase 3 public apps (`apps/landing`, `apps/demo`) use **mock data only** — no TikTok connection.
- Datum → workflow traceability required (ADR-013).
- Display-grade **rules-based** scoring at **08:00 UTC** in P2.
- Rules-based copy in P2; Haiku is copy-layer only in P4+; rules fallback must pass CI when unreachable.
- ML promotion thresholds: `system-design.md` §3 + `thresholds.py` — **Phase 4 only**.
- VP/AHR dual-read May–July 2026 (ADR-005, ADR-006).

## Forbidden (permanent)

Seller Center scraping · buyer PII · unofficial livestream websockets · buyer chat/review text in MVP.
