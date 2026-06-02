# Juli-AI Architecture Evolution

Three-phase progression from UI-only prototype to near-realtime operational intelligence.

## Phase Overview

| Phase | Style | Target Users | Key Principle |
|-------|-------|-------------|---------------|
| **MVP** | UI-first · Mock data | 0–50 | Validate UX and seller workflows — no real backend dependencies |
| **v1.5** | Daily batch intelligence | 50–100 | Wire real data — TikTok API, daily ML compute, daily Scrapy scrape |
| **v2.0** | Near-realtime intelligence | 100+ | Async orchestration — Redis + Celery workers, continuous rolling computation |

**Trigger to advance:**
- MVP → v1.5: UX validated, onboarding proven, ready for real data
- v1.5 → v2.0: Jobs slow / retry-heavy; sellers demand sub-daily freshness

---

## The Critical Architectural Principle

Separate **what the job does** from **how the job runs**.

```python
# ❌ BAD — tightly coupled flow; cannot scale or swap runner
@app.get("/sync")
def sync():
    scrape()
    detect_anomalies()
    forecast()
    recommend()

# ✅ GOOD — isolated jobs, runner-agnostic
def scrape_job(): ...
def anomaly_job(): ...
def forecast_job(): ...
def recommendation_job(): ...

# v1.5 runner:  cron / APScheduler calls daily_pipeline()
# v2.0 runner:  chain(scrape_job.s(), anomaly_job.s(), ...)
```

This single design decision makes migrating from APScheduler → Celery an **upgrade** (runner swap), not a replacement of job logic.

---

## Local Node Responsibilities

### Purpose

The local inference node handles cost-optimized, asynchronous compute work.

### Workloads

- Ollama inference
- Embeddings generation
- Sentiment analysis
- Forecasting
- Anomaly detection
- Recommendations generation
- Scrapy web crawling

### Characteristics

- Asynchronous (non-blocking to APIs)
- Cost-optimized (avoid cloud GPU costs)
- Non-user-facing (background processing)
- Failure-tolerant (degrades gracefully)

---

## Cloud Responsibilities

### Purpose

Cloud infrastructure handles uptime-sensitive, user-facing operational services.

### Services

- API serving (FastAPI / FastUI)
- Authentication & authorization
- Postgres / Supabase database
- Webhook ingestion
- Notification delivery
- Pipeline orchestration (APScheduler in v1.5; Celery Beat in v2.0)
- WebSocket delivery (v2.0)

### Characteristics

- Uptime-critical (SLA sensitive)
- User-facing (blocks user experience)
- Operational infrastructure (persistent state)
- Must maintain availability even if the local node fails

---

## Local AI Compute Dependency Philosophy

### Core Principle 1: Optimization Layer, Not Hard Dependency

Local AI compute is a **cost optimization layer**, NOT a hard platform dependency.

### Core Principle 2: Graceful Degradation

Cloud APIs remain fully operational even if the local inference node temporarily fails or is offline.

### Implications

- Inference tasks are best-effort delivery
- Missing recommendations do not break user workflows
- Alerts may be delayed but ingestion continues
- Cloud services degrade gracefully (not catastrophically)

---

## APScheduler Principle (v1.5)

APScheduler is a **timing/orchestration layer only**. It triggers pipeline execution on schedule; it never owns compute or business logic. All work is delegated to `src/jobs/*` and `src/pipelines/*`.

### Good responsibility

```python
# Correct: Scheduler triggers jobs only
scheduler.add_job(
    run_daily_pipeline,
    trigger="cron",
    hour=1,
)

# Correct: Job contains business logic
def run_daily_pipeline():
    scrape_data()
    forecast_metrics()
    generate_alerts()
```

### Bad responsibility

```python
# WRONG: Scheduler contains business logic
scheduler.add_job(
    lambda: scrape_and_forecast_and_alert(),
)

# WRONG: Complex logic in scheduled task definition
scheduler.add_job(
    perform_ml_inference_and_update_db,
    trigger="cron",
)
```

---

## Phase 1 — MVP (0–50 Users)

### Goal

Validate seller UX flows before wiring any real backend dependencies:

- Seller / Affiliate workspace navigation and information architecture
- Dashboard layout and operational flow comprehension
- Onboarding and retention patterns
- Mock operational data fidelity (does the UI feel real?)

