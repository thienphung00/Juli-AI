# Technology Recommendations & Database Schema

> **Juli-AI canonical phases:** See [`migration_path.md`](../../migration_path.md).
> **v1.5:** Webhook/polling → validation → `src/etl` → Supabase Postgres (no Redis/Celery).
> **v2.0:** Adds Redis + Celery + near-realtime WebSocket (derived state only).

## Recommended Tech Stack

### Backend Services

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| API Framework | FastAPI (Python) or Next.js API Routes | FastAPI for ML-heavy services; Next.js for dashboard backend |
| Task Queue | Celery + Redis (Python) or BullMQ (Node.js) | Distributed job processing with retry logic |
| HTTP Client | httpx (Python) or axios (Node.js) | Async HTTP for TikTok API calls |
| Auth Library | Custom OAuth2 service | TikTok-specific flow (HMAC + OAuth) |

### Frontend

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Framework | Next.js 14+ (App Router) | SSR, API routes, TypeScript |
| UI Library | Tailwind CSS + shadcn/ui | Modern, customizable components |
| Charts | Recharts or Apache ECharts | Rich analytics visualizations |
| State | Zustand or TanStack Query | Server state caching + client state |
| Near-realtime (v2.0) | WebSocket | Live dashboard updates via Redis pub/sub (derived state) |

### Data Layer

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Primary DB | PostgreSQL 16+ | ACID, JSONB, row-level security, mature |
| Analytics DB | ClickHouse or BigQuery | Columnar, fast aggregations, time-series |
| Cache | Redis 7+ (v2.0) | Celery broker, pub/sub, rate limits — **not in v1.5** |
| Ingest handoff | In-process `HandoffFn` → `EtlConsumer` (v1.5) | Validation → ETL → Postgres; optional Postgres queue if spikes justify |
| Object Storage | Cloudflare R2 / S3 | Raw event archive, ML artifacts |

### AI/ML

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Training | Python 3.11+, scikit-learn, XGBoost, Prophet | Standard ML stack |
| Deep Learning | PyTorch (if needed) | LSTM, transformer models |
| Orchestration | Airflow or Prefect | Scheduled training/prediction jobs |
| Model Serving | FastAPI microservice | Low-latency prediction API |
| Experiment Tracking | MLflow | Model versioning, comparison |
| Feature Store | Feast or custom (Redis + PG) | Consistent features for train/serve |

### Infrastructure

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Container Runtime | Docker | Standardized builds |
| Hosting (v1.5) | Railway / Fly.io + Vercel | API, workers, web — no Kubernetes required at current scale |
| CI/CD | GitHub Actions | Automated testing and deployment |
| Monitoring | Sentry (+ optional Prometheus in v2.0) | Errors; queue depth when Celery is enabled |
| Logging | Structured JSON (platform logs) | Correlation across webhook → ETL → DB |
| Secrets | Environment / platform secret stores | Never commit credentials |

---

## Database Schema

### PostgreSQL (OLTP) — Core Tables

#### Sellers & Shops

```sql
CREATE TABLE sellers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_user_id VARCHAR(128) NOT NULL UNIQUE,
    email           VARCHAR(256),
    name            VARCHAR(256),
    status          VARCHAR(16) DEFAULT 'active',
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE shops (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seller_id       UUID NOT NULL REFERENCES sellers(id),
    tiktok_shop_id  VARCHAR(64) NOT NULL UNIQUE,
    shop_cipher     VARCHAR(128),
    shop_name       VARCHAR(256),
    region          VARCHAR(8) NOT NULL,
    seller_type     VARCHAR(16) NOT NULL,  -- 'local' | 'cross_border'
    currency        VARCHAR(3) NOT NULL,
    access_token    TEXT NOT NULL,
    refresh_token   TEXT NOT NULL,
    token_expires_at    TIMESTAMP NOT NULL,
    refresh_expires_at  TIMESTAMP NOT NULL,
    scopes          JSONB,
    sync_status     VARCHAR(16) DEFAULT 'pending',  -- 'pending' | 'syncing' | 'active' | 'paused' | 'revoked'
    last_sync_at    TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_shops_seller ON shops(seller_id);
CREATE INDEX idx_shops_region ON shops(region);
CREATE INDEX idx_shops_sync_status ON shops(sync_status);
CREATE INDEX idx_shops_token_expiry ON shops(token_expires_at);
```

