# Phase 2 TikTok — Coding Agent Handoff

> **Status:** P2-A1 complete through ETL (#294–#299). Layer 1 read resources (#297), Fujiwa polling (#298), and canonical ETL upserts (#299) ship-ready. **Active: #301** Layer 2 sandbox write validation.  
> **Prerequisite:** [`docs/integrations/tiktok_api/contract-collection.md`](../integrations/tiktok_api/contract-collection.md) (verified).  
> **PRD:** [#278](https://github.com/thienphung00/Juli-AI/issues/278).  
> **Slice:** [`EXECUTION.md`](../../EXECUTION.md) P2-A1 → P2-A3, then P2-B1+.

## Context Plan

### Agent Phase
- [x] Planning: Architect Agent (focus → to-prd) — **complete**
- [x] Step 1 — Contract fixtures (#294) — **complete**
- [x] Step 2 — Capability factories (#295) — **complete**
- [x] Step 3 — Runtime guards (#295) — **complete**
- [x] Step 4 — Credential isolation (#296) — **complete**
- [x] Step 6 — Layer 1 read resources (#297) — **complete**
- [x] Step 7 — Polling orchestration (#298) — **complete**
- [x] Step 8 — ETL normalization (#299) — **complete**
- [ ] Implementation: Meta routing → Executor (#301+) — Layer 2 sandbox writes, P2-A3 aggregates
- [x] Review + Testing: review → validate → ship-ready (#294–#299)

### Rules (Tier 2)
- [x] `.cursor/rules/reliability.mdc`
- [x] `.cursor/rules/observability.mdc`
- [x] `.cursor/rules/security.mdc`
- [x] `.cursor/rules/performance.mdc`
- [x] `.cursor/rules/patterns.mdc`

### Skills
- [x] `backend` executor
- [x] `data-platform` executor
- [x] `review` (post-implementation — #294–#299)

### MCPs
- [x] none (TikTok uses local docs)

### Load (Required)
- `EXECUTION.md` (P2-A1, merchant separation)
- `docs/architecture/system-design.md` (rules-only Phase 2; T8 deferred Phase 4)
- `docs/architecture/data-sources.md`
- `docs/architecture/map.md`
- `docs/integrations/tiktok_api/contract-collection.md` (verified cURL)
- `docs/integrations/tiktok_api/endpoints.md`, `authentication.md`, `architecture.md`, `multi-tenant.md`, `tech-stack.md`
- `backend/src/juli_backend/integrations/tiktok/`
- `backend/src/juli_backend/workers/services/polling/`
- `backend/src/juli_backend/services/etl/`

### DO NOT Load
- `web/`, `ios/` (not P2-A1)
- ML trainers (`src/modules/ml/`) — T8 router is Phase 4
- Marketing API (`business-api.tiktok.com`) — out of Shop Partner scope
- VP/AHR dual-read as implementation driver — SPS-first per revised scope

---

## Stop condition (cleared for Layer 1 minimum)

Layer 0 contract collection is complete. Layer 1 minimum-read fixtures are filed under
`docs/integrations/tiktok_api/samples/` and `endpoints.md` reflects verified contracts (#294).

Proceed with implementation roadmap below. Layer 2 sandbox write fixtures remain for
#301.

Previously (gate now passed):

1. ~~Update `docs/integrations/tiktok_api/endpoints.md` with verified method/path/param/schema deltas.~~
2. ~~File sanitized fixtures under `docs/integrations/tiktok_api/samples/`.~~
3. Proceed with implementation roadmap below.

---

## Confirmed decisions

| Decision | Value |
|----------|-------|
| Production merchant | Fujiwa `7658073774813611784` — **read only** |
| Sandbox merchant | SANDBOX_VN `7658096633384781588` — **write validation only** |
| Phase 2 signals | Rules-based only — no T8 router, no trained ML inference |
| Health scope | SPS via Partner API if verified; else `proxy` or `unavailable` |
| VP/AHR | Platform-policy reference — not P2 exit gate |
| Sandbox write success | Technical validation (signing, parse, auth) — business failures OK |

---

## Implementation roadmap

### Step 1 — Contract fixtures
One fixture per verified endpoint; sanitized cURL metadata + response status + sample body.

### Step 2 — Capability factories
Wrap existing `TikTokClient`:
- `ProductionReadClientFactory` (Fujiwa)
- `SandboxWriteClientFactory` (SANDBOX_VN)

### Step 3 — Runtime guards
- `ReadOnlyTransportGuard`: `GET` + allowlisted read-only `POST` search only
- `SandboxOnlyWriteGuard`: write paths sandbox-only
- CI tests: production cannot sign write paths; Fujiwa absent from sandbox fixtures

### Step 4 — Credential isolation
Split storage by merchant authorization ID + capability. Remove “latest credential” from production sync.

### Step 5 — OAuth / refresh
Separate Fujiwa and SANDBOX_VN flows; no shared token lookup.

### Step 6 — Layer 1 read resources
Implement only after contract verified per endpoint:
token refresh → authorized shops → orders → products → returns/cancellations → product details → optional affiliate → SPS if contract exists.

### Step 7 — Polling orchestration
Fujiwa only: pagination, rate limits, token refresh, retry/backoff, per-endpoint sync state.

### Step 8 — ETL normalization
Normalize to canonical entities; idempotent Postgres upserts.

### Step 9 — Rules-only aggregates
SQL/Python feature aggregates over synced production data. SPS consumed only if verified API contract.

### Step 10 — Layer 2 sandbox write resources
Behind `SandboxWriteClientFactory.create_resources()` only (#301). Inventory update,
product create/edit, fulfillment combine/ship/batch/split/uncombine, supply-chain
confirm shipment. Promotion lifecycle (#289) deferred until Layer 0 verifies paths.
Technical validation bar: signing, HTTP status, TikTok code, response parsing.

### Step 11 — Layer 3 mock integration tests
Retries, idempotency, webhook handoff, sync state, DB updates.

### Step 12 — Review / validate gates
Run `review` → `validate` before ship-ready.

---

## Risks

| Risk | Mitigation |
|------|------------|
| SPS not in Partner API | `health_data_source: unavailable`; continue ETL on verified reads |
| Token method/base URL mismatch | Verify in contract collection before changing `TikTokAuth` |
| Promotion/product write paths partly candidate-only | Use `contract-collection.md` as the checklist; do not implement any write resource until API Testing Tool cURL confirms exact path, payload, and response |
| Sparse sandbox data | Layer 2 judges technical correctness only |

---

## Acceptance (P2-A1)

- [x] Contract fixtures filed for minimum Layer 1 read endpoints (#294)
- [x] `endpoints.md` updated with verified contract deltas (#294)
- [x] Production-read factory cannot call write endpoints (test + runtime guard) (#295)
- [x] Fujiwa and SANDBOX_VN credentials isolated by auth ID + capability (#296)
- [x] Polling runs on Fujiwa for orders, products, returns (minimum) (#298)
- [x] ETL upserts canonical entities to Postgres (#299)
- [x] T8 router classifier **not** introduced in Phase 2 code paths
