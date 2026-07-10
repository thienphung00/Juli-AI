# PRD: Phase 2 Contract-First TikTok Shop Read Sync

> Filed for GitHub issue creation. Slice: `EXECUTION.md` P2-A1.

## Problem Statement

Juli's Phase 2 pipeline cannot safely go live on TikTok Shop data until API contracts are verified and production/sandbox merchants are strictly separated. Current docs assumed VP/AHR dual-read and Phase 2 ML (including the T8 router classifier), but the revised scope is contract-first read sync on production merchant Fujiwa, sandbox-only write validation on SANDBOX_VN, rules-based signals only, and SPS-first shop health discovery. Without verified cURL evidence from the Partner Center API Testing Tool, implementation risks wrong HTTP methods, unsigned write calls on production, and fabricated health scores.

## Solution

Gate all Phase 2 TikTok implementation behind a user-filled contract collection template. After verified contracts are returned, implement capability-separated TikTok clients (production-read vs sandbox-write), wire Fujiwa polling through ETL into Postgres, build rules-only aggregates, and validate sandbox write paths technically—not for business workflow success. Shop health uses SPS via Partner API when available; otherwise explicit `health_data_source: proxy | unavailable`.

## User Stories

1. As a **product lead**, I want Phase 2 scope documented as contract-first TikTok sync with merchant separation, so that engineering does not implement before API evidence exists.
2. As a **product lead**, I want T8 router classifier and VP/AHR dual-read removed from Phase 2 exit criteria, so that Phase 2 stays rules-based until Phase 4 ML.
3. As an **engineer**, I want a fill-in template listing every Layer 1 read and Layer 2 sandbox write endpoint with parameters, so that I can return Request Demo cURL and Response Status from the API Testing Tool.
4. As an **engineer**, I want production merchant Fujiwa locked to read-only transport, so that inventory/product/promotion/fulfillment writes cannot be signed or sent from production credentials.
5. As an **engineer**, I want sandbox merchant SANDBOX_VN isolated for write-validation only, so that OAuth, signing, payload shape, and error parsing are tested without touching production sync.
6. As an **engineer**, I want separate credential storage tagged by merchant authorization ID and capability, so that token lookup never crosses production and sandbox boundaries.
7. As an **engineer**, I want a production-read allowlist of GET and read-only POST search endpoints, so that write paths are rejected before signing at runtime.
8. As an **engineer**, I want CI tests that fail if production factories can instantiate write resources, so that guardrails cannot regress silently.
9. As an **engineer**, I want verified contract fixtures filed per endpoint, so that client resources match live API behavior.
10. As an **engineer**, I want token get/refresh contracts verified before changing `TikTokAuth`, so that method and base URL mismatches are resolved from evidence not assumptions.
11. As an **engineer**, I want authorized shops, orders, products, returns, and cancellations read resources implemented only after verification, so that ETL maps confirmed schemas.
12. As an **engineer**, I want optional affiliate creator read endpoints with permission-failure handling, so that re-consent flows work when scope is missing.
13. As an **engineer**, I want SPS/shop health discovered via Partner Center API Reference, so that health is consumed only when an official contract exists.
14. As an **engineer**, I want `health_data_source: unavailable` when SPS has no Partner API, so that Juli never fabricates health scores or scrapes Seller Center.
15. As an **engineer**, I want Fujiwa polling with pagination, rate-limit backoff, token refresh, and per-endpoint sync state, so that production data sync is reliable.
16. As an **engineer**, I want ETL normalization into canonical entities with idempotent Postgres upserts, so that downstream rules aggregates have trustworthy data.
17. As an **engineer**, I want rules-only SQL/Python feature aggregates over synced production data, so that Phase 2 signals do not depend on trained models.
18. As an **engineer**, I want sandbox write validation for inventory update, product publish/edit, promotion lifecycle, and fulfillment ship, so that execution-layer contracts are proven technically.
19. As an **engineer**, I want sandbox business failures treated as successful technical validation when signing and parsing work, so that sparse sandbox data does not block contract proof.
20. As an **engineer**, I want outbound request metadata logged with capability, merchant auth ID, method, and redacted shop ID, so that operations are auditable without leaking secrets.
21. As a **security reviewer**, I want OAuth tokens, app secrets, buyer PII, and full signed URLs excluded from logs, so that credential exposure risk is minimized.
22. As a **QA engineer**, I want Layer 3 mock integration tests for retries, idempotency, webhook handoff, sync state, and DB updates, so that pipeline behavior is deterministic in CI.
23. As an **architect**, I want canonical docs aligned to the revised scope, so that agents load consistent context.
24. As a **coding agent**, I want an implementation handoff with a 12-step roadmap and stop condition, so that work proceeds only after contracts are verified.