#### Products

```sql
CREATE TABLE products (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id         UUID NOT NULL REFERENCES shops(id),
    tiktok_product_id VARCHAR(64) NOT NULL,
    title           VARCHAR(512) NOT NULL,
    description     TEXT,
    category_id     VARCHAR(64),
    category_name   VARCHAR(256),
    brand_id        VARCHAR(64),
    brand_name      VARCHAR(256),
    status          VARCHAR(32),  -- 'ACTIVE' | 'INACTIVE' | 'DRAFT' | 'SUSPENDED'
    images          JSONB,
    attributes      JSONB,
    package_weight_kg DECIMAL(8, 3),
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP,
    synced_at       TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(shop_id, tiktok_product_id)
);

CREATE INDEX idx_products_shop ON products(shop_id);
CREATE INDEX idx_products_status ON products(shop_id, status);
CREATE INDEX idx_products_category ON products(shop_id, category_id);

CREATE TABLE product_skus (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID NOT NULL REFERENCES products(id),
    shop_id         UUID NOT NULL REFERENCES shops(id),
    tiktok_sku_id   VARCHAR(64) NOT NULL,
    seller_sku      VARCHAR(128),
    price_amount    DECIMAL(12, 2),
    price_currency  VARCHAR(3),
    cost_amount     DECIMAL(12, 2),  -- seller-inputted COGS
    sales_attributes JSONB,
    
    UNIQUE(shop_id, tiktok_sku_id)
);

CREATE INDEX idx_skus_product ON product_skus(product_id);
CREATE INDEX idx_skus_shop ON product_skus(shop_id);
```

#### Inventory

```sql
CREATE TABLE inventory (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id         UUID NOT NULL REFERENCES shops(id),
    sku_id          UUID NOT NULL REFERENCES product_skus(id),
    warehouse_id    VARCHAR(64),
    warehouse_name  VARCHAR(256),
    available_qty   INTEGER NOT NULL DEFAULT 0,
    committed_qty   INTEGER NOT NULL DEFAULT 0,
    safety_stock    INTEGER DEFAULT 0,
    lead_time_days  INTEGER DEFAULT 7,
    updated_at      TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(shop_id, sku_id, warehouse_id)
);

CREATE INDEX idx_inventory_shop ON inventory(shop_id);
CREATE INDEX idx_inventory_low_stock ON inventory(shop_id) WHERE available_qty <= safety_stock;
```

#### Orders

```sql
CREATE TABLE orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id         UUID NOT NULL REFERENCES shops(id),
    tiktok_order_id VARCHAR(64) NOT NULL,
    status          VARCHAR(32) NOT NULL,
    payment_status  VARCHAR(32),
    buyer_id        VARCHAR(128),
    buyer_username  VARCHAR(256),
    
    total_amount    DECIMAL(12, 2) NOT NULL,
    shipping_fee    DECIMAL(12, 2) DEFAULT 0,
    platform_discount DECIMAL(12, 2) DEFAULT 0,
    seller_discount DECIMAL(12, 2) DEFAULT 0,
    currency        VARCHAR(3) NOT NULL,
    
    shipping_address JSONB,
    shipping_provider VARCHAR(128),
    tracking_number VARCHAR(128),
    
    order_created_at TIMESTAMP NOT NULL,
    paid_at         TIMESTAMP,
    shipped_at      TIMESTAMP,
    delivered_at    TIMESTAMP,
    cancelled_at    TIMESTAMP,
    
    raw_data        JSONB,
    synced_at       TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(shop_id, tiktok_order_id)
);

CREATE INDEX idx_orders_shop ON orders(shop_id);
CREATE INDEX idx_orders_status ON orders(shop_id, status);
CREATE INDEX idx_orders_created ON orders(shop_id, order_created_at DESC);
CREATE INDEX idx_orders_buyer ON orders(shop_id, buyer_id);

CREATE TABLE order_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES orders(id),
    shop_id         UUID NOT NULL REFERENCES shops(id),
    tiktok_item_id  VARCHAR(64) NOT NULL,
    product_id      UUID REFERENCES products(id),
    sku_id          UUID REFERENCES product_skus(id),
    product_name    VARCHAR(512),
    quantity        INTEGER NOT NULL,
    sale_price      DECIMAL(12, 2) NOT NULL,
    platform_discount DECIMAL(12, 2) DEFAULT 0,
    seller_discount DECIMAL(12, 2) DEFAULT 0,
    currency        VARCHAR(3) NOT NULL
);

CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_order_items_product ON order_items(product_id);
CREATE INDEX idx_order_items_shop ON order_items(shop_id);
```

