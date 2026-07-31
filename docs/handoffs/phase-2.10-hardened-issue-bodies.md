# Phase 2.10-A — Hardened issue bodies (draft for `gh issue edit`)

> Apply after `gh auth login`. Slice IDs: `P2.10-A1` … `P2.10-A11`.
> Routing stubs: `agent-runtime/config/slice-routing.yml` + epicRegistry `524`.

---

## #525 — P2.10-A1: KPI envelope schema + upsert repo

```markdown
## Parent
#524 (Phase 2.10 — 2.10-A Analytics only)

Slice: P2.10-A1

## What to build
Add durable, shop-scoped **Analytics KPI envelope** storage (schema-only Alembic) and a repository that can upsert/read envelopes by `shop_id`. This is the Postgres system-of-record for precomputed Analytics payloads that Redis will cache and Demo will read. No public API or Demo UI in this slice.

### Schema sketch (Executor must follow)
- **New table** `analytics_kpi_envelopes` — do **not** extend in-memory `FeatureAggregateSnapshot`, and do **not** overload `analytics_performance_intervals` (raw Partner intervals remain SoT for history).
- **Columns (minimum):**
  - `id` uuid PK
  - `shop_id` uuid NOT NULL FK → `shops.id`
  - `kind` text NOT NULL — fixed `'analytics'` in 2.10-A (reserve for future Decision envelopes without schema fork)
  - `envelope_version` int NOT NULL — start at `1`
  - `payload` jsonb NOT NULL — versioned envelope document (see shape below)
  - `computed_at` timestamptz NOT NULL
  - `created_at` / `updated_at` timestamptz NOT NULL (server defaults OK)
- **Uniqueness:** `UNIQUE (shop_id, kind)` — one live Analytics envelope per shop (upsert on conflict).
- **Indexes:** `(shop_id, kind)` unique is enough for 2.10-A reads.
- **RLS / tenancy:** ENABLE RLS; isolation policy matching `analytics_performance_intervals` — `shop_id IN (SELECT id FROM shops WHERE user_id = current_setting('app.current_user_id')::uuid)`. Service-role / backend sessions used by workers must continue to work as today for other shop-scoped tables.
- **Do not** Demo-hardcode shop id in the PK or unique key — multi-shop keys from day one (ADR-038).

### Envelope JSON (`payload`) — version 1
```json
{
  "envelope_version": 1,
  "kind": "analytics",
  "shop_id": "<uuid>",
  "computed_at": "<iso8601>",
  "currency": "VND",
  "kpis": {
    "gmv_tiktok": {
      "availability": "available|unavailable",
      "label": "GMV (TikTok)",
      "series": [{"t": "<iso-date>", "v": 0.0}]
    }
  },
  "meta": {
    "source_partitions": ["A-36"],
    "notes": []
  }
}
```
- Every KPI entry **must** include `availability`. Missing sources → `unavailable` with empty/omitted series (no fabricated points).
- Money metric field key for GMV is `gmv_tiktok` with **label** `"GMV (TikTok)"` — never alias as Net Revenue / `net_revenue` / `net-revenue`.
- Later slices (#526–#528) add product/LIVE/unavailable stubs into the same `kpis` map; schema stays additive inside JSONB.

## Acceptance criteria
- Schema-only migration creates `analytics_kpi_envelopes` with columns + `UNIQUE (shop_id, kind)` + RLS as sketched
- Repo can upsert and fetch an envelope for a shop (unit/integration test with DB fixture)
- Upsert is idempotent on `(shop_id, kind)`; `envelope_version` and `payload` round-trip
- Design assumes multi-shop keys (not Demo-hardcoded in the table PK alone)
- No Redis, webhook, public API, or Demo UI changes required to merge

## Out of scope
- Precompute logic / reading `analytics_performance_intervals` (→ #526+)
- Redis cache (#529), masking (#530), public GET (#531)
- Decision envelopes / Action Cards
- Extending `FeatureAggregateSnapshot` or scoring pipeline

## Blocked by
None - can start immediately

## Type
AFK

## User stories
15, 32, 38
```

---

## #526 — P2.10-A2: Precompute GMV (TikTok)

