# ADR-043: Frontend design skill wiring — Open Design + Mobbin upstream of ui-ux

**Status:** Accepted  
**Date:** 2026-07-29  
**Deciders:** grill-with-docs (Architect)

**Builds on:** [ADR-015](015-design-system-token-foundation.md), [ADR-023](023-four-destination-analytics-ownership.md), [ADR-028](028-vietnamese-copy-dictionary-and-design-context.md), [ADR-037](037-phase-2.10-demo-real-data-no-auth.md).  
**Related (ephemeral, not durable):** Demo visual refinement PRD — one-shot Airtable → Open Design extract pipeline for layout reference only.

## Context

Demo visual refinement needs a repeatable way for agents to gather **design references**
before implementing in `apps/demo`. The grill split two concerns:

1. **This PRD only:** a full reference pipeline (Airtable layout extract → Open Design
   components/layouts → Mobbin screen search → Meta-prepared caches → design sub-agents →
   Shadcn atom refinement).
2. **Durable:** how Focus/Meta routes **all future design tasks** — without baking a
   permanent Airtable-first Meta pipeline into the harness.

Alternatives considered:

- **Permanent Airtable Meta pipeline** — rejected: Airtable is a one-shot layout
  reference for this refinement, not copy SoT or IA authority.
- **Replace `ui-ux-design` with Open Design** — rejected: Open Design is upstream
  reference generation; `ui-ux-design` remains the Next.js implementation executor.
- **Wholesale Demo → shadcn migration** — rejected: `@juli/ui` + `@juli/theme` stay the
  Demo surface; shadcn refines atoms then folds into `@juli/ui`.
- **Mobbin as binding spec** — rejected: Mobbin is inspiration only; output must adapt
  to Juli tokens ([ADR-015](015-design-system-token-foundation.md),
  `docs/product/design/`).

## Decision

1. **Durable design skill stack (Focus / skill-catalog / slice-routing):**
   - **Open Design** — upstream design-reference skill/MCP for extracting components,
     layouts, and runnable artifacts before implementation. Sits **above** `ui-ux-design`;
     does **not** replace it.
   - **Mobbin** — reference-only screen/flow inspiration MCP for problem-section lookups;
     never 1:1 binding specs.
   - **`ui-ux-design`** — remains the **implementation executor** for `apps/demo` and
     `apps/dashboard` (Next.js UI, a11y, brand tokens, Vietnamese copy integration).
   - **`ui-ux` domain executor** — unchanged Meta assignment for frontend implementation
     slices; consumes upstream references then implements.
   - **`shadcn` skill** — **atoms only** (buttons, inputs, dialogs, etc.); refine then
     fold into `@juli/ui`; not the Demo page composition layer.

2. **Hybrid component model:**
   - Demo continues to compose from **`@juli/ui`** + **`@juli/theme`**.
   - New or refined atoms may start from shadcn registry, then migrate into `@juli/ui`.
   - No wholesale replacement of Demo surfaces with raw shadcn page scaffolding.

3. **Authority boundaries (unchanged, reinforced):**
   - **Copy SoT:** `dictionary.md` + `design-context.md` ([ADR-028](028-vietnamese-copy-dictionary-and-design-context.md)) — not Airtable, not Mobbin, not Open Design output text.
   - **IA SoT:** [ADR-023](023-four-destination-analytics-ownership.md) — Home / Decisions / Analytics / Settings; no greenfield IA rebuild from reference pipelines.

4. **Ephemeral vs durable:**
   - The **Airtable → Open Design extract → Mobbin → Meta cache** orchestration is
     **scoped to the Demo visual refinement PRD only** — documented as a **design
     reference pipeline**, not registered as permanent harness infrastructure.
   - After that PRD, agents use the **durable skill stack** (Open Design + Mobbin →
     `ui-ux-design` → `@juli/ui`) without an Airtable-first Meta stage.

5. **Harness wiring (acceptance for skill workstream):**
   - Restore or add Open Design skill entry under `.cursor/skills/standalone/` (or
     equivalent catalog registration) and register Open Design + Mobbin in
     `skill-catalog` + Focus routing for design-reference tasks.
   - Update `agent-runtime/config/slice-routing.yml` so design slices load upstream
     references before `ui-ux` executor assignment where applicable.

## Rationale

Separating **reference gathering** (Open Design, Mobbin) from **product implementation**
(`ui-ux-design`, `@juli/ui`) keeps the harness stable while allowing rich visual
exploration. Locking Airtable to a one-shot PRD avoids a second copy/IA authority that
would conflict with ADR-028 and ADR-023. The hybrid component model preserves Phase 2.6+
Demo investment and ADR-015 tokens without a disruptive shadcn rewrite.

## Consequences

- Focus must route **design-reference** tasks to Open Design + Mobbin **before**
  `ui-ux-design`, and **implementation** tasks to `ui-ux` + `ui-ux-design` with
  dictionary + design-context loaded ([ADR-028](028-vietnamese-copy-dictionary-and-design-context.md)).
- New seller-facing strings still require `dictionary.md` keys — Mobbin/Open Design
  copy is never authoritative.
- Skill-catalog and slice-routing changes are the durable deliverable; Airtable extract
  artifacts are PRD-scoped and may be archived after refinement lands.
- `@juli/ui` owns long-lived primitives; shadcn is a staging registry, not the Demo
  composition source of truth.

## Options considered

| Option | Rejected because |
|--------|------------------|
| Permanent Airtable-first Meta pipeline | Creates parallel copy/layout SoT; high harness lock-in for a one-shot reference |
| Open Design replaces ui-ux-design | OD generates references; Juli product apps need repo-aware implementation + ADR-028 copy |
| Full Demo → shadcn migration | Breaks `@juli/ui`/`@juli/theme` contract; unnecessary for visual polish within ADR-023 IA |
| Mobbin 1:1 specs | Conflicts with ADR-015 tokens and Vietnamese copy authority |
