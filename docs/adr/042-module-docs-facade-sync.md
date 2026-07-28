# ADR-042: MODULE.md + map.md sync to enforced facades (MMU-13)

**Status:** Accepted  
**Date:** 2026-07-28  
**Deciders:** Architect (MMU-13 / #563)

**Builds on:** [ADR-036](036-modules-tier1-planning-sot.md), [ADR-022](022-intent-review-guardrails-split.md).  
**Related slice:** MMU-13 — module documentation sync after MMU-1..8 facade enforcement.

## Context

Phase Modular Monolith Upgrade (MMU) slices MMU-1 through MMU-8 introduced package-root
facades (`__init__.py` + lazy PEP 562 re-exports) and import-boundary enforcement via
`.importlinter.toml` and CI drift checks. By MMU-13, several Tier-2/Tier-3 docs still
described pre-facade deep paths:

| Doc | Problem |
|-----|---------|
| `docs/architecture/map.md` | Missing post-MMU layout, facade rule, ownership-registry links |
| `docs/architecture/MODULES.md` | No MMU upgrade section tying planning SoT to enforced surfaces |
| `**/MODULE.md` (touched modules) | Listed leaf submodule APIs instead of package-root `__all__` |

The boundary audit (#550) scored ~5.5 before MMU work; facade enforcement raised the score
toward ~9. Documentation must reflect the enforced public surfaces so Architect planning,
Executor context loading, and `audit_module_drift.py` stay aligned.

## Decision

1. **Sync `map.md`** to the post-MMU-1..8 as-built layout: facade import rule, module
   paths, ownership-registry cross-links, and boundary-audit score narrative.
2. **Extend `MODULES.md`** with an MMU upgrade section linking `ownership-registry.yml`,
   `import-boundaries.md`, and the #550 audit baseline.
3. **Align touched `MODULE.md` files** (integrations/tiktok, api, database, etl, webhook,
   core/security, services/tiktok) so Public Interface sections document only
   package-root exports — not deep leaf modules.
4. **Record drift baseline** via `audit_module_drift.py` (`driftCount=0`) after sync.
5. **Bootstrap MMU-13 harness routing** in `slice-routing.yml` for doc-sync executor context.

## Rationale

- **Single source of truth ladder** (ADR-036): `map.md` owns as-built paths; per-folder
  `MODULE.md` owns implementation precision. When facades change import surfaces, both
  must update together or planning and CI drift checks diverge.
- **Doc-only slice:** no runtime code changes; reduces merge risk while closing the
  documentation gap left after structural refactors.
- **ADR trigger:** `map.md` edits are classified as architectural documentation changes
  under the validate `adr_requirement` gate — this ADR records intent and consequences.

## Consequences

- Positive: Executors loading MMU-13 context see facade-aligned docs; intent-review can
  verify AC1–AC4 against consistent Tier-2/Tier-3 surfaces.
- Positive: `audit_module_drift.py` baseline captured for regression detection in MMU-15+.
- Neutral: No deploy surfaces or migrations; `publicRelease=false`.
- Follow-up: MMU-15 may add pytest contract nodes for MODULES.md/map.md invariants; leaf
  submodule detail stays out of `MODULE.md` per `patterns.mdc`.
