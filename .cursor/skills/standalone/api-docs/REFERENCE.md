# API Docs — Reference

Detailed workflow for converting official vendor API documentation into
`docs/<vendor>_api/`. Load this when executing a full extraction, not for routine
routing.

## Input

One or more of:

- API documentation URLs
- Context7 package / library IDs
- SDK repositories
- OpenAPI specifications
- Vendor documentation portals

**Repo examples:** TikTok Shop Partner API (`docs/integrations/tiktok_api/`), Shopee Open Platform,
Lazada Open Platform, Stripe, Shopify, Meta Graph API.

**Before writing anything new**, read existing vendor docs and
[`docs/architecture/data-sources.md`](../../../../docs/architecture/data-sources.md) to avoid
duplication and to align status (MVP / v1.5 / v2.0 / Out / Forbidden).

---

## Step 1 — Discover

Collect platform facts with **source URLs** for every claim:

| Category | Capture |
|----------|---------|
| Auth | OAuth flows, API keys, signing, scopes |
| Architecture | REST/GraphQL, regions, versioning, base URLs |
| Limits | Rate limits, quotas, burst behavior |
| Events | Webhooks, subscriptions, retry policy |
| Data access | Pagination, cursors, filters, search windows |
| SDKs | Official client libraries and supported languages |
| Errors | Error codes, retryable vs fatal |
| Resources | Supported object types and relationships |

---

## Step 2 — Extract

For **every endpoint** explicitly documented by the vendor:

| Field | Required |
|-------|----------|
| Name / category | Yes |
| HTTP method + path | Yes |
| Required permissions / scopes | Yes |
| Request schema (fields, types, required) | Yes |
| Response schema | Yes |
| Pagination strategy | If documented |
| Rate-limit notes | If documented |
| Caveats / deprecation | If documented |
| Source URL | Yes |

**Rules:**

- Do **not** infer behavior.
- Mark gaps as `UNKNOWN — not in official docs`.
- When sources conflict, cite both and flag `DISCREPANCY`.

---

## Step 3 — Normalize

Map vendor concepts to the **Juli commerce graph** and internal persistence models
(`src/shared/utils/data` — `Shop`, `Creator`, `Product`, `Order`, etc.).

Example mapping table (extend per vendor):

| Vendor term | Juli term | Notes |
|-------------|-----------|-------|
| Seller / Shop | `Shop` | Shop-scoped access |
| SKU / Item | `Product` | |
| Order | `Order` | |
| Shipment / Fulfillment | Fulfillment edge | Not a standalone CRM module |
| Affiliate Creator | `Creator` | Scope-gated |
| Settlement / Payout | Finance signal | Treat as `pending` 7–14d per data-sources rules |

Document mappings in `endpoints.md` (per-resource sections) and `tech-stack.md`
(DB field mapping where persistence is implied).

---

## Step 4 — Generate docs

Write under **`docs/<vendor>_api/`** using the repo file set (mirror `docs/integrations/tiktok_api/`):

| File | Purpose |
|------|---------|
| `README.md` | Index, quick-reference table, prerequisites, related official links |
| `authentication.md` | Auth flows, token lifecycle, refresh, signing, scopes, credential storage |
| `endpoints.md` | Categorized endpoint inventory, schemas, pagination, error codes, vendor→Juli mapping |
| `webhooks.md` | Event catalog, payloads, verification, retry, idempotency notes |
| `rate-limits.md` | Quotas, throttling, backoff, per-tenant bucket strategy |
| `architecture.md` | Integration architecture mapped to **actual** `src/` modules and data flow |
| `multi-tenant.md` | Per-shop credentials, isolation, cross-region routing |
| `risks.md` | API gaps, delayed data, ToS constraints, forbidden patterns |
| `tech-stack.md` | Recommended client boundaries, storage touchpoints, env vars |
| `mvp-roadmap.md` | Phased rollout aligned with `EXECUTION.md` |
| `context-plan.md` | Focus-skill load list (what to load / skip per task type) |

**Content routing** (do not create parallel filenames):

| Would-be file | Fold into |
|---------------|-----------|
| `overview.md` | `README.md` |
| `domain-model.md` | `endpoints.md` + `tech-stack.md` |
| `implementation-notes.md` | `architecture.md` + `tech-stack.md` |
| `source-links.md` | `README.md` + inline `Source:` on major statements |

### `architecture.md` must map to repo modules

Tie integration design to paths from [`docs/architecture/map.md`](../../../../docs/architecture/map.md):

```
Vendor API
  → src/modules/catalog/domain/integrations/<vendor>/   # API client, rate limiter, resources
  → src/modules/identity/infrastructure/auth/         # OAuth / token lifecycle
  → src/apps/api_gateway/services/webhook/            # webhook receiver (HMAC, handoff)
  → src/apps/cron_jobs/services/polling/              # reconciliation sync jobs
  → src/modules/ordering/use_cases/etl/               # dedup, transform, persist
  → src/shared/utils/data/                            # shop-scoped repos
```

Document: data flow, retry strategy, caching, webhook-vs-polling guidance, idempotency keys.

### `README.md` quick-reference template

```markdown
# <Vendor> API — Documentation Index

| Property | Value |
|----------|-------|
| API style | REST / GraphQL / … |
| Auth | … |
| Rate limits | … |
| Regions | … |
| Official portal | <url> |

## Documents

| Document | Description |
|----------|-------------|
| [authentication.md](authentication.md) | … |
| … | … |
```

---

## Step 5 — Platform hooks

### 5.1 `docs/architecture/data-sources.md`

Propose or update a matrix row:

| Field | Example |
|-------|---------|
| Source name | TikTok Shop Partner API (official REST) |
| Status | MVP / v1.5 / v2.0 / Out / Forbidden |
| Powers | Orders, products, creators, … |
| Notes | Bounded history, settlement lag, masked PII, rate-limit buckets |

Follow the status legend and operational rules already in that file.

### 5.2 ADR candidates

When auth boundaries, ingestion model, or forbidden substitutes are non-obvious, draft an ADR candidate:

- File: `docs/adr/NNN-<slug>.md` (three-digit, zero-padded)
- Update `docs/adr/README.md` index
- Use the trade-off-first ADR template (Context / Decision / Options / Consequences)

Example triggers:

- Token refresh worker vs on-demand refresh
- Webhook-primary vs polling-primary ingestion
- Vendor feed marked Forbidden (scraping, unofficial streams)

---

## Output quality standard

A backend engineer should be able to implement, without re-reading vendor docs except for edge cases:

- API client (`integrations/<vendor>/`)
- Webhook consumer (`api_gateway/services/webhook/`)
- Polling sync jobs (`cron_jobs/services/polling/`)
- Auth/token service (`identity/infrastructure/auth/`)
- ETL handoff (`ordering/use_cases/etl/`)

Optimize for engineering execution, not executive summary.

---

## Constraints (non-negotiable)

- Never invent endpoints, fields, or behaviors.
- Never infer undocumented schemas.
- Cite official sources on every major statement.
- Flag documentation conflicts explicitly.
- Respect `docs/architecture/data-sources.md` — do not document Forbidden access patterns as viable integrations.
