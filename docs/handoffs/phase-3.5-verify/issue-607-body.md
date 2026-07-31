## Parent
#598 — Phase 3.5-A0: CDP medallion foundation & serving gold

## What to build
Cut over orders + returns/cancellations (A-7 schema) to silver: `silver.orders` and `silver.returns` (or equivalents) with idempotent natural keys matching today’s domain upserts (`tiktok_order_id` / `tiktok_return_id` per shop). Promote bronze append → silver upsert without gold KPI formula dependency. Bounded dual-write window, then retire legacy `public.orders` / `public.returns` writers for this domain.

**A-7 ownership:** This slice lands silver schema + upsert contract only. A1 owns poll + webhook #11 reconcile logic and `cancellation_rate` KPI population.

Owning module: Domain silver upsert service. Readers: gold compute (A1), ML (future).

## Acceptance criteria
- `silver.orders` / `silver.returns` exist with unique natural keys per shop.
- Integration test: bronze append → silver upsert (minimal fixture; no gold KPI formulas; no live Partner).
- After cutover window, legacy domain writers for orders/returns retired — no indefinite dual-write.
- A1 reconcile / cancellation_rate precompute remains out of scope.

## Blocked by
Blocked by #605