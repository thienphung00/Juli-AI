"""Phase 2 execution-layer webhook catalog — issue #354.

Maps Partner Center ``type`` strings to catalog IDs (#1–#68 subset), ETL channels,
workflow keys, and handler names. Types marked ``confirmed=False`` use best-guess
names until Partner Center registration confirms them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    catalog_id: int
    handler_name: str
    etl_channel: str
    event_types: tuple[str, ...]
    workflow_keys: tuple[str, ...]
    confirmed: bool = True


# Deferred Phase 3+ prefixes — not subscribed or routed through Phase 2 catalog paths.
DEFERRED_EVENT_PREFIXES: tuple[str, ...] = (
    "AFFILIATE",
    "CREATOR",
    "LIVESTREAM",
    "SETTLEMENT",
    "NEW_CONVERSATION",
    "NEW_MESSAGE",
    "CUSTOMER_SERVICE",
    "FINANCE_",
)

PHASE2_CATALOG: dict[int, CatalogEntry] = {
    1: CatalogEntry(
        1,
        "order_status_change",
        "tiktok.order_status_change",
        ("ORDER_STATUS_CHANGE",),
        ("process_order_5",),
    ),
    2: CatalogEntry(
        2,
        "reverse_status_update",
        "tiktok.reverse_status_update",
        ("REVERSE_STATUS_UPDATE",),
        ("prevent_cancellation_8a", "prevent_return_8b", "prevent_refund_8c"),
    ),
    3: CatalogEntry(
        3,
        "recipient_address_update",
        "tiktok.recipient_address_update",
        ("RECIPIENT_ADDRESS_UPDATE",),
        ("process_order_5",),
    ),
    4: CatalogEntry(
        4,
        "package_update",
        "tiktok.package_update",
        ("PACKAGE_UPDATE",),
        ("split_package_6",),
    ),
    5: CatalogEntry(
        5,
        "product_status_change",
        "tiktok.product_status_change",
        ("PRODUCT_STATUS_CHANGE",),
        ("create_hero_product_1", "optimize_product_2"),
    ),
    6: CatalogEntry(
        6,
        "seller_deauthorization",
        "tiktok.account.lifecycle",
        ("SELLER_DEAUTHORIZATION",),
        ("account_platform",),
    ),
    7: CatalogEntry(
        7,
        "auth_expiration_warning",
        "tiktok.account.lifecycle",
        ("UPCOMING_AUTHORIZATION_EXPIRATION",),
        ("account_platform",),
        confirmed=False,
    ),
    11: CatalogEntry(
        11,
        "cancellation_status_change",
        "tiktok.cancellation_status_change",
        ("CANCELLATION_STATUS_CHANGE",),
        ("prevent_cancellation_8a",),
        confirmed=False,
    ),
    12: CatalogEntry(
        12,
        "return_status_change",
        "tiktok.returns.raw",
        ("RETURN_STATUS_CHANGE",),
        ("prevent_return_8b",),
        confirmed=False,
    ),
    21: CatalogEntry(
        21,
        "inbound_fbt_order_status",
        "tiktok.inbound_fbt_order_status",
        ("INBOUND_FBT_ORDER_STATUS_CHANGE",),
        ("replenish_inventory_3b",),
        confirmed=False,
    ),
    24: CatalogEntry(
        24,
        "fbt_inventory_update",
        "tiktok.fbt_inventory_update",
        ("FBT_INVENTORY_UPDATE",),
        ("replenish_inventory_3b", "clear_excess_4", "prevent_return_8b_fbt"),
        confirmed=True,
    ),
    27: CatalogEntry(
        27,
        "inventory_status_change",
        "tiktok.inventory_status_change",
        ("INVENTORY_STATUS_CHANGE",),
        ("replenish_inventory_3", "clear_excess_4"),
        confirmed=False,
    ),
    37: CatalogEntry(
        37,
        "product_audit_status_change",
        "tiktok.product_audit_status_change",
        ("PRODUCT_AUDIT_STATUS_CHANGE",),
        ("create_hero_product_1",),
        confirmed=False,
    ),
    39: CatalogEntry(
        39,
        "activity_status_change",
        "tiktok.activity_status_change",
        ("ACTIVITY_STATUS_CHANGE",),
        (
            "create_activity_7a",
            "update_activity_7c",
            "delete_activity_7b",
            "clear_excess_4",
        ),
        confirmed=False,
    ),
    58: CatalogEntry(
        58,
        "fbt_mcf_order_status",
        "tiktok.fbt_mcf_order_status",
        ("FBT_MCF_ORDER_STATUS",),
        ("process_order_5b",),
        confirmed=False,
    ),
    64: CatalogEntry(
        64,
        "aftersales_request_status",
        "tiktok.aftersales_request_status",
        ("AFTERSALES_REQUEST_STATUS_UPDATE",),
        ("prevent_refund_8c",),
        confirmed=False,
    ),
    65: CatalogEntry(
        65,
        "rma_status_update",
        "tiktok.rma_status_update",
        ("RMA_STATUS_UPDATE",),
        ("prevent_return_8b",),
        confirmed=False,
    ),
    67: CatalogEntry(
        67,
        "refund_success",
        "tiktok.refund_success",
        ("REFUND_SUCCESS",),
        ("prevent_refund_8c",),
        confirmed=False,
    ),
    68: CatalogEntry(
        68,
        "inventory_changed",
        "tiktok.inventory.raw",
        ("INVENTORY_CHANGED",),
        ("replenish_inventory_3", "clear_excess_4"),
        confirmed=False,
    ),
}

PHASE2_CATALOG_IDS: tuple[int, ...] = tuple(sorted(PHASE2_CATALOG))

_EVENT_TYPE_INDEX: dict[str, CatalogEntry] = {
    event_type.upper(): entry
    for entry in PHASE2_CATALOG.values()
    for event_type in entry.event_types
}


def is_deferred_webhook_type(event_type: str) -> bool:
    """Return True when the event type is explicitly out of Phase 2 scope."""
    upper = event_type.upper()
    return any(upper.startswith(prefix) for prefix in DEFERRED_EVENT_PREFIXES)


def resolve_catalog_entry(event_type: str) -> CatalogEntry | None:
    """Resolve a Partner Center event type to a Phase 2 catalog entry."""
    if is_deferred_webhook_type(event_type):
        return None
    return _EVENT_TYPE_INDEX.get(event_type.upper())


def ingest_channel_for_event(event_type: str) -> str:
    """Return the ETL ingest channel for a webhook event type."""
    entry = resolve_catalog_entry(event_type)
    if entry is not None:
        return entry.etl_channel

    from juli_backend.services.tiktok.webhook import EVENT_CATEGORY_ROUTES

    upper = event_type.upper()
    for prefix, channel in EVENT_CATEGORY_ROUTES.items():
        if upper.startswith(prefix):
            return channel
    return f"tiktok.{event_type.lower()}"
