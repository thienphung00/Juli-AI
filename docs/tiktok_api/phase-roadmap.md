# Phase Roadmap

TikTok API rollout aligned with [`EXECUTION.md`](../../EXECUTION.md). Replaces
legacy MVP/v1.5/v2.0 roadmap terminology.

---

## Phase 1 — Mock only (Weeks 1–6)

| Item | Status |
|------|--------|
| `TikTokClient` in repo | ✅ Exists — must not be called from P1 UI |
| Mock order/product/ad fixtures | P1-1 slice |
| OAuth UI flow | Mock / stub |

**Gate:** UX validated with 100 test sellers before P1.5.

---

## Phase 1.5 — ML backtest (Weeks 6–9)

| Item | Status |
|------|--------|
| Live TikTok API | ❌ Forbidden |
| Training data | Parquet / synthetic per `data-sources.md` |
| TikTok API doc refresh | ✅ This `api-docs` run |

**Gate:** Model precision/recall targets in `system-design.md`.

---

## Phase 2 — Live polling (Weeks 9–13)

### P2-1 — API polling (EXECUTION.md)

| Resource | Priority | Workflow |
|----------|----------|----------|
| Orders | P0 | Revenue Leakage Detection |
| Products | P1 | Growth context |
| Affiliate / creators | P1 | Fraud signals |
| Ads | P1 | Growth Copilot — **new client work** |

**P2-1 checklist:**

- [ ] Reconcile API paths (versioned vs `/api/*`)
- [ ] Implement `AdsResource` after official path confirmation
- [ ] Wire `sync_orders`, `sync_products`, `sync_creators` to live credentials
- [ ] Register webhooks (optional additive)
- [ ] Staggered cron per shop + `RateLimiter` tuning
- [ ] No calls before Phase 2 gate

### P2-2 — Daily inference (08:00 UTC)

Models consume Postgres data ingested by polling — not direct API calls.

### P2-3 — Ollama copy layer

Structured signals → Vietnamese copy. Rules fallback required.

**Gate:** 50 live sellers, 2 weeks stable, zero critical bugs.

---

## Later / out of P2

| Item | Phase | Notes |
|------|-------|-------|
| `sync_inventory`, `sync_settlements`, `sync_livestreams` | Remove | `map.md` pending cleanup |
| Kalodata / Shoplus validation | 2.5+ | Not user-facing analytics |
| Redis / Celery realtime | 3+ | ADR-004 |
| Creator ↔ Shop matching graph | 3+ | Superseded ADR-006/007 |

---

## Documentation maintenance

| Trigger | Action |
|---------|--------|
| Partner Center API version bump | Refresh `endpoints.md`, update client paths |
| New scope approved | Update `authentication.md` + `endpoints.md` |
| Webhook events confirmed | Update `webhooks.md` event table |
| P2-1 ships | Close ADR-008/009 candidates in `risks.md` |