#### Returns & Refunds

```sql
CREATE TABLE returns (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id         UUID NOT NULL REFERENCES shops(id),
    order_id        UUID REFERENCES orders(id),
    tiktok_return_id VARCHAR(64) NOT NULL,
    status          VARCHAR(32) NOT NULL,
    reason          VARCHAR(256),
    refund_amount   DECIMAL(12, 2),
    currency        VARCHAR(3),
    requested_at    TIMESTAMP,
    resolved_at     TIMESTAMP,
    synced_at       TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(shop_id, tiktok_return_id)
);

CREATE INDEX idx_returns_shop ON returns(shop_id);
CREATE INDEX idx_returns_order ON returns(order_id);
```

#### Settlements & Finance

```sql
CREATE TABLE settlements (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id         UUID NOT NULL REFERENCES shops(id),
    order_id        UUID REFERENCES orders(id),
    tiktok_transaction_id VARCHAR(64),
    settlement_time TIMESTAMP,
    currency        VARCHAR(3) NOT NULL,
    
    gross_revenue   DECIMAL(12, 2),
    platform_commission DECIMAL(12, 2),
    affiliate_commission DECIMAL(12, 2),
    shipping_fee    DECIMAL(12, 2),
    tax             DECIMAL(12, 2),
    adjustment      DECIMAL(12, 2),
    net_amount      DECIMAL(12, 2),
    
    fee_breakdown   JSONB,
    synced_at       TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(shop_id, tiktok_transaction_id)
);

CREATE INDEX idx_settlements_shop ON settlements(shop_id);
CREATE INDEX idx_settlements_time ON settlements(shop_id, settlement_time DESC);
CREATE INDEX idx_settlements_order ON settlements(order_id);
```

#### Affiliates & Campaigns

```sql
CREATE TABLE affiliate_campaigns (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id         UUID NOT NULL REFERENCES shops(id),
    tiktok_campaign_id VARCHAR(64) NOT NULL,
    campaign_name   VARCHAR(256),
    status          VARCHAR(32),
    commission_rate DECIMAL(5, 2),
    start_date      TIMESTAMP,
    end_date        TIMESTAMP,
    synced_at       TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(shop_id, tiktok_campaign_id)
);

CREATE TABLE affiliate_performance (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     UUID REFERENCES affiliate_campaigns(id),
    shop_id         UUID NOT NULL REFERENCES shops(id),
    creator_id      VARCHAR(128),
    creator_name    VARCHAR(256),
    clicks          INTEGER DEFAULT 0,
    conversions     INTEGER DEFAULT 0,
    revenue         DECIMAL(12, 2) DEFAULT 0,
    commission_paid DECIMAL(12, 2) DEFAULT 0,
    period_start    DATE,
    period_end      DATE
);

CREATE INDEX idx_affiliate_perf_shop ON affiliate_performance(shop_id);
CREATE INDEX idx_affiliate_perf_campaign ON affiliate_performance(campaign_id);
```

### ClickHouse (OLAP) — Analytics Tables

