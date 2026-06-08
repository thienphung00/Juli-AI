# Listing Rules Engine (P1.6-3)

Client-side rules engine that produces a `ProductDraft` from seller inputs.
Deterministic — no LLM, no API calls.

## Public surface

| Export | Responsibility |
|--------|----------------|
| `generateProductDraft(context)` | Build full `ProductDraft` from manual form, URL stub, or opportunity card context |
| `canExportProductDraft(draft)` | Returns `false` when `compliance.status === "blocked"` or draft not `ready_for_export` |
| `READINESS_EXPORT_THRESHOLD` | Minimum readiness score (70) for export-ready status |

## Input context

`ListingGenerationContext` union:

- `manual_form` — seller-entered product fields
- `url_stub` — deterministic hostname/path extraction (no live fetch)
- `opportunity_card` — pre-fill from `Opportunity` + `Distributor` objects

## Dependencies

- `@/lib/mock-data/listing-workflow/schemas` — `ProductDraft` type contract

## Out of scope (P1.6)

- Cloud LLM / Ollama copy rewrite (P2)
- CSV/JSON export (#156)
- Listing workflow UI (#155)
