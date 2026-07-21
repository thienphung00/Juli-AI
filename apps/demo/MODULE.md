# Module: demo

## Responsibility

Standalone public-facing Next.js Demo for Juli's four-destination product shape.
Phase 2.6 uses deterministic mock data and has no backend or authentication
dependency.

## Public interface

- `/` — sparse Home launcher with exactly two cards: Quyết định and Phân tích.
- `/decisions`, `/analytics`, `/settings` — discoverable shell destinations;
  content is delivered by later vertical slices.
- `DemoShell` — responsive four-destination application frame.
- `DemoStateProvider` / `useDemoState` — single owner for mutable mock state,
  persisted Mock mode, disabled Sign-in feedback, deterministic reset, and
  `startExecution(workflowKey)` for approved workflow records.
- `lib/executions.ts` — Workflow 1–4 timeline fixtures and pure `startExecution`.
- `lib/reviews.ts` — Workflow 1–4 five-stage review content and input defaults;
  `APPROVABLE_WORKFLOW_KEYS` gates card Approve for WF1–4.
- `lib/workflows/{optimize-product,replenish-inventory,clear-excess}/` — per-workflow
  review stages and FBS timelines for listing/inventory Decision workflows.
- `RecommendationsPanel` / `InProgressPanel` — Decisions tab panels composed by
  `RecommendationsView`.
- `homeDestinations` / `demoSnapshot` — deterministic mock contracts used by Home.

## Dependencies

- `@juli/contracts` — execution and review stage types.
- `@juli/theme` — semantic tokens.
- `@juli/ui` — accessible destination cards and primary navigation.
- `@juli/utils` — Vietnamese date/number formatting.

## Invariants

- Home contains no KPI, recommendation action, execution queue, template, or threshold.
- User-visible copy is Vietnamese with correct diacritics.
- The app performs no network requests and requires no backend/API environment variables.
- Mock is the only enabled mode; Sign-in remains focusable for truthful
  coming-soon feedback but never routes or requests data.
- Manual Refresh resets every mutable mock-state category and returns to
  `/decisions`, whose default view is Recommendations.
- Contextual Juli assistance explains the active destination and never
  authorizes approval, rejection, or execution.
- Every navigation target is keyboard accessible with a visible focus state and
  at least a 44×44px target.
- The app never imports a sibling app.

## Owners

- domain: web
- code: `apps/demo/`
