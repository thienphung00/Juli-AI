# Phase 4 — Beta Launch (50 Shops)

> **Tier 1 — beta scope.** Read [`phase-3-vision.md`](phase-3-vision.md) first.  
> **Owns:** Phase 4 beta launch capabilities only.  
> **Does not own:** Phase 2/3 mechanics, subsystem envelopes (`system-design.md`).

**Goal:** Validate repeated value creation — not whether users can execute (proven in Phase 3).

The question is: **will users repeatedly return and execute?**

---

## Architecture

| Component | Role |
|-----------|------|
| **Web app** | Seller UI |
| **REST** | FastAPI API layer |
| **Postgres** | Data store |
| **Redis** | Cache + Celery broker |
| **Celery** | Async execution + event-driven recomputation |
| **PostHog** | Product analytics |
| **Webhook receiver** | TikTok event ingestion (**first major architecture change**) |
| **Haiku copy layer** | Claude Haiku 3.5 — summarize + localize ML outputs (**introduced in Phase 4**) |

Still **no WebSockets. No Kafka.**

### Architecture evolution from Phase 3

```
Phase 3:  FastAPI · Postgres · Redis · Celery · PostHog · rules-based copy
Phase 4:  + Webhook ingestion · Haiku copy layer
```

---

## LLM copy layer introduction

Cloud LLM is introduced in Phase 4 — not before. Phases 2–3 validated the pipeline and
user behavior with **rules-based summarization**; Phase 4 swaps the copy layer without
changing ML ranking or execution logic.

```
ML signals → Haiku summarize + localize → action card
         ↘ rules fallback if LLM fails or budget exceeded
```

- Claude Haiku 3.5 (≤6 calls/seller/day) + rules fallback.
- LLM **never** decides what to recommend — only formats copy from structured signals.
- No raw financial PII to LLM (ADR-012).
- Log `copy_source: haiku | rules` per recommendation.

---

## Why webhooks now

Phase 3 used 1×/day polling. At 50 shops with 3×/day refresh, polling becomes inefficient.

Instead:

```
TikTok Event → Webhook → Update Metrics → Recompute Signals
```

### Event flow example

```
Order Created → Webhook → Celery → Update Features → Generate New Action
```

---

## Recommendation refresh

**3×/day:**

- Morning
- Afternoon
- Evening

---

## Infrastructure

| Service | Role |
|---------|------|
| **Frontend** | Next.js web app |
| **Backend** | FastAPI |
| **Postgres** | Data store |
| **Redis** | Broker + cache |
| **Celery worker** | Execution + signal recomputation |
| **Webhook receiver** | TikTok event ingestion endpoint |
| **PostHog** | Product analytics |

---

## Cost

**$100–300/month** — main cost drivers: LLM (introduced this phase), workers, database.

---

## Exit criteria

| Metric | What we prove |
|--------|---------------|
| **Retention** | Weekly usage |
| **Repeat execution** | Multiple actions executed per shop |
| **Outcome** | Shop metrics improve |
| **Automation interest** | Users wanting auto-execution (informs monetization) |

When exit criteria pass → see [`phase-5-public-launch.md`](phase-5-public-launch.md).

---

## Kafka decision

**No** — even at 50 shops. Practical event flow:

```
Webhook → Celery → Execution → Postgres
```

Kafka becomes interesting only at 10,000+ shops or when independent systems need event
replay (forecasting, fraud, automation, billing, analytics all consuming the same stream).
