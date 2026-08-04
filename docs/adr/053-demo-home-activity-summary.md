# ADR-053: Demo Home activity summary (apps/demo Home only)

**Status:** Accepted
**Date:** 2026-08-03
**Deciders:** grill-with-docs (Architect)

**Amends:** [ADR-023](023-four-destination-analytics-ownership.md) Decision item 2
(Home composition) for **`apps/demo` Home only**.
**Related:** [#600](https://github.com/thienphung00/Juli-AI/issues/600) Demo UI fix PRD —
amends that PRD's Home user story (#39) and acceptance theme in the same change.
**Does not change:** ADR-023 four-destination IA; Decisions' exclusive ownership of the
recommendation approval gate; Analytics' exclusive ownership of KPIs/charts/reporting;
authenticated `apps/dashboard` Home (a separate, already-richer experience — out of scope
here).

## Context

`apps/demo` Home is a sparse launchpad: two destination cards (Decisions, Analytics) and
nothing else. Reviewed against the PRD #600 goal of making the Demo feel less passive/
AI-generic, a bare launchpad gives a first-time visitor no signal that Juli has already
done anything — the first screen should prompt "how do I optimize my shop further?" by
showing what Juli has completed, what's running, and what needs the seller's attention,
without turning Home into a second Decisions surface.

Alternatives considered:

| Option | Outcome |
|--------|---------|
| A — Keep the bare two-card launchpad | Preserves ADR-023 literally but stays passive/empty; rejected per user direction |
| B — Move full recommendation cards onto Home | Duplicates Decisions' approval gate on two screens; violates ADR-023's ownership split; rejected |
| **C — Summary-only activity strip above the two cards (chosen)** | Answers "what's happened / what's next" in one glance; no new actions live on Home; existing lifecycle vocabulary reused |

## Decision

1. `apps/demo` Home gains one **summary-only activity section**, rendered above the
   existing two launcher cards (Decisions, Analytics), which are unchanged in role and
   remain the two prominent clickable destinations.
2. The section shows exactly three counts, reusing existing lifecycle/tab vocabulary —
   no new terms are coined:
   | Tile | Meaning | Label | Source |
   |------|---------|-------|--------|
   | Done | Completed executions | **Hoàn tất** | `ExecutionLifecycleStatus.completed` count |
   | Running | Executing or awaiting input | **Đang thực hiện** | `executing` + `needs_input` count |
   | Needs attention | Open recommendations awaiting review | **Đề xuất cần xem xét** | Same count already shown on the Decisions tab/card |
3. Each tile is a **count only** — no per-item list, no Approve/Reject, no execution
   detail, no recommendation card content on Home. Tapping a tile routes to Decisions
   (Recommendations tab for "needs attention"; In Progress tab for "done"/"running").
   Home never exposes the approval gate directly — that stays Decisions-exclusive.
4. First-run/empty state (no executions and no recommendations yet): render one calm
   explanatory state instead of three zero-value tiles.
5. Home's mental model changes from strictly "Where do I want to go?" to "What has Juli
   done for me, and where do I go next?" — it still is not a metrics/KPI surface;
   Analytics keeps exclusive ownership of all KPI/chart/reporting content.

## Rationale

A summary strip answers the "what's happening" question a returning seller actually has
without re-implementing Decisions' recommendation review or execution detail on a second
screen. Reusing the exact lifecycle/tab vocabulary already shipped in
`in-progress-panel.tsx` and `recommendations-panel.tsx` means no new glossary term, no
translation drift, and no second source of truth for these counts.

## Consequences

- `docs/product/design/soul.md`, `design.md`, `ux_principles.md`, and `Screens/home.md`
  update Home's "forbidden" language to distinguish **summary counts** (now allowed) from
  **queues, lists, and approval actions** (still forbidden on Home).
- PRD #600's Home user story (#39) and its acceptance theme are amended to reference this
  ADR instead of asserting a bare two-card launchpad.
- `apps/dashboard` Home is unaffected — it already runs a separate, richer authenticated
  Home (`SellerHomeShell` / `HomeSummaryShell`) that this ADR does not touch or reconcile.
- Adding a fourth tile or any per-item detail to the Home section requires a new ADR
  amendment — this one caps the section at exactly three counts, summary-only.
