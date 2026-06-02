# Technical & Competitive Risks

## Risk Summary Matrix

| Risk | Probability | Impact | Severity | Mitigation |
|------|-------------|--------|----------|------------|
| Rate limit throttling | High | Medium | High | Queue-based throttling, webhooks-first |
| Token expiry/deauth | Medium | High | High | Aggressive refresh, monitoring |
| API breaking changes | Medium | High | High | Version pinning, abstraction layer |
| Data consistency gaps | High | Medium | Medium | Reconciliation jobs, idempotent writes |
| TikTok policy changes | Medium | Medium | Medium | Changelog monitoring, flexible schema |
| Competitor launch | Medium | Low | Low | Differentiate with AI/UX |
| Security breach | Low | Critical | High | Encryption, isolation, audit trails |
| Regional regulatory changes | Medium | Medium | Medium | Region-aware processing, config-driven |

---

## Technical Risks

### 1. Rate Limiting & Throttling

**Risk:** With 1000+ sellers, aggregate API calls exceed TikTok's per-app or per-shop limits, causing 429 errors and data sync delays.

**Impact:** Delayed or missing data, stale dashboards, missed SLA alerts.

**Mitigation:**
- Webhooks-first architecture (minimize polling)
- Redis token bucket per (app × shop × endpoint)
- Priority queue: critical operations (ship confirm) > sync > backfill
- Adaptive polling: reduce frequency for low-activity shops
- Monitor 429 rate; alert if > 1%

### 2. Token Lifecycle Failures

**Risk:** Access tokens expire without refresh, or sellers deauthorize without notice, breaking data sync.

**Impact:** Complete data loss for affected sellers until re-authorization.

**Mitigation:**
- Refresh tokens daily (5 days before expiry)
- Monitor `UPCOMING_AUTHORIZATION_EXPIRATION` webhook (30-day warning)
- Handle `SELLER_DEAUTHORIZATION` immediately (stop jobs, notify)
- Health check: verify token validity before each sync cycle
- User-facing banner when re-auth is needed

### 3. API Breaking Changes

**Risk:** TikTok updates API versions, deprecates endpoints, or changes response schemas without adequate notice.

**Impact:** Service disruption, data parsing failures, incorrect analytics.

**Mitigation:**
- Abstract TikTok API behind a service layer (easy to update one place)
- Store raw API responses as JSONB for reprocessing
- Pin to specific API version; upgrade deliberately
- Monitor TikTok Partner Center changelog weekly
- Integration test suite against API mocks (update when schema changes)
- Feature flags to roll back to previous behavior

### 4. Data Consistency & Gaps

**Risk:** Webhook deliveries missed during downtime, out-of-order events, or delayed settlement data create inconsistencies.

**Impact:** Incorrect dashboard metrics, wrong inventory levels, missed orders.

**Mitigation:**
- Reconciliation jobs (hourly order count check, daily inventory full sync)
- Idempotent database writes (upsert on entity_id + update_time)
- Use `update_time_from` filters to detect gaps
- Out-of-order resolution: only apply updates with newer timestamps
- Settlement data: expect 7-14 day lag; mark as "pending" until confirmed

### 5. Webhook Reliability

**Risk:** TikTok's webhook delivery fails (their infra issue), or our endpoint is unreachable during deploys.

**Impact:** Missed events, data gaps until next poll cycle.

**Mitigation:**
- Zero-downtime deployments (rolling updates)
- Multiple webhook endpoint replicas behind load balancer
- Reconciliation polling as fallback (every 15 minutes)
- Dead letter queue for unprocessable events
- Alert on webhook volume drops (expect N events/hour; alert if < 50% of norm)

### 6. Regional Complexity

**Risk:** Fee structures, tax calculations, and settlement fields vary by market; incorrect handling produces wrong profit calculations.

**Impact:** Misleading financial data, seller distrust.

**Mitigation:**
- Region-aware calculation engine (config-driven per market)
- Unit tests per region for fee/settlement calculations
- Document known regional differences in code and this doc
- Flag fields that don't apply universally (e.g., "revenue" excludes tax in US/UK)
- Validate against actual settlement payouts

### 7. Scalability Bottlenecks

**Risk:** System can't handle peak loads (holiday sales, flash events) or 10,000+ sellers.

**Impact:** Delayed processing, dashboard timeouts, webhook acknowledgment failures.