MVP deliberately defers real API calls, ML models, and scraping to v1.5.

### Stack

| Layer | Tool | Purpose |
|-------|------|---------|
| Web UI | Next.js 14 (App Router) | Dashboard in UI-only mode (`NEXT_PUBLIC_UI_ONLY=1`) |
| Mobile | SwiftUI (iOS) | Native app shell |
| Mock data | `web/src/lib/mock-data/*` | Typed fixtures per screen (seller + affiliate variants) |
| Service layer | `web/src/lib/services/*` | Routes components to mock or real data |
| Auth | Supabase Auth (phone-OTP) | Real auth validates onboarding UX |
| DB schema | Supabase Postgres + Alembic | Schema scaffolded; populated via mock in UI-only mode |
| API | FastAPI (`src/api/`) | Serves mock-compatible response shapes |
| Hosting | Railway (API) + Vercel (web) | |
| Error tracking | Sentry | |

### Data Flow (UI-only mode)

```
Component
  └── web/src/lib/services/livestreams.ts
        └── if isUiOnly → return MOCK_LIVESTREAMS
        └── else        → api.livestreams.list()   ← not active in MVP
```

### Cost Estimate

| Component | Monthly |
|-----------|---------|
| Railway | $5–15 |
| Supabase | $0–25 |
| Vercel | $0 |
| Sentry | Free |
| Domain + email | $5–10 |
| **Total** | **~$10–50 / month** |

---

## Phase 2 — v1.5 (50–100 Users) — Daily Batch Intelligence

### Goal

Wire real data while staying batch-oriented and low-cost:

- TikTok Shop Official API (orders, products, inventory, livestreams, settlements)
- Daily Scrapy scrapes (vendor intelligence feeds: FastMoss, Kalodata, Shoplus)
- Daily ML compute (forecasting, anomaly detection, scoring, recommendations, sentiment)
- Webhook + polling ingestion with validation → ETL → Supabase

### Architecture Philosophy

```
Scheduled Monolith
  + Local ML compute (Ollama) — optional cost layer
  + Cloud API + DB
```

No Redis. No Celery yet. APScheduler triggers jobs (timing only).
Code is structured as **isolated jobs** so the runner upgrade to Celery in v2.0 is trivial.

### Stack

| Layer | Tool | Purpose |
|-------|------|---------|
| API | FastAPI | REST `/v1/*` |
| Hosting | Railway / Fly.io | API + worker hosting |
| DB | Supabase Postgres | Orders, products, inventory, settlements, intelligence results |
| Webhook ingestion | `src/services/webhook` | HMAC verification → persist / hand off to ETL |
| Polling sync | `src/services/polling` | `sync_orders`, `sync_products`, `sync_inventory` |
| ETL | `src/etl` | Transform, dedup → `src/data` repos |
| TikTok client | `src/integrations/tiktok` | Signed API calls, rate limiting |
| ML — scoring | `src/intelligence/scoring` | Livestream score, anomaly detection, Vietnamese sentiment |
| ML — forecasting | `src/intelligence/forecasting` | SKU depletion, low-stock risk, velocity |
| Recommendations | `src/recommendations` | Product push suggestions |
| Alerts | `src/alerts` | FCM + Zalo OA delivery |
| **Jobs layer** | `src/jobs/{scraping,forecasting,anomaly,recommendation,sentiment}` | Isolated executable tasks |
| **Pipelines** | `src/pipelines/` | Compose jobs into named pipelines |
| **Orchestration** | `src/orchestration/` → APScheduler | Trigger `daily_pipeline()` nightly |
| Scraping | Scrapy (`src/jobs/scraping/`) | Vendor feed scraping (cross-shop creator / competitor intelligence) |
| Archive | Cloudflare R2 | Raw event payloads |
| Error tracking | Sentry | |

### Folder Structure

