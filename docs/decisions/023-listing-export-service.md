# ADR 023: Listing Export Service — Client-Side CSV/JSON

## Status
Accepted

## Context

- [ADR-020](020-new-seller-listing-workflow-scope.md) scoped Phase 1.6 execute step as
  client-side export for manual TikTok Seller Center upload (no API publish).
- Issues #154 (rules engine) and #155 (workflow UI) shipped draft generation and
  dual-path navigation; export step was a placeholder until #156.
- Issue #156 acceptance criteria require `exportProductDraft`, blocked-draft guard,
  Vietnamese manual-upload success copy, and `export_completed` UX instrumentation.

## Decision

- We will: implement `exportProductDraft(draft, format)` in
  `web/src/lib/workflows/new-seller/listing/export.ts` returning
  `{ content, mimeType, filename }` for CSV and JSON formats.
- We will: reuse `canExportProductDraft` (#154) as the single guard — UI disables
  export button and serializer throws `ExportBlockedError` when blocked.
- We will: wire the execute step in `ListingWorkflowPanel` with format picker,
  download trigger, and Vietnamese Seller Center upload instructions on success.
- We will: emit `export_completed` via the existing `juli:analytics` CustomEvent
  pattern (fail-silent).
- We will not: call TikTok API, write to Postgres, or add server-side export routes in P1.6.

## Rationale

Client-side serialization keeps P1.6 UI-only and testable without backend infra.
Returning structured export results separates serialization (unit-testable) from
DOM download side effects. Reusing the rules-engine export guard avoids divergent
blocked-draft logic between UI and export module.

## Consequences

- **Positive:** Completes copilot E2E chain recommend → approve → path → forms → execute (export).
- **Negative:** CSV uses flat dot-notation columns — not a TikTok bulk-upload template (P2 may add).
- **Follow-ups:** Shop progress widget (#157); TikTok Products API publish (P2-8).
