# TikTok Shop Partner API — Documentation Index

Reference documentation for integrating with the TikTok Shop Partner API (TTS API). This folder contains implementation-ready specs derived from official documentation and integration research.

## Quick Reference

| Property | Value |
|----------|-------|
| API Style | RESTful JSON |
| Auth | OAuth 2.0 + HMAC-SHA256 request signing |
| Access Token TTL | 7 days |
| Refresh Token TTL | ~2 months |
| Rate Limits | Per (app_id × shop_id) pair |
| Regions | US, UK, SEA (TH, VN, MY, PH, SG, ID) |
| Partner Center | https://partner.tiktokshop.com |

## Documents

| Document | Description |
|----------|-------------|
| [authentication.md](authentication.md) | OAuth2 flow, token lifecycle, HMAC signing |
| [endpoints.md](endpoints.md) | API categories, key endpoints, data models |
| [webhooks.md](webhooks.md) | Event types, payload handling, registration |
| [rate-limits.md](rate-limits.md) | Throttling strategy, quotas, backoff |
| [multi-tenant.md](multi-tenant.md) | Multi-shop/seller architecture, cross-border |
| [architecture.md](architecture.md) | System design, data flow, infrastructure |
| [dashboard-features.md](dashboard-features.md) | Core analytics and dashboard capabilities |
| [ai-analytics.md](ai-analytics.md) | ML/predictive analytics opportunities |
| [mvp-roadmap.md](mvp-roadmap.md) | Phased implementation plan |
| [risks.md](risks.md) | Technical, competitive, and policy risks |
| [tech-stack.md](tech-stack.md) | Technology recommendations and schema |

## Architecture Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  TikTok Shop    │────▶│  Ingestion Layer │────▶│  Message Queue  │
│  Partner API    │     │  (Webhooks +     │     │  src/etl        │
│                 │◀────│   Pollers)       │     │                 │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                         ┌────────────────────────────────┼───────────┐
                         │                                │           │
                         ▼                                ▼           ▼
                  ┌──────────────┐              ┌──────────────┐  ┌──────┐
                  │  PostgreSQL  │              │  ClickHouse/ │  │ Redis│
                  │  (OLTP)      │              │  BigQuery    │  │      │
                  └──────┬───────┘              └──────┬───────┘  └──────┘
                         │                             │
                         ▼                             ▼
                  ┌──────────────────────────────────────────┐
                  │         Next.js Dashboard (Frontend)      │
                  └──────────────────────────────────────────┘
```

## Prerequisites for Implementation

1. Register as ISV in TikTok Shop Partner Center
2. Create an App (custom or public) — obtain App Key + App Secret
3. Configure redirect URI for OAuth flow
4. Enable required API scopes (Shop Authorization, Product, Order, etc.)
5. Register webhook URLs for near-realtime events (v2.0) / low-latency push (v1.5 handoff)

## Related Resources

- [TikTok Shop Partner Center](https://partner.tiktokshop.com)
- [TikTok Shop Open API Docs](https://partner.tiktokshop.com/docv2/page)
- [OAuth 2.0 Authorization Guide](https://partner.tiktokshop.com/docv2/page/6507ead7b99d5302be949ba9)
