"""Field allowlist for every raw platform payload Juli stores (ADR-116 §4, D76; grill D5, D8).

Applied before every raw write: the bronze order / return appends
(``services/etl/bronze_append.py``), the batch-reconcile order pages
(``services/cdp_batch/partition_checkpoints.py``) and the Connector ingest
gateway (``services/ingest/gateway.py``). Anything not listed is dropped at any
depth; buyer name, phone, address, e-mail and messages are never listed
(``FORBIDDEN_KEY_FRAGMENTS`` + ``tests/unit/test_payload_allowlist.py``).

How each list was derived -- from what downstream code reads off the STORED
payload, not from what the platform sends:

- ``tiktok`` / ``orders.raw`` (a ``normalize_order`` row): the bronze writer and
  the bronze handoff (``order_id``, ``tiktok_order_id``, ``update_time``), the
  Shared Compute promotion (``order_id``), ``etl.transform._transform_order``
  (status, amounts, ``payment.*``, ``buyer_id``, currency, the five timestamps,
  ``cancel_reason``, ``is_seller_fault``), ``normalize_order``'s own inputs so a
  stored row re-normalizes to the same value (``id``, ``status``,
  ``payment.currency``, ``cancellation_initiator``) and
  ``expand_order_line_items`` (``line_items[]`` ids, price, quantity).
  ``user_id`` is NOT kept: ``normalize_order`` has already copied it to
  ``buyer_id``, which is stored as the shop's pseudonym.
- ``tiktok`` / ``returns.raw`` (a ``normalize_return`` / ``normalize_cancellation``
  row): the writer / handoff / promotion ids, ``etl.transform._transform_return``
  (ids, ``refund_amount``, ``buyer_id``, product / SKU, type, condition, reason,
  status fields, timestamps) and the normalizers' inputs (``id``, ``cancel_id``,
  ``refund`` / ``refund_amount`` totals, ``return_line_items[]`` /
  ``cancel_line_items[]`` ids, the platform's reason label).
- ``tiktok`` / ``orders.reconcile_page``: the batch-reconcile page envelope --
  ``records[]`` as an order row, ``_batch_reconcile`` the resume cursor
  ``recover_checkpoint_from_bronze`` reads.
- ``tiktok`` / ``orders.diagnosis_snapshot`` (an ``orders/search`` order as the
  Partner API returns it, written to the shop diagnosis snapshot's
  ``orders.json``): what ``services/shop_diagnosis`` and
  ``optimize_product.order_windows`` read -- ``id``, ``status``, ``create_time``,
  ``payment.sub_total``, ``line_items[]`` (``product_id``, ``sale_price``,
  ``is_gift``, ``platform_discount``, ``seller_discount``). No buyer id at all.
- ``tiktok`` / ``webhook.order`` / ``webhook.return`` / ``webhook.other`` /
  ``webhook.unknown`` (a webhook delivery, envelope and ``data``, as
  ``workflow_webhook_signals.payload`` and ``webhook_raw_events.raw_body`` keep it;
  owner decision D16): no code reads either column back, so each keeps what
  explains a delivery after the fact and keys it again -- the envelope (``type``,
  ``shop_id``, ``timestamp``, ``tts_notification_id``), the ids
  ``etl.event_id.extract_event_id`` keys on, and the event's own ids, statuses
  and times per Partner Center's webhook pages. ``webhook.unknown`` (a type not
  in the catalog) keeps the envelope only. Free text (``reason``, ``message``,
  ``comment``, ``note``) is never listed; a ``buyer_id`` is pseudonymised when
  the shop is known and dropped otherwise (``services/tiktok/webhook_redaction``).
- ``<platform>`` / ``ingest.<dataset>``: the Connector body (``IngestBody``) with
  each row limited to its dataset's declared row fields, built from
  ``services/ingest/mapping.DATASETS`` so a new dataset is covered when it is
  declared. The row's open ``extra`` object keeps numbers / booleans / nulls only;
  a string there could carry free text, so it is dropped from the raw copy.

REASONS (owner decision A, audit gap 5): ``cancel_reason``, ``return_reason``,
``return_reason_text`` and ``cancel_reason_text`` are listed as a :class:`ReasonRule`,
not ``True``: a reason code or a catalogued platform label is kept, any other value
(free text a buyer may have typed) is stored as ``"other"`` (``reason_labels``).

FAIL CLOSED. An unknown (platform, endpoint) raises :class:`UnknownPayloadEndpoint`
and the caller stores nothing: an unlisted endpoint is a code path nobody has
reviewed yet, so refusing the write is safer than guessing which ids are safe.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any

from juli_backend.services.privacy.reason_labels import safe_reason

#: A spec maps a key to ``True`` (keep a scalar value) or to a nested spec (keep
#: an object / list of objects filtered by it; a scalar there is kept as-is).
Spec = Mapping[str, Any]

#: Keep any key of this object, but only number / boolean / null values.
OPEN_NUMERIC = object()

TIKTOK = "tiktok"


@dataclass(frozen=True)
class ReasonRule:
    """Keep a scalar reason only as a code or a catalogued label; else ``"other"``."""

    platform: str
    field: str

    def apply(self, value: Any) -> Any:
        return safe_reason(self.platform, self.field, value)


ORDERS_RAW = "orders.raw"
RETURNS_RAW = "returns.raw"
ORDERS_RECONCILE_PAGE = "orders.reconcile_page"
ORDERS_DIAGNOSIS_SNAPSHOT = "orders.diagnosis_snapshot"
WEBHOOK_ORDER = "webhook.order"
WEBHOOK_RETURN = "webhook.return"
WEBHOOK_OTHER = "webhook.other"
WEBHOOK_UNKNOWN = "webhook.unknown"
INGEST_PREFIX = "ingest."

#: No listed key may contain one of these (case-insensitive). A test walks every spec.
FORBIDDEN_KEY_FRAGMENTS: tuple[str, ...] = (
    "name",
    "phone",
    "mobile",
    "email",
    "address",
    "recipient",
    "message",
    "note",
    "avatar",
    "nickname",
    "cpf",
    "district",
    "city",
    "street",
    "zip",
    "postal",
    "user_id",
)
#: Allowed despite a fragment match: product / platform data, not the buyer.
FORBIDDEN_FRAGMENT_EXCEPTIONS: frozenset[str] = frozenset({"item_name"})

_AMOUNT: Spec = {
    "currency": True,
    "total_amount": True,
    "payment_amount": True,
    "sub_total": True,
}
_REFUND_AMOUNT: Spec = {
    "currency": True,
    "refund_total": True,
    "total_amount": True,
    "refund_subtotal": True,
    "refund_shipping_fee": True,
    "refund_tax": True,
}

TIKTOK_ORDER_SPEC: Spec = {
    "order_id": True,
    "id": True,
    "tiktok_order_id": True,
    "buyer_id": True,
    "status": True,
    "order_status": True,
    "total_amount": True,
    "payment_amount": True,
    "currency": True,
    "payment": _AMOUNT,
    "create_time": True,
    "update_time": True,
    "payment_time": True,
    "paid_time": True,
    "ship_time": True,
    "shipping_time": True,
    "delivery_time": True,
    "delivered_time": True,
    "cancel_reason": ReasonRule(TIKTOK, "cancel_reason"),
    "cancellation_initiator": True,
    "is_seller_fault": True,
    "line_items": {
        "id": True,
        "sku_id": True,
        "product_id": True,
        "sale_price": True,
        "unit_price": True,
        "original_price": True,
        "quantity": True,
        "currency": True,
    },
}

_RETURN_LINE: Spec = {
    "sku_id": True,
    "product_id": True,
    "order_line_item_id": True,
    "return_line_item_id": True,
    "cancel_line_item_id": True,
    "refund_amount": _REFUND_AMOUNT,
}

TIKTOK_RETURN_SPEC: Spec = {
    "return_id": True,
    "id": True,
    "cancel_id": True,
    "tiktok_return_id": True,
    "order_id": True,
    "tiktok_order_id": True,
    "buyer_id": True,
    "product_id": True,
    "sku_id": True,
    "refund_amount": _REFUND_AMOUNT,
    "refund": _REFUND_AMOUNT,
    "return_type": True,
    "return_condition": True,
    "return_reason": ReasonRule(TIKTOK, "return_reason"),
    "return_reason_text": ReasonRule(TIKTOK, "return_reason_text"),
    "cancel_reason": ReasonRule(TIKTOK, "cancel_reason"),
    "cancel_reason_text": ReasonRule(TIKTOK, "cancel_reason_text"),
    "status": True,
    "return_status": True,
    "cancel_status": True,
    "create_time": True,
    "update_time": True,
    "return_line_items": _RETURN_LINE,
    "cancel_line_items": _RETURN_LINE,
}

TIKTOK_RECONCILE_PAGE_SPEC: Spec = {
    "records": TIKTOK_ORDER_SPEC,
    "_batch_reconcile": {
        "partition_date": True,
        "fetched_page_token": True,
        "next_page_token": True,
    },
}

TIKTOK_DIAGNOSIS_ORDER_SPEC: Spec = {
    "id": True,
    "status": True,
    "create_time": True,
    "update_time": True,
    "payment": _AMOUNT,
    "line_items": {
        "id": True,
        "sku_id": True,
        "product_id": True,
        "sale_price": True,
        "original_price": True,
        "platform_discount": True,
        "seller_discount": True,
        "is_gift": True,
        "currency": True,
    },
}

#: Every webhook envelope; ``data`` is filled in per kind below.
_WEBHOOK_ENVELOPE: dict[str, Any] = {
    "type": True,
    "shop_id": True,
    "timestamp": True,
    "tts_notification_id": True,
    "event_id": True,
}
#: The ids ``extract_event_id`` keys a webhook on, and the shop keys #68 uses.
_WEBHOOK_KEYS: dict[str, Any] = {
    "event_id": True,
    "order_id": True,
    "product_id": True,
    "sku_id": True,
    "seller_id": True,
    "shop_id": True,
    "create_time": True,
    "update_time": True,
}
_WEBHOOK_ORDER_DATA: Spec = {
    **_WEBHOOK_KEYS,
    "buyer_id": True,
    "order_status": True,
    "is_on_hold_order": True,
    "package_id": True,
    "sc_type": True,
    "role_type": True,
    "fulfillment_order_id": True,
    "fulfillment_order_status": True,
    "package_list": {
        "package_id": True,
        "sku_list": {"sku_id": True, "quantity": True},
    },
}
_WEBHOOK_RETURN_DATA: Spec = {
    **_WEBHOOK_KEYS,
    "buyer_id": True,
    "reverse_order_id": True,
    "reverse_order_status": True,
    "reverse_event_type": True,
    "reverse_type": True,
    "return_id": True,
    "return_status": True,
    "return_type": True,
    "return_role": True,
    "cancel_id": True,
    "cancel_status": True,
    "cancellations_role": True,
    "aftersales_request_id": True,
    "request_id": True,
    "rma_id": True,
    "status": True,
    "refund_id": True,
}
_WEBHOOK_OTHER_DATA: Spec = {
    **_WEBHOOK_KEYS,
    "id": True,
    "status": True,
    "product_status": True,
    "audit_status": True,
    "activity_id": True,
    "activity_status": True,
    "activity_type": True,
    "change_type": True,
    "change_time": True,
    "warehouse_id": True,
    "inbound_order_id": True,
    "fbt_order_id": True,
    "quantity": True,
    "available_quantity": True,
    "expiration_time": True,
}

_STATIC_SPECS: dict[tuple[str, str], Spec] = {
    (TIKTOK, ORDERS_RAW): TIKTOK_ORDER_SPEC,
    (TIKTOK, RETURNS_RAW): TIKTOK_RETURN_SPEC,
    (TIKTOK, ORDERS_RECONCILE_PAGE): TIKTOK_RECONCILE_PAGE_SPEC,
    (TIKTOK, ORDERS_DIAGNOSIS_SNAPSHOT): TIKTOK_DIAGNOSIS_ORDER_SPEC,
    (TIKTOK, WEBHOOK_ORDER): {**_WEBHOOK_ENVELOPE, "data": _WEBHOOK_ORDER_DATA},
    (TIKTOK, WEBHOOK_RETURN): {**_WEBHOOK_ENVELOPE, "data": _WEBHOOK_RETURN_DATA},
    (TIKTOK, WEBHOOK_OTHER): {**_WEBHOOK_ENVELOPE, "data": _WEBHOOK_OTHER_DATA},
    (TIKTOK, WEBHOOK_UNKNOWN): dict(_WEBHOOK_ENVELOPE),
}


class UnknownPayloadEndpoint(LookupError):
    """No allowlist for this (platform, endpoint): the caller must store nothing."""

    def __init__(self, platform: str, endpoint: str) -> None:
        super().__init__(f"no payload allowlist for {platform}/{endpoint}; refusing to store")
        self.platform = platform
        self.endpoint = endpoint


def ingest_endpoint(dataset: str) -> str:
    """The allowlist endpoint name of a Connector ingest dataset."""
    return f"{INGEST_PREFIX}{dataset}"


@cache
def _ingest_specs() -> dict[tuple[str, str], Spec]:
    # Imported here: ``services.ingest`` imports this module (its gateway filters
    # the raw copy), so a top-level import would be circular.
    from juli_backend.services.ingest.mapping import DATASETS

    specs: dict[tuple[str, str], Spec] = {}
    for (platform, dataset), dataset_spec in DATASETS.items():
        row: dict[str, Any] = {name: True for name in dataset_spec.row_model.model_fields}
        row["extra"] = OPEN_NUMERIC
        specs[(platform, ingest_endpoint(dataset))] = {
            "source": True,
            "source_version": True,
            "captured_at": True,
            "period": {"start": True, "end": True, "granularity": True},
            "order_type": True,
            "platform_shop_id": True,
            "rows": row,
        }
    return specs


def spec_for(platform: str, endpoint: str) -> Spec:
    """The allowlist of one endpoint; raises :class:`UnknownPayloadEndpoint` if none."""
    spec = _STATIC_SPECS.get((platform, endpoint)) or _ingest_specs().get((platform, endpoint))
    if spec is None:
        raise UnknownPayloadEndpoint(platform, endpoint)
    return spec


def all_specs() -> dict[tuple[str, str], Spec]:
    """Every known (platform, endpoint) and its allowlist."""
    return {**_STATIC_SPECS, **_ingest_specs()}


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _filter_open_numeric(value: Any) -> Any:
    if not isinstance(value, dict):
        return None
    return {k: v for k, v in value.items() if v is None or isinstance(v, int | float)}


def _filter_object(value: Mapping[str, Any], spec: Spec) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, child in value.items():
        rule = spec.get(key)
        if rule is None:
            continue
        if rule is OPEN_NUMERIC:
            out[key] = _filter_open_numeric(child)
        elif isinstance(rule, ReasonRule):
            if _is_scalar(child):
                out[key] = rule.apply(child)
        elif rule is True:
            if _is_scalar(child):
                out[key] = child
        else:
            filtered = _filter_value(child, rule)
            if filtered is not _DROP:
                out[key] = filtered
    return out


_DROP = object()


def _filter_value(value: Any, spec: Spec) -> Any:
    if isinstance(value, dict):
        return _filter_object(value, spec)
    if isinstance(value, list):
        return [_filter_object(item, spec) for item in value if isinstance(item, dict)]
    if _is_scalar(value):
        return value
    return _DROP


def allowlist_payload(platform: str, endpoint: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """``payload`` reduced to the endpoint's allowlist (a new dict; input untouched)."""
    return _filter_object(payload, spec_for(platform, endpoint))
