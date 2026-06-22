# ADR 005: Alert on VP/AHR milestones — not silent degradation

## Status
Accepted

## Context

TikTok Shop VN enforces seller account health through Violation Points (VP) milestones
at 12 / 24 / 36 / 48, transitioning to Account Health Rating (AHR) milestones at
150 / 100 / 50 / 0 (July 2026). At VP ≥ 12, affiliate enrollment and campaign
enrollment are blocked for 7 days — a direct revenue impact.

Juli must surface these threshold hits proactively as **in-workflow policy signals**,
not a standalone alerts microservice.

## Decision

- We will: Fire deterministic alerts when seller VP or AHR crosses documented milestones.
  VP ≥ 7 → warn; VP ≥ 12 → affiliate blocked alert + suppress recruitment recommendations;
  VP ≥ 24 → critical stabilization alert; AHR ≤ 199 / ≤ 150 → equivalent post-July 2026.
- We will not: Silently downgrade affiliate or growth recommendations without surfacing
  the underlying policy reason to the seller.

## Consequences

- Phase 2 MVP: VP-based alerts active alongside API polling.
- May–July 2026: dual-read VP + AHR ([ADR-006](006-dual-read-vp-ahr-transition.md)).
- Post-July 2026: AHR-primary alerts; VP read deprecated.
