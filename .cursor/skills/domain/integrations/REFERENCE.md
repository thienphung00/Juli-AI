# Integrations reference (platform-agnostic)

Curated patterns for the 80% path. For library API details and churn-prone behavior,
use the **Context7 CLI** at Executor time when Focus/Meta selects it (see **Sources /
live Context7 pointers**). Load on demand — not always injected in full.

---

## 1. HTTP client resilience

- **Timeouts:** connect + read timeouts on every outbound call; fail fast on hung sockets.
- **Retries:** retry only idempotent reads or vendor-documented safe retries; exponential
  backoff with jitter; cap max attempts.
- **Classification:** map responses before retrying —
  - **429 / 5xx / vendor “system” codes** → transient; backoff + retry within budget.
  - **401 / 403 / 404 / validation 4xx** → non-retryable; surface typed error to caller.
- **Idempotency:** use vendor idempotency keys or dedupe keys where the API supports
  safe replay; never blind-retry mutating POSTs.
- **Observability:** log `request_id` / correlation ids from vendor payloads; never log
  auth headers or signing material.

---

## 2. Webhook verification + replay protection

- **Verify before parse:** HMAC or vendor scheme over raw body + canonical headers;
  constant-time compare; reject missing/invalid auth before JSON decode when possible.
- **ACK quickly:** return vendor-success envelope within their SLA; persistence is async
  via `handoff_fn`.
- **Replay protection:** enforce timestamp skew window when vendor sends one; treat
  duplicate `event_id` / delivery id as idempotent accept (ETL dedup lives downstream).
- **Scope gate:** unknown or deferred event types → ACK without handoff when catalog
  says so; never hand off unverified payloads.

---

## 3. Rate limiting / token bucket / backoff

- **Shop-scoped buckets:** `(app_id, shop_id, endpoint)` — never share counters across
  merchants.
- **Token bucket:** atomic acquire (e.g. Redis `INCR` + conditional `EXPIRE`); return
  `False` when exhausted; expose `time_until_reset` for poll loops.
- **Poll/backfill coexistence:** check rate limiter before each HTTP attempt; separate
  run-level call budget governor caps total attempts per operator run (soft stop vs hard
  limit).
- **Backoff:** on exhaustion, wait for TTL or skip cycle; do not spin-retry inside the
  same tick.

---

## 4. Cursor / watermark sync and backfill windowing

- **Incremental sync:** persist cursor/watermark per shop + resource key; advance only
  after at least one successful handoff; on API error, log and leave cursor unchanged
  (except documented scope/consent errors).
- **Date-window fetch:** use vendor-documented inclusive/exclusive date bounds; one-day
  UTC windows are a common partition primitive for analytics APIs.
- **Backfill orchestration:** walk `(bucket × ascending date)`; skip partitions marked
  complete; pause mid-run on budget without marking the in-flight partition complete.
- **Reconciliation:** polling remains backstop when webhooks are primary; document both
  in `data-sources.md`.

---

## 5. Secrets handling

- **Never log** access tokens, refresh tokens, app secrets, or signing keys.
- **Inject at process boundary:** fetch from secrets manager / env in launcher or
  worker wiring; pass credentials into clients as constructor args — clients do not
  persist tokens.
- **Operator CLIs:** prefer in-memory inject at child process start without writing
  secrets to disk (see
  [ADR-020](../../../docs/adr/020-vps-ssh-continuous-delivery-and-secrets-manager.md);
  ADR-030 when present on branch for operator backfill path).
- **Redact before archive:** denylist PII fields in raw webhook audit payloads.

---

## 6. Juli path cheat-sheet (example implementation)

Patterns are vendor-agnostic; TikTok modules illustrate one in-repo implementation.

| Pattern | Example module(s) |
|---------|---------------------|
| Signed vendor client + resources | `integrations/tiktok/` (`client`, `signing`, `resources/`, `exceptions`) |
| OAuth lifecycle (no persistence in client) | `integrations/tiktok/auth.py` |
| Redis token bucket | `integrations/tiktok/rate_limiter.py` |
| Webhook verify → handoff | `services/webhook/` + vendor catalog/handlers |
| Scheduled poll + sync state | `workers/services/polling/` |
| Analytics partition + call budget | `services/analytics_backfill/` |
| Vendor API docs (issue load) | `docs/integrations/tiktok_api/` |

New marketplaces add `integrations/<vendor>/` + `docs/integrations/<vendor>_api/`;
reuse the same recipes from [`SKILL.md`](SKILL.md).

---

## 7. Sources / live Context7 pointers

This workspace uses the **Context7 CLI** (`npx ctx7@latest`), not Context7 MCP.
Resolve library IDs at Executor time, then fetch docs per topic. Do not rely on stale
hard-coded excerpts for churn-prone APIs.

```bash
npx ctx7@latest library httpx "timeout and retry configuration"
npx ctx7@latest docs /encode/httpx "timeout and retry configuration"
```

| Topic | Suggested CLI queries |
|-------|----------------------|
| HTTP timeouts & retries | `library httpx` → `docs <id>` — timeout config, transport retries |
| Retry/backoff decorators | `library tenacity` → `docs <id>` — wait_exponential_jitter, stop conditions |
| FastAPI inbound webhooks | `library fastapi` → `docs <id>` — raw body, dependency injection, response models |
| Async test client | `library httpx` → `docs <id>` — `AsyncClient`, `ASGITransport` |
| Redis atomic counters | `library redis` → `docs <id>` — pipelines, `INCR`, TTL |
| AWS Secrets Manager (operator inject) | `library boto3` → `docs <id>` — `get_secret_value` |

**Example library IDs** (resolve with `library` before use — IDs may change):
`/encode/httpx`, `/websites/fastapi_tiangolo`, `/jd/tenacity`.

See [`.cursor/rules/context7-cli.mdc`](../../../rules/context7-cli.mdc).

**Repo authority:** `MODULE.md` for affected modules,
[ADR-031](../../../docs/adr/031-integrations-executor-domain.md),
[`data-sources.md`](../../../docs/architecture/data-sources.md).
