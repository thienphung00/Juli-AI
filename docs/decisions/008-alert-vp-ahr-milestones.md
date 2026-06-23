# ADR-008: Alert on VP/AHR milestones — not silent degradation

## Status
Accepted

## Context

TikTok Shop VN enforces seller account health through Violation Points (VP) milestones
at 12 / 24 / 36 / 48, transitioning to Account Health Rating (AHR) milestones at
150 / 100 / 50 / 0 (July 2026). At VP ≥ 12, affiliate enrollment and campaign
enrollment are blocked for 7 days — a direct revenue impact.

Juli's Revenue Leakage Detection and New Seller Copilot workflows must surface these
threshold hits proactively. Silent degradation (e.g., continuing to recommend affiliate
recruitment when VP ≥ 12) would mislead sellers and erode trust.

Prior art: ADR-005 (alerts module) was superseded and removed with the matching pivot.
Phase 2 reintroduces threshold alerting as **in-workflow UI signals** tied to the three
seller-money workflows, not a standalone alerts microservice.

## Decision

- We will: Fire deterministic alerts when seller VP or AHR crosses documented milestones.
  VP ≥ 7 → warn; VP ≥ 12 → affiliate blocked alert + suppress recruitment recommendations;
  VP ≥ 24 → critical stabilization alert; AHR ≤ 199 / ≤ 150 → equivalent post-July 2026.
- We will not: Silently downgrade affiliate or growth recommendations without surfacing
  the underlying policy reason to the seller.

## Why this architecture

- **Speed:** Rule-based thresholds need no ML; ship in Phase 2 alongside API polling.
- **Reliability:** Milestone hits are binary — no model confidence ambiguity.
- **Operability:** Alerts tie to Revenue Leakage workflow bands sellers already understand.

## Options considered

- **Option A: Standalone alerts module (ADR-005 revival)** → Pros: channel adapters.
  Cons: out of Phase 2 scope; extra module maintenance. Not chosen.
- **Option B: In-workflow policy signals (chosen)** → Pros: aligns with seller-money
  workflows; no new module. Cons: no push-channel delivery until Phase 3+.

## Consequences

- **Positive:** Sellers see why affiliate recommendations stopped; aligns with TikTok enforcement.
- **Negative:** Requires daily VP/AHR polling even if API exposure is partial/UNKNOWN.
- **Follow-ups:** Confirm VP/AHR API fields in `docs/tiktok_api/endpoints.md`; implement
  P2-4 UI surfacing; load Vietnamese copy templates per implementation-hooks.

## Rollout / Migration plan

- Phase 2 launch: VP-based alerts active.
- May–July 2026: dual-read VP + AHR (see ADR-009).
- Post-July 2026: AHR-primary alerts; VP read deprecated.
