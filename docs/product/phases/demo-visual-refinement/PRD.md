# PRD: Demo Visual & Decisions Copy Refinement

> **Canonical docs:** [`EXECUTION.md`](../../../../EXECUTION.md) ·
> [ADR-023](../../../adr/023-four-destination-analytics-ownership.md) (four-destination IA) ·
> [ADR-015](../../../adr/015-design-system-token-foundation.md) (tokens) ·
> [ADR-028](../../../adr/028-vietnamese-copy-dictionary-and-design-context.md) (copy authority) ·
> [ADR-037](../../../adr/037-phase-2.10-demo-real-data-no-auth.md) ·
> [ADR-038](../../../adr/038-phase-2.10-dual-layer-pipeline.md) ·
> [ADR-041](../../../adr/041-frontend-design-skill-wiring.md) (durable skill wiring) ·
> [`docs/product/design/`](../../design/README.md) ·
> [`CONTEXT.md`](../../../../CONTEXT.md).
>
> **Parent issue:** [#580](https://github.com/thienphung00/Juli-AI/issues/580) — filed via
> `to-prd` from grill-with-docs (2026-07-29).
>
> **Compatibility:** Phase 2.10 dual-layer wire ([#534](https://github.com/thienphung00/Juli-AI/issues/534) and siblings); no IA conflict; In Progress sub-tab untouched.

## Assumptions

- Grill handoff (2026-07-29) is authoritative; no re-interview.
- IA remains ADR-023 four destinations; no greenfield rebuild.
- Copy authority stays `dictionary.md` + `design-context.md`; Airtable and Mobbin are never copy SoT.
- Decision intelligence reuses existing Decision envelope, fixtures, and Phase 2.10 feed when available — no new ranking engine.
- Default tests cover seller-surface copy guards, Recommendations routing/presentation, five-stage review navigation, Settings disabled state, and `@juli/ui` regressions on touched surfaces.
- The **design reference pipeline** (Airtable extract) runs once for this PRD; **durable skill wiring** ([ADR-041](../../../adr/041-frontend-design-skill-wiring.md)) is a separate acceptance workstream.

## Problem Statement

The public Demo implements the correct four-destination IA and is wiring to real data in
Phase 2.10, but the visual layer, Home iconography, Analytics polish, and Decisions
Recommendations copy still feel rough: backend jargon leaks into seller UI, deprecated
confidence/FBS badges clutter cards, and the five-stage review flow does not read as a
coherent seller journey. Agents also lack a stable, documented path for gathering design
references before implementing — leading to ad-hoc polish or conflicting tool choices.

Sellers and visitors need a Demo that looks intentional, speaks clear benefit-led
Vietnamese, and walks Recommendations through Why → Analytics → Inputs → Preview →
Approve — without redesigning IA, touching In Progress, or inventing new backend
intelligence.

## Solution

Two coordinated workstreams:

### Workstream A — Demo visual & copy refinement (product)

Within locked ADR-023 IA, ship a visual/copy/UX pass on **Home**, **Decisions
(Recommendations only)**, **Analytics**, and **Settings (disabled placeholder only)**:

- Run a **one-shot design reference pipeline** for layout inspiration: Airtable → Open
  Design extract → Mobbin problem-section refs → Meta-prepared caches → design
  sub-agents → Shadcn atom refinement → implement in `@juli/ui` / `apps/demo`.
- **Home:** refresh destination-card iconography (Lucide/Shadcn-sourced, folded into
  `@juli/ui`).
- **Analytics:** visual polish only — spacing, hierarchy, chart chrome — no new metrics
  or IA changes.
- **Decisions / Recommendations:** fix presentation and routing; implement seller-language
  five-stage review; tighten card copy (signal + one reason); strip backend jargon from
  rendered UI; wire to existing Decision envelope / fixtures / 2.10 feed when available.
- **Settings:** keep nav destination; interaction disabled for visitors (`aria-disabled` /
  placeholder pattern like Sign-in); no visual polish beyond disabled state.
- **Copy cleanup:** remove "Có thể thực thi qua FBS" and "Độ tin cậy: Cao/…" from UI
  **and** `dictionary.md`; keep machine fields in fixtures/code only.

### Workstream B — Durable design skill wiring (harness)

Implement [ADR-041](../../../adr/041-frontend-design-skill-wiring.md):

- Restore/add Open Design skill; register Open Design + Mobbin in skill-catalog and Focus
  for design-reference tasks.
- Confirm routing: Open Design + Mobbin **upstream** of `ui-ux-design`; `ui-ux` remains
  implementation executor; Shadcn atoms-only, folded into `@juli/ui`.
- Update slice-routing where design slices need upstream references before executor
  assignment.
- **Do not** register the Airtable-first Meta pipeline as permanent harness infrastructure.

## Deep modules (expected)

| Module | Responsibility | Public interface (words) |
|--------|----------------|--------------------------|
| Design reference orchestrator (ephemeral) | One-shot Airtable extract → OD layouts → Mobbin refs → cached artifacts for sub-agents | Produce reference bundles per destination/section; no runtime API |
| Demo Home shell | Sparse launchpad cards with refreshed icons | Two prominent cards: Decisions, Analytics |
| Demo Analytics views | Visual polish on existing KPI/chart surfaces | Same data contracts; improved hierarchy and chrome |
| Recommendations panel | Card list presentation + routing into detail | Ranked cards; Approve/Reject/Expand; seller copy only |
| Five-stage review flow | Why → Analytics → Inputs → Preview → Approve | Stage navigation; seller language; existing Decision payload |
| Seller copy sanitizer | Strip jargon and deprecated badges from rendered strings | Dictionary-driven VI; fixtures retain machine fields |
| Settings disabled gate | Non-interactive Settings for visitors | aria-disabled + visible placeholder explanation |
| `@juli/ui` atom fold-in | Absorb Shadcn-refined primitives | Exported components matching ADR-015 tokens |
| Focus/skill-catalog wiring | Durable OD + Mobbin upstream routing | Design-task detection → reference skills → ui-ux executor |

## User Stories

### Visitor / seller experience

1. As a visitor, I want Home to show clear, polished Decisions and Analytics cards with recognizable icons, so that I immediately know where to go.
2. As a visitor, I want Home to stay a sparse launchpad with exactly two prominent cards, so that ADR-023 IA is preserved.
3. As a visitor, I want Analytics charts and KPI chrome to feel cohesive and readable, so that I trust the data presentation without new metrics being invented.
4. As a visitor, I want Analytics to keep the same six Main KPI structure and hero/selector layout, so that IA and contracts do not shift under me.
5. As a visitor, I want Recommendation cards to show a clear signal and one concise reason, so that I understand why Juli suggests an action without reading backend jargon.
6. As a visitor, I want Recommendation cards to never show webhooks, endpoints, feature IDs, tool names, or FBS/FBT badges, so that the product speaks seller language.
7. As a visitor, I want "Độ tin cậy" and "Có thể thực thi qua FBS" removed everywhere in the Demo UI, so that outdated copy does not undermine trust.
8. As a visitor, I want to open a Recommendation and walk Why → Analytics → Inputs → Preview → Approve in plain Vietnamese, so that the decision feels guided and controlled.
9. As a visitor, I want the Analytics stage in review to link to evidence I can inspect, so that recommendations feel grounded in shop performance.
10. As a visitor, I want Inputs and Preview stages to use prefilled, editable seller fields without exposing internal workflow step names, so that I focus on decisions not integrations.
11. As a visitor, I want Approve to open the existing approval gate with seller-facing labels, so that human control is obvious.
12. As a visitor, I want Reject and Expand to behave as today but with tightened copy, so that interactions stay familiar while wording improves.
13. As a visitor, I want Settings to remain in navigation but clearly disabled with an accessible explanation, so that I know configuration exists but is not available without Sign-in.
14. As a visitor, I want Settings to look like a placeholder — not a half-polished config surface — so that expectations stay honest.
15. As a visitor, I want all visible copy in benefit-led, short Vietnamese with correct diacritics, so that the Demo feels native and persuasive.
16. As a visitor, I want verbose eligibility blocks, knownLimits, and risks omitted from cards unless the review step genuinely needs them, so that cards stay scannable.
17. As a visitor, I want In Progress to behave exactly as before, so that deferred redesign is not accidentally disturbed.
18. As a visitor exploring Decisions after Phase 2.10 wire, I want Recommendations to consume the same Decision envelope as live data when available, so that polish applies to real and mock paths consistently.

### Design & implementation agents

19. As a design agent, I want Open Design extracts from the Airtable reference for this PRD, so that layout/component patterns are available before coding.
20. As a design agent, I want Mobbin screen references for problem sections, so that I can adapt proven patterns to Juli tokens — not clone them.
21. As a design agent, I want Meta to pass prepared caches/artifacts and skill wiring to design sub-agents, so that reference gathering is not repeated ad hoc.
22. As a design agent, I want Shadcn limited to atom refinement, so that page composition stays in `@juli/ui` and ADR-015 tokens.
23. As an implementation agent, I want Focus to load Open Design + Mobbin before `ui-ux-design` on design tasks, so that references precede code ([ADR-041](../../../adr/041-frontend-design-skill-wiring.md)).
24. As an implementation agent, I want `dictionary.md` and `design-context.md` loaded for every copy touch, so that ADR-028 authority is preserved.
25. As an implementation agent, I want hybrid `@juli/ui` + `@juli/theme` to remain the Demo composition surface, so that I do not rewrite pages in raw shadcn.

### Copy & content governance

26. As a copy reviewer, I want removed strings deleted from `dictionary.md` as well as UI, so that agents do not reintroduce deprecated phrasing.
27. As a copy reviewer, I want new seller strings added as dictionary keys before use, so that wording stays centralized.
28. As a copy reviewer, I want design-context rules applied (address form, money/dates, error patterns), so that voice stays consistent.
29. As a product owner, I want Airtable treated as layout reference only for this PRD, so that we do not create a second copy or IA source of truth.
30. As a product owner, I want Mobbin treated as inspiration only, so that Juli brand tokens and Vietnamese copy remain authoritative.

### QA & accessibility

31. As a QA engineer, I want tests asserting banned strings ("Độ tin cậy", "Có thể thực thi qua FBS", tool_name patterns) do not render in Demo UI, so that regressions are caught.
32. As a QA engineer, I want five-stage review navigation covered by behavioral tests, so that routing fixes do not break silently.
33. As a QA engineer, I want Settings disabled state to meet the same accessibility pattern as Sign-in stub, so that visitors are not trapped in dead controls.
34. As an a11y reviewer, I want focus order and aria labels preserved through visual polish, so that prettier UI does not harm keyboard users.
35. As a QA engineer, I want Home icon changes covered by snapshot or role-based tests, so that card targets remain identifiable.

### Platform & harness

36. As Meta, I want skill-catalog entries for Open Design and Mobbin on design-reference tasks, so that Focus routing is explicit ([ADR-041](../../../adr/041-frontend-design-skill-wiring.md)).
37. As Meta, I want slice-routing updated for design slices, so that upstream references load before `ui-ux` executor assignment.
38. As Meta, I want the Airtable-first pipeline **not** persisted in agent-runtime config after this PRD, so that harness complexity stays bounded.
39. As a frontend engineer, I want Shadcn-refined atoms migrated into `@juli/ui` when touched, so that the package remains the long-lived primitive source.
40. As a Phase 2.10 engineer, I want this refinement compatible with #534 Demo wire, so that visual polish can land on mock or live envelopes without blocking data work.

## Implementation Decisions

### Scope & IA

- **In scope destinations:** Home, Decisions (Recommendations sub-tab only), Analytics, Settings (disabled gate only).
- **IA lock:** ADR-023 four destinations; no new tabs, no Analytics metric additions, no Settings configuration UI.
- **In Progress:** **DO NOT TOUCH** — leave presentation, statuses, and routes as-is.
- **Phase 2.10 compatibility:** Refinement may land before, during, or after #534; Decision read path uses envelope/fixtures/2.10 API when present — no new backend scoring.

### This-PRD design reference pipeline (ephemeral)

1. Extract layout/component patterns from **Airtable** (one-shot visual reference).
2. Materialize extracts in **Open Design** (components/layouts).
3. Search **Mobbin** for problem-section screen references; adapt to Juli tokens — not 1:1 specs.
4. **Meta** prepares caches/artifacts and passes skill wiring to design sub-agents.
5. **Shadcn** refines atoms; fold into `@juli/ui`.
6. **`ui-ux-design` + `ui-ux` executor** implement in `apps/demo`.

This pipeline is **not** registered as permanent Meta/harness infrastructure.

### Durable skill wiring (Workstream B)

Per [ADR-041](../../../adr/041-frontend-design-skill-wiring.md):

- Restore/add Open Design skill; register OD + Mobbin in skill-catalog and Focus.
- Open Design **upstream** of `ui-ux-design`; does not replace it.
- `ui-ux` remains implementation executor for Next.js Demo/dashboard slices.
- Shadcn **atoms only**; `@juli/ui` + `@juli/theme` remain Demo composition surface.

Acceptance: Focus routing table + slice-routing.yml reflect the stack; design tasks document the upstream → executor order.

### Components & theming

- **Hybrid model:** keep `@juli/ui` + `@juli/theme`; no wholesale Demo→shadcn migration.
- **Home icons:** Lucide/Shadcn-sourced, exported via `@juli/ui`.
- **Analytics:** visual polish only — typography, spacing, chart chrome, empty/loading states.
- **Tokens:** ADR-015 semantic palette and motion rules unchanged.

### Decisions / Recommendations

- Fix **presentation and routing** for Recommendations list → detail.
- Implement **five-stage review:** Why → Analytics → Inputs → Preview → Approve with seller language.
- Wire to existing **Decision envelope** / fixtures / Phase 2.10 public read when available.
- **No new recommendation engine** or ranking logic.
- Card copy: **signal + one reason**; drop verbose eligibility/knownLimits/risks unless a review stage requires them.

### Copy rules

- **Remove entirely:** "Có thể thực thi qua FBS", "Độ tin cậy: Cao/…" (and variants) from UI and `dictionary.md`.
- **Seller surface:** no webhooks, endpoints, `feature_id`, tool names, FBS/FBT badges in rendered Demo UI.
- **Fixtures/code:** machine fields may remain for dry-run; never render in Demo UI.
- **Authority:** `dictionary.md` + `design-context.md` ([ADR-028](../../../adr/028-vietnamese-copy-dictionary-and-design-context.md)).
- **Copywriting bar:** clear, persuasive, short Vietnamese — benefit-led, one idea per line.

### Settings

- Keep Settings in bottom/side nav.
- Disable interaction for visitors (`aria-disabled`, visible placeholder copy mirroring Sign-in stub pattern).
- No configuration templates polish, no threshold editors, no workflow template UI work.

## Testing Decisions

- **Behavior over implementation:** assert rendered seller copy, navigation stages, and disabled Settings — not internal fixture field names.
- **Copy guard tests:** Demo UI must not render banned confidence/FBS strings or backend jargon patterns agreed in this PRD.
- **Five-stage review:** route transitions and stage headings in Vietnamese; Approve gate reachable from Preview.
- **Settings:** disabled control exposes explanation; no navigation to editable config.
- **Home / Analytics:** visual regressions via existing demo test patterns + key `data-testid` anchors.
- **`@juli/ui`:** unit/snapshot tests for new or changed exported atoms when Shadcn fold-in occurs.
- **Skill wiring:** documentation/routing acceptance via skill-catalog and slice-routing review — no live Mobbin/OD calls required in CI.
- **Prior art:** `apps/demo` component tests, `apps/dashboard` recommendation card tests (confidence removal precedent), demo contract markers where applicable.

## Out of Scope

- **In Progress** sub-tab — any visual, copy, routing, or status changes.
- **Settings polish** beyond disabled placeholder state.
- **IA changes** — new destinations, tabs, KPI sets, or Analytics ownership shifts.
- **New ranking/recommendation backend** or ML scoring.
- **Permanent Airtable-first Meta pipeline** in agent-runtime.
- **Full shadcn migration** of Demo pages or deletion of `@juli/ui`.
- **Mobbin or Airtable as copy or IA authority.**
- **Landing** (`apps/landing`) and **Sign-in/OAuth** (Phase 3).
- **Phase 2.11 DOCP** instrumentation.
- **Wholesale redesign** of design package root authorities (`design.md`, `flows.md`, etc.) unless required to resolve a conflict found during implementation.

## Further Notes

### Relationship to Phase 2.10

This PRD is a **presentation-layer refinement** compatible with Phase 2.10 dual-layer wire
([ADR-038](../../../adr/038-phase-2.10-dual-layer-pipeline.md)). It may proceed in parallel
with #534; Recommendations should read from the same Decision envelope whether data is
fixture- or API-backed.

### Workstream sequencing

Workstream A may begin reference extraction while Workstream B lands harness routing.
Durable skill wiring (B) should complete before broad agent-driven polish so sub-agents
follow ADR-041 consistently.

### Risks

- Reintroducing deprecated copy via stale dictionary keys — mitigate with removal + guard tests.
- Accidental In Progress edits — mitigate with explicit path filters in issues and review checklist.
- Over-scoping Settings — mitigate with disabled-only acceptance criteria.
- Treating Mobbin/Airtable output as authoritative copy — mitigate via ADR-028 workflow and review.

### Rollout

- Ship incrementally by destination (Home → Analytics → Recommendations → copy dictionary cleanup).
- No migration or feature flag required beyond existing Mock/Sign-in mode.
- Public Demo deploy follows standard PR + Merge Queue path.

### Follow-ups (not this PRD)

- In Progress redesign (deferred).
- Settings full configuration UI (Phase 3+ Sign-in).
- Landing visual alignment (Phase 2.7 / Phase 3).
