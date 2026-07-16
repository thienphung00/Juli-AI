# ADR 026: Analytics becomes a non-blocking Phase 2.6 exit-gate item

## Status

Accepted

**Builds on:** [ADR-023](023-four-destination-analytics-ownership.md) (four-destination
IA; Analytics as one of four locked primary destinations) and
[ADR-024](024-phase-2.6-2.7-frontend-resequencing.md) (Phase 2.6 scope and exit gate).
**Precedent:** issue #405 already made full editable Settings a non-blocking Phase 2.6
stretch goal, with a truthful placeholder permitted at exit. This ADR applies the same
pattern to Analytics (#404).

## Context

Grilling the Phase 2.6 PRD (2026-07-16) surfaced that the PRD's Exit Gate section and
issue #407 (verify) both treat the full six-KPI Analytics experience (#404) as a hard
blocker — #407 lists "Blocked by #401, #402, #403, #404, and #406," and #408 (publish)
requires "real Home, Decisions, and Analytics routes over HTTPS." This is a stronger
commitment than Settings, which #405 already exempted from the exit gate.

Analytics is one of ADR-023's four locked primary destinations, so removing it from the
exit gate reverses a previously-explicit, named requirement — this is hard to reverse
without a written record, surprising to a future reader without context, and involves a
real trade-off (schedule/risk reduction vs. full-IA completeness at public launch).

## Decision

1. Full six-KPI Analytics (#404) becomes a **non-blocking Phase 2.6 stretch goal**,
   mirroring #405's treatment of Settings exactly. A truthful Analytics placeholder
   (visible, honest "not yet available" state — never fabricated KPI values) is
   sufficient for exit.
2. Home's Analytics launcher card is unaffected — Home always renders both cards
   per ADR-023 regardless of what `/analytics` currently renders.
3. `docs/product/phases/phase-2.6/PRD.md`'s Exit Gate section is corrected to name both
   Settings and Analytics as non-blocking stretch goals with truthful-placeholder
   fallback.
4. Issue #407 drops #404 from its "Blocked by" list and gains an explicit AC line
   ("Exit gate does not depend on optional Analytics issue #404"), matching its existing
   #405 exemption line.
5. Issue #408 drops the mandatory "real ... Analytics routes" requirement; Analytics is
   verified only if shipped, never blocking the public release.
6. If #404 ships anyway before exit, its full acceptance criteria (unchanged) still
   apply — this ADR only removes the *requirement* to ship it, not its criteria once
   built.

## Rationale

Decoupling Analytics depth from the public launch gate, the same way Settings already
was decoupled, lets Phase 2.6 ship on schedule even if the six-KPI build proves larger
than estimated, without pretending Analytics is complete. Sellers and reviewers still
see a real four-destination shell (ADR-023 unchanged); only the *depth* of one
destination's content is deferred, consistent with the mock/no-fabrication invariant
already required everywhere else in the Demo.

## Consequences

- `docs/product/phases/phase-2.6/PRD.md` Exit Gate, User Story 7, and Testing Decisions
  sections are corrected to reflect Analytics as optional (this ADR's companion edit).
- Issue #407's "Blocked by" list and AC, and #408's route requirement, are corrected to
  match (this ADR's companion edit).
- If #404 later ships, no further ADR is needed to re-tighten the gate — the
  full-acceptance-criteria requirement in #404 was never relaxed, only its blocking
  status.
- `EXECUTION.md`'s Phase 2.6 exit-gate description should note both Settings and
  Analytics as non-blocking stretch goals in its next edit pass.
