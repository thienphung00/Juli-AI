# ADR 016: Listing workflow implementation

## Status
Accepted

## Context

The Create New Product Listing workflow is the primary executable workflow for `NEW_SHOP`
profile shops. It was validated on mock fixtures during the completed pre-MVP phase and
ships in Phase 2 MVP with live Products API publish.

## Decision

### Rules engine

- **We will:** Implement `generateProductDraft(context) → ProductDraft` as a pure,
  deterministic TypeScript module under `web/src/lib/workflows/new-seller/listing/`.
- **We will:** Gate export via `canExportProductDraft(draft)` when compliance is blocked.
- **We will not:** Call external APIs or cloud LLM in client-side draft generation.

### Workflow UI

- **We will:** Launch listing workflow as modal from approved `list_products` tasks.
- **We will:** Implement Path A (product form → distributor → draft review) and Path B
  (constraints → opportunity browse → distributor → draft review) as client-side state machine.
- **We will:** Call rules engine at draft review; export step produces CSV/JSON.

### Shop progress tracker

- **We will:** Track listing milestone via session-scoped storage with widget states:
  `no_distributor` → `distributor_known` → `draft_generated` → `published_stub`.
- **We will:** Increment listing count on successful export; render progress widget on Home.
- **Phase 2 MVP:** Persist shop progress in Postgres; Products API publish executor.

## Rationale

Consolidates seller-money rescope: keeps enforcement aligned with TikTok VN policy while routing alerts through the operations pipeline instead of a standalone service.

## Consequences

- E2E path: recommend → approve → Path A or B → forms → export (mock) → live publish (Phase 2 MVP).
- Blocked-category list must align with platform prohibited-category docs.