```sql
-- Fact table: order events (append-only, partitioned by day)
CREATE TABLE fact_order_events (
    event_time      DateTime,
    shop_id         String,
    order_id        String,
    event_type      String,  -- 'created', 'paid', 'shipped', 'delivered', 'cancelled'
    total_amount    Decimal(12, 2),
    currency        String,
    item_count      UInt32,
    region          String,
    buyer_id        String
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_time)
ORDER BY (shop_id, event_time, order_id);

-- Aggregated daily metrics (materialized view)
CREATE MATERIALIZED VIEW mv_daily_shop_metrics
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (shop_id, date)
AS SELECT
    toDate(event_time) AS date,
    shop_id,
    countIf(event_type = 'created') AS orders_created,
    countIf(event_type = 'paid') AS orders_paid,
    countIf(event_type = 'delivered') AS orders_delivered,
    countIf(event_type = 'cancelled') AS orders_cancelled,
    sumIf(total_amount, event_type = 'paid') AS gmv,
    uniqIf(buyer_id, event_type = 'paid') AS unique_buyers
FROM fact_order_events
GROUP BY date, shop_id;

-- Product performance (daily aggregation)
CREATE TABLE fact_product_sales (
    date            Date,
    shop_id         String,
    product_id      String,
    sku_id          String,
    units_sold      UInt32,
    revenue         Decimal(12, 2),
    returns         UInt32,
    currency        String
) ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (shop_id, date, product_id);

-- Inventory snapshots (daily)
CREATE TABLE fact_inventory_snapshots (
    snapshot_date   Date,
    shop_id         String,
    sku_id          String,
    available_qty   Int32,
    daily_velocity  Float32
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(snapshot_date)
ORDER BY (shop_id, snapshot_date, sku_id)
TTL snapshot_date + INTERVAL 365 DAY;
```

---

## Service Architecture

### Service Boundaries

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Gateway / Load Balancer                │
└───────────┬──────────────────┬──────────────────┬───────────────┘
            │                  │                  │
    ┌───────▼───────┐  ┌──────▼──────┐  ┌───────▼───────┐
    │  Auth Service │  │  API Service │  │  Webhook Svc  │
    │               │  │  (Dashboard) │  │  (Receiver)   │
    │  - OAuth flow │  │  - REST APIs │  │  - Validate   │
    │  - Token mgmt │  │  - Analytics │  │  - Handoff    │
    │  - Refresh    │  │  - CRUD      │  │  - ACK        │
    └───────────────┘  └──────────────┘  └───────────────┘
            │                  │                  │
            └──────────────────┼──────────────────┘
                               │
    ┌──────────────────────────┼──────────────────────────┐
    │         src/etl (validation → dedup → Postgres)       │
    └──────┬───────────────────┼──────────────────┬───────┘
           │                   │                  │
    ┌──────▼───────┐  ┌───────▼──────┐  ┌───────▼───────┐
    │  Polling     │  │  APScheduler │  │  ML (local/   │
    │  workers     │  │  + jobs/*    │  │  batch)       │
    └──────────────┘  └──────────────┘  └───────────────┘
```

### Inter-Service Communication

| Pattern | Phase | Use Case |
|---------|-------|----------|
| In-process handoff | v1.5 | Webhook/polling → `EtlConsumer.ingest` |
| Sync (HTTP) | All | Dashboard queries, user-facing actions |
| Pub/Sub (Redis) | v2.0 | Near-realtime dashboard updates (derived state) |
| Cron (APScheduler → Celery Beat) | v1.5 → v2.0 | Polling, `daily_pipeline`, token refresh |

---

## Deployment Configuration

### Environment Tiers

| Environment | Purpose | Infrastructure |
|-------------|---------|---------------|
| Development | Local development | Docker Compose (Postgres + API + optional Redis for v2.0 experiments) |
| Staging | Integration testing | Railway/Fly preview + Supabase branch |
| Production | Live service | Railway/Fly + Vercel + Supabase (see `migration_path.md`) |

### Docker Compose (Development — v1.5 baseline)

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: juli
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]

  api:
    build: .
    ports: ["8000:8000"]
    depends_on: [postgres]
    environment:
      DATABASE_URL: postgresql://postgres:${DB_PASSWORD}@postgres:5432/juli

  # v2.0 only — Celery broker + pub/sub
  # redis:
  #   image: redis:7-alpine
  #   ports: ["6379:6379"]

volumes:
  pgdata:
```

Wire webhook handoff in-process: `make_etl_handoff(EtlConsumer(...))` — no broker
container required for local ingest tests.

### Production sizing (simple — no Kubernetes in v1.5)

| Component | v1.5 | v2.0 |
|-----------|------|------|
| API + webhook | 1–2 Railway/Fly services | Same + horizontal scale as needed |
| ETL | In-process with API or dedicated worker process | Celery worker pool |
| Scheduler | APScheduler in `src/orchestration/` | Celery Beat |
| Redis | Not used | Broker + pub/sub |
