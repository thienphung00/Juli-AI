# Listing Rules Engine + Export (P1.6-3 / P1.6-4)

Client-side rules engine and export service for the new-seller listing workflow.
Deterministic — no LLM, no API calls, no Postgres writes.

## Public surface

| Export | Responsibility |
|--------|----------------|
| `generateProductDraft(context)` | Build full `ProductDraft` from manual form, URL stub, or opportunity card context |
| `canExportProductDraft(draft)` | Returns `false` when `compliance.status === "blocked"` or draft not `ready_for_export` |
| `exportProductDraft(draft, format)` | Serialize approved draft to CSV or JSON; throws `ExportBlockedError` when blocked |
| `downloadExportResult(result)` | Trigger browser download from export result (client-only) |
| `trackExportCompleted(...)` | Fail-silent `export_completed` analytics event |
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
- TikTok Products API publish (P2-8)
- Shop progress widget (#157)
