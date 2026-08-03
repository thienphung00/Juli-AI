"""Shared Compute enqueue_reason helpers (#627)."""


def webhook_catalog_enqueue_reason(catalog_id: int) -> str:
    """Deterministic enqueue reason for material webhook catalog triggers."""
    return f"webhook_catalog:{catalog_id}"
