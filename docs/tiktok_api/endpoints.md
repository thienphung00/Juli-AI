# API Endpoints & Data Models

## Overview

The TikTok Shop Partner API is organized into domain-specific endpoint groups. All endpoints follow the pattern:

```
https://open-api.tiktokglobalshop.com/{path}
```

Base URLs vary by region (US, UK, SEA) — use the seller's region endpoint.

## Endpoint Categories

### Shop & Authorization

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v2/authorized_shop/list` | GET | List all shops authorized to your app |
| `/api/v2/shop/get_authorized_shop` | GET | Get shop details (name, region, status) |

**Key Fields Returned:**
- `shop_id` — Unique shop identifier
- `shop_cipher` — Encrypted ID for cross-border API calls
- `shop_name` — Display name
- `region` — Market code (US, GB, TH, VN, etc.)
- `seller_type` — `local` or `cross_border`

---

### Products & Catalog

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/products/search` | POST | Search/list products with filters |
| `/api/products/details` | GET | Get full product detail by ID |
| `/api/products` | POST | Create a new product listing |
| `/api/products/{id}` | PUT | Update product attributes |
| `/api/products/{id}/inventory` | PUT | Update stock for a product |
| `/api/products/categories` | GET | Get category tree |
| `/api/products/attributes` | GET | Get required attributes for a category |
| `/api/products/brands` | GET | Search/list brands |

**Product Data Model:**

```json
{
  "product_id": "string",
  "title": "string",
  "description": "string (HTML)",
  "category_id": "string",
  "brand_id": "string",
  "status": "ACTIVE | INACTIVE | DRAFT | SUSPENDED",
  "images": [{"url": "string", "width": 0, "height": 0}],
  "skus": [
    {
      "sku_id": "string",
      "seller_sku": "string",
      "price": {"amount": "string", "currency": "string"},
      "stock": {"quantity": 0, "warehouse_id": "string"},
      "sales_attributes": [{"name": "Color", "value": "Red"}]
    }
  ],
  "package_weight": {"value": "string", "unit": "KILOGRAM"},
  "package_dimensions": {"length": "string", "width": "string", "height": "string", "unit": "CENTIMETER"},
  "created_at": 1234567890,
  "updated_at": 1234567890
}
```

---

### Orders & Fulfillment

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/orders/search` | POST | List orders with filters (status, date range) |
| `/api/orders/detail/query` | POST | Get full order details by IDs |
| `/api/orders/{id}/shipping_info` | GET | Get shipping/tracking info |
| `/api/orders/shipment` | POST | Confirm shipment (upload tracking) |
| `/api/orders/{id}/cancel` | POST | Cancel an order |

**Order Data Model:**

```json
{
  "order_id": "string",
  "shop_id": "string",
  "status": "UNPAID | ON_HOLD | AWAITING_SHIPMENT | AWAITING_COLLECTION | IN_TRANSIT | DELIVERED | COMPLETED | CANCELLED",
  "payment_status": "PENDING | PAID",
  "buyer": {
    "buyer_id": "string",
    "username": "string",
    "email": "string (masked)"
  },
  "shipping_address": {
    "name": "string",
    "phone": "string (masked)",
    "address_line": "string",
    "city": "string",
    "state": "string",
    "postal_code": "string",
    "country_code": "string"
  },
  "line_items": [
    {
      "item_id": "string",
      "product_id": "string",
      "sku_id": "string",
      "product_name": "string",
      "quantity": 1,
      "sale_price": "string",
      "platform_discount": "string",
      "seller_discount": "string"
    }
  ],
  "payment": {
    "total_amount": "string",
    "shipping_fee": "string",
    "platform_discount": "string",
    "seller_discount": "string",
    "currency": "string"
  },
  "create_time": 1234567890,
  "update_time": 1234567890,
  "shipping_provider": "string",
  "tracking_number": "string"
}
```

---

### Inventory

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/inventory/search` | POST | Query stock levels by SKU/warehouse |
| `/api/inventory/update` | POST | Update stock quantities |

**Inventory Data Model:**

```json
{
  "sku_id": "string",
  "warehouse_id": "string",
  "available_quantity": 0,
  "committed_quantity": 0,
  "warehouse_name": "string"
}
```

---

### Finance & Settlement

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/finance/settlements/search` | POST | List settlement records |
| `/api/finance/transactions/search` | POST | List transaction details |
| `/api/finance/order/settlement` | GET | Get settlement for specific order |

**Settlement Data Model:**

```json
{
  "order_id": "string",
  "settlement_time": 1234567890,
  "currency": "string",
  "revenue": "string",
  "platform_commission": "string",
  "affiliate_commission": "string",
  "shipping_fee": "string",
  "tax": "string",
  "adjustment": "string",
  "net_amount": "string"
}
```

> **Note:** Some financial fields (like `revenue`) apply to all regions except UK/US where calculation differs.

---

### Affiliate & Creator Marketplace

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/affiliate/campaigns/search` | POST | List affiliate campaigns |
| `/api/affiliate/creators/search` | POST | Search creators for collaboration |
| `/api/affiliate/open_collaboration` | POST | Create open collaboration |

---

### Messaging

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/customer_service/conversations` | GET | List buyer conversations |
| `/api/customer_service/messages` | GET | Get messages in a conversation |
| `/api/customer_service/messages/send` | POST | Send reply to buyer |

---

### Returns & Refunds

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/return_refund/list` | POST | List return/refund requests |
| `/api/return_refund/{id}` | GET | Get return details |
| `/api/return_refund/{id}/approve` | POST | Approve a return |
| `/api/return_refund/{id}/reject` | POST | Reject a return |

## Common Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `page_size` | int | Results per page (max varies, typically 50-100) |
| `page_token` | string | Cursor for pagination (next page) |
| `create_time_from` | int | Unix timestamp filter (inclusive) |
| `create_time_to` | int | Unix timestamp filter (inclusive) |
| `update_time_from` | int | Unix timestamp filter |
| `update_time_to` | int | Unix timestamp filter |
| `sort_by` | string | Sort field |
| `sort_order` | string | `ASC` or `DESC` |

## Error Response Format

```json
{
  "code": 0,
  "message": "Success",
  "request_id": "unique-request-id",
  "data": {}
}
```

Common error codes:
- `0` — Success
- `100001` — Invalid parameter
- `100002` — Unauthorized (token expired or invalid)
- `100003` — Permission denied (missing scope)
- `100004` — Resource not found
- `100005` — Rate limit exceeded
- `100006` — System error (retry)

## Implementation Notes

- All timestamps are Unix epoch (seconds)
- Currency amounts are strings to preserve precision (convert to decimal in your code)
- Masked PII (emails, phones) — you may not get full buyer contact info
- Pagination is cursor-based for most list endpoints (not offset-based)
- Cross-border requests require `shop_cipher` parameter
- Product images use TikTok CDN URLs (may have expiry)
