# System Architecture

## Overview

A scalable, event-driven architecture for ingesting TikTok Shop data from multiple sellers, processing it through a unified pipeline, and serving analytics dashboards with real-time and historical insights.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              INGESTION LAYER                                     │
│                                                                                  │
│  ┌──────────────────┐    ┌──────────────────┐    ┌───────────────────────┐      │
│  │  Webhook Receiver │    │  Polling Workers │    │  OAuth/Auth Service   │      │
│  │  (FastAPI)        │    │  (Celery/Workers)│    │  (Token Management)  │      │
│  └────────┬─────────┘    └────────┬─────────┘    └───────────────────────┘      │
│           │                        │                                             │
└───────────┼────────────────────────┼─────────────────────────────────────────────┘
            │                        │
            ▼                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              MESSAGE BUS (Kafka)                                 │
│                                                                                  │
│  Topics: orders | products | inventory | returns | settlements | webhooks.raw    │
│                                                                                  │
└──────┬────────────────┬────────────────────┬────────────────┬───────────────────┘
       │                │                    │                │
       ▼                ▼                    ▼                ▼
┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  ┌──────────────┐
│  OLTP Write │  │  Analytics  │  │  ML Pipeline     │  │  Alerting    │
│  (Postgres) │  │  ETL → DWH  │  │  (Feature Store) │  │  Service     │
└──────┬──────┘  └──────┬──────┘  └────────┬─────────┘  └──────┬───────┘
       │                │                   │                    │
       ▼                ▼                   ▼                    ▼
┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  ┌──────────────┐
│  PostgreSQL │  │  ClickHouse │  │  ML Model Store  │  │  Notification│
│             │  │  / BigQuery │  │  (Predictions)   │  │  (Email/SMS) │
└──────┬──────┘  └──────┬──────┘  └────────┬─────────┘  └──────────────┘
       │                │                   │
       └────────────────┼───────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              API LAYER (Backend)                                  │
│                                                                                  │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────────┐       │
│  │  REST API        │    │  GraphQL (opt.)  │    │  WebSocket (live)    │       │
│  │  (Next.js API /  │    │                  │    │  (dashboard updates) │       │
│  │   FastAPI)       │    │                  │    │                      │       │
│  └──────────────────┘    └──────────────────┘    └──────────────────────┘       │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (Next.js)                                   │
│                                                                                  │
│  Dashboard | Analytics Charts | Inventory Alerts | Seller Management            │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Component Breakdown

### 1. Ingestion Layer

#### Webhook Receiver

- **Technology:** FastAPI (Python) or Express (Node.js)
- **Responsibility:** Accept TikTok webhook events, validate signatures, publish to Kafka
- **SLA:** Respond within 3 seconds, process async
- **Scaling:** Horizontal auto-scale behind load balancer

#### Polling Workers

- **Technology:** Celery (Python) or BullMQ (Node.js)
- **Responsibility:** Scheduled data fetching for initial sync, backfill, and gap recovery
- **Schedule:**
  - Orders: Every 15 minutes (incremental by update_time)
  - Products: Every hour
  - Inventory: Every 30 minutes
  - Settlements: Daily
- **Scaling:** Worker count scales with seller count

#### Auth Service

- **Responsibility:** Token storage, refresh scheduling, OAuth flow handling
- **Dependencies:** PostgreSQL (encrypted token storage), Redis (token cache)
- **Jobs:** Daily token refresh, deauthorization handling

### 2. Message Bus (Kafka)

#### Topic Design

| Topic | Key | Partitions | Retention |
|-------|-----|------------|-----------|
| `tiktok.orders.raw` | shop_id | 12 | 7 days |
| `tiktok.products.raw` | shop_id | 6 | 7 days |
| `tiktok.inventory.raw` | shop_id | 6 | 3 days |
| `tiktok.returns.raw` | shop_id | 6 | 7 days |
| `tiktok.settlements.raw` | shop_id | 4 | 30 days |
| `tiktok.webhooks.raw` | shop_id | 12 | 3 days |
| `tiktok.events.dlq` | — | 2 | 30 days |

#### Guarantees

- At-least-once delivery (consumers handle idempotency)
- Ordered within partition (partitioned by shop_id)
- Dead letter queue for poison messages

### 3. Storage Layer

#### PostgreSQL (OLTP)

Primary transactional database for current-state data:

- Seller credentials and shop metadata
- Current order state and line items
- Product catalog (current version)
- Inventory levels
- Customer records (aggregated)

#### ClickHouse / BigQuery (OLAP)

Analytical warehouse for historical queries:

- All historical order events (append-only)
- Time-series sales data (partitioned by day)
- Product performance metrics
- Settlement history
- ML feature tables

