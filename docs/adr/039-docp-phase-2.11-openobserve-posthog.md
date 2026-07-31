# ADR-039: DOCP Phase 2.11 — OpenObserve + PostHog thin MVP

**Status:** Accepted  
**Date:** 2026-07-27  
**Deciders:** grill-with-docs (Architect)

**Builds on:** [ADR-020](020-vps-ssh-continuous-delivery-and-secrets-manager.md),
[ADR-035](035-public-release-evidence-and-automatic-rollback.md),
[ADR-036](036-modules-tier1-planning-sot.md).  
**Amends:** ADR-020’s “journalctl-only / no Datadog-New Relic-ELK” monitoring stance for
**production public surfaces** — thin SaaS observability is now in scope for Phase 2.11.  
**Does not change:** ADR-020 VPS/SSH product deploy (no Docker on product VPS for
OpenObserve); ADR-035 ECS/#498 remains under CI/CD (not DOCP); seller Analytics KPIs
and Demo Analytics destination remain product BI (not PostHog).

## Context

Public Demo and API are live with only `/health`, a 15-minute uptime check → Slack, and
host journals. Before Phase 3 expands blast radius (Landing deploy + Demo Sign-in),
engineering needs a **Developer Observability Control Plane (DOCP)** so downtime and
UX breakage are visible without cloning seller KPI Analytics into a second BI product.

Grill settled vendors (OpenObserve + PostHog), phase numbering (2.11 before Phase 3;
not 3.1), thin MVP vs 2.11-B deepening, Cloud SaaS (not self-host on product VPS),
hot retention then S3 cold archive (archive pipeline deferred), MODULES homes
(§15 DOCP vs §12.1 ECS), Slack alerts, and thin correlation IDs.

## Decision

1. **Phase 2.11** ships the thin DOCP MVP after 2.10 and before Phase 3 Landing/Sign-in.
   **Phase 2.11-B** deepens DOCP (fuller traces/APM, Landing `product.*`, correlation
   plane, **hot→S3 cold archive export**). 2.11-B does not block Phase 3.

2. **Vendors:** OpenObserve Cloud (runtime logs/metrics/alerts) + PostHog Cloud
   (UX reliability: sessions, journeys, sampled replay). One PostHog project with
   namespaces `reliability.*` (2.11) and `product.*` (Phase 3 engagement). Phase 3
   exit drops standalone “wire PostHog” once 2.11 owns the project.

3. **Not seller product analytics:** DOCP must not duplicate Demo **Analytics** KPIs,
   SPS/GMV/ROAS, or Decisions BI. No custom unified control-plane UI in 2.11 — use
   vendor UIs.

4. **Hosting:** SaaS only for 2.11. Do not self-host OpenObserve on the Juli product
   VPS. Do not use CloudWatch as the primary store for VPS app logs/metrics/replay.
   CloudWatch remains for AWS-native compute under ADR-035 / #498 (§12.1). Secrets
   Manager holds OO/PostHog keys.

5. **Hot retention (2.11 policy):** OO logs 14 days; OO metrics 90 days; PostHog
   events/replay 30 days (or free/default tier). **Cold archive:** after hot window,
   export to AWS S3 (lifecycle/Glacier as needed) instead of discard — **implement
   export in 2.11-B**; document policy in 2.11.

6. **Hard deny** in OO and PostHog (and any future S3 archive): OAuth/API tokens,
   Secrets Manager payloads, Authorization headers, buyer PII, payment data, raw
   bodies that may contain the above. Prefer route, status, latency, error code,
   `request_id`, masked/aliased shop identifiers only.

7. **2.11 wire scope:** structured API (+ Demo server) logs → OO; RED metrics on
   public API + Demo; Slack alerts (uptime + OO 5xx/health); PostHog on `apps/demo`
   only (`reliability.*`, sampled replay); deploy `release_sha` markers; `request_id`
   propagation (API + best-effort PostHog on API failure). Vendor UIs only.

8. **MODULES:** new top-level **Observability (DOCP)**; ECS/#498 under **CI/CD & Infra
   §12.1**. Thin ADR-035 release-evidence plan required for Demo/API instrumentation
   (smoke + no secrets in client + rollback via env/prior release) — not full ECS
   cutover in 2.11.

## Consequences

- Engineers can detect and triage Demo/API failures before Phase 3 expands surface.
- ADR-020 monitoring minimalism is superseded for public production signals; VPS
  “no Docker / no new compute class” for product hosting remains.
- PostHog dual-use (reliability vs product engagement) needs event namespace discipline.
- Until 2.11-B archive ships, data older than hot retention may be lost — acceptable
  for thin MVP if policy and bucket/IAM sketch are documented.
- Cost stays dominated by SaaS ingest + PostHog free/paid tier, not a second VPS
  observability stack.
