# ADR 007: VN-specific regional platform configuration

## Status
Accepted

## Context

TikTok Shop platform rules vary by market. Juli launches in Vietnam first. Hard-coding
VN thresholds in application logic would block multi-market expansion.

Key VN-specific rules: creator affiliate tier ≥ 1,000 followers; CCCD = tax code;
CHR/AHR zone boundaries; VP → AHR transition May–July 2026.

## Decision

- We will: Model platform policy thresholds as **region-variant configuration**
  keyed by shop/creator `region` (default `VN`). Store thresholds in config, not
  inline magic numbers. Reference source articles in `docs/tiktok_platform/`.
- We will not: Assume global TikTok policy applies to all shops without region lookup.

## Rationale

Consolidates seller-money rescope: keeps enforcement aligned with TikTok VN policy while routing alerts through the operations pipeline instead of a standalone service.

## Consequences

- Phase 2 MVP: Single region `VN` in config; all shops default to VN thresholds.
- Phase 3+: Add region seeds per `docs/<vendor>_platform/` pass.
