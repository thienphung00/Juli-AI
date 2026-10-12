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
    # Legacy (API v1) webhook: its only page is the docv1 "Reverse Status Update"
    # (tagged ``v1_deprecated``, last edited 2024-01-29); the docv2 webhook list
    # has no type 2. API 202309 (2023-09-19) split it into 11 (cancellation) and
    # 12 (return / refund-only). Kept so a shop still subscribed is routed as
    # before; 11 and 12 below carry its workflows and fetches. See
    # ``LEGACY_SUPERSEDED_BY`` and docs/runbooks/apiwatch.md ("Đã xử lý").
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
        # Payload ``type: 11`` per docv2 page 11-cancellation-status-change.
        confirmed=True,
    ),
    12: CatalogEntry(
        12,
        "return_status_change",
        "tiktok.returns.raw",
        ("RETURN_STATUS_CHANGE",),
        # ``return_type`` REFUND (refund only) arrives here too since type 2 left.
        ("prevent_return_8b", "prevent_refund_8c"),
        # Payload ``type: 12`` per docv2 page 12-return-status-change.
        confirmed=True,
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
    # Fast track P23 (D30.4): product and promotion changes for the history
    # tables. Handled by ``services/product_history`` (re-read + diff), never
    # handed to the ETL consumer -- see ``HISTORY_CATALOG_IDS``.
    15: CatalogEntry(
        15,
        "product_information_change",
        "tiktok.product_information_change",
        ("PRODUCT_INFORMATION_CHANGE",),
        ("optimize_product_2",),
    ),
    16: CatalogEntry(
        16,
        "product_creation",
        "tiktok.product_creation",
        ("PRODUCT_CREATION",),
        ("create_hero_product_1",),
    ),
    18: CatalogEntry(
        18,
        "product_category_change",
        "tiktok.product_category_change",
        ("PRODUCT_CATEGORY_CHANGE",),
        ("optimize_product_2",),
    ),
    63: CatalogEntry(
        63,
        "activity_change",
        "tiktok.activity_change",
        ("ACTIVITY_CHANGE",),
        ("create_activity_7a", "update_activity_7c", "delete_activity_7b"),
        confirmed=False,
    ),
    68: CatalogEntry(
        68,
        "inventory_changed",
        "tiktok.inventory.raw",
        ("INVENTORY_CHANGED",),
        ("replenish_inventory_3", "clear_excess_4"),
        confirmed=True,
    ),
}

PHASE2_CATALOG_IDS: tuple[int, ...] = tuple(sorted(PHASE2_CATALOG))

# Material catalog types enqueue shop Analytics precompute after ingest (#532 / ADR-038).
MATERIAL_CATALOG_IDS: frozenset[int] = frozenset({1, 2, 5, 11, 12, 27, 39, 67, 68})
#: Legacy webhook types and the documented types that replace them. 2
#: (``REVERSE_STATUS_UPDATE``) is absent from the docv2 webhook list; a shop
#: subscribed to 11 + 12 gets everything 2 drove (workflows 8a/8b/8c, material
#: fetch). Unknown or legacy types are still acked 200 and stored raw.
LEGACY_SUPERSEDED_BY: dict[int, tuple[int, ...]] = {2: (11, 12)}
INVENTORY_CHANGED_CATALOG_ID = 68
#: Fast track P23 (D30.4): types that trigger a product / activity re-read for the
#: history tables (``services/product_history/webhooks.py``). 39 also keeps its
#: workflow signal and material compute; 15 / 16 / 18 / 63 skip the ETL handoff
#: (their bodies carry only ids: the product transform would overwrite the
#: product's title with "Unknown").
HISTORY_CATALOG_IDS: frozenset[int] = frozenset({15, 16, 18, 39, 63})
HISTORY_ONLY_CHANNELS: frozenset[str] = frozenset(
    {
        "tiktok.product_information_change",
        "tiktok.product_creation",
        "tiktok.product_category_change",
        "tiktok.activity_change",
    }
)
COALESCE_68_SECONDS = 15 * 60

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
    """Resolve a Partner Center event type to a Phase 2 catalog entry.

    Accepts either the confirmed type string (e.g. ``INVENTORY_CHANGED``) or the
    numeric Partner Center catalog id as a string (e.g. ``\"68\"``).
    """
    if is_deferred_webhook_type(event_type):
        return None
    entry = _EVENT_TYPE_INDEX.get(event_type.upper())
    if entry is not None:
        return entry
    if event_type.isdigit():
        return PHASE2_CATALOG.get(int(event_type))
    return None


def is_material_catalog_id(catalog_id: int) -> bool:
    """Return True when a catalog id should enqueue Analytics precompute (#532)."""
    return catalog_id in MATERIAL_CATALOG_IDS


def catalog_id_for_event(event_type: str) -> int | None:
    """Resolve event type to catalog id, or None when unknown/deferred."""
    entry = resolve_catalog_entry(event_type)
    return entry.catalog_id if entry is not None else None


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
