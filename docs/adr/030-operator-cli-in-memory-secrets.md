# ADR 030: Operator CLI in-memory Secrets Manager inject (no on-disk env)

**Status:** Accepted  
**Date:** 2026-07-22  
**Deciders:** grill-with-docs (Phase 2.9 / #472)  
**Related:** [ADR-020](020-vps-ssh-continuous-delivery-and-secrets-manager.md) (SoT + IAM; disk
`EnvironmentFile` delivery unchanged for systemd), [ADR-029](029-phase-2.9-analytics-historical-backfill.md)

## Context

Phase 2.9 HITL (#472) needs a production-grade Fujiwa analytics backfill run. Operators
were manually exporting `DATABASE_URL`, TikTok app secrets, and encryption keys into the
shell — insecure and multi-step. ADR-020 already stores runtime secrets in AWS Secrets
Manager (`juli/api/production`) and materializes `/etc/juli/api.env` for systemd. That
on-disk env file fails the bar that **app secrets must not live as durable env files on
the VPS** for the operator backfill path.

Alternatives: source `/etc/juli/api.env` in a wrapper; fetch Secrets Manager on a laptop
with new IAM; defer secrets wiring to a follow-on after #472 merges; have the Python CLI
own boto3 fetch with no wrapper.

## Decision

- **SoT stays AWS Secrets Manager** (`juli/api/production`) with the existing VPS Roles
  Anywhere reader role (ADR-020). No new secret inventory for backfill.
- **Operator backfill path (#472):** a thin launcher fetches the secret JSON at process
  start, injects values into the **child process environment only**, and never writes
  `KEY=value` to disk / never `source`s `/etc/juli/*.env` for this path.
- **Systemd / `fetch-secrets.sh` disk delivery is unchanged for now** — full API/web
  cutover off on-disk env is an explicit follow-on ADR, not #472.
- **CLI shape:** optional `--shop-id`; default resolves Fujiwa from the
  `production_read` credential’s `shop_id`. Explicit `--shop-id` remains for later shops.
- **Credentials:** CLI keeps strict `resolve_production_read_credential` (merchant
  `7658073774813611784` + `production_read`). Prefer restore of that row from a
  known-good source; if unavailable, one-time explicit remap after a Section A smoke
  probe — never dual-accept `seller_connect`. Permanent seller grant → rotate access via
  refresh (no re-OAuth unless refresh fails).
- **Token rotation for this CLI:** force refresh at every invocation start; on Partner
  auth failure, refresh once, rebuild client, retry once, then hard-fail. Polling workers
  keep the existing 30-minute buffer.
- **Scope:** land in #472 / PR #483 (mocked Partner in CI; wrapper tests mock
  `GetSecretValue`).

## Consequences

- Operators get a single command for Fujiwa budgeted backfill without pasting secrets.
- Dual secret-delivery patterns coexist briefly (disk for systemd, in-memory for this
  CLI) until a follow-on migrates `juli-api` / `juli-web`.
- Live Fujiwa run still requires a correct `production_read` row before Partner HTTP
  succeeds — secrets wiring alone does not invent that credential.

## Options considered

| Alternative | Why rejected |
|-------------|--------------|
| Source `/etc/juli/api.env` for backfill | Leaves full secret inventory as durable plaintext on disk — fails the security bar |
| Laptop-only Secrets Manager fetch as primary | Requires new operator IAM; VPS already has Roles Anywhere |
| Dual-accept `seller_connect` in backfill CLI | Weakens P2-A1 Section A isolation |
| Defer wrapper to a follow-on after #472 | Re-creates the same insecure HITL failure mode on merge |
| Force-refresh every partition mid-run | Unnecessary given ~7d access token TTL and budgeted run length; auth-failure retry is enough |
