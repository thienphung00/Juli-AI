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
- `homeDestinations` / `demoSnapshot` — deterministic mock contracts used by Home.

## Dependencies

- `@juli/theme` — semantic tokens.
- `@juli/ui` — accessible destination cards and primary navigation.
- `@juli/utils` — Vietnamese date/number formatting.

## Invariants

- Home contains no KPI, recommendation action, execution queue, template, or threshold.
- User-visible copy is Vietnamese with correct diacritics.
- The app performs no network requests and requires no backend/API environment variables.
- Every navigation target is keyboard accessible with a visible focus state and
  at least a 44×44px target.
- The app never imports a sibling app.

## Owners

- domain: web
- code: `apps/demo/`
