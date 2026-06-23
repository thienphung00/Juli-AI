# Phase 3 — First User Testing (10 Shops)

> **Tier 1 — user-testing scope.** Read [`EXECUTION.md`](../../EXECUTION.md) first.  
> **Owns:** Phase 3 user behavior validation, product analytics, and exit criteria.  
> **Does not own:** Phase 2 pipeline mechanics (`phase-2-mvp.md`), subsystem envelopes (`system-design.md`).

**Goal:** Validate user behavior — not whether we can generate recommendations (solved in Phase 2).

The question is: **do sellers trust recommendations enough to approve and execute them?**

---

## Architecture

| Component | Role |
|-----------|------|
| **Web app** | Next.js seller UI — Morning Report, recommendations, approval flow |
| **REST** | FastAPI API layer |
| **Postgres** | Data store |
| **Redis** | Cache + Celery broker |
| **Celery** | Async tool execution (carried forward from Phase 2) |
| **PostHog** | Product analytics (introduced in Phase 3) |

Still **no WebSockets. No Kafka.**

### Architecture evolution from Phase 2

```
Phase 2:  FastAPI · Postgres · Redis · Celery · rules-based copy
Phase 3:  + Web app · PostHog
```

Copy layer remains **rules-based** — deterministic templates from ML signals. No cloud LLM.

---

## User flow

```
Morning Report → Recommendation → Approve → Execution
```

Product analytics events to track:

| Event | Meaning |
|-------|---------|
| `recommendation_viewed` | Seller saw the recommendation |
| `recommendation_approved` | Seller explicitly approved |
| `execution_started` | Celery job dispatched |
| `execution_succeeded` | Tool call completed successfully |

---

## Recommendation refresh

**1×/day** — morning report cadence. Same daily batch pipeline as Phase 2.

---

## Cost

**$30–100/month** — primarily hosting, Postgres, Redis. No LLM cost (rules-only copy).

---

## Exit criteria

| Metric | What we learn |
|--------|---------------|
| **Activation** | Connected shop |
| **Engagement** | Daily report opened |
| **Trust** | Recommendation approved |
| **Core metric: Execution rate** | Approved recommendations → executed actions |

If recommendations are viewed but not executed, **the product failed** — regardless of
recommendation quality.

When exit criteria pass → see [`phase-4-beta-launch.md`](phase-4-beta-launch.md).

---

## Deferred from this phase

The following are explicitly **not** Phase 3 scope:

- Webhook ingestion (event-driven refresh)
- WebSockets (live execution status)
- Cloud LLM copy (Haiku / Claude)
- Kafka / polyglot data plane (ClickHouse, S3, SQS)
- Creator ↔ shop matching
- Real-time recommendation refresh (>1×/day)
- TikTok LIVE API integration
- Sentiment / CSAT modeling

---

## What stays forbidden (all phases)

- Seller Center scraping
- Buyer PII storage (masked/hashed IDs only)
- Realtime unofficial livestream websockets