```markdown
## Parent
#524 (Phase 2.10 — 2.10-A Analytics only)

Slice: P2.10-A2

## What to build
Build a shop-scoped compute step that reads warm `analytics_performance_intervals` (A-36 / revenue partition) and upserts a **GMV (TikTok)** time series into the KPI envelope (`kpis.gmv_tiktok` per #525). Label must be GMV — never Net Revenue. Verifiable via calling the precompute function and asserting envelope series + labels.

### Contract notes
- Write path: upsert `analytics_kpi_envelopes` for `(shop_id, kind='analytics')`.
- Series points: daily (or interval grain present in fixtures) `{t, v}` from non-null `gmv` rows; `currency` from `gmv_currency` when present (default VND).
- If no usable GMV rows: set `availability: "unavailable"` — do not invent zeros that imply real days.

## Acceptance criteria
- Precompute for a seeded shop produces a GMV series from intervals fixtures
- Envelope marks GMV available when data exists; does not invent points
- Metric is labeled GMV (TikTok) / never aliased as Net Revenue in envelope fields (`gmv_tiktok` key; no `net_revenue` alias)
- One focused pytest on public precompute behavior

## Blocked by
Blocked by #525

## Type
AFK

## User stories
1, 4
```

---

## #527 — P2.10-A3 (slice ID only + light AC)

```markdown
## Parent
#524 (Phase 2.10 — 2.10-A Analytics only)

Slice: P2.10-A3

## What to build
Extend KPI precompute to populate **product funnel (A-34)** and **LIVE (A-28/A-29)** series when warm data exists, with per-KPI availability flags. Inventory/Ops/CSAT only if existing aggregates already compute them — no new ETL science.

Suggested `kpis` keys: `product_funnel`, `live_performance` (plus optional aggregate-backed keys only when builders already exist).

## Acceptance criteria
- Precompute fills product/LIVE series from fixtures when present
- Missing sources yield `unavailable` (not fabricated)
- Inventory/Ops/CSAT included only when aggregate builders already provide values; otherwise unavailable
- Pytest covers available vs unavailable paths for at least one product and one LIVE KPI

## Blocked by
Blocked by #525

## Type
AFK

## User stories
2, 35
```

---

## #528 — P2.10-A4 (slice ID only)

```markdown
## Parent
#524 (Phase 2.10 — 2.10-A Analytics only)

Slice: P2.10-A4

## What to build
Lock the Analytics envelope contract so **Ads (ROAS/CAC/CTR)**, **Shop Status (SPS/AHR/VP)**, and **T1 forecast overlays** are truthful `unavailable` in 2.10-A, and Main KPI naming never presents GMV as Net Revenue.

## Acceptance criteria
- Envelope/API contract documents Ads, SPS/AHR/VP, T1 overlays as unavailable for 2.10-A
- Tests assert these KPIs are unavailable even when GMV/product/LIVE are live
- No code path renames or aliases GMV to Net Revenue
- Visual-layer Main KPI hero can use GMV where Net Revenue is unavailable without lying about the name

## Blocked by
Blocked by #526, #527

## Type
AFK

## User stories
3, 4
```

---

## #529 — P2.10-A5 (slice ID only)

```markdown
## Parent
#524 (Phase 2.10 — 2.10-A Analytics only)

Slice: P2.10-A5

## What to build
Add **required** Redis read-through cache for Analytics KPI envelopes: read cache first, fall back to Postgres SoT, refresh/overwrite cache after successful precompute. Cache miss/failure must not lose last-good Postgres rows.

Cache key sketch: `analytics:kpi_envelope:{shop_id}` (versioned payload as stored).

## Acceptance criteria
- Get envelope hits Redis when populated; loads from Postgres and fills cache on miss
- Successful precompute upserts Postgres then refreshes Redis for that shop
- Redis outage still allows Postgres read (degraded path tested)
- Redis is never the only copy of truth

## Blocked by
Blocked by #526

## Type
AFK

## User stories
16, 36
```

---

## #530 — P2.10-A6 (slice ID only)

```markdown
## Parent
#524 (Phase 2.10 — 2.10-A Analytics only)

Slice: P2.10-A6

## What to build
Transform envelopes for public Demo: **identity mask, real magnitudes** — alias shop display name; stable aliases for merchant/order/SKU ids and titles; keep real GMV/trend numbers. Buyer PII remains forbidden.

## Acceptance criteria
- Mask function aliases shop name and SKU/product titles to stable demo aliases
- Numeric GMV/series magnitudes unchanged by masking
- Raw merchant id / real product titles not present in masked public payload
- Unit tests with fixtures prove alias stability across calls

## Blocked by
Blocked by #526

## Type
AFK

## User stories
5, 6, 34
```

