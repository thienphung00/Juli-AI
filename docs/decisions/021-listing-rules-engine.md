# ADR 021: Listing Rules Engine Module

## Status
Accepted

## Context

- [ADR-020](020-new-seller-listing-workflow-scope.md) established Phase 1.6 as mock
  fixtures plus rules-only listing generation — no cloud LLM, no TikTok API.
- Issue #154 implements the client-side rules engine that produces `ProductDraft`
  from seller inputs (manual form, URL stub, opportunity card).
- `docs/architecture/map.md` gains a deployed row for
  `web/src/lib/workflows/new-seller/listing/`.

## Decision

- We will: implement `generateProductDraft(context) → ProductDraft` as a pure,
  deterministic TypeScript module under `web/src/lib/workflows/new-seller/listing/`.
- We will: gate export via `canExportProductDraft(draft)` when
  `compliance.status === "blocked"`.
- We will not: call external APIs, use LLM services, or persist drafts in Postgres
  in P1.6 (deferred to P2 per ADR-020).

## Rationale

A small public interface with deep internal modules (extraction, compliance,
readiness) lets the listing workflow UI (#155) integrate without coupling to
implementation details. Deterministic output supports golden tests and demo
reproducibility before P2 Ollama copy rewrite.

## Consequences

- **Positive:** #155 and #156 can consume a stable contract; same inputs always
  produce identical drafts.
- **Negative:** Blocked-category list is a P1.6 stub — must align with platform
  prohibited-category docs when curated.
- **Follow-ups:** Wire UI re-validation on inline edit (#155); CSV/JSON export (#156).
