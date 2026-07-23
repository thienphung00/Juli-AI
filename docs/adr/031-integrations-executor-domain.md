# ADR 031: Integrations executor domain (platform-agnostic)

**Status:** Accepted  
**Date:** 2026-07-23  
**Deciders:** grill-with-docs (domain skill upgrade)  
**Related:** [ADR-003](003-ai-native-cicd-policy.md) (artifact `executorDomain`),
[ADR-022](022-intent-review-guardrails-split.md) (domain skills vs structure authority),
[ADR-004](004-etl-kafka-consumer.md) (ETL handoff boundary)

## Context

Executor domain skills under `.cursor/skills/domain/` were process-heavy (TDD +
artifact handoff) and thin on Juli-specific implementer recipes. Vendor-facing work
(HTTP clients, webhooks, polling, analytics sync/backfill) was routed as `backend`,
which diluted both skills and caused ownership overlap.

Alternatives: (1) deepen only the existing four domains and keep TikTok recipes inside
`backend/REFERENCE.md`; (2) add a TikTok-branded domain skill; (3) add a fifth
**platform-agnostic** `integrations` domain with a hard boundary vs `backend` /
`data-platform`.

## Decision

1. **Add executor domain `integrations`** to the harness allowlist
   (`EXECUTOR_DOMAINS`, implementation-artifact schema, Focus/Meta routing,
   `agent-runtime.config.yml` domain skill list).
2. **`integrations` is platform-agnostic** — owns patterns for vendor clients
   (auth/signing/rate limits/retries), inbound webhooks (verify + ETL handoff),
   polling/scheduled sync, and analytics fetch/partition backfill. Vendor docs
   (`docs/integrations/<vendor>_api/`) are issue-specific loads, not the skill’s
   identity.
3. **Hard ownership boundary:**
   - `integrations` — talks to external commerce platforms.
   - `backend` — Juli product logic and `/v1/*` product API (scoring, copy, action
     cards, aggregates, Juli JWT/session auth).
   - `data-platform` — schema, migrations, repos, ETL consumer durability.
4. **Skill shape:** each domain uses `SKILL.md` (Juli recipes + load map) +
   `REFERENCE.md` (repo depth + Context7 hybrid: curated extracts for the 80% path,
   live Context7 pointers for niche/churn). Keep `domain/testing-patterns/`.
5. **Shared TDD/artifact process** lives in
   [`agent-runtime/docs/agent-runtime.md`](../../agent-runtime/docs/agent-runtime.md);
   domain `SKILL.md` files keep a thin stub + domain-specific test surfaces only.
6. **Delivery:** two PRs — (1) harness + `integrations` skill; (2) deepen the
   existing four domains.

## Consequences

- Meta can assign `integrations` without stuffing vendor I/O into `backend`.
- Adding a later marketplace (Shopee/Lazada) reuses the same domain skill; only
  vendor docs and client modules change.
- Existing open issues/artifacts that used `backend` for polling/backfill may be
  mis-tagged until Meta routing rules are updated — acceptable one-time drift.
- Domain skills must stay within Focus’s single-primary-domain injection budget;
  `REFERENCE.md` is load-on-demand, not always injected in full.
