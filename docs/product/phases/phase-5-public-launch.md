# Phase 5 — Public Launch (Paid Tier)

> **Tier 1 — public launch scope.** Read [`phase-4-beta-launch.md`](phase-4-beta-launch.md) first.  
> **Owns:** Phase 5 monetization, WebSocket introduction, and automation positioning.  
> **Does not own:** Phase 2–4 mechanics, subsystem envelopes (`system-design.md`).

**Goal:** Sell automation — not analytics, not forecasts.

Users pay for **automatic execution**, not more charts.

---

## Product positioning

| Users pay for | Users do not pay for |
|---------------|---------------------|
| Automatic execution | More charts |
| Reliable outcome improvement | Forecasts alone |
| Hands-off shop operations | Dashboard vanity metrics |

---

## Architecture

| Component | Role |
|-----------|------|
| **Web** | Seller UI with live execution status |
| **REST** | FastAPI API layer |
| **Webhook** | TikTok event ingestion |
| **Celery** | Async execution |
| **Redis** | Broker + cache |
| **Postgres** | Data store |
| **PostHog** | Product analytics |
| **WebSocket** | Live execution and analysis status (**introduced in Phase 5**) |

Still **no Kafka.**

### Architecture evolution from Phase 4

```
Phase 4:  FastAPI · Postgres · Redis · Celery · PostHog · Webhook
Phase 5:  + WebSocket
```

---

## Why WebSockets now

Execution becomes continuous. Users need live feedback:

```
Action Triggered → Execution Started → TikTok API → Result Returned
```

UI shows: Executing… → Success / Failed / Retrying — in real time.

### WebSocket usage

| Channel | Events |
|---------|--------|
| **Execution status** | Pending · Running · Completed · Failed |
| **AI analysis** | Analysis started · 50% · 100% |
| **Multi-device sync** | Action approved on desktop → mobile updates instantly |

### Event flow

```
Webhook → Celery → Execution → WebSocket → UI
```

---

## Recommendation refresh

**Near real-time** — target 1–5 minutes after important events.

Not milliseconds. Not trading-system latency. Practical seller operations cadence.

---

## Cost

For **50–500 shops:** **$300–1,500/month**.

Main costs: LLM, workers, database, execution volume. WebSockets are surprisingly cheap at this scale.

---

## Exit criteria

| Metric | Requirement |
|--------|-------------|
| **Monetization** | Users pay for automation |
| **Reliability** | Execution success >99% |
| **Outcome** | Automated actions improve KPIs |

---

## Kafka decision

**Probably no** — even at 500 shops.

Practical Phase 5 event flow:

```
Webhook → Celery → Execution → Postgres → WebSocket
```

Kafka becomes interesting only when:

- 10,000+ shops, or
- Independent systems need event replay: forecasting, fraud, automation, billing, and
  analytics all consuming the same event stream.

---

## Recommended architecture evolution (full arc)

```
Phase 2:  FastAPI · Postgres · Redis · Celery · rules-based copy
Phase 3:  + PostHog
Phase 4:  + Webhook · Haiku copy layer
Phase 5:  + WebSocket
```

This keeps complexity aligned with product maturity and focuses engineering effort on the
actual differentiator:

```
Recommendation → Execution → Measured Business Outcome → Automation
```

rather than prematurely investing in distributed systems infrastructure.
