# ADR-004: Alerts module with pluggable channel adapters

**Status:** Accepted  
**Date:** 2026-05-27  
**Deciders:** Engineering

## Context

MVP sellers need threshold-based alerts (revenue milestones, low stock, anomalies,
policy risk) delivered through push channels. PRD stories #38–#41 require a rule
engine, per-shop configuration, deduplication, and FCM as the always-on channel
with room for Zalo OA (#40) without rewriting core logic.

## Decision

Introduce `src/alerts` as a Tier-2 module that:

1. Persists rules via existing `AlertConfig` / `AlertHistory` in `src/data`
   (adds `threshold_json` and unique `(shop_id, alert_type)`).
2. Exposes `evaluate_rules`, `configure_rules`, and `deliver_alert` as the public API.
3. Defines `ChannelAdapter` protocol; ships `FcmAdapter` with retry + exponential backoff.
4. Enforces per-`alert_type` cooldown (default 3600s) using `AlertHistory`.

## Rationale

- Keeps delivery channels swappable (FCM now, Zalo #40 next) per execution plan.
- Reuses commerce analytics tables from #28 instead of a parallel config store.
- Integration tests target module-level pytest functions for CI acceptance mapping.

## Consequences

- **Positive:** Unblocks API alerts slice (#43), Zalo adapter (#40), iOS push (#46).
- **Negative:** FCM HTTP v1 wiring remains a follow-up behind injectable `_send_fn`.
- **Migration:** `003_alert_config_threshold` must run before configuring thresholds.
