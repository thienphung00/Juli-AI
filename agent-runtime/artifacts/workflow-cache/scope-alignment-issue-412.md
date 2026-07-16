# Scope Alignment — Issue #412 (child of parent #395)

**Parent issue:** #395 (constant — `parent-cache-issue-395.json`)  
**Status:** valid  
**Cache block version:** 1  
**Last validated:** 2026-07-16  
**Companion artifact:** `agent-runtime/artifacts/workflow-cache/issue-context-cache-412.json`

## Authority chain (this run)

Precedence: `EXECUTION.md` → parent cache → child issue AC → handoff.

| Rank | Source | Applies because |
|------|--------|---------------|
| 1 | `EXECUTION.md` slice P2-6 | Phase/slice law |
| 2 | `parent-cache-issue-395` | Epic constant for all children |
| 3 | GitHub issue #412 | **Child** acceptance criteria (unique) |
| 4 | `docs/product/phases/phase-2.6/PRD.md` | Epic handoff (when not superseded) |

## Conflicts resolved

| Topic | Conflicting sources | Decision | Winner rule |
|-------|---------------------|----------|-------------|
| Work surface | P2-6 handoff emphasizes `apps/demo` screens · #412 AC is `packages/ui` elements only | **Implement `packages/ui` element primitives only**; do not build destination screens | Child AC (rank 3) |
| Existing Home primitives | #397 shipped DestinationCard / PrimaryNavigation · #412 lists buttons/badges/chips/health/progress | **Keep #397 exports**; add the five element families; leave Home compositions untouched except re-export hygiene | Child AC + parent deferral of screen work |
| Blocker | #412 blocked by #397 · #397 CLOSED (PR #409 merged) | **Unblocked** — proceed | Parent/epic completion |
| Atomic build order | grill 2026-07-16: elements → compositions → screens | **This issue = elements only**; compositions/screens are later siblings | Parent/epic + child AC |

## In scope (this issue)

- Typed `packages/ui` exports for: Button, Badge, Chip (status/filter/input as design requires), HealthBar, ProgressBar (standard + RealEstimated as design requires)
- Render + interaction-state Vitest coverage for applicable states per element
- Token usage exclusively via `@juli/theme` / CSS variables — no hardcoded colors/spacing
- 44×44 touch targets + visible focus-visible on interactive controls
- `prefers-reduced-motion` for any motion
- Vietnamese default/copy strings where the element renders text
- Import-boundary proof: `apps/demo` can import these; `packages/ui` never imports `apps/*`

## Out of scope (explicit deferrals)

- Destination screen compositions (recommendation cards, shop health cards, analytics layouts)
- Later `packages/ui` composition library issues
- Backend, auth, OAuth, live data, PostHog
- Changes to `apps/dashboard` product code (historical reference only)
- Public deploy / DNS

## DO NOT load (deprecated for this run)

- `docs/handoffs/archive/`
- `docs/product/features/`
- `backend/`
- `ios/`
- Sibling issue context caches
- `.cursor/skills/standalone/open-design-system/SKILL.md` (not present at parent `bootstrapRef` pin)

## Open questions

- (empty when valid)

## Prompt cache note

The `promptCacheBlock` in `issue-context-cache-412.json` is the machine-injectable
summary of this file. On cache hit, agents load the JSON block first and skip
re-reading full upstream docs unless fingerprints are stale.

## Edge docs (Meta → Executor; not in derived requiredDocs)

Load these in addition to the derived P2-6 profile when implementing elements:

- `docs/product/design/Components/buttons.md`
- `docs/product/design/Components/badges.md`
- `docs/product/design/Components/chips.md`
- `docs/product/design/Components/health-bars.md`
- `docs/product/design/Components/progress-bars.md`
- `docs/product/design/colors_and_type.css` (already in derived requiredDocs)
- Existing patterns: `packages/ui/src/destination-card.tsx`, `packages/ui/styles.css`, `packages/theme/tokens.css`
