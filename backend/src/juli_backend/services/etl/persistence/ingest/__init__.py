"""Public ETL ingest persistence — idempotency ledger (#558 MMU-9a)."""

from juli_backend.services.etl.persistence.ingest.model import ProcessedEvent
from juli_backend.services.etl.persistence.ingest.repo import ProcessedEventsRepo

__all__ = ["ProcessedEvent", "ProcessedEventsRepo"]
