# Scope Alignment — Issue #413 (child of parent #395)

**Parent issue:** #395 (constant — `parent-cache-issue-395.json`)  
**Status:** valid  
**Cache block version:** 1  
**Last validated:** 2026-07-16  
**Companion artifact:** `agent-runtime/artifacts/workflow-cache/issue-context-cache-413.json`

## Authority chain (this run)

Precedence: `EXECUTION.md` → parent cache → child issue AC → handoff.

| Rank | Source | Applies because |
|------|--------|---------------|
| 1 | `EXECUTION.md` slice P2-6 | Phase/slice law |
| 2 | `parent-cache-issue-395` | Epic constant for all children |
| 3 | GitHub issue #413 | **Child** acceptance criteria (unique) |
| 4 | `docs/product/phases/phase-2.6/PRD.md` | Epic handoff (when not superseded) |

## Conflicts resolved

| Topic | Conflicting sources | Decision | Winner rule |
|-------|---------------------|----------|-------------|
| Work surface | P2-6 handoff covers full Demo · #413 AC is surface compositions only | **Implement `packages/ui` surface compositions only** (cards, dialogs, forms, tables, popovers); no destination screens | Child AC (rank 3) |
| Existing cards | #397/#412 shipped DestinationCard + RecommendationCard · #413 lists cards | **Keep existing card exports**; add Standard/Interactive/surface card primitives and any missing Decision/execution card compositions per `cards.md` without rewriting Home launchers | Child AC + parent deferral of screen work |
| Blocker | #413 blocked by #412 · #412 merged via PR #415 | **Unblocked** — proceed from `origin/main` | Parent/epic completion |
| Parallel sibling | #414 also touches `packages/ui` | **Parallel with partitioned file ownership** (see Meta); do not edit #414 feedback/nav/chart files | Meta routing + issue-workflow partition |
| Atomic build order | grill 2026-07-16: elements → compositions → screens | **This issue = surface compositions**; elements from #412 are dependencies; screens are later siblings | Parent/epic + child AC |

## In scope (this issue)

- Typed `packages/ui` exports for surface compositions: cards, dialogs, forms, tables, popovers
- Compose from #412 elements (Button, Badge, Chip, HealthBar, ProgressBar) — no duplicated primitive logic
- Render + interaction-state Vitest coverage for applicable states per composition
- Dialogs/popovers: focus trap, Escape dismissal, outside-click dismissal per `ux_principles.md`
- Tables and forms: keyboard-navigable with labelled inputs
- 44×44 touch targets + visible focus-visible on interactive controls
- Vietnamese default/copy strings where the composition renders text
- Import-boundary proof: `apps/demo` can import these; `packages/ui` never imports `apps/*`

## Out of scope (explicit deferrals)

- Feedback/navigation compositions (toasts, loaders, navigation, charts) — **#414**
- Destination screen wiring in `apps/demo` beyond import-boundary proof
- Backend, auth, OAuth, live data, PostHog
- Changes to `apps/dashboard` product code (historical reference only)
- Public deploy / DNS

## DO NOT load (deprecated for this run)

- `docs/handoffs/archive/`
- `docs/product/features/`
- `backend/`
- `ios/`
- Sibling issue context caches (`issue-context-cache-414.json` etc.)
- `.cursor/skills/standalone/open-design-system/SKILL.md` (not present at parent `bootstrapRef` pin)

## Open questions

- (empty when valid)

## Prompt cache note

The `promptCacheBlock` in `issue-context-cache-413.json` is the machine-injectable
summary of this file. On cache hit, agents load the JSON block first and skip
re-reading full upstream docs unless fingerprints are stale.

## Edge docs (Meta → Executor; not in derived requiredDocs)

Load these in addition to the derived P2-6 profile when implementing surface compositions:

- `docs/product/design/Components/cards.md` (also in derived requiredDocs)
- `docs/product/design/Components/dialogs.md`
- `docs/product/design/Components/forms.md`
- `docs/product/design/Components/tables.md`
- `docs/product/design/Components/popovers.md`
- Existing patterns: `packages/ui/src/destination-card.tsx`, `packages/ui/src/recommendation-card.tsx`, `packages/ui/src/button.tsx`, `packages/ui/styles.css`, `packages/theme/tokens.css`

## Parallel file ownership (#413 exclusive)

| Own | Do not touch |
|-----|--------------|
| `packages/ui/src/card.tsx` (and card variants you add) | `toast.tsx`, `loading-indicator.tsx`, `chart*.tsx` |
| `packages/ui/src/dialog.tsx` | Rewriting `primary-navigation.tsx` API |
| `packages/ui/src/form*.tsx` / `table.tsx` / `popover.tsx` | #414 tests |
| Matching `__tests__/*` for the above | Sibling worktree files |
| Append-only `#413` sections in `styles.css` + `index.ts` exports for #413 only | #414 export blocks |
