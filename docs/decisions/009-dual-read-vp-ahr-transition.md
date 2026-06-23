# ADR-009: Dual-read VP + AHR during platform transition

## Status
Accepted

## Context

TikTok Shop VN is replacing Violation Points (VP) with Account Health Rating (AHR):

| Milestone | Date |
|-----------|------|
| May 2026 | AHR preview — visible, reference only; enforcement on VP |
| Mid-June 2026 | AHR begins gradual replacement |
| July 2026 | AHR fully replaces VP |

Juli Phase 2 (weeks 9–13) deploys live API polling and daily inference. The VP → AHR
transition window (May–July 2026) overlaps Phase 2 production rollout. Reading only
VP after July 2026 or only AHR before enforcement switches would produce incorrect
gates and alerts.

## Decision

- We will: Implement dual-read of VP and AHR from May 2026 through July 2026 cutover.
  Use VP milestones for enforcement-aligned gates until July 2026; use AHR zones
  (Green 200–1000, Orange 151–199, Red 1–150, Black 0) as the post-cutover source
  of truth. Control the switch via a feature flag (`health_check_mode: vp | dual | ahr`).
- We will not: Hard-cut to AHR on a fixed calendar date without verifying TikTok's
  enforcement has switched for the seller's shop.

## Why this architecture

- **Reliability:** Avoids false negatives during a platform-managed migration.
- **Operability:** Feature flag allows rollback if TikTok delays cutover.
- **Speed:** Dual-read is additive — no rewrite of alert logic, only input selection.

## Options considered

- **Option A: VP-only until forced migration** → Pros: simple. Cons: stale after July 2026.
- **Option B: AHR-only from May preview** → Pros: forward-looking. Cons: enforcement
  still on VP until July — false positives on gates.
- **Option C: Dual-read with feature flag (chosen)** → Pros: safe overlap window.

## Consequences

- **Positive:** Correct gates and alerts across the entire transition window.
- **Negative:** Two health fields to poll, store, and test; transition test matrix grows.
- **Follow-ups:** Add `health_check_mode` to env/config; document in P2-1 polling job;
  schedule flag flip review for July 2026.

## Rollout / Migration plan

1. **May 2026:** `health_check_mode=dual`; AHR stored but VP drives gates/alerts.
2. **July 2026:** Verify TikTok enforcement on AHR for pilot shops; flip to `ahr`.
3. **Post-cutover:** Retain VP field read-only for 90 days (VP reset cycle), then drop.
