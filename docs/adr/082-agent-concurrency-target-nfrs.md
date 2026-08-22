# ADR-082: Agent concurrency and progress target NFRs — bounded queue, per-(category, product) exclusion, polled overview

**Status:** Proposed (target design — **out of scope for current implementation**; no current W-slice is gated on this ADR, and no code change ships with it)
**Date:** 2026-08-22
**Deciders:** grill-with-docs (Architect) with owner

**Builds on:** ADR-041 (Redis ephemeral — broker is never the queue of record), ADR-068/ADR-073
(WorkflowRunner, one-active-run partial unique index, basis-snapshot concurrency guard),
ADR-074 (Postgres-authoritative event streaming, per-run sequences), ADR-075 (approval gate,
approve-is-run-creation — pending).

## Context

The agent execution subsystem (W1–W4) was designed and validated around a single running
workflow. The product's user-facing scale requirements were never stated as NFRs:
one seller automating many workflows simultaneously; bursts of ~100 run requests for one
shop; surges on Campaign/Sales days; accurate progress visibility across many concurrent
agents. Left unstated, these targets risk being foreclosed by decisions that are individually
correct today — most concretely the `(shop_id, product_id)` active-run unique index and the
one-card-per-category `action_cards` uniqueness, both of which cap concurrency in ways the
target model does not want.

This ADR records the agreed **target** NFRs so current work merely avoids foreclosing them.
It deliberately changes nothing now.

## Decision

1. **Queue, not parallelism (T1).** "Handle 100 workflow requests for one user" means
   *acceptance*, not simultaneous execution: 100 run requests for one shop are accepted in
   < 5 s and none are lost. Runs are born as Postgres `queued` rows (already true) and drain
   through a **config-bounded per-shop slot pool — initial target 10 concurrently executing
   runs**; the rest wait with visible queue state. Surge handling is a queue-depth problem,
   not a compute problem. Because the Redis broker is ephemeral (ADR-041), broker loss must
   be recoverable by re-enqueueing from Postgres `queued` rows (a reaper-family sweep).

2. **Concurrency vocabulary (T2).** An **agent** is a `WorkflowRun` in flight — there is no
   persistent agent pool. A **task** is one approved Decision (Action Card). A **workflow
   category** is a workflow kind (`workflow_key`). One agent executes one task; two agents
   never share a card. A category may run many agents simultaneously — one per card — which
   requires Action Cards to become **subject-scoped**: today's unique `(shop, workflow_key)`
   widens to `(shop, workflow_key, subject)`.

3. **Exclusion key = `(shop, workflow category, product)` (T3).** One agent per workflow per
   product. Two agents may work the same product **only under different categories** (e.g.
   Optimize Product and Inventory Management concurrently on product X); same category +
   same product queues behind the active run. This is the same rule as "one active run per
   subject-scoped card" stated at the index level. Cross-category field collisions on a
   shared product are arbitrated by the existing basis-snapshot guard (one re-proposal with
   fresh values, then `concurrency_conflict`) — not by admission-time exclusion. The current
   `(shop_id, product_id)` index is therefore **too coarse** for the target design: it blocks
   the allowed cross-category case and must re-key when subject-scoped cards land.

4. **Progress surface (T4).** The overview (all runs + queue positions) is a **polled
   Postgres read model** (2–5 s cadence) built on the same rows the event stream persists,
   so overview and stream can never disagree; any opened run uses the existing per-run SSE
   with `Last-Event-ID` replay unchanged (ADR-074). Invariant: every rendered state exists
   as a Postgres row first. A multiplexed per-shop event stream is **deferred behind an
   explicit trigger** — a product requirement for < 1 s overview reaction, or measurable
   polled-overview load at N tenants — because it would force composite/global cursor
   semantics that ADR-074's per-run sequences were chosen to avoid. Edge prerequisite either
   way: HTTP/2 and unbuffered SSE at nginx on the run-events location.

## Options considered and rejected

- **100 concurrently executing agents** — multiplies LLM spend and TikTok rate pressure,
  and exceeds what a seller can supervise through approval gates. Rejected for the slot pool.
- **Product-level exclusion across categories** (keep the current index shape) — turns a
  Sales-day burst into a serial crawl on exactly the hot products; rejected.
- **Per-run SSE over HTTP/2 as the whole answer** — leaves queued runs invisible (a queued
  run has no events); incomplete rather than wrong; its edge fix survives inside T4.
- **Multiplexed per-shop stream now** — rebuilds reconnect/cursor semantics that already
  work, for an overview whose consumer today is one seller's browser; deferred with trigger.

## Consequences

- **Entity implications (deferred with T-slices, not scheduled here):** subject-scoped
  `action_cards`; active-run index re-key to `(shop, workflow_key, product)` / card-level;
  card→run FK (lands naturally with ADR-075's approve-is-run-creation); run-list read model
  with queue positions; slot-pool admission in dispatch; broker-loss re-enqueue sweep.
- **Docs:** `system-design.md` gains an "Agent concurrency & scale envelopes (target)"
  section; `MODULES.md` §16 carries the targets as out-of-scope goals; `CONTEXT.md` defines
  **Run queue**, **Agent concurrency key**, and **Agent progress surface**.
- **Non-consequence, by design:** no current gate, executor slice, or CI check changes.