---

## #531 — P2.10-A7: Public Demo Analytics GET

```markdown
## Parent
#524 (Phase 2.10 — 2.10-A Analytics only)

Slice: P2.10-A7

## What to build
Unauthenticated **GET** Analytics endpoint that returns a **masked** envelope for the single server-configured reference shop. Visitors cannot pass arbitrary `shop_id`. Public force-recompute stays disabled (prefer disabled over rate-limited).

### API contract
- **Path:** `GET /v1/demo/analytics`
- **Auth:** none
- **Query:** optional `range=7d|30d|90d` for client chart windows only — **must not** accept `shop_id` (ignore or `400` if present)
- **Env / settings:** `DEMO_REFERENCE_SHOP_ID` (uuid of Fujiwa / `production_read` shop row). Bound server-side only.
- **Response:** HTTP 200 JSON — masked Analytics envelope compatible with #525 `payload` shape (`envelope_version`, `kpis`, …). Include `Content-Type: application/json`.
- **Read path:** Redis read-through → Postgres SoT (#529); apply masking (#530) before response.
- **Must not** enqueue Transform→Compute or Partner fetch.

## Acceptance criteria
- `GET /v1/demo/analytics` returns masked Analytics envelope without auth
- Shop id comes from `DEMO_REFERENCE_SHOP_ID` (or equivalent settings) only — query/body `shop_id` ignored or rejected
- Response uses cache+SoT path from prior slices
- Tests cover happy path + rejection/ignore of visitor-supplied shop switching
- No compute enqueue from this GET

## Blocked by
Blocked by #528, #529, #530

## Type
AFK

## User stories
7, 20, 21
```

---

## #532 — P2.10-A8: Material webhook → Analytics compute

```markdown
## Parent
#524 (Phase 2.10 — 2.10-A Analytics only)

Slice: P2.10-A8

## What to build
After Phase 2 catalog ingest, **enqueue Analytics precompute** only for material types: #1, #2, #5, #12, #27, #39, #67, and **#68 with 15-minute per-shop coalesce**. Other catalog types ingest/signal only. Light per-shop mutex to prevent stampede. **2.10-A scope: Analytics precompute only** (no Decision/scoring wire).

### API fetch after webhook (settled for this slice)
- On material ACK + successful ETL handoff: enqueue a **shop-scoped fetch-then-precompute** job (Celery task).
- **Fetch reuse:** call the existing Fujiwa poll workers for the affected shop — same resources as `_FUJIWA_POLL_STEPS` in `workers/services/polling/orchestrate.py`: orders, products, returns, inventory (`ORDER_SEARCH` / `PRODUCT_SEARCH` / `RETURN_SEARCH` / `INVENTORY_SEARCH`). Do **not** invent a parallel HTTP client.
- **Analytics intervals:** if the job needs fresher A-36/A-34/A-28/A-29 rows, reuse existing analytics sync/backfill callables already used by poll/backfill — do not start a full 2.9 orchestrator run. Prefer incremental/recent window fetch; gaps remain truthful.
- After fetch success (or when raw rows already sufficient): run Analytics KPI precompute (#526/#527) → upsert envelope → refresh Redis (#529).
- Non-material types: ingest only; **no** fetch-enqueue and **no** precompute enqueue.

## Acceptance criteria
- Material types enqueue one shop Analytics compute job after successful ingest handoff
- Job performs (or skips when warm) the poll-step resource fetches above, then precompute
- #68 coalesces to ≤1 compute enqueue per shop per 15 minutes (tested with time fixture)
- Non-material catalog types (#3,#4,#6,#7,#11,#21,#24,#37,#58,#64,#65) do not enqueue compute
- Concurrent material events do not fan out unbounded jobs (mutex/coalesce behavior tested)

## Blocked by
Blocked by #526

## Type
AFK

## User stories
17, 18, 26, 27
```

---

## #533 — P2.10-A9: Hourly Mock reconciler