#### Redis

- OAuth token cache (7-day TTL)
- Rate limit counters per (app × shop)
- Real-time inventory cache (hot SKUs)
- Session data for dashboard users
- Pub/sub for live dashboard updates

### 4. Processing Layer

#### ETL Pipeline

```
Kafka Consumer → Transform/Enrich → Write to Postgres + ClickHouse
```

- **Deduplication:** Use (entity_id, update_time) composite key
- **Enrichment:** Resolve product names, category paths, currency conversion
- **Validation:** Schema validation before write, reject malformed to DLQ

#### Reconciliation Jobs

- **Daily:** Full order count check (API total vs DB total per shop)
- **Hourly:** Inventory level verification for high-velocity SKUs
- **Weekly:** Product catalog full sync to detect missed updates

### 5. API Layer

Backend APIs serving the dashboard frontend:

| Service | Endpoints | Data Source |
|---------|-----------|-------------|
| Orders API | `/api/orders`, `/api/orders/:id` | PostgreSQL |
| Analytics API | `/api/analytics/revenue`, `/api/analytics/products` | ClickHouse |
| Inventory API | `/api/inventory`, `/api/inventory/alerts` | Redis + PostgreSQL |
| Sellers API | `/api/sellers`, `/api/sellers/:id/connect` | PostgreSQL |
| ML API | `/api/predictions/demand`, `/api/predictions/anomalies` | ML Model Store |

### 6. Frontend Layer

- **Framework:** Next.js with TypeScript
- **Charts:** Recharts or Apache ECharts
- **Real-time:** WebSocket for live order feed
- **Multi-tenant:** Seller selector + scoped views

## Data Flow Sequences

### New Order Flow

```
TikTok (ORDER_STATUS_CHANGE webhook)
    → Webhook Receiver (validate, publish)
    → Kafka topic: tiktok.orders.raw
    → Consumer A: Write to PostgreSQL (orders table)
    → Consumer B: Write to ClickHouse (order_events table)
    → Consumer C: Update Redis cache (daily revenue counter)
    → Consumer D: Check alert rules (large order notification)
    → Dashboard auto-refreshes via WebSocket
```

### Initial Sync Flow (New Seller Onboarded)

```
Seller authorizes app
    → Auth Service stores tokens
    → Trigger full sync job
    → Polling Worker: GET /orders/search (last 90 days)
    → Polling Worker: GET /products/search (all products)
    → Polling Worker: GET /inventory/search (all SKUs)
    → All data → Kafka → DB/Warehouse
    → Dashboard ready for seller
```

## Failure Modes & Mitigation

| Failure | Impact | Mitigation |
|---------|--------|------------|
| Webhook endpoint down | Missed events (TikTok retries ~3x) | Reconciliation job detects gaps; redundant endpoints |
| Kafka broker failure | Message loss or delay | Multi-broker cluster (3+), replication factor 3 |
| PostgreSQL down | Dashboard reads fail | Read replicas, connection pooling, circuit breaker |
| Token expired (missed refresh) | API calls fail for that seller | Aggressive refresh schedule (daily), alert on failures |
| Rate limit exceeded | Delayed data sync | Queue-based throttling, exponential backoff |
| TikTok API outage | All sync stops | Circuit breaker pattern, queue accumulation, resume on recovery |

## Deployment Architecture

```
┌─────────────────────────────────────────────────────┐
│                 Kubernetes Cluster                    │
│                                                      │
│  ┌─────────────┐  ┌────────────┐  ┌──────────────┐ │
│  │ Webhook Svc │  │ Worker Svc │  │ API Svc      │ │
│  │ (3 replicas)│  │ (auto-HPA) │  │ (3 replicas) │ │
│  └─────────────┘  └────────────┘  └──────────────┘ │
│                                                      │
│  ┌─────────────┐  ┌────────────┐  ┌──────────────┐ │
│  │ Auth Svc    │  │ ML Svc     │  │ Alert Svc    │ │
│  │ (2 replicas)│  │ (GPU node) │  │ (2 replicas) │ │
│  └─────────────┘  └────────────┘  └──────────────┘ │
│                                                      │
└─────────────────────────────────────────────────────┘

External Services:
  - AWS RDS (PostgreSQL)
  - AWS MSK (Kafka)
  - ClickHouse Cloud / BigQuery
  - ElastiCache (Redis)
  - S3 (raw event archive)
```

## Observability

- **Logs:** Structured JSON → CloudWatch/ELK
- **Metrics:** Prometheus + Grafana (API latency, queue depth, sync lag)
- **Traces:** OpenTelemetry distributed tracing across services
- **Alerts:** PagerDuty/OpsGenie for P0 failures
