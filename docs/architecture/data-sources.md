# Data Sources

Canonical source-by-source matrix for Juli-AI. `discover`, `focus`, and
`review` must consult this file before proposing work that depends on any
external data. For module layout and dependencies, see
[`map.md`](map.md). For phased rollout (MVP → v1.5 → v2.0), see
[`migration_path.md`](../../migration_path.md).

## Status Legend

| Status | Meaning |
|--------|---------|
| **MVP** | In scope for the TikTok Shop MVP; may already be implemented |
| **v1.5** | Planned after MVP; do not block MVP on it |
| **v2.0** | Near-realtime async layer (Redis + Celery); not in v1.5 |
| **Out** | Explicitly out of product scope |
| **Forbidden** | Must not appear in any PR (ToS, privacy, or stability risk) |

## Matrix

| # | Source | Status | Powers | Notes |
|---|--------|--------|--------|-------|
| 1 | TikTok Shop Partner API (official REST) | **MVP** | Orders, products, inventory, shop profile, finance/settlements, post-stream livestream summaries, affiliate creators (scope-gated) | Bounded order history (~90d), per-(app × shop × endpoint) rate limits, settlement lag 7–14d, buyer contact masked |
| 2 | Supabase Postgres (`src/data`) | **MVP** | OLTP persistence, Alembic migrations, shop-scoped repos | Single backend DB; Auth via Supabase (ADR-002); source of truth for all dashboard state |
| 3 | Webhook + polling → ETL (`src/services/webhook`, `src/services/polling`, `src/etl`) | **MVP** | Ingestion, dedup, persist via `src/data` | HMAC verification on webhooks; validation before ETL; pair webhooks with reconciliation polling |
| 4 | TikTok webhooks → `src/services/webhook` | **MVP** | Low-latency order/inventory/product events | HMAC verification required; pair with reconciliation polling |
| 5 | Polling workers (`src/services/polling`) | **MVP** | `sync_orders`, `sync_products`, `sync_inventory` | Stagger per shop; idempotent upserts |
| 6 | Derived insights (`src/intelligence/*`) | **MVP** | Post-stream scoring, anomalies, sentiment | Near-realtime from pipeline in v2.0; daily batch in v1.5; **not** in-stream telemetry |
| 7 | Post-stream livestream summaries (API #1) | **MVP** | `score_livestream`, retention estimates, stream-attributed orders | Only official post-stream fields; curves are **estimates** |
| 8 | Realtime in-stream websockets / unofficial streams | **Forbidden** | — | ToS risk; breaks on TikTok updates — use #7 + webhook latency instead |
| 9 | Seller Center browser scraping | **Forbidden** | — | Account suspension risk — use official API only |
| 10 | Cross-shop creator / competitor intelligence | **v1.5** | Creator ranking, benchmarks | Not exposed by TikTok; vendor feeds (FastMoss, Kalodata, Shoplus) via Scrapy (`src/jobs/scraping/`) |
| 11 | Historical orders & trends >90d | **v1.5** | Long-horizon analytics | API search window is bounded in MVP |
| 12 | Zalo OA + FCM (alert **output**) | **MVP** (alerts layer planned) | Seller notifications | Zalo template/approval constraints; FCM fallback; delivery best-effort |
| 13 | Local inference (Ollama, `src/jobs/*` on local node) | **v1.5** | Cost-optimized ML: sentiment, forecasting, embeddings | **Optional** optimization layer — cloud APIs stay up if local node is offline |
| 14 | Redis + Celery + WebSocket derived updates | **v2.0** | Near-realtime job orchestration and live UI refresh | Redis pub/sub pushes **derived** dashboard state; DB remains source of truth |
| 15 | Shopee / Lazada / other marketplaces | **Out** | — | Post-MVP multi-platform vision only |
| 16 | MoMoPay / non-TikTok wallets | **Out** | — | TikTok Shop Finance API covers MVP settlement signals |
| 17 | Buyer PII / DM / private chat storage | **Forbidden** | — | Use masked `buyer_id` only |
| 18 | Product page views / true on-site conversion | **Out** (MVP) | — | Use orders ÷ stream-attributed sessions as proxy where available |

## Substitutes (when a “want” is not available)

| Want | Reality | Substitute |
|------|---------|------------|
| Realtime viewers / gifts / comments in-stream | No safe API (#8 forbidden) | Post-stream summaries (#7); fast webhook-driven cockpit (#4–#6) |
| Hidden Seller Center analytics | Scraping forbidden (#9) | Ship only what #1 exposes |
| Cross-shop creator intel | Not in TikTok API (#10) | Defer to v1.5 vendor feeds |
| Trends beyond ~90d | Bounded search (#11) | v1.5 archives / vendor data |
| True conversion rate | Not in API (#18) | Stream-attributed order proxy |
| Millisecond dashboard updates | Polling + batch inference limits | Near-realtime in v2.0 (seconds–minutes); see `migration_path.md` |

## Operational Rules

- **Webhooks + polling:** Treat webhooks as authoritative for UX latency; run reconciliation polling at least every 15 minutes.
- **Rate limits:** Never sync all shops in the same second; respect per-(app × shop × endpoint) buckets.
- **Settlements:** Hold values as `pending` for 7–14 days before treating as final.
- **ML gates:** Anomaly detection and forecasting require ≥30 days of shop history; use moving-average fallback below that.
- **Alerts:** Channel-pluggable abstraction (FCM + Zalo OA in MVP scope); failures must not block ingestion.
- **Local AI:** Best-effort; missing inference must not block API or DB writes.

## PR Checklist (review / focus)

Before merging integration or intelligence work:

- [ ] Data source row cited in PR / issue description
- [ ] No #8, #9, or #17 dependencies introduced
- [ ] Shop-scoped access enforced in `src/data` and `src/api`
- [ ] Secrets and PII not logged (see `.cursor/rules/observability.mdc`)
- [ ] v1.5 work does not require Redis/Celery (#14) unless explicitly scoped to v2.0
