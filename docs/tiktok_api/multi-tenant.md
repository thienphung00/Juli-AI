# Multi-Tenant & Multi-Shop Architecture

## Overview

The TikTok Shop Partner API is inherently multi-tenant: one partner app serves multiple sellers, each with their own shops, credentials, and data. The system must isolate data, manage credentials per tenant, and handle regional variations.

## Seller & Shop Hierarchy

```
Partner App (your app)
├── Seller A (local, Thailand)
│   └── Shop A1 (TH market)
├── Seller B (cross-border)
│   ├── Shop B1 (US market)
│   ├── Shop B2 (UK market)
│   └── Shop B3 (TH market)
└── Seller C (local, US)
    └── Shop C1 (US market)
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| Seller | A merchant account on TikTok Shop |
| Shop | A specific storefront in a market/region |
| Local seller | Sells in one country only |
| Cross-border seller | Sells from one origin to multiple destination markets |
| `shop_id` | Unique numeric shop identifier |
| `shop_cipher` | Encrypted shop ID required for cross-border API calls |
| `open_id` | Seller's unique ID in your app context |

## Credential Management

### Per-Seller Token Storage

```sql
CREATE TABLE seller_credentials (
    id              UUID PRIMARY KEY,
    seller_open_id  VARCHAR(64) NOT NULL UNIQUE,
    shop_id         VARCHAR(64) NOT NULL,
    shop_cipher     VARCHAR(128),
    shop_name       VARCHAR(256),
    region          VARCHAR(8) NOT NULL,
    seller_type     VARCHAR(16) NOT NULL,  -- 'local' | 'cross_border'
    access_token    TEXT NOT NULL,          -- encrypted
    refresh_token   TEXT NOT NULL,          -- encrypted
    token_expires_at    TIMESTAMP NOT NULL,
    refresh_expires_at  TIMESTAMP NOT NULL,
    scopes          JSONB,
    status          VARCHAR(16) DEFAULT 'active',  -- 'active' | 'expired' | 'revoked'
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_credentials_status ON seller_credentials(status);
CREATE INDEX idx_credentials_token_expiry ON seller_credentials(token_expires_at);
```

### Token Refresh Scheduler

```python
async def refresh_expiring_tokens():
    """Run daily — refresh tokens expiring within 2 days."""
    expiring = await db.fetch_all(
        "SELECT * FROM seller_credentials WHERE status = 'active' AND token_expires_at < NOW() + INTERVAL '2 days'"
    )
    
    for seller in expiring:
        try:
            new_tokens = await tiktok_client.refresh_token(seller.refresh_token)
            await db.update_tokens(seller.id, new_tokens)
        except RefreshTokenExpired:
            await db.mark_status(seller.id, "expired")
            await notify_seller_reauth_needed(seller)
```

## Cross-Border Handling

Cross-border sellers have multiple shops (one per destination market). API calls must include the correct `shop_cipher` to target the right shop.

### Request Routing

```python
async def call_tiktok_api(seller_id: str, shop_id: str, endpoint: str, params: dict):
    credential = await get_credential(seller_id, shop_id)
    
    if credential.seller_type == "cross_border":
        params["shop_cipher"] = credential.shop_cipher
    
    params["app_key"] = APP_KEY
    params["timestamp"] = int(time.time())
    params["access_token"] = decrypt(credential.access_token)
    params["sign"] = sign_request(APP_SECRET, endpoint, params)
    
    return await http_client.get(BASE_URL + endpoint, params=params)
```

### Shop Discovery After Auth

After a seller authorizes your app, fetch all their shops:

```python
async def discover_shops(access_token: str) -> list[Shop]:
    """Fetch authorized shops to learn which markets the seller operates in."""
    response = await tiktok_client.get_authorized_shops(access_token)
    return [
        Shop(
            shop_id=s["shop_id"],
            shop_cipher=s.get("shop_cipher"),
            shop_name=s["shop_name"],
            region=s["region"],
            seller_type=s["seller_type"]
        )
        for s in response["data"]["shops"]
    ]
```

## Data Isolation

### Database-Level Isolation

Every data table includes `shop_id` as a mandatory foreign key:

```sql
CREATE TABLE orders (
    order_id        VARCHAR(64) PRIMARY KEY,
    shop_id         VARCHAR(64) NOT NULL REFERENCES seller_credentials(shop_id),
    status          VARCHAR(32),
    total_amount    DECIMAL(12, 2),
    currency        VARCHAR(3),
    -- ...
    created_at      TIMESTAMP
);

CREATE INDEX idx_orders_shop ON orders(shop_id);
CREATE INDEX idx_orders_shop_created ON orders(shop_id, created_at DESC);
```

### Query Scoping

All queries must be scoped to a shop:

```python
async def get_orders(shop_id: str, filters: OrderFilters) -> list[Order]:
    query = "SELECT * FROM orders WHERE shop_id = $1"
    params = [shop_id]
    
    if filters.status:
        query += " AND status = $2"
        params.append(filters.status)
    
    return await db.fetch_all(query, *params)
```

### Row-Level Security (PostgreSQL)

For additional protection:

```sql
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

CREATE POLICY shop_isolation ON orders
    USING (shop_id = current_setting('app.current_shop_id'));
```

## Regional Variations

### Market-Specific Configuration

| Region | Currency | Tax Handling | FBT Available | Settlement Notes |
|--------|----------|-------------|---------------|-----------------|
| US | USD | Platform-collected | Yes | Revenue field excludes tax |
| UK | GBP | Platform-collected | No | Revenue field excludes tax |
| TH | THB | Seller-managed | No | Shipping included in settlement |
| VN | VND | Seller-managed | No | Shipping included in settlement |
| MY | MYR | Mixed | No | Standard settlement |
| SG | SGD | Platform-collected | No | Standard settlement |
| ID | IDR | Seller-managed | No | Standard settlement |
| PH | PHP | Seller-managed | No | Standard settlement |

### Region-Aware Processing

```python
def calculate_net_revenue(order: Order, shop: Shop) -> Decimal:
    """Net revenue calculation varies by region."""
    if shop.region in ("US", "GB"):
        # Tax is platform-collected, not in seller revenue
        return order.total_amount - order.platform_commission - order.affiliate_commission
    elif shop.region in ("TH", "VN"):
        # Shipping is included in settlement for SEA local sellers
        return order.total_amount - order.platform_commission - order.shipping_fee_subsidy
    else:
        return order.total_amount - order.platform_commission
```

## Onboarding Flow

```
1. Seller clicks "Connect TikTok Shop" in your platform
2. Redirect to TikTok OAuth with your app_key + redirect_uri
3. Seller logs in and grants scopes
4. TikTok redirects back with auth_code
5. Exchange auth_code for tokens
6. Call /authorized_shop/list to discover shops
7. Store credentials + shop metadata
8. Trigger initial data sync (orders, products, inventory)
9. Register webhook subscriptions for this shop
10. Seller sees their dashboard
```

## Deauthorization Handling

When a seller revokes access:

1. Receive `SELLER_DEAUTHORIZATION` webhook
2. Mark credentials as `revoked` in DB
3. Stop all sync jobs for that shop
4. Retain historical data (don't delete) for audit
5. Show "disconnected" status in UI with re-connect option

## Scaling Considerations

| Sellers | Architecture Approach |
|---------|----------------------|
| 1-100 | Single worker, sequential processing |
| 100-1000 | Worker pool with per-shop queues |
| 1000-10000 | Distributed workers (Kubernetes), partitioned by shop_id |
| 10000+ | Dedicated microservice per region, sharded DB |

### Worker Assignment

```python
# Partition sellers across workers using consistent hashing
def get_worker_for_shop(shop_id: str, num_workers: int) -> int:
    return int(hashlib.md5(shop_id.encode()).hexdigest(), 16) % num_workers
```