```markdown
## Parent
#524 (Phase 2.10 — 2.10-A Analytics only)

Slice: P2.10-A9

## What to build
Narrow hourly job that runs Analytics precompute (+ cache refresh) for the configured **Mock/reference shop only**. Not a global daily scoring cron. Complements material webhooks.

### Scheduler (ADR-038 narrow exception to ADR-021)
- **Mechanism:** Celery Beat entry (preferred) scheduling one task hourly — **not** a systemd timer and **not** a return to global `DAILY_SCORING_CRON_UTC` for all shops.
- **Target:** only `DEMO_REFERENCE_SHOP_ID` (same binding as #531).
- Document in MODULE/comments that this is Phase 2.10 Mock-mode reconciliation only (ADR-038 §5).

## Acceptance criteria
- Celery Beat (or documented equivalent) hourly entrypoint recomputes Analytics envelopes for the configured reference shop
- Does not fan out to all shops in 2.10-A
- Idempotent with material-webhook compute (upsert semantics)
- Test asserts job invokes precompute for configured shop id only

## Blocked by
Blocked by #526, #532

## Type
AFK

## User stories
19
```

---

## #534 — P2.10-A10: Contracts + Demo wire + Fake Refresh

```markdown
## Parent
#524 (Phase 2.10 — 2.10-A Analytics only)

Slice: P2.10-A10

## What to build
Align `packages/contracts` KPI shapes with the public Analytics envelope; wire `apps/demo` Analytics to `GET /v1/demo/analytics`; implement **Fake Demo Refresh** (re-fetch envelopes / reset client UI — **must not** enqueue Transform→Compute). Home/Settings stay mock; Sign-in stub stays disabled.

### Contract ↔ Demo field checklist (vs `MAIN_KPI_ORDER`)
Demo `MAIN_KPI_ORDER` today: `sps`, `net-revenue`, `roas`, `inventory-turnover`, `fulfillment-accuracy-rate`, `csat`.

| Demo metricKey | 2.10-A live source | Display rule |
|----------------|--------------------|--------------|
| `net-revenue` | **Do not** map from GMV silently | Keep key for IA; show **GMV (TikTok)** from `kpis.gmv_tiktok` as the Revenue hero **or** mark Net Revenue unavailable and surface GMV as the live revenue series without renaming GMV→Net Revenue |
| `sps` | unavailable | Keep unavailable reason (Shop Status) |
| `roas` | unavailable | Ads unavailable |
| `inventory-turnover` | live only if #527 aggregate path filled it | else unavailable |
| `fulfillment-accuracy-rate` | live only if aggregates exist | else unavailable |
| `csat` | unavailable unless source exists | else unavailable |

Also map product/LIVE chart sections from `kpis.product_funnel` / `kpis.live_performance` when available.

## Acceptance criteria
- Demo Analytics renders live GMV/product/LIVE from API when available; unavailable KPIs stay truthful
- Contract types include envelope fields needed for the table above (no silent GMV→Net Revenue)
- Fake Demo Refresh re-reads `GET /v1/demo/analytics` (cache path) and does not call any force-recompute endpoint
- Home and Settings unchanged (mock); Sign-in remains non-functional stub
- Frontend tests cover live render + Fake Refresh non-recompute behavior

## Blocked by
Blocked by #531

## Type
AFK

## User stories
8, 9, 28, 29, 37
```

---

## #535 — P2.10-A11 (slice ID only)

```markdown
## Parent
#524 (Phase 2.10 — 2.10-A Analytics only)

Slice: P2.10-A11

## What to build
Human-in-the-loop production wiring: supply Redis URL/credentials, set `DEMO_REFERENCE_SHOP_ID` / Demo public config, deploy, and smoke-verify masked Analytics on `demo.app-juli.com`. Confirm Fake Refresh and no visitor OAuth.

## Acceptance criteria
- Redis reachable from API/workers in the target environment
- Reference shop id configured server-side for public Analytics GET
- Smoke: Demo Analytics shows masked live GMV (and product/LIVE if data warm)
- Smoke: Fake Refresh does not trigger Partner fetch storms; Sign-in still stub
- Operator notes any release-evidence needs if Demo/runtime config changed

## Blocked by
Blocked by #534

## Type
HITL

## User stories
30 (2.10-A exit portion)
```

---

## #524 parent header refresh

Replace stale “Child slices: via to-issues” with the child list from local `docs/product/phases/phase-2.10/PRD.md` (already updated locally — sync GitHub body).
