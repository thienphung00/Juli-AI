# System Architecture

## Overview

Juli-AI ingests TikTok Shop data from multiple sellers through a **scheduled monolith**
(v1.5) that upgrades to **near-realtime async orchestration** (v2.0) without rewriting
job logic. The platform serves operational dashboards with batch and, later,
seconds-to-minutes freshness.

**Canonical evolution doc:** [`migration_path.md`](../../migration_path.md) (MVP → v1.5 → v2.0).

## Phased Architecture (Summary)

| Phase | Ingestion | Orchestration | Intelligence | Live UI |
|-------|-----------|---------------|--------------|---------|
| **MVP** | Mock / UI-only | — | — | Static fixtures |
| **v1.5** | Webhook + polling → validation → ETL → Postgres | APScheduler triggers `daily_pipeline()` only | Daily batch (`src/jobs/*`, local Ollama optional) | REST + polling |
| **v2.0** | Same paths, higher cadence | Celery Beat + Redis (runner upgrade) | Rolling / near-realtime jobs | Redis pub/sub → WebSocket (**derived** state) |

Redis and Celery are **v2.0 only** — not introduced in v1.5.

---

## High-Level Architecture (v1.5 — Scheduled Monolith)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         CLOUD — INGESTION & API                                  │
│                                                                                  │
│  ┌──────────────────┐    ┌──────────────────┐    ┌───────────────────────┐      │
│  │  Webhook Receiver │    │  Polling Workers │    │  OAuth / Auth (Supabase)│      │
│  │  (FastAPI)        │    │  (async tasks)   │    │  + TikTok tokens       │      │
│  └────────┬─────────┘    └────────┬─────────┘    └───────────────────────┘      │
│           │ validate HMAC          │ fetch + rate limit                          │
│           └────────────┬───────────┘                                             │
│                        ▼                                                         │
│                 ┌─────────────┐                                                  │
│                 │  src/etl    │  dedup · transform · load                         │
│                 └──────┬──────┘                                                  │
│                        ▼                                                         │
│                 ┌─────────────┐     ┌──────────────────┐                         │
│                 │  Postgres   │◄────│  FastAPI /v1/*   │                         │
│                 │  (Supabase) │     │  (user-facing)   │                         │
│                 └─────────────┘     └──────────────────┘                         │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────┐
│                    LOCAL NODE — OPTIONAL COST LAYER (v1.5+)                      │
│                                                                                  │
│  Ollama · Scrapy · batch ML jobs invoked from src/jobs/*                         │
│  (cloud APIs remain up if local node is offline)                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

        APScheduler (cloud) — triggers only, no business logic inside scheduler
              │
              ▼
        daily_pipeline()  →  scrape · anomaly · forecast · recommend · sentiment
```

---

## High-Level Architecture (v2.0 — Near-Realtime)

Adds **Redis + Celery** as execution upgrade; `src/jobs/*` logic unchanged.

```
Ingestion (same as v1.5)
  Webhook / polling → validation → ETL → Postgres (source of truth)

Celery workers (parallel)
  ingestion · scrape · anomaly · forecast · recommend · notify

Redis pub/sub  →  WebSocket clients  (derived dashboard updates — not event sourcing)
```

See **WebSocket Architecture** and **Why Near-Realtime** in [`migration_path.md`](../../migration_path.md).

---

## Component Breakdown

### 1. Ingestion Layer (cloud)

#### Webhook Receiver

- **Technology:** FastAPI (`src/services/webhook`)
- **Responsibility:** Accept TikTok webhook events, validate HMAC signatures, ACK quickly, pass validated payloads to ETL path
- **SLA:** Respond within 3 seconds; persistence and enrichment async
- **Scaling:** Horizontal scale behind load balancer (simple replicas — no Kubernetes required at current scale)

#### Polling Workers

- **Technology:** Async Python (`src/services/polling`)
- **Responsibility:** Scheduled data fetching for incremental sync, backfill, and gap recovery
- **Schedule (typical):**
  - Orders: Every 15 minutes (incremental by `update_time`)
  - Products: Every hour
  - Inventory: Every 30 minutes
  - Settlements: Daily
- **Scaling:** Stagger per shop; respect per-(app × shop × endpoint) rate limits

#### Auth

- **Responsibility:** Supabase phone-OTP, JWT validation, TikTok OAuth token lifecycle
- **Storage:** Encrypted credentials in Postgres via `src/data`

### 2. ETL & Storage

#### ETL (`src/etl`)

```
Validated payload → dedup (event_id) → transform → src/data repos → Postgres
```

- **Deduplication:** Idempotent ledger / `(entity_id, update_time)` semantics
- **Enrichment:** Resolve product metadata, currency, shop scope
- **Failures:** DLQ or dead-letter table — poison messages must not block the API

#### PostgreSQL (Supabase) — source of truth

- Seller credentials and shop metadata
- Orders, products, inventory, settlements, livestream summaries
- Intelligence outputs, recommendations, alert history

Optional v1.5 enhancement under load: **Postgres-backed queue** between validation and ETL (only if spike volume justifies it).

#### Redis (v2.0 only)

- Celery broker and result backend
- Pub/sub for **derived** dashboard updates to WebSocket layer
- Rate-limit counters and hot caches as needed

### 3. Jobs & Orchestration

| Concern | v1.5 | v2.0 |
|---------|------|------|
| Job definitions | `src/jobs/*` | Same modules |
| Composition | `src/pipelines/daily.py` | Same pipelines; more frequent triggers |
| Runner | APScheduler in `src/orchestration/` | Celery Beat (upgrade, not rewrite) |
| Rule | Scheduler **triggers only** — never embed ML or scraping logic in scheduler config |

### 4. API & Frontend Layer

| Service | Endpoints | Data Source |
|---------|-----------|-------------|
| Orders API | `/v1/orders`, detail routes | Postgres via `src/data` |
| Analytics / intelligence | Scoring, forecasting, recommendations | Postgres + `src/intelligence/*` |
| Inventory / alerts | Stock risk, alert config | Postgres + `src/alerts` |
| Live updates (v2.0) | WebSocket | Derived snapshots from Redis pub/sub; refresh from REST on disconnect |

- **Web UI:** Next.js (`web/`)
- **Mobile:** SwiftUI (`ios/`)
- **Charts:** Recharts / ECharts
- **Near-realtime UI (v2.0):** WebSocket for live refresh — not a replayable event log

### 5. Local Node (optional, v1.5+)

- Ollama inference, Scrapy crawls, heavy batch ML
- **Not** a hard dependency — see Local AI philosophy in `migration_path.md`

---

## Data Flow Sequences

### New Order Flow (v1.5+)

```
TikTok (ORDER_STATUS_CHANGE webhook)
    → Webhook Receiver (validate HMAC)
    → ETL consumer (dedup, transform)
    → PostgreSQL (orders) — source of truth
    → Alert rules (best-effort, non-blocking)
    → Dashboard reads via REST (v2.0: optional WebSocket push of derived state)
```

### Initial Sync Flow (New Seller Onboarded)

```
Seller authorizes app
    → Auth stores tokens in Postgres
    → Polling: orders (90d), products, inventory
    → ETL → Postgres
    → Dashboard ready for seller
```

### Daily Intelligence (v1.5)

```
APScheduler (1 AM) → daily_pipeline()
    → scrape_job → vendor feeds
    → anomaly_job · forecast_job · recommendation_job · sentiment_job
    → Postgres intelligence tables
```

---

## Failure Modes & Mitigation

| Failure | Impact | Mitigation |
|---------|--------|------------|
| Webhook endpoint down | Missed events (TikTok retries ~3×) | Reconciliation polling; gap detection |
| ETL / DB write slow | Delayed freshness | Backpressure; idempotent retries; API still serves stale-but-consistent reads |
| PostgreSQL down | Dashboard reads fail | Connection pooling; circuit breaker; status page |
| Token expired | API calls fail for that shop | Proactive refresh; alert on auth errors |
| Rate limit exceeded | Delayed sync | Per-shop throttling; exponential backoff |
| Local Ollama offline | No new local ML outputs | Cloud API and ingestion continue; recommendations marked unavailable |
| WebSocket down (v2.0) | No live push | Client polls REST; DB unchanged |
| Notification channel down | Alert not delivered | Log + retry; pipeline continues |

Full isolation rules: **Failure Isolation Principles** in [`migration_path.md`](../../migration_path.md).

---

## Deployment Architecture (intentionally simple)

```
┌─────────────────────────────────────────────┐
│  Railway / Fly.io — API + workers           │
│  Vercel — Next.js web                       │
│  Supabase — Postgres + Auth                 │
│  Cloudflare R2 — raw archive (optional)     │
│  Local machine — Ollama + Scrapy (optional) │
└─────────────────────────────────────────────┘
```

Kubernetes, dedicated stream processors, and distributed tracing are **deferred**
until triggers in `migration_path.md` (Deferred Infrastructure) are met.

---

## Observability (current scope)

- **Logs:** Structured JSON (Sentry + platform logs); correlation IDs on webhook → ETL → DB
- **Metrics (optional v2.0):** Prometheus for Celery queue depth and worker health
- **Alerts:** Sentry for errors; operational alerts for auth and ingestion stalls

Distributed tracing and service mesh are explicitly out of scope until multi-service complexity warrants them.

---

## Related Documents

| Document | Purpose |
|----------|---------|
| [`migration_path.md`](../../migration_path.md) | Phases, local/cloud split, deferred infra, failure isolation |
| [`docs/architecture/map.md`](../architecture/map.md) | Module map and dependency graph |
| [`docs/architecture/data-sources.md`](../architecture/data-sources.md) | Allowed data sources by phase |
| [`tech-stack.md`](tech-stack.md) | Schema and technology notes (align with phased rollout when implementing) |
