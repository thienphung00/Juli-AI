# ADR 033: Weekly secrets-first security check (report + prepare)

**Status:** Accepted  
**Date:** 2026-07-23  
**Deciders:** grill-with-docs  
**Related:** [ADR-020](020-vps-ssh-continuous-delivery-and-secrets-manager.md),
[ADR-030](030-operator-cli-in-memory-secrets.md)

## Context

We need a recurring security automation as the main secrets hygiene gate: inspect
and audit secrets/keys, detect leaks, and prepare rotation when needed. A generic
medium+ AppSec hunter (authZ, SQLi, XSS, etc.) duplicates PR `bandit` /
`gitleaks` and Review `guardrails`, spreads weekly attention thin, and under-invests
in the real gap: secret inventory, VPS/web delivery, and rotation debt.

## Decision

- **Mission:** secrets-first weekly check. Also report non-secret vulns only when
  they create a validated **credential-exfiltration** path against the **repo**,
  **VPS**, or **website** (`juli-web` / dashboard).
- **Action:** report + prepare remediations (rotate steps or config/delivery fix).
  Do not execute live rotation until a human has successfully performed the same
  rotate path at least once; full automation is an explicit later unlock.
- **Live access:** repo/docs plus read-only probes (public web/API, file perms,
  SM metadata/age when IAM allows). Never put live secret **values** in chat,
  issues, or memory.
- **Inventory:** core runtime SM blobs + TikTok app/encryption keys + DB +
  Supabase + VPS AWS reader path + GHA SSH; plus sandbox CI, debug/reviewer,
  Slack webhook, Redis when session-relevant.
- **Prepare rotate when:** confirmed exposure, policy age (≥90 days without
  recorded rotation), or hygiene gap (prefer delivery/config fix when the secret
  itself is not burned).
- **Memory:** `Juli-AI-v2---flagged-secret-findings*.json` family (≤100/file);
  no Slack unless Additional Instructions say so; no `new-findings*` scratch files.
- **Human loop:** one weekly GitHub rollup issue when there are new findings;
  no PRs from this workflow.

## Consequences

- Weekly agent stays deep on secrets and leak paths that CI diff scans miss.
- Full AppSec remains change-triggered (PR + Review), not this cron.
- Rotation automation stays gated on proven manual success.

## Options considered

| Alternative | Why rejected |
|-------------|--------------|
| Full weekly medium+ AppSec | Low marginal gain vs bandit/gitleaks/guardrails; high noise; weak rotate focus |
| Report-only (no prepare) | Fails “rotate if needed” / manual-once learning loop |
| Execute rotate in phase 1 | Blast radius on single VPS with no staging |
| Slack-default posting | Unnecessary secret-finding sprawl until explicitly opted in |
