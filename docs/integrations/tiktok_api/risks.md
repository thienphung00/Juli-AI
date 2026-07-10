# Risks & Constraints

Technical and compliance risks for TikTok Shop API integration. Complements
[`platform-docs`](../tiktok_platform/) (seller/creator features and rules) when available.

---

## Risk matrix

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Rate limit throttling (100005) | High | Medium | Redis `RateLimiter`, staggered polling, webhooks |
| Token expiry / deauth | Medium | High | Proactive refresh; stop jobs on auth failure |
| API version / path drift | Medium | High | Pin versions; reconcile `/api/*` vs `/product/202502/*` in P2-1 |
| VP/AHR/withholding fields not exposed in Partner API | High (P2) | High | **P2-1 gate:** verify in Partner Center API Reference + API Testing Tool; implement degraded-mode `health_data_source: api \| proxy \| unavailable`; **no Seller Center scraping** |
| Undocumented Ads endpoints | High (P2) | Medium | Block Growth Copilot live ads until paths scoped |
| Bounded order history (~90d) | High | Medium | Document in UI; long-horizon in Phase 3+ vendor data |
| Settlement lag 7–14d | High | Low | `pending` status; out of P2 core |
| Affiliate scope denial | Medium | Medium | Re-consent UX; do not block orders/products sync |
| Webhook catalog incomplete | Medium | Medium | Polling reconciliation every 15 min minimum |
| Policy / ToS change | Medium | Medium | `platform-docs` refresh; changelog monitoring |
| Buyer PII exposure | Low | Critical | Masked `buyer_id` only (#17) |

---

## Forbidden patterns

| Pattern | Why | `data-sources.md` |
|---------|-----|-------------------|
| Seller Center scraping | Account suspension | #9 |
| In-stream unofficial websockets | ToS + breakage | #8 |
| Buyer PII / DM storage | Privacy | #17 |
| TikTok for Business API without Shop doc citation | Wrong API surface | UNVERIFIED |

---

## Known API gaps

| Want | Reality | Substitute |
|------|---------|------------|
| Realtime live viewers / gifts | No safe API | Post-stream summaries only (out of P2 core) |
| Ads performance (P2) | Client not built | Implement after official Ads paths confirmed |
| Full order schema in docs | Not extracted this pass | Partner Center API Reference per field |
| Exact rate limit numbers | Not public | Calibrate from `100005` + headers |
| Complete webhook event list | Not extracted | Partner Center webhook registration UI |
| Numeric seller health scores (VP/AHR) | **UNKNOWN** until P2-1 verification | Use account-health API if exposed; else compute proxies; else surface “unavailable” (never fabricate) |

---

## Version discrepancy (action required P2-1)

Official SDK uses versioned paths (e.g. `ProductV202502`, `AuthorizationV202309`).
Deployed client uses unversioned `/api/products/search`, `/api/orders/search`, etc.

**Action:** During P2-1, diff client paths against Partner Center API Reference;
migrate to current versioned paths or confirm alias behavior with API Testing Tool.

**Source:** [integrate-java-sdk](https://partner.tiktokshop.com/docv2/page/integrate-java-sdk)

---

## ADR candidates

- [ ] **ADR-005: Webhook-primary vs polling-primary for P2** — EXECUTION.md emphasizes
  polling; webhooks optional until registration proven stable.
- [ ] **ADR-006: API path version migration** — unversioned client paths vs 202502/202309
  official surface.
- [ ] **ADR-NNN: Degraded health polling (api | proxy | unavailable)** — if VP/AHR are not exposed,
  Juli must degrade explicitly (no fabricated numbers) and never scrape Seller Center. See
  [`docs/architecture/data-sources.md`](../architecture/data-sources.md) + [`endpoints.md`](endpoints.md).
- [ ] **ADR-NNN: Alert on VP/AHR vs silent degradation** — VP/AHR milestone hits block affiliate
  enrollment; Juli must surface immediately when provable. See [`docs/integrations/tiktok_platform/risks.md`](../tiktok_platform/risks.md).
- [ ] **ADR-NNN: Dual-system health-check during VP → AHR transition** — AHR replaces VP
  in July 2026; Phase 2 (Weeks 9–13) overlaps; requires feature-flagged dual-read logic.
- [ ] **ADR-NNN: VN-specific regional config** — CHR thresholds, tax code KYC, 1k follower
  threshold differ from other markets; need per-market config, not hardcoded globals.
