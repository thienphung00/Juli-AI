"""Buyer data never lands: the payload allowlist and the per-shop ``buyer_id`` pseudonym.

ADR-116 §4 and its Verification bullet, grill log D5 / D8, on the SQLite schema:

- a TikTok order / return / cancellation shaped like the Partner API's (fixtures in
  ``tests/fixtures/tiktok_privacy/``, recipient and buyer fields included) leaves
  none of them in the stored bronze, silver or ingest row, at any depth;
- the stored ``buyer_id`` is ``HMAC-SHA256(shop key, platform buyer id)``: the same
  buyer in one shop is one id, in two shops two ids; the key is stored sealed;
- silver promotion produces the same non-buyer values as from the unfiltered row;
- an unknown (platform, endpoint) is refused, so nothing is stored;
- the ingest gateway refuses a shop without an open ``service`` consent;
- the clean-up command removes the fields from stored rows and re-keys ids, writes
  nothing on a dry run, and changes nothing the second time;
- migration 104 is additive, its role grants are SELECT / INSERT only, and the
  deferred tail moved onto it.

The Postgres claims (RLS with two tenants, the grants, the 104 round trip, the
clean-up as the owner) are in ``tests/integration/test_payload_privacy_db.py``.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import importlib.util
import json
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.database.token_crypto import (
    decrypt_for_purpose,
    decrypt_token,
    encrypt_for_purpose,
)
from juli_backend.integrations.tiktok.mapping import (
    expand_order_line_items,
    normalize_cancellation,
    normalize_order,
    normalize_return,
)
from juli_backend.models.ingest import IngestRawPayload
from juli_backend.models.models import (
    BronzeOrderRawPayload,
    BronzeReturnRawPayload,
    Order,
    Return,
)
from juli_backend.models.pseudonym_keys import ShopPseudonymKey
from juli_backend.services import ingest as ingest_service
from juli_backend.services.cdp_batch.partition_checkpoints import (
    append_reconcile_bronze_page,
    recover_checkpoint_from_bronze,
)
from juli_backend.services.cdp_speed.targeted_fetch_bronze_handoff import (
    BronzeAppendTracker,
    make_targeted_fetch_bronze_handoff,
)
from juli_backend.services.consent import revoke_consent
from juli_backend.services.etl import append_targeted_order_payload, append_targeted_return_payload
from juli_backend.services.etl.silver_promotion import SilverOrdersReturnsPromoter
from juli_backend.services.etl.transform import (
    bronze_order_to_upsert_kwargs,
    bronze_return_to_upsert_kwargs,
)
from juli_backend.services.privacy.payload_allowlist import (
    FORBIDDEN_FRAGMENT_EXCEPTIONS,
    FORBIDDEN_KEY_FRAGMENTS,
    OPEN_NUMERIC,
    ORDERS_RAW,
    RETURNS_RAW,
    TIKTOK,
    UnknownPayloadEndpoint,
    all_specs,
    allowlist_payload,
)
from juli_backend.services.privacy.payload_cleanup import clean_shop, run_cleanup
from juli_backend.services.privacy.pseudonym import (
    KEY_PURPOSE,
    buyer_pseudonym,
    is_pseudonym,
    pseudonymize_buyer_id,
    shop_pseudonym_key,
)
from juli_backend.services.privacy.raw_payload import sanitize_raw_payload
from tests.support.builders import make_order, make_tenant
from tests.support.consent import grant_service_consent

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests/fixtures/tiktok_privacy"
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
MIGRATION = MIGRATIONS / "versions/104_shop_pseudonym_keys.py"
BACKFILL = MIGRATIONS / "deferred/101_write_mode_backfill.py"

RECEIVED = datetime(2026, 10, 26, 3, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 26, 3, 0)
DAY = date(2026, 10, 25)
PII_MARKER = "PII_MARKER"


def _fixture(name: str) -> dict[str, Any]:
    data = json.loads((FIXTURES / name).read_text("utf-8"))
    data.pop("_source", None)
    return data


def _order() -> dict[str, Any]:
    return _fixture("order_search_202309_order.json")


def _return() -> dict[str, Any]:
    return _fixture("return_search_202309_return.json")


def _cancellation() -> dict[str, Any]:
    return _fixture("cancellation_search_202309_cancellation.json")


def _keys(value: Any) -> set[str]:
    """Every object key at any depth."""
    if isinstance(value, dict):
        found = set(value)
        for child in value.values():
            found |= _keys(child)
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for item in value:
            found |= _keys(item)
        return found
    return set()


def _assert_no_buyer_data(stored: Any) -> None:
    text = json.dumps(stored, ensure_ascii=False)
    assert PII_MARKER not in text, text
    for key in _keys(stored):
        lowered = key.lower()
        if key in FORBIDDEN_FRAGMENT_EXCEPTIONS:
            continue
        assert not any(fragment in lowered for fragment in FORBIDDEN_KEY_FRAGMENTS), key


def _hmac(key: bytes, raw: str) -> str:
    return hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()


# -- the allowlists themselves ------------------------------------------------------------


def _spec_keys(spec: Any) -> set[str]:
    found: set[str] = set()
    for key, rule in spec.items():
        found.add(key)
        if isinstance(rule, dict):
            found |= _spec_keys(rule)
    return found


def test_no_allowlist_lists_a_buyer_field():
    specs = all_specs()
    assert {
        (TIKTOK, ORDERS_RAW),
        (TIKTOK, RETURNS_RAW),
        (TIKTOK, "orders.reconcile_page"),
        ("shopee", "ingest.traffic_overview"),
        ("shopee", "ingest.item_by_source"),
        ("shopee", "ingest.item_performance"),
        ("shopee", "ingest.shop_traffic"),
    } <= set(specs)
    for (platform, endpoint), spec in specs.items():
        for key in _spec_keys(spec):
            if key in FORBIDDEN_FRAGMENT_EXCEPTIONS:
                continue
            assert not any(f in key.lower() for f in FORBIDDEN_KEY_FRAGMENTS), (
                platform,
                endpoint,
                key,
            )


def test_every_connector_dataset_has_an_allowlist():
    from juli_backend.services.ingest.mapping import DATASETS

    specs = all_specs()
    for platform, dataset in DATASETS:
        rows = specs[(platform, f"ingest.{dataset}")]["rows"]
        assert rows["extra"] is OPEN_NUMERIC


@pytest.mark.parametrize("endpoint", ["orders.webhook", "orders", "products.raw", ""])
def test_an_unknown_endpoint_is_refused(endpoint):
    with pytest.raises(UnknownPayloadEndpoint):
        allowlist_payload(TIKTOK, endpoint, _order())
    with pytest.raises(UnknownPayloadEndpoint):
        allowlist_payload("lazada", ORDERS_RAW, _order())


async def test_sanitize_refuses_an_unknown_endpoint_before_touching_keys(session):
    _, shop = await make_tenant(session)
    with pytest.raises(UnknownPayloadEndpoint):
        await sanitize_raw_payload(
            session, shop.id, platform=TIKTOK, endpoint="orders.webhook", payload=_order()
        )
    assert (await session.execute(select(ShopPseudonymKey))).first() is None


def test_a_listed_scalar_key_holding_an_object_is_dropped():
    payload = {"order_id": "1", "cancel_reason": {"name": "x"}, "line_items": ["free text"]}
    assert allowlist_payload(TIKTOK, ORDERS_RAW, payload) == {"order_id": "1", "line_items": []}


def test_the_input_is_not_mutated():
    raw = normalize_order(_order())
    before = copy.deepcopy(raw)
    allowlist_payload(TIKTOK, ORDERS_RAW, raw)
    assert raw == before


# -- bronze ---------------------------------------------------------------------------------


async def _stored_order(session, shop) -> BronzeOrderRawPayload:
    row_id = await append_targeted_order_payload(
        session,
        shop_id=shop.id,
        payload=normalize_order(_order()),
        received_at=RECEIVED,
        source_event_id=f"evt-{uuid.uuid4()}",
    )
    assert row_id is not None
    return await session.get(BronzeOrderRawPayload, row_id)


async def test_bronze_order_keeps_no_buyer_field_and_buyer_id_is_the_hmac(session):
    _, shop = await make_tenant(session)
    row = await _stored_order(session, shop)

    _assert_no_buyer_data(row.payload)
    assert "user_id" not in row.payload
    key = await shop_pseudonym_key(session, shop.id)
    assert row.payload["buyer_id"] == _hmac(key, "7494011223344556677")
    assert row.tiktok_order_id == "576461413038785752"
    # What downstream reads is still there.
    assert row.payload["payment"] == {
        "currency": "VND",
        "sub_total": "300000",
        "total_amount": "315000",
    }
    assert [item["sku_id"] for item in row.payload["line_items"]] == [
        "1729582718312380123",
        "1729582718312380124",
    ]


@pytest.mark.parametrize(
    ("loader", "normalize", "event"),
    [(_return, normalize_return, "ret"), (_cancellation, normalize_cancellation, "can")],
)
async def test_bronze_return_and_cancellation_keep_no_buyer_field(
    session, loader, normalize, event
):
    _, shop = await make_tenant(session)
    raw = loader()
    row_id = await append_targeted_return_payload(
        session,
        shop_id=shop.id,
        payload=normalize(raw),
        received_at=RECEIVED,
        source_event_id=f"{event}-1",
    )
    row = await session.get(BronzeReturnRawPayload, row_id)
    _assert_no_buyer_data(row.payload)
    assert row.tiktok_order_id == "576461413038785752"
    if "user_id" in raw:
        key = await shop_pseudonym_key(session, shop.id)
        assert row.payload["buyer_id"] == _hmac(key, raw["user_id"])


async def test_the_bronze_handoff_stores_the_sanitized_row(session):
    _, shop = await make_tenant(session)
    tracker = BronzeAppendTracker()
    handoff = make_targeted_fetch_bronze_handoff(
        session, shop_id=shop.id, job_token="job-1", tracker=tracker, clock=lambda: RECEIVED
    )
    await handoff("tiktok.orders.raw", "shop-key", json.dumps(normalize_order(_order())).encode())
    await handoff(
        "tiktok.returns.raw", "shop-key", json.dumps(normalize_return(_return())).encode()
    )

    order_row = await session.get(BronzeOrderRawPayload, tracker.order_row_ids[0])
    return_row = await session.get(BronzeReturnRawPayload, tracker.return_row_ids[0])
    _assert_no_buyer_data(order_row.payload)
    _assert_no_buyer_data(return_row.payload)
    assert order_row.payload["buyer_id"] == return_row.payload["buyer_id"]


async def test_reconcile_pages_keep_order_fields_and_the_cursor(session):
    _, shop = await make_tenant(session)
    appended = await append_reconcile_bronze_page(
        session,
        shop_id=shop.id,
        partition_date=DAY,
        fetched_page_token=None,
        next_page_token="tok-2",
        payloads=[normalize_order(_order())],
        received_at=RECEIVED.replace(tzinfo=None),
    )
    assert appended == 1
    row = (await session.execute(select(BronzeOrderRawPayload))).scalar_one()
    _assert_no_buyer_data(row.payload)
    assert is_pseudonym(row.payload["records"][0]["buyer_id"])
    checkpoint = await recover_checkpoint_from_bronze(session, shop_id=shop.id, partition_date=DAY)
    assert checkpoint is not None and checkpoint.page_token == "tok-2"


# -- silver: same values, pseudonymous buyer -----------------------------------------------


def _without_buyer(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in kwargs.items() if k != "buyer_id"}


@pytest.mark.parametrize(
    ("loader", "normalize", "endpoint", "transform"),
    [
        (_order, normalize_order, ORDERS_RAW, bronze_order_to_upsert_kwargs),
        (_return, normalize_return, RETURNS_RAW, bronze_return_to_upsert_kwargs),
        (_cancellation, normalize_cancellation, RETURNS_RAW, bronze_return_to_upsert_kwargs),
    ],
)
def test_silver_values_are_unchanged_by_the_allowlist(loader, normalize, endpoint, transform):
    unfiltered = normalize(loader())
    if isinstance(unfiltered.get("refund_amount"), dict):
        # normalize_cancellation leaves TikTok's refund object as-is, and the
        # transform needs a number (a separate, pre-existing gap); flatten it the
        # way normalize_return does so both sides can be compared.
        unfiltered["refund_amount"] = unfiltered["refund_amount"]["refund_total"]
    kept = allowlist_payload(TIKTOK, endpoint, unfiltered)
    before = transform(unfiltered, received_at=RECEIVED)
    after = transform(kept, received_at=RECEIVED)
    assert _without_buyer(after) == _without_buyer(before)
    assert after["buyer_id"] == before["buyer_id"]  # pseudonymised separately


def test_line_item_expansion_is_unchanged_by_the_allowlist():
    unfiltered = normalize_order(_order())
    kept = allowlist_payload(TIKTOK, ORDERS_RAW, unfiltered)
    assert expand_order_line_items(kept) == expand_order_line_items(unfiltered)


def test_a_stored_row_normalizes_to_itself():
    kept = allowlist_payload(TIKTOK, ORDERS_RAW, normalize_order(_order()))
    assert allowlist_payload(TIKTOK, ORDERS_RAW, normalize_order(kept)) == kept


async def test_promotion_writes_the_pseudonym_to_silver_and_joins_returns(session):
    _, shop = await make_tenant(session)
    order_row = await _stored_order(session, shop)
    return_id = await append_targeted_return_payload(
        session,
        shop_id=shop.id,
        payload=normalize_return(_return()),
        received_at=RECEIVED,
        source_event_id="ret-join",
    )
    promoter = SilverOrdersReturnsPromoter(session)
    order = await promoter.promote_order(order_row)
    ret = await promoter.promote_return(await session.get(BronzeReturnRawPayload, return_id))

    key = await shop_pseudonym_key(session, shop.id)
    assert order.buyer_id == ret.buyer_id == _hmac(key, "7494011223344556677")
    assert ret.order_id == order.id
    assert order.status == "cancelled" and order.tiktok_order_id == "576461413038785752"


# -- the pseudonym ---------------------------------------------------------------------------


async def test_same_buyer_same_shop_one_id_two_shops_two_ids(session):
    _, shop_a = await make_tenant(session)
    _, shop_b = await make_tenant(session)
    a1 = await pseudonymize_buyer_id(session, shop_a.id, "7494011223344556677")
    a2 = await pseudonymize_buyer_id(session, shop_a.id, 7494011223344556677)
    b1 = await pseudonymize_buyer_id(session, shop_b.id, "7494011223344556677")
    assert a1 == a2 and is_pseudonym(a1)
    assert b1 != a1 and is_pseudonym(b1)
    assert await pseudonymize_buyer_id(session, shop_a.id, "another-buyer") != a1


async def test_pseudonymising_is_idempotent_and_leaves_empty_values(session):
    _, shop = await make_tenant(session)
    once = await pseudonymize_buyer_id(session, shop.id, "7494011223344556677")
    assert await pseudonymize_buyer_id(session, shop.id, once) == once
    assert await pseudonymize_buyer_id(session, shop.id, None) is None
    assert await pseudonymize_buyer_id(session, shop.id, "") == ""


async def test_the_key_is_random_per_shop_stored_sealed_and_reused(session, engine):
    _, shop = await make_tenant(session)
    key = await shop_pseudonym_key(session, shop.id)
    assert len(key) == 32
    await session.commit()

    row = (await session.execute(select(ShopPseudonymKey))).scalar_one()
    assert row.shop_id == shop.id
    assert row.key_ciphertext.startswith(f"enc:p1:{KEY_PURPOSE}:")
    assert base64.b64encode(key).decode() not in row.key_ciphertext
    # A fresh session (no cache) opens the same key.
    async with async_sessionmaker(engine, expire_on_commit=False)() as fresh:
        assert await shop_pseudonym_key(fresh, shop.id) == key
        assert await pseudonymize_buyer_id(fresh, shop.id, "x") == buyer_pseudonym(key, "x")


def test_a_sealed_value_opens_only_for_its_purpose():
    sealed = encrypt_for_purpose("secret-key", purpose=KEY_PURPOSE)
    assert decrypt_for_purpose(sealed, purpose=KEY_PURPOSE) == "secret-key"
    with pytest.raises(ValueError, match="not sealed for purpose"):
        decrypt_for_purpose(sealed, purpose="other")
    # The token helper treats it as an unknown (plaintext) value, never decrypts it.
    assert decrypt_token(sealed) == sealed


# -- silver through the ETL consumer --------------------------------------------------------


async def test_the_consumer_pseudonymises_returns_too(session):
    from juli_backend.services.etl.consumer import EtlConsumer, ProcessOutcome
    from juli_backend.services.etl.record import IngestRecord

    _, shop = await make_tenant(session)
    await session.commit()

    async def no_dlq(*_: Any) -> None:
        raise AssertionError("no DLQ expected")

    consumer = EtlConsumer(session=session, dlq_handoff=no_dlq)
    outcome = await consumer.ingest(
        IngestRecord(
            channel="tiktok.returns.raw",
            shop_key=shop.tiktok_shop_id,
            value=json.dumps(normalize_return(_return())).encode(),
        )
    )
    assert outcome == ProcessOutcome.PROCESSED
    ret = (await session.execute(select(Return))).scalar_one()
    key = await shop_pseudonym_key(session, shop.id)
    assert ret.buyer_id == _hmac(key, "7494011223344556677")


# -- the ingest gateway -------------------------------------------------------------------


def _ingest_body(**extra: Any) -> dict[str, Any]:
    return {
        "source": "extension",
        "source_version": "0.1.0",
        "captured_at": "2026-10-26T09:30:00+07:00",
        "period": {"start": DAY.isoformat(), "end": DAY.isoformat(), "granularity": "day"},
        "order_type": "confirmed",
        "rows": [
            {
                "date": DAY.isoformat(),
                "item_id": "123",
                "item_name": "Áo thun",
                "source": "psd_label_product_card",
                "sales": 100000,
                "orders": 1,
                "extra": {"sales_ratio": 0.2, "flag": True, "none": None, **extra},
            }
        ],
    }


async def _shopee_shop(session):
    _, shop = await make_tenant(session, platform="shopee", tiktok_shop_id=None)
    return shop


async def _post(session, shop, body):
    return await ingest_service.ingest(
        session,
        shop_id=shop.id,
        platform="shopee",
        dataset="item_by_source",
        body=ingest_service.IngestBody.model_validate(body),
        token_id=None,
        now=NOW,
    )


async def test_the_ingest_raw_copy_keeps_only_listed_fields(session):
    shop = await _shopee_shop(session)
    await grant_service_consent(session, shop.id)
    result = await _post(session, shop, _ingest_body(note=f"{PII_MARKER} call 0900"))

    raw = await session.get(IngestRawPayload, result.raw_payload_id)
    _assert_no_buyer_data(raw.payload)
    assert raw.payload["rows"][0]["extra"] == {"sales_ratio": 0.2, "flag": True, "none": None}
    assert raw.payload["rows"][0]["item_name"] == "Áo thun"
    assert raw.payload["period"] == {
        "start": DAY.isoformat(),
        "end": DAY.isoformat(),
        "granularity": "day",
    }


async def test_the_gateway_refuses_a_shop_without_service_consent(session):
    shop = await _shopee_shop(session)
    with pytest.raises(ingest_service.IngestRejected) as info:
        await _post(session, shop, _ingest_body())
    assert info.value.code == "consent_required" and info.value.status == 403

    await grant_service_consent(session, shop.id)
    await revoke_consent(session, shop.id, "service", revoked_at=NOW)
    with pytest.raises(ingest_service.IngestRejected, match="consent_required"):
        await _post(session, shop, _ingest_body())
    assert (await session.execute(select(IngestRawPayload))).first() is None


# -- the clean-up command ------------------------------------------------------------------


async def _seed_legacy_rows(session, shop) -> None:
    """Rows as stored before the allowlist: full payloads, platform buyer ids."""
    session.add(
        BronzeOrderRawPayload(
            shop_id=shop.id,
            ingest_source="targeted_fetch",
            payload=normalize_order(_order()),
            received_at=NOW,
            tiktok_order_id="576461413038785752",
            source_event_id="legacy-order",
        )
    )
    session.add(
        BronzeReturnRawPayload(
            shop_id=shop.id,
            ingest_source="targeted_fetch",
            payload=normalize_return(_return()),
            received_at=NOW,
            tiktok_return_id="4035244019822920123",
            tiktok_order_id="576461413038785752",
            source_event_id="legacy-return",
        )
    )
    session.add(
        IngestRawPayload(
            shop_id=shop.id,
            platform="shopee",
            dataset="item_by_source",
            source="extension",
            source_version="0.1.0",
            captured_at=NOW,
            received_at=NOW,
            period_start=DAY,
            period_end=DAY,
            granularity="day",
            order_type="confirmed",
            content_hash=uuid.uuid4().hex,
            row_count=1,
            payload=_ingest_body(note=f"{PII_MARKER} free text"),
        )
    )
    session.add(
        IngestRawPayload(
            shop_id=shop.id,
            platform="shopee",
            dataset="retired_dataset",
            source="extension",
            source_version="0.0.1",
            captured_at=NOW,
            received_at=NOW,
            period_start=DAY,
            period_end=DAY,
            granularity="day",
            order_type="none",
            content_hash=uuid.uuid4().hex,
            row_count=1,
            payload={"rows": [{"buyer": f"{PII_MARKER}"}]},
        )
    )
    await make_order(session, shop, buyer_id="7494011223344556677")
    await session.flush()


async def test_clean_shop_removes_fields_rekeys_ids_and_is_idempotent(session):
    _, shop = await make_tenant(session)
    await _seed_legacy_rows(session, shop)

    first = await clean_shop(session, shop.id)
    assert {name: c.changed for name, c in first.items()} == {
        "bronze.order_raw_payloads": 1,
        "bronze.return_raw_payloads": 1,
        "public.ingest_raw_payloads": 2,
        "public.orders": 1,
        "public.returns": 0,
    }
    key = await shop_pseudonym_key(session, shop.id)
    for model in (BronzeOrderRawPayload, BronzeReturnRawPayload, IngestRawPayload):
        for row in (await session.execute(select(model))).scalars():
            _assert_no_buyer_data(row.payload)
    order_payload = (await session.execute(select(BronzeOrderRawPayload))).scalar_one().payload
    assert order_payload["buyer_id"] == _hmac(key, "7494011223344556677")
    retired = (
        await session.execute(
            select(IngestRawPayload).where(IngestRawPayload.dataset == "retired_dataset")
        )
    ).scalar_one()
    assert retired.payload == {}  # unknown endpoint: nothing kept
    order = (await session.execute(select(Order))).scalar_one()
    assert order.buyer_id == _hmac(key, "7494011223344556677")

    second = await clean_shop(session, shop.id)
    assert all(count.changed == 0 for count in second.values())
    assert second["bronze.order_raw_payloads"].scanned == 1


async def test_dry_run_writes_nothing_and_apply_writes_it(session, engine):
    _, shop = await make_tenant(session)
    _, other = await make_tenant(session)
    await _seed_legacy_rows(session, shop)
    await session.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    dry = await run_cleanup(factory, apply=False)
    assert dry.shops == 2
    assert dry.tables["bronze.order_raw_payloads"].changed == 1
    async with factory() as check:
        stored = (await check.execute(select(BronzeOrderRawPayload))).scalar_one()
        assert PII_MARKER in json.dumps(stored.payload, ensure_ascii=False)
        assert (await check.execute(select(ShopPseudonymKey))).first() is None

    applied = await run_cleanup(factory, apply=True, only=[shop.id])
    assert applied.shops == 1 and applied.tables["public.orders"].changed == 1
    rendered = applied.render(applied=True)
    assert "bronze.order_raw_payloads: scanned 1, changed 1" in rendered
    assert PII_MARKER not in rendered and str(shop.id) not in rendered
    async with factory() as check:
        stored = (await check.execute(select(BronzeOrderRawPayload))).scalar_one()
        _assert_no_buyer_data(stored.payload)

    again = await run_cleanup(factory, apply=True)
    assert all(count.changed == 0 for count in again.tables.values())
    assert other.id  # the second shop had nothing to clean


# -- migration 104 ---------------------------------------------------------------------------


def _migration_module():
    spec = importlib.util.spec_from_file_location("mig104", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_fits_alembic_and_the_deferred_tail_moved_onto_it():
    mig = _migration_module()
    assert mig.revision == "104_shop_pseudonym_keys" and len(mig.revision) <= 32
    assert mig.down_revision == "103_data_use_consents"
    assert f'down_revision: str | None = "{mig.revision}"' in BACKFILL.read_text("utf-8")


def test_the_app_role_may_only_select_and_insert():
    text = MIGRATION.read_text("utf-8")
    assert "GRANT SELECT, INSERT ON public.{TABLE} TO {APP_ROLE}" in text
    for forbidden in ("DELETE ON", "UPDATE ON", "FOR DELETE", "FOR UPDATE", "GRANT UPDATE"):
        assert forbidden not in text


def test_the_additive_gate_accepts_migration_104():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION])
    assert result.accepted, result.report()


def test_shop_pseudonym_keys_is_classified_tenant_direct():
    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    assert TABLE_CLASSIFICATION_MAP[("public", "shop_pseudonym_keys")] == "tenant_direct"
