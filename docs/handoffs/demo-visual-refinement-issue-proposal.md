# Demo Visual Refinement — issue breakdown (created)

> **Parent PRD issue:** [#580](https://github.com/thienphung00/Juli-AI/issues/580)  
> **Source PRD:** [`docs/product/phases/demo-visual-refinement/PRD.md`](../product/phases/demo-visual-refinement/PRD.md)  
> **ADR:** [041 — frontend design skill wiring](../adr/041-frontend-design-skill-wiring.md)  
> **Status:** **Created** (2026-07-29, user-approved 8-slice breakdown)

## Created issues

| Slice | Issue | Title |
|-------|-------|-------|
| DVR-B1 | [#581](https://github.com/thienphung00/Juli-AI/issues/581) | ADR-041 — Wire Open Design + Mobbin upstream of ui-ux-design |
| DVR-A0 | [#583](https://github.com/thienphung00/Juli-AI/issues/583) | Ephemeral design reference bundles (Airtable → OD → Mobbin) |
| DVR-A1 | [#584](https://github.com/thienphung00/Juli-AI/issues/584) | Strip FBS/confidence copy + RecommendationCard + guard tests |
| DVR-A2 | [#586](https://github.com/thienphung00/Juli-AI/issues/586) | Home destination card icon refresh (@juli/ui) |
| DVR-A3 | [#585](https://github.com/thienphung00/Juli-AI/issues/585) | Analytics visual polish (no new metrics) |
| DVR-A4 | [#587](https://github.com/thienphung00/Juli-AI/issues/587) | Recommendations list — seller copy + signal/reason cards |
| DVR-A5 | [#588](https://github.com/thienphung00/Juli-AI/issues/588) | Five-stage review — seller language + navigation |
| DVR-A6 | [#582](https://github.com/thienphung00/Juli-AI/issues/582) | Settings visitor disabled gate (Sign-in stub pattern) |

Full bodies: [`docs/handoffs/demo-visual-refinement-issue-bodies/`](demo-visual-refinement-issue-bodies/)

## Global constraints (all slices)

- ADR-023 four-destination IA; **In Progress sub-tab DO NOT TOUCH**
- Parallel-safe with Phase 2.10 / [#534](https://github.com/thienphung00/Juli-AI/issues/534)
- No new recommendation/ranking backend
- Settings: disabled placeholder only (no config polish)
- Hybrid `@juli/ui` + Shadcn atoms-only fold-in; no full shadcn migration
- Copy authority: `dictionary.md` + `design-context.md` (ADR-028)
- Ephemeral Airtable pipeline **not** persisted in agent-runtime config

## Parallel implementation waves

| Wave | Issues | Notes |
|------|--------|-------|
| **0** | #581 (B1) | Harness routing — start first or parallel with Wave 1 |
| **1** | #583 (A0) ∥ #584 (A1) ∥ #582 (A6) | A0 is HITL; A1 touches `packages/ui` + Recommendations — **Isolate from A2/A3** until merged if editing same files |
| **2** | #586 (A2) ∥ #585 (A3) | Path-disjoint (Home vs Analytics) — **Parallel** after B1 ideally; consume A0 bundles when ready |
| **3** | #587 (A4) | After #584 merges — touches Recommendations list + shared `RecommendationCard` |
| **4** | #588 (A5) | After #587 merges — review flow + workflow review modules |

### Isolate vs Parallel (issue-workflow)

- **Parallel:** #586 + #585 (disjoint paths: `apps/demo/src/app/page.tsx` vs `apps/demo/src/app/analytics/`)
- **Parallel:** #583 + #582 (disjoint: handoff artifacts vs Settings components)
- **Isolate:** #584 before #586/#587 if all touch `packages/ui/src/recommendation-card.tsx`
- **Isolate:** #587 before #588 (hard dependency; shared `recommendation-review.tsx` / workflow review paths)
- **Shared core:** none of these slices touch `packages/contracts` — standard parallel product PR rules apply

## Dependency graph

```
#581 B1 ──(soft)──► #586 A2, #585 A3
#583 A0 ──(soft)──► #586 A2, #585 A3
#584 A1 ──────────► #587 A4 ──────────► #588 A5
#582 A6 (independent)
```
