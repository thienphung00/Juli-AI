# Blueprint Examples

## Example 1: Phase 2 TikTok Order Polling Slice

### User Request

> "Wire TikTok order polling for Revenue Leakage Detection in Phase 2."

### Upstream inputs

- `api-docs` handoff: `docs/tiktok_api/` — Orders API, rate limits, auth
- `platform-docs` handoff: seller operational limits, ISV data obligations

### Clarifying Questions Asked

1. Phase fit? → Phase 2 slice **P2-1** (polling live)
2. Webhook or polling? → Polling for MVP; webhooks deferred to v1.5
3. Idempotency key? → `(shop_id, order_id, update_time)`
4. Failure handling? → ETL DLQ handoff + structured logs; no silent drops
5. Data source allowed? → TikTok Shop Official API only (`data-sources.md` #1)

### Canonical doc updates

| File | Change |
|------|--------|
| `EXECUTION.md` | Confirmed **P2-1** slice; linked issue ref |
| `docs/system-design.md` | Data pipeline Phase 2 row — Orders polling mechanism |
| `docs/architecture/map.md` | `src/services/polling/` + `src/integrations/tiktok/` edges |
| `docs/architecture/data-sources.md` | Row #1 status confirmed MVP |
| `docs/decisions/` | None (reused existing ADR-002 Supabase boundary) |

### Handoff highlight

- Modules: `src/integrations/tiktok`, `src/services/polling`, `src/data`
- API surface: additive internal jobs; no new public HTTP in P2-1 alone

---

## Example 2: Rescope — Creator Matching Deferred

### User Request

> "Should we build creator ↔ shop matching in the next quarter?"

### Clarifying Questions Asked

1. North star alignment? → **No** — seller-money workflows take priority
2. UX validation done? → Not yet for matching; seller copilots validated first
3. Data sources? → Matching would need creator APIs + policy gates (Phase 3+)

### Canonical doc updates

| File | Change |
|------|--------|
| `EXECUTION.md` | Creator matching in **Explicitly out**; ADR-006/007 referenced as superseded |
| `docs/system-design.md` | No matching subsystem rows added |
| `docs/decisions/006-matching-pivot.md` | Status → Superseded (if not already) |

### Handoff highlight

- Feature deferred; `to-prd` not invoked unless user requests a Phase 3+ spike PRD

---

## Example 3: New Seller Copilot — Phase 1 UI Slice

### User Request

> "Add mocked onboarding flow for new sellers."

### Clarifying Questions Asked

1. Phase fit? → Phase 1 slice **P1-2**
2. Real API? → **No** — mock JSON only per Phase 1 exit gate
3. Seller-stage routing? → Rules-based tree (**P1-6** dependency)
4. Executor? → Approval flow no-op (**P1-5**)

### Canonical doc updates

| File | Change |
|------|--------|
| `EXECUTION.md` | **P1-2** slice description refined; dependency on P1-5, P1-6 noted |
| `docs/system-design.md` | Agent decision tree Phase 1 column — onboarding task sequence |
| `docs/architecture/map.md` | `web/` workflow routes (no new backend modules) |

### Handoff highlight

- UI-only; `to-prd` receives scope for GitHub issue #108 alignment
