# ADR 021: Manual-refresh pipeline, Postgres-only Action Card persistence, and Phase 2 scope reconciliation

## Status
Accepted

**Context session:** `grill-with-docs`, 2026-07-13 — Phase 2 exit-gate reconciliation.
**Amends:** [`EXECUTION.md`](../../EXECUTION.md) Milestone A/B slice list, [`phase-2-mvp.md`](../product/phases/phase-2-mvp.md)
architecture diagram and daily schedule.
**Reaffirms:** [ADR-012](012-architecture-reconciliation-mvp-vs-target.md) (single Postgres store),
[ADR-013](013-operations-pipeline-spine.md) (pipeline stage spine), [ADR-014](014-decision-copilot-app-structure-and-journey.md)
(Decision as primary product object).

## Context

The Phase 2 exit-gate report (`docs/product/phases/phase-2-exit-gate-report.html`, 2026-07-13)
found the rules pipeline (`services/scoring/pipeline.py`) fully implemented and tested
end-to-end, but running **in-memory only** — no persistence, no scheduler wiring, and the
execution layer registered only a `noop.ping` tool. Three architectural questions needed a
decision before Phase 2 could exit:

1. **How does the pipeline get triggered in production?** `phase-2-mvp.md`'s original
   "Daily schedule (UTC)" table and `EXECUTION.md`'s Milestone A/B language both assumed
   Celery beat / cron (overnight poll, 06:00 aggregates, 08:00 scoring). No scheduler was ever
   wired, and the product decision landing in this grill session is to **not** build one —
   Phase 2.5's dashboard will drive refresh via user action, not a clock.
2. **Where do generated recommendations live, and does Redis become required?**
   `EXECUTION.md`'s Phase 2 "In scope" line lists `Postgres · Redis`, and `phase-2-mvp.md`'s
   storage diagram makes Redis the action-card cache. No Redis-backed persistence was ever
   built; Postgres has been the only store actually exercised by every Phase 2 slice shipped
   to date (`ToolExecution`, `WorkflowWebhookSignal`, `WorkflowOutcomeRecord` are all Postgres
   tables with no Redis dependency).
3. **Is the shipped webhook catalog (#354) actually in-scope for Phase 2?** `EXECUTION.md`'s
   "Explicitly out (Phase 2)" list still says "Webhook ingestion (deferred to 4.5)," but
   `services/webhook/` shipped, is tested (91 passing tests), and is load-bearing for the
   signal engine (`WorkflowWebhookSignal` persistence feeds workflow-intent gating). The
   exclusion line is stale, not aspirational — it was never updated after #354 shipped.

## Decision

### 1. Manual refresh only — no scheduler in Phase 2

The aggregates → signals → recommendations → copy → persist chain runs **exactly once per
call** to `POST /v1/action-cards/refresh`, dispatched to a Celery task so the HTTP handler
never blocks. No Celery beat, no cron, no APScheduler, no background poller-on-a-timer.
TikTok polling (`run_fujiwa_poll_cycle`) is likewise invoked by the same refresh flow (or
manually via existing CLI/scripts) — not on a schedule.

The pipeline **implementation does not change** — `run_daily_scoring_for_shop` /
`run_daily_scoring_batch` are reused unmodified. Only the trigger changes: a clock is
replaced by an authenticated HTTP call. `DAILY_SCORING_CRON_UTC` in
`services/scoring/schedule.py` becomes dead code once the refresh endpoint ships; it is not
deleted immediately (avoid unrelated churn) but is documented as unused.

This is a **reversible-but-costly-to-reverse** decision: reintroducing a scheduler later
(Phase 4.5 per `EXECUTION.md`'s existing real-time roadmap) is additive, not a rewrite,
because the pipeline stays a plain callable either way.

### 2. Postgres is the only mandatory store for Action Cards

A new `action_cards` table (backend name for the **Decision** product object — see
`CONTEXT.md`) is the durable home for pipeline output. Redis is removed from Phase 2's
mandatory stack. Redis may return later as an **optional** read-through cache in front of
Postgres if latency demands it — never as the system of record. This matches every
persistence pattern already shipped in Phase 2 (`ToolExecution`, `WorkflowWebhookSignal`,
`WorkflowOutcomeRecord` — all Postgres, none Redis-backed) and removes a false architectural
requirement that nothing in the codebase actually depends on today.

The refresh endpoint is idempotent: each pipeline run upserts one `action_cards` row per
`(shop_id, workflow_key)` rather than inserting duplicates. Re-running refresh updates
existing cards (new copy, new priority/severity, `updated_at` bump) instead of accumulating
stale rows.

### 3. Webhook ingestion is retroactively in-scope for Phase 2

`EXECUTION.md`'s "Explicitly out (Phase 2)" line is corrected: webhook ingestion is **in
scope** — it shipped under #354, is tested, and the signal/execution architecture already
depends on it (`WorkflowWebhookSignal` gates workflow intent; polling remains the
reconciliation backstop per `docs/architecture/data-sources.md`). Cloud LLM (Haiku/Claude)
remains **out of Phase 2** and deferred to Phase 4 — the shipped copy layer is confirmed
rules-only (`services/scoring/MODULE.md`); this part of the original exclusion list was
never wrong and is unchanged.

## Consequences

- `EXECUTION.md`: "In scope (Phase 2)" drops `Redis` as mandatory, keeps webhooks explicit;
  "Explicitly out (Phase 2)" drops the webhook-ingestion line, keeps the Cloud LLM line;
  Milestone B slice list gains explicit manual-refresh framing.
- `phase-2-mvp.md`: architecture diagram and "Daily schedule (UTC)" table are rewritten to
  reflect on-demand refresh; Redis becomes an explicitly optional future cache, not a
  Phase 2 component.
- `CONTEXT.md`: adds **Action Card (backend)** and **Manual refresh pipeline** terms; corrects
  two stale ADR citations (Copy layer → ADR-012, not ADR-006; Decision → ADR-014, not ADR-007).
- Reopens #303 (P2-B1) and #305 (P2-B4) with acceptance criteria reflecting persistence and
  real-executor gaps respectively — the refresh endpoint + `ActionCard` persistence work
  lands as reopened-#303 scope, not a separate issue, since it is the same P2-B1 slice; files
  new issues for P2-B6 (#379), P2-B7 (#380), P2-B9 (#381), and webhook Partner Center
  confirmation (#382).