## Implementation Decisions

- **Merchants:** Fujiwa (`7658073774813611784`) production read-only; SANDBOX_VN (`7658096633384781588`) sandbox write-validation only.
- **Client architecture:** `ProductionReadClientFactory` + `ReadOnlyTransportGuard` vs `SandboxWriteClientFactory` + `SandboxOnlyWriteGuard` wrapping existing `TikTokClient`.
- **Phase 2 signals:** Deterministic rules for shop profile (`NEW_SHOP` / `MID_LARGE_SHOP`); T8 router classifier deferred to Phase 4.
- **Health:** SPS-first via Partner API; `health_data_source: api | proxy | unavailable`; VP/AHR not a P2 polling gate.
- **Layer 1 reads (minimum):** token refresh, authorized shops, orders, products, returns/cancellations, product details; optional inventory search and affiliate creators; SPS if contract found.
- **Layer 2 writes (sandbox):** inventory update; product category/image/create/edit/activate; promotion activity and coupon lifecycle; fulfillment split/combine/package/ship. Candidate paths are in `docs/tiktok_api/contract-collection.md`; implementation remains blocked until cURL + response status.
- **Polling scope:** Fujiwa only for production sync; no expansion of settlements, livestreams, production inventory unless explicitly accepted.
- **Dependency injection:** Polling/ETL receive read client only; sandbox tools receive write-validation client only.
- **Stop gate:** No endpoint resource implementation until user returns filled `docs/tiktok_api/contract-collection.md`.

### Assumptions

- User will complete the contract collection template before coding starts.
- SPS may not exist in Partner API; Phase 2 proceeds with `unavailable` or proxy health.
- Some promotion/product write paths are candidate operations until API Testing Tool cURL confirms exact versioned paths and payloads.
- Phase 2.5 deployment baseline is already live; P2-A1 continues on that stack internally.

## Testing Decisions

- **Contract tests:** One fixture per verified endpoint from API Testing Tool output (sanitized).
- **Guard tests:** Production factory cannot instantiate write resources; write paths absent from production allowlist; Fujiwa auth ID absent from sandbox fixtures.
- **Integration tests:** Mock TikTok responses for retries, idempotency, sync state, ETL upserts—no live API in CI.
- **Sandbox Layer 2:** Assert signing, HTTP status, TikTok `code`, and response parsing; do not require business-success for sparse sandbox data.
- **Modules under test:** TikTok capability factories/guards, credential isolation, read resources, polling orchestration, ETL normalization, rules aggregate jobs.

## Out of Scope

- T8 router classifier training or inference in Phase 2
- VP/AHR dual-read as Phase 2 exit gate
- Marketing API (`business-api.tiktok.com`) integration
- Seller Center scraping for health scores
- Trained ML models (T1–T8) at 08:00 UTC batch
- Cloud LLM copy layer (Phase 4)
- Public users, landing page, creator matching
- Webhook ingestion (Phase 4.5)
- Expanding settlements, livestreams, production inventory unless explicitly accepted

## Further Notes

- **Docs:** `EXECUTION.md`, `phase-2-mvp.md`, `system-design.md`, `data-sources.md`, `tiktok_api/*`, handoffs updated.
- **User action:** Fill [`contract-collection.md`](../tiktok_api/contract-collection.md).
- **Handoff:** [`phase-2-tiktok-implementation.md`](phase-2-tiktok-implementation.md).
- **Rollout:** P2-A1 → P2-A2 → P2-A3 → P2-B1+.
