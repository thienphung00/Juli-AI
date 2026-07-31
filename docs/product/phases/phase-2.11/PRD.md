# PRD: Phase 2.11 — Developer Observability Control Plane (thin MVP)

> **Canonical docs:** [`EXECUTION.md`](../../../../EXECUTION.md) Phase 2.11 brief ·
> [ADR-039](../../../adr/039-docp-phase-2.11-openobserve-posthog.md) ·
> [`MODULES.md`](../../../architecture/MODULES.md) §15 ·
> [`CONTEXT.md`](../../../../CONTEXT.md).
>
> **Parent issue:** [#539](https://github.com/thienphung00/Juli-AI/issues/539) — filed via
> `to-prd` from grill-with-docs (2026-07-27).
> Child slices via `to-issues` after parent acceptance.

## Assumptions

- Grill handoff is authoritative; no re-interview.
- Deep modules below match Architect intent; default tests cover request-id middleware,
  log redaction deny-list, PostHog event naming, deploy marker emission, and alert
  config smoke (no live vendor calls required in CI).
- OpenObserve Cloud and PostHog Cloud accounts/keys will be provisioned by ops into
  Secrets Manager before production cutover.
- Phase 2.10 Demo/API remain the public surfaces instrumented in 2.11.
- Phase 2.11 planning work proceeds on a `2.11` planning branch; implementation issues
  follow after `to-issues`.

## Problem Statement

Engineers cannot see runtime failures, API degradation, or Demo UX breakage with enough
signal before Phase 3 puts Landing and Sign-in in front of more visitors. Today’s
health check and host journals are too thin. Building a full correlation control plane
or cloning seller Analytics into a second BI tool would waste time and money. We need a
thin developer observability plane—now—that surfaces downtime and bugs without becoming
product analytics.

## Solution

Ship **Phase 2.11**: a thin **Developer Observability Control Plane (DOCP)** using
**OpenObserve Cloud** for logs/metrics/alerts and **PostHog Cloud** for Demo UX
reliability (`reliability.*`, sampled replay). Use vendor UIs only. Alert to Slack.
Tag deploys with release SHA and propagate request IDs. Document hot retention and
defer cold **S3 archive**, deep traces, and full correlation to **Phase 2.11-B**.
Keep seller KPI Analytics untouched. Land this **before** Phase 3 Landing/Sign-in.

## User Stories

1. As an on-call engineer, I want Slack when the public API or Demo is unhealthy, so that I do not learn about outages from visitors first.
2. As an on-call engineer, I want Slack when API 5xx rates spike, so that I can respond before Phase 3 increases traffic.
3. As a backend engineer, I want structured API logs in OpenObserve, so that I can search failures by route and status without SSH/journalctl first.
4. As a backend engineer, I want RED metrics (rate, errors, duration) for the public API, so that I can see degradation trends.
5. As a frontend engineer, I want Demo pageviews and key journeys in PostHog under `reliability.*`, so that I can see where the Demo breaks for visitors.
6. As a frontend engineer, I want sampled session replay on Demo, so that I can reproduce UI failures without recording every session.
7. As a release engineer, I want each deploy tagged with `release_sha` in OpenObserve and PostHog, so that I can ask “did this start after release X?”
8. As a backend engineer, I want every API request to carry a `request_id` in logs and responses, so that I can stitch a single failure across log lines.
9. As a frontend engineer, I want failed Demo API calls to attach `request_id` to PostHog when available, so that I can jump from a session to server logs later.
10. As a security-conscious engineer, I want tokens, secrets, and buyer PII never sent to OpenObserve or PostHog, so that observability does not become a leak channel.
11. As an ops engineer, I want OO/PostHog keys in Secrets Manager, so that credentials follow the existing VPS secret pattern.
12. As an Architect, I want DOCP listed as MODULES §15 separate from ECS §12.1, so that deploy platform work (#498) is not confused with app telemetry.
13. As a product lead, I want seller Analytics KPIs to stay out of PostHog, so that DOCP does not duplicate product BI.
14. As a product lead, I want Phase 2.11 before Landing/Sign-in, so that reliability signals exist before blast radius grows.
15. As an ops engineer, I want a documented hot retention policy (14d logs / 90d metrics / 30d PostHog), so that SaaS cost stays bounded.
16. As an ops engineer, I want a documented plan that cold data later archives to S3 instead of discard, so that free-tier/startup credits can preserve history in 2.11-B.
17. As a Meta/Executor agent, I want a thin ADR-035 release-evidence plan for instrumentation, so that Demo/API config changes are not shipped blind.
18. As an on-call engineer, I want to use OpenObserve and PostHog UIs directly, so that we do not build a custom control-plane app in 2.11.
19. As a Phase 3 engineer, I want one PostHog project with `product.*` reserved for engagement, so that Landing metrics reuse the 2.11 wiring.
20. As a future 2.11-B engineer, I want full traces, S3 export, and deeper correlation deferred cleanly, so that the thin MVP can ship fast.
21. As a Demo visitor (indirect), I want fewer unnoticed outages and bugs, so that the public Demo stays usable.
22. As an ops engineer, I want CloudWatch to remain for AWS ECS health later—not as the VPS app log brain—so that we do not dual-write telemetry for free-tier optics.
23. As a reviewer, I want deny-list tests around logging helpers, so that regressions do not start shipping Authorization headers to SaaS.
24. As a release engineer, I want rollback of instrumentation via env flags or prior release, so that a bad SDK config does not strand production.

## Implementation Decisions

### Deep modules (by responsibility)

1. **Runtime log & metrics bridge** — Emit structured logs and RED metrics from the
   public API (and Demo server where applicable) to OpenObserve Cloud; enforce deny-list
   redaction; include `request_id` and `release_sha`.
2. **Request identity** — Ensure every API request has a `request_id` (accept inbound or
   generate); echo on responses; include in structured logs.
3. **Demo reliability analytics** — Initialize PostHog on Demo only; emit `reliability.*`
   page/journey/error events; sampled replay; scrub forms/query strings; no seller KPI
   events.
4. **Deploy markers** — On successful release/cutover, record `release_sha` (and time)
   into OpenObserve and PostHog so both planes share a release dimension.
5. **Alerting** — Keep existing uptime → Slack; add OpenObserve alert rules for API 5xx
   rate and health failure to the same Slack channel pattern.
6. **Secrets & config** — Store OpenObserve and PostHog credentials in Secrets Manager;
   feature flags/env to disable SDKs for rollback.
7. **Governance docs** — EXECUTION Phase 2.11, MODULES §15 + §12.1, ADR-039, runbook
   notes for eng login to vendor UIs and retention policy.
8. **Release evidence (thin)** — Named surfaces (Demo + API), smoke that shells/health
   still pass with SDKs on, assert no secrets in client bundles, rollback assertion.

### Architectural decisions (grill → ADR-039)

- Phase **2.11** before Phase 3 (not 3.1); planning on `2.11` branch.
- Thin MVP now; **2.11-B** for S3 archive, deep traces, full correlation, Landing product
  events ownership expansion.
- OpenObserve Cloud + PostHog Cloud; no OO self-host on product VPS; no CloudWatch as
  primary VPS app store.
- Hot retention then S3 archive **policy** in 2.11; **export jobs** in 2.11-B.
- MODULES: §15 DOCP vs §12.1 ECS (#498).
- Alerts: Slack only in 2.11; correlation: `request_id` + `release_sha` only.

### Schema / API

- No seller product schema changes required for 2.11.
- API responses gain/keep `request_id` (header and/or envelope — match existing patterns
  if present; otherwise prefer response header + log field).

## Testing Decisions

- Prefer behavior tests: redaction helpers reject forbidden keys; middleware assigns
  `request_id`; PostHog client only loads when configured; event names use
  `reliability.` prefix; deploy marker emitter formats SHA correctly.
- Do not require live OpenObserve/PostHog network calls in CI — mock exporters.
- Prior art: uptime workflow tests, deploy smoke scripts, Secrets Manager fetch patterns,
  Demo e2e smoke for release evidence.
- Modules under test: request identity, redaction, Demo PostHog init/events (unit),
  deploy marker helper, release-evidence plan artifact presence for instrumentation issues.

## Out of Scope

- Custom unified observability dashboard / seller-facing observability UI
- Seller KPI Analytics, Decisions BI, GMV/ROAS/SPS in PostHog
- Self-hosted OpenObserve on the product VPS; Docker observability stack on that host
- CloudWatch as primary app logs/metrics/replay store; dual-write OO + CloudWatch
- S3 cold archive export jobs (Phase 2.11-B)
- Full distributed tracing / DB APM / automated change→deploy→user graph (2.11-B)
- Landing `product.*` engagement instrumentation (Phase 3)
- iOS / Dashboard rebuild instrumentation
- PagerDuty / non-Slack paging
- ECS candidate platform (#498) — tracked under MODULES §12.1, not this PRD’s exit
- Replacing ADR-035 ECS target or VPS SSH deploy model

## Further Notes

- **Cost:** SaaS ingest + PostHog tier dominate; keep sampling and retention tight;
  AWS startup credits reserved mainly for later S3 archive and ECS (#498), not for
  replacing OO/PostHog in 2.11.
- **Risk:** Until 2.11-B archive runs, data older than hot retention may be lost —
  acceptable for MVP if documented.
- **Risk:** PostHog namespace discipline (`reliability.*` vs `product.*`) must be
  reviewed in PR checklist.
- **Rollout:** instrument behind env flags; thin release-evidence; keep uptime.yml.
- **Follow-up:** `to-issues` for 2.11 implementation slices; separate brief/PRD for
  2.11-B when ready.
