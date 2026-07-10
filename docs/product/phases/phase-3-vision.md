# Phase 3.0 — Vision (Forward-Looking)

> **Tier 1 — forward scope.** Read [`EXECUTION.md`](../../EXECUTION.md) first.  
> **Owns:** Phase 3 capabilities only. Detail: ADR-004 (Kafka), ADR-012 (polyglot).

Phase 3 expands Juli from batch/daily MVP to real-time, polyglot, and creator-facing
capabilities — adopted only when data volume, dashboard latency, or webhook burst
justify the infrastructure cost.

---

## Real-time

- Supabase Realtime subscriptions and/or SSE for live KPI updates
- Event-driven action-card refresh (vs daily 08:00 UTC batch)
- Sub-second seller alerts for critical policy milestones

**MVP posture:** Batch/daily only in Phase 2 (ADR-012).

---

## Live-stream / TikTok LIVE API

- Official TikTok LIVE and live-stream API integration for creator analytics
- `sync_livestreams` and in-stream signal collection (currently forbidden for unofficial websockets)
- Creator ↔ shop matching workflows (explicitly deferred from MVP)

**Reference:** [`tiktok_platform/creator/feature-guide.md`](../tiktok_platform/creator/feature-guide.md)

---

## Polyglot data plane

When Postgres alone cannot serve analytics latency or raw-archive volume:

| Component | Role |
|-----------|------|
| **ClickHouse** | High-volume analytics queries, dashboard aggregates |
| **Amazon S3** | Raw JSON landing, replayable archive |
| **AWS SQS** | Async webhook queue, burst ingestion |
| **Kafka** | Event streams ([ADR-004](../adr/004-etl-kafka-consumer.md)) |

Migration path: read ClickHouse from Postgres replication — planned migration, not rewrite.

**Interim (pre-polyglot):** In-DB `raw_payloads` (`jsonb`) table for replayable archive.

---

## Additional Phase 3 capabilities

- **Sentiment / CSAT:** Requires buyer review/comment/chat text sources (none in MVP)
- **Celery / multi-node workers:** Background job scaling beyond cron/APScheduler
- **Vendor scrapers:** Kalodata, Shoplus, FastMoss (training data enrichment)
- **DSPy prompt optimization:** After labeled eval set exists
- **Sync preferences / cross-device:** Supabase Realtime or push
- **`src/` folder reshaping:** Modular monolith → service boundaries

---

## What stays forbidden (all phases)

- Seller Center scraping
- Buyer PII storage (masked/hashed IDs only)
- Realtime unofficial livestream websockets