```
src/
├── api/
├── auth/
├── data/
├── integrations/tiktok/
├── services/
│   ├── webhook/
│   └── polling/
├── etl/
├── intelligence/
│   ├── scoring/
│   └── forecasting/
├── recommendations/
├── alerts/
├── jobs/                    ← NEW in v1.5
│   ├── scraping/            # Scrapy daily scrapes (vendor feeds)
│   ├── forecasting/         # Daily ML forecast jobs
│   ├── anomaly/             # Daily anomaly detection
│   ├── recommendation/      # Daily recommendation scoring
│   └── sentiment/           # Daily comment sentiment
├── pipelines/               ← NEW in v1.5
│   └── daily.py             # Compose jobs into daily_pipeline()
└── orchestration/           ← NEW in v1.5
    └── scheduler.py         # APScheduler (upgraded to Celery Beat in v2.0)
```

### Data Flow

```
Ingestion (continuous)
  Webhook receiver → validation → ETL → src/data
  Polling workers  → validation → ETL → src/data

1 AM nightly (APScheduler — triggers only)
  daily_pipeline()
    ├── scrape_job()            → vendor feeds → raw archive → src/data
    ├── anomaly_job()           → reads src/data → writes intelligence results
    ├── forecast_job()          → reads src/data → writes forecast results
    ├── recommendation_job()    → reads src/data → writes recommendations
    └── sentiment_job()         → reads livestream comments → writes sentiment
```

Optional (if ingestion spikes justify it): Postgres-backed queue between validation and ETL — not required for v1.5 scale.

### Cost Estimate

| Component | Monthly |
|-----------|---------|
| Railway / Fly | $20–60 |
| Supabase | $25–75 |
| Sentry | $0–20 |
| Cloudflare R2 | $5–10 |
| Proxies (scraping, optional) | $10–50 |
| Electricity (local ML) | $10–30 |
| **Total** | **~$70–250 / month** |

---

## Phase 3 — v2.0 (100+ Users) — Near-Realtime Intelligence

### Goal

Transition from daily batch insights to **continuous operational intelligence**:

- Celery workers replace APScheduler as the runner (job logic in `src/jobs/*` unchanged)
- Redis pub/sub distributes operational updates to WebSocket-connected clients
- Multiple worker pools run in parallel (scrape, anomaly, recommendation, ingestion, notification)
- Rolling incremental forecasting and near-realtime anomaly alerts

### Architecture Philosophy

```
Event-driven async (monolith + workers)
  + Hybrid local / cloud inference
  + Redis + Celery (v2.0 only)
```

### Why "Near-Realtime" (Not "Realtime")

Latency sources that prevent true realtime:

- TikTok API polling windows (15–60 sec batches)
- Web scraping freshness limits (5–10 min crawl cycles)
- Batch inference windows (reduces GPU cost)
- Alert aggregation (reduces notification spam)

**Result:** The system achieves seconds-to-minutes latency, not millisecond latency. The term **near-realtime** accurately reflects this boundary.

### WebSocket Architecture Clarification

**Data flow:** Redis pub/sub distributes operational updates to WebSocket-connected clients.

**Critical distinction:**

- WebSocket updates are **derived state** (cached/summarized updates)
- NOT source-of-truth event streams
- NOT event sourcing architecture
- NOT a persistent event log

**Source of truth:** Database (Postgres / Supabase) remains source-of-truth. WebSocket delivers cached/summarized updates only.

**Implication:** If WebSocket delivery fails, state remains consistent in the database; clients can refresh from the API; no cascading failures.

### What Changes in v2.0

Only the **execution layer** changes. `src/jobs/*` business logic is identical.

| Before (v1.5) | After (v2.0) |
|---------------|-------------|
| `daily_pipeline()` called by APScheduler | `chain(scrape_job.s(), ...)` dispatched by Celery Beat |
| Sequential execution | Parallel Celery workers |
| Single runner process | Multiple worker pools |
| No pub/sub | Redis pub/sub → WebSocket (derived state to clients) |

### Stack Additions

| Layer | Tool | Purpose |
|-------|------|---------|
| Queue broker | Redis | Celery task broker + pub/sub (v2.0 only) |
| Workers | Celery | `scrape_worker`, `anomaly_worker`, `recommendation_worker`, `ingestion_worker`, `notification_worker` |
| Scheduler | Celery Beat | Upgrades APScheduler (same triggers, different runner) |
| Near-realtime UI | Redis pub/sub → WebSocket | Live dashboard updates (derived state) |
| Monitoring | Prometheus (optional) | Job queue depth, worker health |

### Cost Estimate