**Mitigation:**
- Horizontal scaling: Kubernetes HPA on all services
- In-process ETL handoff with per-shop backpressure; optional Postgres queue if spikes justify
- ClickHouse/BigQuery for heavy analytics (don't query OLTP for dashboards)
- Connection pooling (PgBouncer) for PostgreSQL
- CDN for frontend assets
- Load test before peak seasons (simulate 10x normal traffic)

---

## Security Risks

### 8. Credential Breach

**Risk:** Stored OAuth tokens or App Secret is compromised, giving attacker access to all seller data.

**Impact:** Critical — full data breach, regulatory consequences.

**Mitigation:**
- Encrypt tokens at rest (AES-256 via KMS)
- App Secret in environment variables / secrets manager (never in code)
- Rotate App Secret periodically (requires TikTok Partner Center)
- Least-privilege DB access (services only read their own tokens)
- Audit logs for all token access
- Per-shop worker isolation (compromised shop doesn't affect others)

### 9. Seller Data Isolation Failure

**Risk:** A bug allows one seller to see another's data (multi-tenant leak).

**Impact:** Data breach, trust loss, potential legal liability.

**Mitigation:**
- All queries scoped by shop_id (enforced at ORM/query layer)
- Row-level security in PostgreSQL as defense-in-depth
- Integration tests verifying cross-tenant isolation
- API middleware validates shop_id ownership before serving data
- Penetration testing focused on tenant boundaries

### 10. Webhook Spoofing

**Risk:** Attacker sends fake webhook events to our endpoint, injecting false data.

**Impact:** Corrupted data, incorrect analytics, potential automated actions on false data.

**Mitigation:**
- Verify HMAC signature on every webhook (reject unsigned)
- Validate event structure against expected schema
- Cross-reference critical events with API (e.g., verify order exists before processing)
- Rate limit webhook endpoint by IP
- Log and alert on signature verification failures

---

## Competitive Risks

### 11. Market Landscape

**Current State:** The TikTok Shop analytics market is nascent. Few established vendors exist.

| Competitor Type | Examples | Strengths | Weaknesses |
|----------------|----------|-----------|------------|
| Multi-channel integrators | Shoplazza, ChannelAdvisor | Broad platform support | Shallow TikTok-specific features |
| 3PL platforms | Warpspeed, ShipBob | Fulfillment focus | Limited analytics |
| TikTok native tools | Seller Center analytics | Free, built-in | Basic, no AI, no cross-platform |
| Custom solutions | In-house dev teams | Tailored | Expensive, slow to build |

**Our Differentiation:**
- Unified analytics + AI predictions (not just data display)
- Multi-shop management with cross-border support
- Proactive alerts and recommendations (not reactive reporting)
- Fast time-to-value (connect and see insights in minutes)

### 12. TikTok Building Native Features

**Risk:** TikTok builds similar analytics into Seller Center, reducing need for third-party tools.

**Impact:** Reduced value proposition for basic analytics features.

**Mitigation:**
- Focus on advanced features TikTok won't build (AI forecasting, cross-platform)
- Build deep workflow integrations (auto-fulfill, 3PL sync)
- Provide superior UX compared to Seller Center
- Offer multi-platform view (TikTok + Shopee + Lazada)
- Enterprise/agency features TikTok won't prioritize

---

## Operational Risks

### 13. Data Gaps (Unavailable via API)

Known data not available through TikTok Shop Partner API:

| Desired Data | Availability | Workaround |
|-------------|-------------|------------|
| Livestream detailed metrics | Not in Shop API | Infer from order timestamps; request Creator API access |
| Ad campaign performance | Separate TikTok Ads API | Integrate TikTok Marketing API later |
| Product page views | Not available | Cannot compute true conversion rate |
| Source of traffic | Limited | Use affiliate codes as proxy |
| Buyer contact details | Masked (privacy) | Only buyer_id for retention analysis |
| Competitor pricing | Not available | Manual or third-party scraping tools |

### 14. TikTok Platform Availability

**Risk:** TikTok Shop banned or restricted in certain markets (e.g., US regulatory concerns).

**Impact:** Entire market segment becomes unavailable.

**Mitigation:**
- Multi-platform strategy (don't depend solely on TikTok)
- Phase 3 adds Shopee, Lazada, Shopify connectors
- Modular architecture makes platform-agnostic core easy
- Monitor regulatory news; have contingency communication plan

### 15. Team & Knowledge Risks

**Risk:** TikTok API expertise is niche; losing a key developer creates knowledge gap.

**Impact:** Slower bug resolution, integration maintenance challenges.

**Mitigation:**
- Comprehensive documentation (this folder)
- Pair programming on critical integrations
- Abstract TikTok specifics behind clean interfaces
- Integration test suite as living documentation
- On-call runbook for common TikTok API issues
