# ADR 006: Dual-read VP + AHR during platform transition

## Status
Accepted

## Context

TikTok Shop VN is replacing Violation Points (VP) with Account Health Rating (AHR):

| Milestone | Date |
|-----------|------|
| May 2026 | AHR preview — visible, reference only; enforcement on VP |
| Mid-June 2026 | AHR begins gradual replacement |
| July 2026 | AHR fully replaces VP |

The VP → AHR transition window (May–July 2026) overlaps Phase 2 MVP production rollout.

## Decision

- We will: Implement dual-read of VP and AHR from May 2026 through July 2026 cutover.
  Use VP milestones for enforcement-aligned gates until July 2026; use AHR zones
  (Green 200–1000, Orange 151–199, Red 1–150, Black 0) as the post-cutover source
  of truth. Control the switch via `health_check_mode: vp | dual | ahr`.
- We will not: Hard-cut to AHR on a fixed calendar date without verifying TikTok's
  enforcement has switched for the seller's shop.

## Rollout

1. **May 2026:** `health_check_mode=dual`; AHR stored but VP drives gates/alerts.
2. **July 2026:** Verify TikTok enforcement on AHR for pilot shops; flip to `ahr`.
3. **Post-cutover:** Retain VP field read-only for 90 days, then drop.