| Component | Monthly |
|-----------|---------|
| API infra | $50–150 |
| DB scaling | $50–150 |
| Redis | $20–60 |
| Celery workers | $50–150 |
| WebSocket infra | $10–50 |
| Monitoring | $20–50 |
| R2 / storage | $10–30 |
| Proxies | $30–100 |
| Electricity (local ML) | $20–50 |
| **Total** | **~$250–700 / month** |

---

## Deferred Infrastructure

The following systems are intentionally **not** introduced until operationally justified by scale, complexity, or cost pressures.

| System | Reason deferred | Trigger for introduction |
|--------|-----------------|--------------------------|
| Kubernetes | Deployment complexity exceeds benefit for &lt;100 users | &gt;1000 concurrent users OR multi-region requirement |
| Stream processing (e.g. dedicated event bus) | Batch scheduling + Celery sufficient at v2.0 | &gt;10,000 events/sec OR dedicated real-time analytics requirement |
| Microservices | Monolith + local node model sufficient | Component failure isolation becomes critical |
| Event sourcing | State management simple; event log overhead unjustified | Audit trail requirement OR complex state replay queries |
| Distributed tracing | Single-process / monolith visibility sufficient | &gt;10 interconnected deployables OR latency debugging across many hops |
| GPU cloud inference | Local + API inference sufficient | Cost/latency trade-off favors cloud scaling |
| Service mesh | Logs + metrics meet needs; mesh adds complexity | &gt;20 service-to-service connections OR policy complexity |

**Philosophy:** Optimize for founder velocity and operational simplicity. Introduce infrastructure only when scale or complexity justifies the cost. Avoid resume-driven architecture.

---

## Failure Isolation Principles

The architecture is designed to degrade gracefully. Failures in non-critical components must not cascade.

### Scraping failures

- Scraping failure ≠ API outage
- Ingestion endpoints remain available
- Users can still query existing data
- Alerts generated but non-blocking

### ML / inference failures

- Local Ollama offline ≠ database outage
- API remains fully functional
- Missing embeddings/sentiment do NOT block ingestion
- Recommendations degrade gracefully (marked unavailable)

### Notification failures

- Alert delivery is best-effort, non-blocking
- Failed alerts logged; pipelines continue
- Retry with exponential backoff
- Fallback channel (e.g. email) when primary fails

### Local inference outages

- Cloud APIs fully operational
- User dashboards remain responsive
- Batch recommendations skip until next cycle
- No cascading failures to cloud services

### Design implications

- Circuit breakers for external service calls
- Graceful degradation (partial data vs. error page)
- Log failures for analysis; do not fail entire requests for non-critical paths
- Non-critical services must not block critical APIs

### System resilience priority

1. API availability (highest)
2. Database consistency (second)
3. Background processing (third)
4. Recommendations / alerts (best-effort)

---

## Migration Timeline

| Milestone | Trigger | What Changes |
|-----------|---------|-------------|
| Launch MVP | — | UI + mock data live; auth scaffolded |
| MVP → v1.5 | UX validated; first paying users | Wire TikTok API; enable validation + ETL; enable daily ML jobs via APScheduler |
| v1.5 → v2.0 | Jobs retry-heavy; sellers demand sub-daily freshness | Upgrade APScheduler → Celery Beat; add Redis; add workers |

## What Never Changes

Across all phases, these surfaces remain untouched by the migration:

- `src/jobs/*` — business logic for every compute task
- `src/intelligence/*` — ML algorithms and models
- `src/data` — schema, repos, Alembic migrations
- `src/api` — REST contract surfaces

The execution-layer upgrade is the entire migration. Logic stays.

---

## Changelog (architecture refinement)

| Area | Change |
|------|--------|
| Removed | All Kafka / message-broker / event-stream references |
| Added | Local vs cloud responsibilities; local AI philosophy; APScheduler good/bad examples |
| Added | Deferred Infrastructure; Failure Isolation Principles |
| Refined | Ingestion: validation → ETL → DB; optional Postgres queue only if justified |
| Terminology | "Realtime" → "near-realtime" with latency justification |
| WebSocket | Documented as derived-state distribution, not event sourcing |
| Preserved | MVP → v1.5 → v2.0 progression; APScheduler → Celery upgrade path; `src/jobs/*`, `src/pipelines/*`, `src/orchestration/*` |
