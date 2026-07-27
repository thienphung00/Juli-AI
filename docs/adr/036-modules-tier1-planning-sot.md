# ADR-036: MODULES.md as Tier-1 module planning SoT

**Status:** Accepted  
**Date:** 2026-07-27  
**Deciders:** grill-with-docs (Architect)

## Context

Architect and Developer planning needed a single place to track **per-module** purpose,
goals, refinement, and feature progression. Existing Tier-1 docs split other concerns:

| File | Owns |
|------|------|
| `EXECUTION.md` | Phase/slice progression of the **whole codebase** (multi-module parallel work) |
| `system-design.md` | Pipeline envelopes / capability matrix |
| `data-sources.md` | Allowed/forbidden sources by phase |
| `map.md` | As-built paths and public surfaces |

None of those is the right home for “what should module X refine or add next?” Options:
(1) overload `map.md` with goals/features; (2) keep goals only in EXECUTION slices;
(3) add `MODULES.md` as Tier-1 planning SoT beside the other architecture docs.

## Decision

1. Add [`docs/architecture/MODULES.md`](../architecture/MODULES.md) as **Tier 1** —
   module catalog and **individual module progression** (refinement + new features).
2. Keep **`map.md`** as as-built path registry only (split ownership, not a merge).
3. Keep **`EXECUTION.md`** as phase law: a phase may implement **multiple modules at once**;
   it does not replace per-module feature backlogs in MODULES.
4. Establish the planning → implementation **tier ladder**:

   | Tier | Role |
   |------|------|
   | **0** | Phase law — `EXECUTION.md` |
   | **1** | System/module planning SoT — MODULES, system-design, data-sources |
   | **2** | Rationale + as-built — ADRs, map, phase PRDs/runbooks as needed |
   | **3** | Implementation precision — `**/MODULE.md`, issue AC, API/contracts docs |

   Higher tiers cover more of the system with less detail (Architect + Developer planning).
   Lower tiers add specs for accurate implementation (Executor / implementers).

5. **Authority for planning conflicts:**  
   `EXECUTION.md` > `MODULES.md` > `system-design.md` > `map.md`.  
   Purpose/goals → MODULES wins; live paths → map wins until MODULES is updated.

6. Domain-level entries with selective nesting (Frontend children, Hermes under Agent Runtime).
   Omit Sentry/APM and empty `integrations/{identity,catalog,ordering}` stubs from the catalog.

## Consequences

- Architect planning reads EXECUTION → MODULES before diving into map paths or Tier-3 specs.
- `docs/architecture/*` banners and `EXECUTION.md` / `docs/README.md` routing must cite MODULES.
- Feature roadmaps for a single module live in MODULES; cross-module phase gates stay in EXECUTION.
- Does not delete or replace `map.md`, `system-design.md`, or per-folder `MODULE.md`.
