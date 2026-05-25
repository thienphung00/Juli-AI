# Technology Recommendations & Database Schema

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
| Real-time | WebSocket (Socket.io) | Live order feed, dashboard updates |

### Data Layer

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Primary DB | PostgreSQL 16+ | ACID, JSONB, row-level security, mature |
| Analytics DB | ClickHouse or BigQuery | Columnar, fast aggregations, time-series |
| Cache | Redis 7+ | Tokens, rate limits, hot data |
| Message Queue | Apache Kafka (or Redpanda) | Event streaming, durability, replay |
| Object Storage | S3 / GCS | Raw event archive, ML artifacts |

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
| Orchestration | Kubernetes (EKS/GKE) | Auto-scaling, service mesh |
| IaC | Terraform | Reproducible infrastructure |
| CI/CD | GitHub Actions | Automated testing and deployment |
| Monitoring | Prometheus + Grafana | Metrics and alerting |
| Logging | ELK Stack or CloudWatch | Centralized structured logs |
| Tracing | OpenTelemetry + Jaeger | Distributed request tracing |
| Secrets | AWS Secrets Manager / Vault | Encrypted credential storage |

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
    │  - Token mgmt │  │  - Analytics │  │  - Publish    │
    │  - Refresh    │  │  - CRUD      │  │  - ACK        │
    └───────────────┘  └──────────────┘  └───────────────┘
            │                  │                  │
            └──────────────────┼──────────────────┘
                               │
    ┌──────────────────────────┼──────────────────────────┐
    │                    Kafka / Event Bus                  │
    └──────┬───────────────────┼──────────────────┬───────┘
           │                   │                  │
    ┌──────▼───────┐  ┌───────▼──────┐  ┌───────▼───────┐
    │  Sync Worker │  │  ETL Worker  │  │  ML Service   │
    │              │  │              │  │               │
    │  - Polling   │  │  - Transform │  │  - Forecast   │
    │  - Backfill  │  │  - Enrich    │  │  - Anomaly    │
    │  - Reconcile │  │  - Load DWH  │  │  - Score      │
    └──────────────┘  └──────────────┘  └───────────────┘
```

### Inter-Service Communication

| Pattern | Use Case |
|---------|----------|
| Async (Kafka) | Data ingestion, ETL, non-urgent processing |
| Sync (HTTP/gRPC) | Dashboard queries, user-facing actions |
| Pub/Sub (Redis) | Real-time dashboard updates, cache invalidation |
| Cron (Scheduler) | Token refresh, reconciliation, ML training |

---

## Deployment Configuration

### Environment Tiers

| Environment | Purpose | Infrastructure |
|-------------|---------|---------------|
| Development | Local development | Docker Compose (all services) |
| Staging | Integration testing | Kubernetes (reduced replicas) |
| Production | Live service | Kubernetes (full HA) |

### Docker Compose (Development)

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: tiktok_analytics
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  kafka:
    image: confluentinc/cp-kafka:7.5.0
    ports: ["9092:9092"]
    environment:
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092

  api:
    build: ./services/api
    ports: ["3000:3000"]
    depends_on: [postgres, redis]
    environment:
      DATABASE_URL: postgresql://postgres:${DB_PASSWORD}@postgres:5432/tiktok_analytics
      REDIS_URL: redis://redis:6379

  webhook:
    build: ./services/webhook
    ports: ["8080:8080"]
    depends_on: [kafka, redis]

  worker:
    build: ./services/worker
    depends_on: [kafka, postgres, redis]

volumes:
  pgdata:
```

### Production Kubernetes (Key Resources)

| Resource | Replicas | CPU | Memory | Auto-scale |
|----------|----------|-----|--------|------------|
| API Service | 3 | 500m-2000m | 512Mi-2Gi | HPA (CPU 70%) |
| Webhook Receiver | 3 | 250m-1000m | 256Mi-1Gi | HPA (CPU 60%) |
| Sync Workers | 2-10 | 500m-2000m | 512Mi-2Gi | KEDA (queue depth) |
| ETL Workers | 2-5 | 1000m-4000m | 1Gi-4Gi | KEDA (Kafka lag) |
| ML Service | 1-2 | 2000m-8000m | 4Gi-16Gi | Manual |
