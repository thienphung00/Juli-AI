# TikTok Shop Partner API — Documentation Index

Implementation-ready reference for the **TikTok Shop Open API** (ISV / developer
integration). Extracted from the official [TikTok Shop Developer Guide](https://partner.tiktokshop.com/docv2/page/tts-developer-guide)
and cross-checked against the deployed client in
`backend/integrations/catalog/domain/integrations/tiktok/`.

**Status:** Net-new docs (2026-06-05). **Refresh** of prior `docs/integrations/tiktok_api/` after
seller-money rescope ([`EXECUTION.md`](../../EXECUTION.md)).

## Quick reference

| Property | Value |
|----------|-------|
| API style | RESTful JSON |
| Base URL | `https://open-api.tiktokglobalshop.com` |
| Auth | OAuth 2.0 (auth code) + HMAC-SHA256 request signing |
| Shop scoping | `shop_cipher` query param + `x-tts-access-token` header on versioned routes |
| Access token TTL | `access_token_expire_in` from token response (tests use 604800s / 7d) |
| Rate limits | Per (app_key × shop) — exact quotas **not publicly documented** |
| Regions | US, UK, SEA (TH, VN, MY, PH, SG, ID) — confirm per shop `region` field |
| Partner portal | [partner.tiktokshop.com](https://partner.tiktokshop.com) |
| API documentation | [Partner Center Documents](https://partner.tiktokshop.com/docv2/page/) |
| Developer guide | [tts-developer-guide](https://partner.tiktokshop.com/docv2/page/tts-developer-guide) |

## API Reference categories

Use the official [Partner Center Documents](https://partner.tiktokshop.com/docv2/page/)
page, then open **API Reference** and select the category below. The category tree is
rendered in Partner Center and may require login for full endpoint details.

| API Reference category | Official location |
|------------------------|-------------------|
| Products | Partner Center Documents → API Reference → Products |
| Promotion | Partner Center Documents → API Reference → Promotion |
| Orders | Partner Center Documents → API Reference → Orders |
| Fulfillment | Partner Center Documents → API Reference → Fulfillment |
| Fulfilled by TikTok (FBT) | Partner Center Documents → API Reference → Fulfilled by TikTok (FBT) |
| Logistics | Partner Center Documents → API Reference → Logistics |
| Return and Refund | Partner Center Documents → API Reference → Return and Refund |
| Finance | Partner Center Documents → API Reference → Finance |
| Analytics | Partner Center Documents → API Reference → Analytics |
| Customer Service | Partner Center Documents → API Reference → Customer Service |
| Customer Engagement | Partner Center Documents → API Reference → Customer Engagement |
| Affiliate Creator | Partner Center Documents → API Reference → Affiliate Creator |
| Affiliate Partner | Partner Center Documents → API Reference → Affiliate Partner |
| Affiliate Seller | Partner Center Documents → API Reference → Affiliate Seller |
| Supply Chain | Partner Center Documents → API Reference → Supply Chain |
| Tools | Partner Center Documents → API Reference → Tools |

## Juli phase alignment

| Phase | TikTok API usage | See |
|-------|------------------|-----|
| **P1** | Mock JSON only — no network | [`EXECUTION.md`](../../EXECUTION.md) pre-MVP |
| **P2-A1 (contract gate)** | API Testing Tool cURL + response status per endpoint | [`contract-collection.md`](contract-collection.md) |
| **P2** | Live polling (Fujiwa read) + sandbox write validation (SANDBOX_VN) | [`EXECUTION.md`](../../EXECUTION.md) P2-A1 |

**Merchant separation:** Production merchant **Fujiwa** (`7658073774813611784`) is read-only.
Sandbox merchant **SANDBOX_VN** (`7658096633384781588`) is write-validation only.
See [`contract-collection.md`](contract-collection.md).

Forbidden permanently: Seller Center scraping (#9), in-stream unofficial websockets (#8),
buyer PII (#17). See [`data-sources.md`](../architecture/data-sources.md).

## Documents

| Document | Description |
|----------|-------------|
| [contract-collection.md](contract-collection.md) | **Fill-in template** — API Testing Tool cURL + response status per endpoint |
| [authentication.md](authentication.md) | OAuth flow, token lifecycle, HMAC signing, scopes |
| [endpoints.md](endpoints.md) | Endpoint inventory, schemas, vendor → Juli mapping |
| [webhooks.md](webhooks.md) | Event delivery, verification, ACK window |
| [rate-limits.md](rate-limits.md) | Throttling model, backoff, per-shop buckets |
| [architecture.md](architecture.md) | Data flow mapped to `backend/` modules |
| [multi-tenant.md](multi-tenant.md) | Per-shop credentials, `shop_cipher`, isolation |
| [risks.md](risks.md) | API gaps, policy risk, version drift |
| [tech-stack.md](tech-stack.md) | Client boundaries, env vars, persistence touchpoints |
| [context-plan.md](context-plan.md) | `focus` skill load list per task type |
| [integration-audit-2026-06.md](integration-audit-2026-06.md) | Full Partner API integration audit + remediation status |
| [samples/README.md](samples/README.md) | Live API response capture workflow |

## Official links

| Resource | URL |
|----------|-----|
| API documentation (index) | https://partner.tiktokshop.com/docv2/page/ |
| Developer guide | https://partner.tiktokshop.com/docv2/page/tts-developer-guide |
| Products API overview | https://partner.tiktokshop.com/docv2/page/products-api-overview |
| Search inventory | https://partner.tiktokshop.com/docv2/page/search-inventory-202309 |
| Update inventory | https://partner.tiktokshop.com/docv2/page/update-inventory-202309 |
| Get authorized shops | https://partner.tiktokshop.com/docv2/page/call-get-authorized-shops |
| Sign API requests | https://partner.tiktokshop.com/docv2/page/sign-your-api-request |
| API entity tags | https://partner.tiktokshop.com/docv2/page/api-entity-tags |
| Java SDK integration | https://partner.tiktokshop.com/docv2/page/integrate-java-sdk |
| Node.js SDK integration | https://partner.tiktokshop.com/docv2/page/integrate-node-js-sdk |
| API Reference categories | Partner Center Documents → API Reference (see category table above) |
| API Testing Tool | Partner Center → Documents → API Testing Tool |

## Prerequisites (ISV onboarding)

1. Register as ISV in [TikTok Shop Partner Center](https://partner.tiktokshop.com).
2. Create an App — obtain **App Key** + **App Secret** (Console → App & Service).
3. Configure OAuth **redirect URI**.
4. Request API scopes per resource (Affiliate scopes need per-seller approval).
5. Create or link a **test seller account** for sandbox calls.
6. Register webhook URL in Partner Center (production).
