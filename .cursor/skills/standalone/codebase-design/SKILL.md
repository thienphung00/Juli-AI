---
name: codebase-design
description: >-
  Shared architecture vocabulary and deepening patterns for module design reviews.
  Use when improve-codebase-architecture, grilling, or interface design needs terms
  like depth, seam, adapter, leverage, and locality — or the design-it-twice pattern.
disable-model-invocation: true
---

# Codebase design

Shared vocabulary for **deepening** shallow modules — refactors that concentrate
complexity behind a narrow interface so tests and AI navigation improve.

Use these terms **exactly** in every suggestion. Do not drift into "component,"
"service," "API," or "boundary."

## Vocabulary

| Term | Meaning |
|------|---------|
| **Module** | A unit of code with one primary responsibility and a named interface. Not a file — a conceptual boundary that may span files. |
| **Interface** | Everything a caller needs to use a module: public functions, types, and the contracts they imply. The interface is the test surface. |
| **Depth** | How much complexity sits *behind* the interface vs how much leaks through it. A deep module hides detail; a shallow one exposes nearly as much as its implementation. |
| **Seam** | A place where one module ends and another begins — where you can substitute, mock, or observe behavior without reaching inside. |
| **Adapter** | Code that translates between a module's interface and an external system (DB, API, filesystem). One adapter = hypothetical seam; **two adapters on the same boundary = real seam**. |
| **Leverage** | How much behavior change one interface edit unlocks. High leverage = one seam change improves many call sites or tests. |
| **Locality** | Whether related logic lives together. Low locality = understanding one concept requires bouncing across many small modules. |

## Principles

1. **The deletion test** — Would deleting this module concentrate complexity somewhere useful, or just scatter it? "Yes, concentrates" signals a deepening candidate.
2. **The interface is the test surface** — If you cannot test behavior through the public interface, the module is too shallow or the seam is in the wrong place.
3. **One adapter = hypothetical seam, two = real** — A single adapter might be accidental; two independent adapters on the same boundary confirm a genuine seam worth deepening.

## Design-it-twice (parallel sub-agents)

When exploring alternative interfaces for a deepened module, run **two** Task subagents
in parallel with different constraints:

| Agent | Constraint |
|-------|------------|
| **A — Minimal interface** | Smallest public surface; push complexity inward; optimize for testability through the interface. |
| **B — Explicit seams** | Named adapter boundaries for every external dependency; optimize for substitutability and observability. |

Compare outcomes on: interface size, test surface, locality, leverage, and ADR alignment.
Present both to the user; do not pick a winner until they choose or combine.

## Repo anchors (Juli)

| Artifact | Location |
|----------|----------|
| Domain vocabulary | `CONTEXT.md` (repo root) |
| Recorded decisions | `docs/adr/` |
| Module registry | `docs/architecture/map.md` |
| Per-module context | `**/MODULE.md` under `backend/`, `apps/dashboard/`, `ios/` |

When naming modules in reviews, prefer **CONTEXT.md** terms (e.g. "Order intake module")
over handler/class names (e.g. `FooBarHandler`).
