# Shop Progress Tracker (P1.6-5)

Session-scoped mock listing count and task-card widget states for the new-seller
`list_products` workflow. No TikTok API; `published_stub` is mock-only.

## Public surface

| Export | Responsibility |
|--------|----------------|
| `loadShopProgress(personaId)` | Read persona-scoped session (baseline 3 SKU) |
| `updateListingWidgetState(personaId, state)` | Persist widget enum |
| `recordExportCompleted(personaId)` | Increment listing count + `published_stub` |
| `computeListingMilestone(count)` | Percent toward 10-listing Standard status |
| `getReadinessScoreBucket(score)` | Analytics bucket: low / medium / high |
| `syncShopProgressFromWorkflow(personaId, state)` | Map workflow step → widget state |
| `useShopProgress(personaId)` | React hook with session persistence |

## Widget states

`no_distributor` → `distributor_known` → `draft_generated` → `published_stub`

## Dependencies

- `@/lib/workflows/new-seller/listing/state-machine` — workflow step sync
- `sessionStorage` — persona-keyed persistence (`juli_shop_progress_<personaId>`)

## Out of scope (P1.6)

- TikTok Products API publish (P2-8)
- Postgres persona profile writes (P2)
