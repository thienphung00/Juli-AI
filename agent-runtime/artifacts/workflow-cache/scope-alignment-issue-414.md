# Scope Alignment — Issue #414 (child of parent #395)

**Parent issue:** #395 (constant — `parent-cache-issue-395.json`)  
**Status:** valid  
**Cache block version:** 1  
**Last validated:** 2026-07-16  
**Companion artifact:** `agent-runtime/artifacts/workflow-cache/issue-context-cache-414.json`

## Authority chain (this run)

Precedence: `EXECUTION.md` → parent cache → child issue AC → handoff.

| Rank | Source | Applies because |
|------|--------|---------------|
| 1 | `EXECUTION.md` slice P2-6 | Phase/slice law |
| 2 | `parent-cache-issue-395` | Epic constant for all children |
| 3 | GitHub issue #414 | **Child** acceptance criteria (unique) |
| 4 | `docs/product/phases/phase-2.6/PRD.md` | Epic handoff (when not superseded) |

## Conflicts resolved

| Topic | Conflicting sources | Decision | Winner rule |
|-------|---------------------|----------|-------------|
| Work surface | P2-6 handoff covers full Demo · #414 AC is feedback + navigation compositions only | **Implement `packages/ui` feedback/nav/chart compositions only** (toasts, loaders, navigation, charts); no destination screens | Child AC (rank 3) |
| Existing navigation | #397 shipped PrimaryNavigation · #414 lists navigation | **Keep PrimaryNavigation API**; extend/complete navigation compositions per `navigation.md` without breaking Home shell consumers | Child AC + preserve shipped exports |
| Blocker | #414 blocked by #412 · #412 merged via PR #415 | **Unblocked** — proceed from `origin/main` | Parent/epic completion |
| Parallel sibling | #413 also touches `packages/ui` | **Parallel with partitioned file ownership** (see Meta); do not edit #413 surface composition files | Meta routing + issue-workflow partition |
| Atomic build order | grill 2026-07-16: elements → compositions → screens | **This issue = feedback + navigation compositions**; screens are later siblings | Parent/epic + child AC |

## In scope (this issue)

- Typed `packages/ui` exports for: toasts, loading indicators, primary/secondary navigation compositions, charts
- Compose from #412 elements where applicable — no duplicated primitive logic
- Toasts and loading indicators: `prefers-reduced-motion` + accessible live regions
- Charts: Recharts, series colors from `packages/theme` CSS variables, keyboard-accessible, text equivalent for screen readers
- Navigation: keyboard-operable, visible focus-visible, correct active-route indication
- Vietnamese copy where the composition renders text
- Import-boundary proof: `apps/demo` can import these; `packages/ui` never imports `apps/*`

## Out of scope (explicit deferrals)

- Surface compositions (cards, dialogs, forms, tables, popovers) — **#413**
- Destination screen wiring in `apps/demo` beyond import-boundary proof
- Full Analytics destination (#404 stretch) — charts are library primitives only
- Backend, auth, OAuth, live data, PostHog
- Changes to `apps/dashboard` product code (historical reference only)
- Public deploy / DNS

## DO NOT load (deprecated for this run)

- `docs/handoffs/archive/`
- `docs/product/features/`
- `backend/`
- `ios/`
- Sibling issue context caches (`issue-context-cache-413.json` etc.)
- `.cursor/skills/standalone/open-design-system/SKILL.md` (not present at parent `bootstrapRef` pin)

## Open questions

- (empty when valid)

## Prompt cache note

The `promptCacheBlock` in `issue-context-cache-414.json` is the machine-injectable
summary of this file. On cache hit, agents load the JSON block first and skip
re-reading full upstream docs unless fingerprints are stale.

## Edge docs (Meta → Executor; not in derived requiredDocs)

Load these in addition to the derived P2-6 profile when implementing feedback/nav compositions:

- `docs/product/design/Components/toasts.md`
- `docs/product/design/Components/loading-indicators.md`
- `docs/product/design/Components/navigation.md` (also in derived requiredDocs)
- `docs/product/design/Components/charts.md`
- Existing patterns: `packages/ui/src/primary-navigation.tsx`, `packages/ui/src/progress-bar.tsx`, `packages/ui/styles.css`, `packages/theme/tokens.css`
- Optional historical reference only: Recharts usage under `apps/dashboard` (do not import from apps)

## Parallel file ownership (#414 exclusive)

| Own | Do not touch |
|-----|--------------|
| `packages/ui/src/toast.tsx` | `card.tsx`, `dialog.tsx`, `form*.tsx`, `table.tsx`, `popover.tsx` |
| `packages/ui/src/loading-indicator.tsx` | Rewriting RecommendationCard / DestinationCard |
| `packages/ui/src/chart*.tsx` | #413 tests |
| Navigation composition files (extend PrimaryNavigation carefully) | Sibling worktree files |
| Matching `__tests__/*` for the above | #413 export blocks |
| Append-only `#414` sections in `styles.css` + `index.ts` exports for #414 only | |
