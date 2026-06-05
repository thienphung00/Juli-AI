# ADR-010: VN-specific regional platform configuration

## Status
Accepted

## Context

TikTok Shop platform rules vary by market. The `platform-docs` pass for VN
(seller-vn.tiktok.com) surfaced region-specific constraints that differ from
global defaults:

| Rule | VN value | Typical global assumption |
|------|----------|--------------------------|
| Creator affiliate tier threshold | ≥ 1,000 followers | May differ by market |
| Creator KYC / tax code | CCCD = tax code; mandatory since Jul 1, 2025 | Not all markets |
| CHR / AHR zone boundaries | Green 200–1000, Orange 151–199, Red 1–150, Black 0 | Scale may differ |
| New seller AHR start | 200 | May differ |
| Commission settlement | 3rd or 15th day after delivery | May differ |
| VP → AHR transition | May–July 2026 (VN announcement) | Market-specific rollout |

Juli launches in Vietnam first. Hard-coding VN thresholds in application logic would
block multi-market expansion and create compliance risk if thresholds change per region.

## Decision

- We will: Model platform policy thresholds as **region-variant configuration**
  keyed by shop/creator `region` (default `VN`). Store thresholds in config (env or
  DB seed), not inline magic numbers. Reference source articles in
  `docs/tiktok_platform/`.
- We will not: Assume global TikTok policy applies to all shops without region lookup.

## Why this architecture

- **Scalability:** Adding TH, ID, or other markets is a config seed, not a refactor.
- **Reliability:** VN tax-code mandate is a hard gate — wrong region = wrong compliance.
- **Maintainability:** Platform-docs updates flow to config seeds + operational rules.

## Options considered

- **Option A: Hard-code VN constants** → Pros: fastest Phase 2. Cons: blocks expansion.
- **Option B: Region-variant config (chosen)** → Pros: correct abstraction for VN-first,
  multi-market later. Cons: small config layer upfront.

## Consequences

- **Positive:** VN compliance rules (tax code, follower tier, CHR zones) are explicit
  and testable per region.
- **Negative:** Config surface to maintain when TikTok updates regional policy.
- **Follow-ups:** Define `PlatformPolicyConfig` schema in Phase 2; seed VN defaults from
  implementation-hooks; add region field to shop/creator records if not present.

## Rollout / Migration plan

- Phase 2: Single region `VN` in config; all shops default to VN thresholds.
- Phase 3+ (multi-market): Add region seeds per `docs/<vendor>_platform/` pass.
