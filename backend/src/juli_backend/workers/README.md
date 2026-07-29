# backend/workers

Background workers: Celery task execution, scheduled polling sync, Mock-mode hourly Analytics reconciler.

**Includes:** TikTok polling (`backend/workers/services/polling/`), webhook receiver (`backend/api/services/webhook/`).

See `MODULE.md` for Phase 2.10 Mock reconciler (ADR-038 §5, #533).
