"""Content hashes, per-field attribution and ``seller_change`` events (fast track P60-1b).

ADR-107 "Amendment 2026-10-20" §6 (hashes + audit link), §8 (attribution) and
§9 (the revert check on hashes). The Postgres-only claims (migration round trip,
CHECK, RLS, the migration's data step, the backfill as ``juli_app``) are in
``tests/integration/test_change_attribution_db.py``.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from juli_backend.models.card_events import CardEvent
from juli_backend.models.history import (
    ATTRIBUTIONS,
    KIND_CATEGORY,
    KIND_CONTENT,
    KIND_PRICE,
    KIND_PROMOTION,
    ExternalChange,
)
from juli_backend.models.models import ActionCard, ProductionWriteAudit
from juli_backend.models.run_changes import RunWriteValue
from juli_backend.services.agent.runner.write_capture import (
    LISTING_OPERATION,
    PRICE_OPERATION,
    FieldWrite,
    changed_fields,
    field_values,
)
from juli_backend.services.card_events import keys
from juli_backend.services.card_events.backfill import backfill_shop
from juli_backend.services.card_events.natural import (
    LINK_LAST_WRITE,
    LINK_OPEN_WINDOW,
    NATURAL_WORKFLOW_KEY,
    OPEN_PLAN_WINDOW,
    RunRef,
    link_card,
    seller_change_spec,
)
from juli_backend.services.product_history import store
from juli_backend.services.product_history.attribution import (
    JULI_WRITE_LOOKAHEAD,
    JULI_WRITE_LOOKBACK,
    WriteRecord,
    all_juli,
    attribution_fields,
    event_attribution,
    label_fields,
    summarize,
)
from juli_backend.services.product_history.normalize import (
    ProductFields,
    field_value_hash,
    normalize_detail,
)
from juli_backend.services.run_changes.planner import RevertPlan
from juli_backend.services.run_changes.recorder import SqlWriteValueRecorder
from tests.support.builders import make_product, make_tenant
from tests.support.builders import make_workflow_run as _make_workflow_run

REPO = Path(__file__).resolve().parents[2]
VERSIONS = REPO / "backend/src/juli_backend/database/migrations/versions"
MIGRATION = VERSIONS / "096_change_attribution.py"
DEFERRED = (
    REPO
    / "backend/src/juli_backend/database/migrations/deferred/074_users_placeholder_phone_cleanup.py"
)

T0 = datetime(2026, 10, 20, 3, 0)


def _raw(**kw):
    body = {
        "id": "tt-1",
        "title": "  Nồi lẩu điện mini  ",
        "description": "<p>mô tả</p>",
        "main_images": [{"uri": "img-a"}, {"uri": "img-b"}],
        "skus": [
            {"id": "s2", "price": {"tax_exclusive_price": "72000.00", "currency": "VND"}},
            {"id": "s1", "price": {"tax_exclusive_price": "50000", "currency": "VND"}},
        ],
        "status": "ACTIVATE",
    }
    body.update(kw)
    return body


# -- migration pins ------------------------------------------------------------------------


def _migration():
    spec = importlib.util.spec_from_file_location("mig096", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_and_vocabulary():
    mig = _migration()
    assert mig.revision == "096_change_attribution" and len(mig.revision) <= 32
    assert mig.down_revision == "095_card_events"
    assert mig.ATTRIBUTIONS == ATTRIBUTIONS == ("juli", "seller_revert", "seller_change", "mixed")
    assert 'down_revision: str | None = "096_change_attribution"' in DEFERRED.read_text("utf-8")
    children = [
        p.name
        for p in VERSIONS.glob("*.py")
        if 'down_revision: str | None = "095_card_events"' in p.read_text("utf-8")
    ]
    assert children == ["096_change_attribution.py"]


def test_migration_grants_nothing_new_on_the_append_only_tables():
    text = MIGRATION.read_text("utf-8")
    assert "GRANT UPDATE" not in text and "GRANT SELECT" not in text
    # The one grant is EXECUTE on the identifiers-only enumeration, never PUBLIC.
    assert "REVOKE ALL ON FUNCTION public.{FUNCTION_SIGNATURE} FROM PUBLIC" in text
    assert "SECURITY DEFINER" in text


def test_model_columns_are_added_by_the_migration():
    text = MIGRATION.read_text("utf-8")
    for column in ("before_hash", "after_hash", "before_read_at", "production_write_audit_id"):
        assert column in RunWriteValue.__table__.columns
        assert f'"{column}"' in text
    for column in ("attribution", "field_attribution"):
        assert column in ExternalChange.__table__.columns
        assert f'"{column}"' in text


# -- the shared hash helper ------------------------------------------------------------------


def test_field_hashes_equal_the_snapshot_hashing():
    """A Juli write's value (write_capture form) hashes like the product read (snapshot form)."""
    raw = _raw()
    product = normalize_detail(raw)
    state = ProductFields.of(product)
    listing = field_values(LISTING_OPERATION, raw)
    price = field_values(PRICE_OPERATION, raw)["price"]
    assert field_value_hash("description", listing["description"]) == product.description_hash
    for name in ("title", "description", "main_images"):
        assert field_value_hash(name, listing[name]) == state.field_hash(name)
    assert field_value_hash("price", price) == state.field_hash("price", like=price)
    # The same state stored as a snapshot hashes the same.
    snap = store._snapshot_row(uuid.uuid4(), product, now=T0, source="reconcile")
    stored = store.product_fields_of_snapshot(snap)
    for name in ("title", "description", "main_images"):
        assert stored.field_hash(name) == state.field_hash(name)
    assert stored.field_hash("price", like=price) == state.field_hash("price", like=price)


def test_hash_canonical_forms():
    assert field_value_hash("title", "  a ") == field_value_hash("title", "a")
    assert field_value_hash("main_images", [{"uri": "x"}, "y"]) == field_value_hash(
        "main_images", ["x", "y"]
    )
    assert field_value_hash("main_images", ["x", "y"]) != field_value_hash(
        "main_images", ["y", "x"]
    )
    # Price amounts in the snapshot's plain-decimal form, SKUs in any order.
    one = [{"sku_id": "s1", "amount": "50000.00"}, {"sku_id": "s2", "amount": "72000"}]
    two = [{"sku_id": "s2", "amount": "72000.0"}, {"sku_id": "s1", "amount": "5E+4"}]
    assert field_value_hash("price", one) == field_value_hash("price", two)
    assert field_value_hash("title", None) is None


def test_price_hash_covers_only_the_skus_juli_wrote():
    state = ProductFields.of(normalize_detail(_raw()))
    wrote = [{"sku_id": "s1", "amount": "50000"}]
    assert field_value_hash("price", wrote) == state.field_hash("price", like=wrote)
    assert state.field_hash("price", like=wrote) != state.field_hash("price")


# -- attribute_fields matrix -----------------------------------------------------------------


def _write(field, before, after, at, run_id=None):
    return WriteRecord(
        field=field,
        recorded_at=at,
        before_value=before,
        after_value=after,
        workflow_run_id=run_id,
    )


STATE = ProductFields.of(normalize_detail(_raw(title="Mới")))


def _labels(writes, *, fields=("title",), occurred_at=T0, known_at=None, kind=KIND_CONTENT):
    return label_fields(
        kind, list(fields), STATE, writes, occurred_at=occurred_at, known_at=known_at
    )


@pytest.mark.parametrize(
    ("offset", "label"),
    [
        (timedelta(0), "juli"),
        (-JULI_WRITE_LOOKBACK, "juli"),  # the window's oldest edge is inside
        (-JULI_WRITE_LOOKBACK - timedelta(seconds=1), "seller_change"),
        (JULI_WRITE_LOOKAHEAD, "juli"),  # the skew edge is inside
        (JULI_WRITE_LOOKAHEAD + timedelta(seconds=1), "seller_change"),
    ],
)
def test_juli_needs_the_write_inside_the_window(offset, label):
    assert _labels([_write("title", "Cũ", "Mới", T0 + offset)]) == {"title": label}


def test_seller_revert_matches_the_latest_writes_before_value_at_any_age():
    old = T0 - timedelta(days=60)
    reverted = ProductFields.of(normalize_detail(_raw(title="Cũ")))
    writes = [_write("title", "Cũ", "Mới", old)]
    labels = label_fields(KIND_CONTENT, ["title"], reverted, writes, occurred_at=T0)
    assert labels == {"title": "seller_revert"}
    # Only the most recent write counts: an older before-value is not a revert.
    writes.append(_write("title", "Mới", "Mới hơn", old + timedelta(days=1)))
    labels = label_fields(KIND_CONTENT, ["title"], reverted, writes, occurred_at=T0)
    assert labels == {"title": "seller_change"}


def test_a_write_after_detection_is_not_seen():
    """``known_at``: the live path cannot see a write recorded after it detected the change."""
    write = _write("title", "Cũ", "Mới", T0 + timedelta(minutes=30))
    assert _labels([write]) == {"title": "juli"}
    assert _labels([write], known_at=T0 + timedelta(minutes=10)) == {"title": "seller_change"}


def test_mixed_and_fields_juli_never_writes():
    writes = [_write("title", "Cũ", "Mới", T0)]
    labels = _labels(writes, fields=("title", "attributes"))
    assert labels == {"title": "juli", "attributes": "seller_change"}
    assert summarize(labels) == "mixed" and not all_juli(labels)
    assert event_attribution(labels) == "seller_change"
    assert summarize({"title": "juli", "description": "juli"}) == "juli"
    assert event_attribution({"title": "juli", "main_images": "seller_revert"}) == "seller_revert"


def test_kinds_juli_never_writes_are_seller_changes():
    assert _labels([], fields=("category_id",), kind=KIND_CATEGORY) == {
        "category_id": "seller_change"
    }
    assert attribution_fields(KIND_PRICE, ["price", "list_price", "sale_price"]) == ["price"]


def test_price_change_attributed_on_the_written_skus():
    wrote = [{"sku_id": "s1", "amount": "50000", "currency": "VND"}]
    before = [{"sku_id": "s1", "amount": "45000", "currency": "VND"}]
    labels = _labels(
        [_write("price", before, wrote, T0)], fields=("price", "list_price"), kind=KIND_PRICE
    )
    assert labels == {"price": "juli"}


def test_a_write_with_no_after_value_still_counts_as_before():
    """``_value_matches`` treated an unrecorded after-value as not comparable = a match."""
    assert _labels([_write("title", "Cũ", None, T0)]) == {"title": "juli"}


def test_stored_hash_is_used_when_present():
    write = WriteRecord(
        field="title",
        recorded_at=T0,
        before_value="Cũ",
        after_value="Mới",
        after_hash="0" * 64,  # a stored hash wins over the value
    )
    assert _labels([write]) == {"title": "seller_change"}


# -- card linkage -----------------------------------------------------------------------------


CARD_A, CARD_B = uuid.uuid4(), uuid.uuid4()
RUN_A, RUN_B, RUN_REVERT = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _runs(**over):
    runs = {
        RUN_A: RunRef(
            RUN_A, CARD_A, "optimize_product", "tt-1", T0 - timedelta(days=20), True, False
        ),
        RUN_B: RunRef(RUN_B, CARD_B, "content", "tt-1", T0 - timedelta(days=3), True, False),
    }
    runs.update(over)
    return runs


def test_link_prefers_the_card_whose_run_last_wrote_the_field():
    writes = [_write("title", "a", "b", T0 - timedelta(days=21), RUN_A)]
    link = link_card(
        fields=["title"],
        tiktok_product_id="tt-1",
        occurred_at=T0,
        known_at=T0,
        writes=writes,
        runs=_runs(),
    )
    assert (link.card_id, link.run_id, link.how) == (CARD_A, RUN_A, LINK_LAST_WRITE)
    assert link.workflow_key == "optimize_product"


def test_link_falls_back_to_the_open_plan_window():
    link = link_card(
        fields=["attributes"],
        tiktok_product_id="tt-1",
        occurred_at=T0,
        known_at=T0,
        writes=[],
        runs=_runs(),
    )
    assert (link.card_id, link.how) == (CARD_B, LINK_OPEN_WINDOW)


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        # The window closes OPEN_PLAN_WINDOW after the run executed (exclusive) ...
        ({RUN_B: RunRef(RUN_B, CARD_B, "c", "tt-1", T0 - OPEN_PLAN_WINDOW, True, False)}, None),
        (
            {
                RUN_B: RunRef(
                    RUN_B,
                    CARD_B,
                    "c",
                    "tt-1",
                    T0 - OPEN_PLAN_WINDOW + timedelta(seconds=1),
                    True,
                    False,
                )
            },
            CARD_B,
        ),
        # ... and opens only for an executed, non-revert run of this product.
        ({RUN_B: RunRef(RUN_B, CARD_B, "c", "tt-1", T0 - timedelta(days=1), False, False)}, None),
        ({RUN_REVERT: RunRef(RUN_REVERT, CARD_B, "c", "tt-1", T0, True, True)}, None),
        ({RUN_B: RunRef(RUN_B, CARD_B, "c", "tt-2", T0 - timedelta(days=1), True, False)}, None),
        ({RUN_B: RunRef(RUN_B, CARD_B, "c", "tt-1", T0 + timedelta(hours=1), True, False)}, None),
    ],
)
def test_open_window_edges(runs, expected):
    link = link_card(
        fields=["attributes"],
        tiktok_product_id="tt-1",
        occurred_at=T0,
        known_at=T0,
        writes=[],
        runs=runs,
    )
    assert link.card_id == expected


def test_card_less_natural_action_and_shop_level_change():
    link = link_card(
        fields=["title"],
        tiktok_product_id="tt-9",
        occurred_at=T0,
        known_at=T0,
        writes=[],
        runs=_runs(),
    )
    assert (link.card_id, link.run_id, link.workflow_key, link.how) == (
        None,
        None,
        NATURAL_WORKFLOW_KEY,
        None,
    )
    shop_level = link_card(
        fields=["promotion"],
        tiktok_product_id=None,
        occurred_at=T0,
        known_at=T0,
        writes=[],
        runs=_runs(),
    )
    assert shop_level.card_id is None


def test_seller_change_spec_key_payload_and_all_juli():
    change = SimpleNamespace(
        id=uuid.uuid4(),
        shop_id=uuid.uuid4(),
        tiktok_product_id="tt-1",
        occurred_at=T0,
        detected_at=T0,
        kind=KIND_CONTENT,
        source="webhook_15",
    )
    link = link_card(
        fields=["title"], tiktok_product_id="tt-1", occurred_at=T0, known_at=T0, writes=[], runs={}
    )
    labels = {"title": "seller_revert", "description": "juli"}
    spec = seller_change_spec(change, labels, link, source="live")
    assert spec is not None
    assert spec.dedup_key == keys.seller_change(change.id) == f"seller_change:{change.id}"
    assert spec.card_id is None and spec.workflow_key == NATURAL_WORKFLOW_KEY
    assert (spec.event_type, spec.actor, spec.subject_id) == ("seller_change", "seller", "tt-1")
    assert spec.payload["attribution"] == "seller_revert"
    assert spec.payload["fields"] == ["title"]
    assert spec.payload["field_attribution"] == labels
    assert seller_change_spec(change, {"title": "juli"}, link, source="live") is None


# -- the revert check on hashes ---------------------------------------------------------------


def test_revert_check_compares_hashes_and_falls_back_to_values():
    live = {"title": " Mới ", "description": "d", "main_images": ["a"]}
    expected = {"title": "Mới", "main_images": ["a"]}
    hashes = {
        "title": field_value_hash("title", "Mới"),
        "main_images": field_value_hash("main_images", ["a"]),
    }
    assert changed_fields(LISTING_OPERATION, live=live, expected=expected) == []
    assert (
        changed_fields(LISTING_OPERATION, live=live, expected=expected, expected_hashes=hashes)
        == []
    )
    changed = {**live, "title": "Seller viết"}
    assert changed_fields(
        LISTING_OPERATION, live=changed, expected=expected, expected_hashes=hashes
    ) == ["title"]
    # A missing hash (a pre-096 row) compares the values, as before.
    assert changed_fields(
        LISTING_OPERATION, live=changed, expected=expected, expected_hashes={"title": None}
    ) == ["title"]


def test_revert_plan_carries_hashes_and_keeps_the_old_state_shape():
    plan = RevertPlan(reverts_run_id="r", restore={"title": "a"}, expected={"title": "b"})
    assert "expected_hashes" not in plan.to_state()
    hashed = RevertPlan(
        reverts_run_id="r",
        restore={"title": "a"},
        expected={"title": "b"},
        expected_hashes={"title": "h"},
    )
    again = RevertPlan.from_state({"revert_plan": hashed.to_state()})
    assert again is not None and again.expected_hashes == {"title": "h"}


def test_field_write_equality_ignores_the_read_time():
    a = FieldWrite("title", "a", "b", "read_back")
    b = FieldWrite("title", "a", "b", "read_back", before_read_at=T0)
    assert a == b


# -- on the SQLite schema ----------------------------------------------------------------------


async def make_workflow_run(session, shop, **kw):
    kw.setdefault("subject_ref", uuid.uuid4().hex)
    return await _make_workflow_run(session, shop, **kw)


async def _card(session, shop, product) -> ActionCard:
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop.id,
        workflow_key=f"wk_{uuid.uuid4().hex[:8]}",
        subject_type="product",
        subject_id=str(product.id),
        revision=1,
        priority=1,
        severity="high",
        title="Tối ưu",
        description="d",
        recommendation_payload="{}",
        status="active",
        metadata_json="{}",
        computed_at=T0,
    )
    session.add(card)
    await session.flush()
    return card


def _sync_recorder_session(session):
    """The recorder runs on a sync session; the SQLite unit schema's sync handle."""
    return session.sync_session


@pytest.mark.asyncio
async def test_recorder_writes_hashes_read_time_and_a_unique_audit_link(session):
    _, shop = await make_tenant(session)
    product = await make_product(session, shop)
    run = await make_workflow_run(session, shop, product=product, status="completed")
    audit = ProductionWriteAudit(
        id=uuid.uuid4(),
        run_id=run.id,
        shop_id=shop.id,
        tiktok_product_id=product.tiktok_product_id,
        mutation_kind="update_product_listing",
        release_sha="0" * 40,
    )
    session.add(audit)
    await session.commit()

    def record(sync_session):
        SqlWriteValueRecorder(sync_session, shop_id=shop.id, workflow_run_id=run.id).record(
            tool_name="update_product_listing",
            tool_call_id="call-1",
            tiktok_product_id=product.tiktok_product_id,
            writes=[FieldWrite("title", " Cũ ", "Mới", "read_back", before_read_at=T0)],
        )

    await session.run_sync(record)
    row = (await session.execute(select(RunWriteValue))).scalar_one()
    assert row.before_hash == field_value_hash("title", "Cũ")
    assert row.after_hash == field_value_hash("title", "Mới")
    assert row.before_read_at == T0
    assert row.production_write_audit_id == audit.id

    # Two audit rows for the same mutation: no link (ambiguous).
    session.add(
        ProductionWriteAudit(
            id=uuid.uuid4(),
            run_id=run.id,
            shop_id=shop.id,
            tiktok_product_id=product.tiktok_product_id,
            mutation_kind="update_product_price",
            release_sha="0" * 40,
        )
    )
    session.add(
        ProductionWriteAudit(
            id=uuid.uuid4(),
            run_id=run.id,
            shop_id=shop.id,
            tiktok_product_id=product.tiktok_product_id,
            mutation_kind="update_product_price",
            release_sha="0" * 40,
        )
    )
    await session.commit()

    def record_price(sync_session):
        SqlWriteValueRecorder(sync_session, shop_id=shop.id, workflow_run_id=run.id).record(
            tool_name="update_product_price",
            tool_call_id="call-2",
            tiktok_product_id=product.tiktok_product_id,
            writes=[
                FieldWrite(
                    "price",
                    [{"sku_id": "s", "amount": "1"}],
                    [{"sku_id": "s", "amount": "2"}],
                    "read_back",
                )
            ],
        )

    await session.run_sync(record_price)
    price = (
        await session.execute(select(RunWriteValue).where(RunWriteValue.field == "price"))
    ).scalar_one()
    assert price.production_write_audit_id is None
    assert price.after_hash == field_value_hash("price", [{"sku_id": "s", "amount": "2"}])


async def _juli_write(session, shop, product, run, *, before, after, at):
    row = RunWriteValue(
        shop_id=shop.id,
        workflow_run_id=run.id,
        tool_call_id=uuid.uuid4().hex,
        tool_name="update_product_listing",
        tiktok_product_id=product.tiktok_product_id,
        field="title",
        before_value=before,
        after_value=after,
        after_source="read_back",
        before_hash=field_value_hash("title", before),
        after_hash=field_value_hash("title", after),
        recorded_at=at,
    )
    session.add(row)
    await session.flush()
    return row


async def _read(session, shop, product, title, *, previous, at):
    new = normalize_detail(_raw(id=product.tiktok_product_id, title=title, update_time=None))
    return await store.record_read(
        session, shop_id=shop.id, new=new, previous=previous, source="reconcile", now=at
    )


@pytest.mark.asyncio
async def test_record_read_attributes_and_emits_seller_change_live(session):
    _, shop = await make_tenant(session)
    product = await make_product(session, shop)
    card = await _card(session, shop, product)
    run = await make_workflow_run(
        session,
        shop,
        product=product,
        action_card_id=card.id,
        status="completed",
        stop_reason="final_response",
        completed_at=T0.replace(tzinfo=UTC),
    )
    base = await _read(session, shop, product, "Cũ", previous=None, at=T0 - timedelta(days=1))
    assert base.snapshot is not None and base.changes  # creation (no baseline flag)
    await _juli_write(session, shop, product, run, before="Cũ", after="Mới", at=T0)

    juli = await _read(
        session, shop, product, "Mới", previous=base.snapshot, at=T0 + timedelta(minutes=5)
    )
    [juli_row] = juli.changes
    assert (juli_row.juli_write, juli_row.attribution) == (True, "juli")
    assert juli_row.field_attribution == {"title": "juli"}

    revert = await _read(
        session, shop, product, "Cũ", previous=juli.snapshot, at=T0 + timedelta(days=5)
    )
    [revert_row] = revert.changes
    assert (revert_row.juli_write, revert_row.attribution) == (False, "seller_revert")

    other = await _read(
        session, shop, product, "Khác", previous=revert.snapshot, at=T0 + timedelta(days=6)
    )
    [other_row] = other.changes
    assert other_row.attribution == "seller_change"

    events = list(
        (
            await session.execute(
                select(CardEvent)
                .where(CardEvent.event_type == "seller_change")
                .order_by(CardEvent.occurred_at)
            )
        ).scalars()
    )
    by_change = {e.payload["external_change_id"]: e for e in events}
    assert str(juli_row.id) not in by_change
    assert by_change[str(revert_row.id)].card_id == card.id  # the card whose run wrote it
    assert by_change[str(revert_row.id)].payload["attribution"] == "seller_revert"
    assert by_change[str(revert_row.id)].payload["card_link"] == LINK_LAST_WRITE
    assert by_change[str(other_row.id)].payload["attribution"] == "seller_change"
    assert all(e.source == "live" for e in events)

    # The backfill derives the same keys: the creation, revert and change rows
    # are considered and nothing is inserted twice.
    report = await backfill_shop(session, shop.id)
    assert report.considered["seller_change"] == 3
    assert report.inserted.get("seller_change", 0) == 0


@pytest.mark.asyncio
async def test_card_less_change_on_a_product_with_no_card(session):
    _, shop = await make_tenant(session)
    product = await make_product(session, shop)
    base = await _read(session, shop, product, "A", previous=None, at=T0)
    changed = await _read(
        session, shop, product, "B", previous=base.snapshot, at=T0 + timedelta(days=1)
    )
    [row] = changed.changes
    event = (
        await session.execute(
            select(CardEvent).where(CardEvent.dedup_key == keys.seller_change(row.id))
        )
    ).scalar_one()
    assert event.card_id is None and event.workflow_key == NATURAL_WORKFLOW_KEY


@pytest.mark.asyncio
async def test_promotion_rows_are_labelled_by_juli_write(session):
    _, shop = await make_tenant(session)
    juli = await store.record_change(
        session,
        shop_id=shop.id,
        tiktok_product_id=None,
        kind=KIND_PROMOTION,
        fields=["promotion"],
        occurred_at=T0,
        detected_at=T0,
        source="webhook_63",
        juli_write=True,
        details=None,
        dedup_key="promo:1",
    )
    seller = await store.record_change(
        session,
        shop_id=shop.id,
        tiktok_product_id=None,
        kind=KIND_PROMOTION,
        fields=["promotion"],
        occurred_at=T0,
        detected_at=T0,
        source="webhook_63",
        juli_write=False,
        details=None,
        dedup_key="promo:2",
    )
    assert juli is not None and juli.attribution == "juli"
    assert seller is not None and seller.attribution == "seller_change"
    event = (
        await session.execute(select(CardEvent).where(CardEvent.event_type == "seller_change"))
    ).scalar_one()
    assert (event.subject_type, event.subject_id, event.card_id) == ("shop", "", None)


@pytest.mark.asyncio
async def test_a_failing_seller_change_write_never_breaks_the_read(session, monkeypatch, caplog):
    from juli_backend.services.card_events import natural

    async def boom(*_a, **_k):
        raise RuntimeError("log down")

    monkeypatch.setattr(natural, "_live_link", boom)
    _, shop = await make_tenant(session)
    product = await make_product(session, shop)
    base = await _read(session, shop, product, "A", previous=None, at=T0)
    assert base.changes and base.changes[0].attribution == "seller_change"
    assert "card_event_write_failed" in caplog.text


@pytest.mark.asyncio
async def test_backfill_labels_a_pre_096_row_from_its_snapshot(session):
    """A row written before 096 (no attribution) is labelled as the live path would."""
    _, shop = await make_tenant(session)
    product = await make_product(session, shop)
    card = await _card(session, shop, product)
    run = await make_workflow_run(session, shop, product=product, action_card_id=card.id)
    base = await _read(session, shop, product, "Cũ", previous=None, at=T0 - timedelta(days=9))
    await _juli_write(
        session, shop, product, run, before="Cũ", after="Mới", at=T0 - timedelta(days=8)
    )
    snap = store._snapshot_row(
        shop.id,
        normalize_detail(_raw(id=product.tiktok_product_id, title="Cũ", description="khác")),
        now=T0,
        source="reconcile",
    )
    session.add(snap)
    await session.flush()
    legacy = ExternalChange(
        shop_id=shop.id,
        tiktok_product_id=product.tiktok_product_id,
        kind=KIND_CONTENT,
        fields=["title", "description"],
        occurred_at=T0,
        detected_at=T0,
        source="reconcile",
        juli_write=False,
        details={"snapshot_id": str(snap.id)},
        dedup_key="legacy:1",
    )
    session.add(legacy)
    await session.flush()
    assert base.snapshot is not None

    report = await backfill_shop(session, shop.id)
    assert report.inserted["seller_change"] >= 1
    event = (
        await session.execute(
            select(CardEvent).where(CardEvent.dedup_key == keys.seller_change(legacy.id))
        )
    ).scalar_one()
    assert event.source == "backfill" and event.card_id == card.id
    assert event.payload["field_attribution"] == {
        "title": "seller_revert",
        "description": "seller_change",
    }
    assert event.payload["attribution"] == "seller_change"
    again = await backfill_shop(session, shop.id)
    assert again.inserted.get("seller_change", 0) == 0


@pytest.mark.asyncio
async def test_fanout_reaches_shops_with_history_but_no_credential(session):
    from juli_backend.workers.tasks.card_events_backfill import (
        enumerate_backfill_shops,
        run_fanout,
    )

    _, history_shop = await make_tenant(session)
    _, empty_shop = await make_tenant(session)
    await store.record_change(
        session,
        shop_id=history_shop.id,
        tiktok_product_id="tt-x",
        kind=KIND_CATEGORY,
        fields=["category_id"],
        occurred_at=T0,
        detected_at=T0,
        source="reconcile",
        juli_write=False,
        details=None,
        dedup_key="cat:1",
    )
    await session.commit()
    found = {shop.shop_id for shop in await enumerate_backfill_shops(session)}
    assert history_shop.id in found and empty_shop.id not in found
    seen: list[str] = []
    assert await run_fanout(session, enqueue=seen.append) == len(found)
    assert str(history_shop.id) in seen


# -- migration 096's frozen copies stay equal to the services --------------------------------


HASH_CASES = [
    ("title", "  Nồi lẩu  "),
    ("description", "<p>mô tả</p>"),
    ("main_images", [{"uri": "a"}, "b"]),
    ("price", [{"sku_id": "s2", "amount": "72000.0"}, {"sku_id": "s1", "amount": "5E+4"}]),
    ("price", [{"sku_id": "s1", "amount": ""}, {"sku_id": "s3", "amount": "junk"}]),
    ("attributes", [["a", ["1"]]]),
    ("title", None),
]


@pytest.mark.parametrize(("field", "value"), HASH_CASES)
def test_migration_hash_copy_equals_the_service(field, value):
    assert _migration().field_hash(field, value) == field_value_hash(field, value)


def _as_migration(state: ProductFields) -> dict:
    return {
        "title": state.title,
        "description_hash": state.description_hash,
        "image_uris": list(state.image_uris),
        "list_prices": dict(state.list_prices),
    }


LABEL_CASES = [
    # (kind, fields, title on TikTok, writes [(field, before, after, offset)], juli_write)
    (KIND_CONTENT, ["title"], "Mới", [("title", "Cũ", "Mới", timedelta(0))], False),
    (KIND_CONTENT, ["title"], "Mới", [("title", "Cũ", "Mới", -JULI_WRITE_LOOKBACK)], False),
    (
        KIND_CONTENT,
        ["title"],
        "Mới",
        [("title", "Cũ", "Mới", -JULI_WRITE_LOOKBACK - timedelta(seconds=1))],
        False,
    ),
    (KIND_CONTENT, ["title"], "Mới", [("title", "Cũ", "Mới", JULI_WRITE_LOOKAHEAD)], False),
    (KIND_CONTENT, ["title"], "Cũ", [("title", "Cũ", "Mới", -timedelta(days=60))], False),
    (
        KIND_CONTENT,
        ["title"],
        "Cũ",
        [
            ("title", "Cũ", "Mới", -timedelta(days=60)),
            ("title", "Mới", "Mới hơn", -timedelta(days=59)),
        ],
        False,
    ),
    (KIND_CONTENT, ["title", "attributes"], "Mới", [("title", "Cũ", "Mới", timedelta(0))], False),
    (KIND_CONTENT, ["title"], "Mới", [("title", "Cũ", None, timedelta(0))], False),
    (
        KIND_PRICE,
        ["price", "list_price"],
        "Mới",
        [
            (
                "price",
                [{"sku_id": "s1", "amount": "1"}],
                [{"sku_id": "s1", "amount": "50000"}],
                timedelta(0),
            )
        ],
        False,
    ),
    (KIND_CATEGORY, ["category_id"], "Mới", [], False),
    (KIND_PROMOTION, ["promotion"], "Mới", [], True),
    (KIND_CONTENT, [], "Mới", [], False),
]


@pytest.mark.parametrize(("kind", "fields", "title", "writes", "juli_write"), LABEL_CASES)
def test_migration_label_copy_equals_the_service(kind, fields, title, writes, juli_write):
    mig = _migration()
    state = ProductFields.of(normalize_detail(_raw(title=title)))
    records = [_write(f, before, after, T0 + offset) for f, before, after, offset in writes]
    rows = [
        {
            "field": r.field,
            "recorded_at": r.recorded_at,
            "before_value": r.before_value,
            "after_value": r.after_value,
            "before_hash": None,
            "after_hash": None,
        }
        for r in records
    ]
    known = T0 + timedelta(minutes=30)
    if juli_write or kind not in (KIND_CONTENT, KIND_PRICE):
        from juli_backend.services.product_history.attribution import uniform_labels

        expected = uniform_labels(kind, fields, juli_write=juli_write)
    else:
        expected = label_fields(kind, fields, state, records, occurred_at=T0, known_at=known)
    got = mig.label_fields(
        kind, fields, _as_migration(state), rows, T0, known, juli_write=juli_write
    )
    assert got == expected
    assert mig.summarize(got) == summarize(expected)
    # And without a snapshot: every field a seller change, as the service says.
    if kind in (KIND_CONTENT, KIND_PRICE) and not juli_write:
        assert mig.label_fields(kind, fields, None, rows, T0, known) == label_fields(
            kind, fields, None, records, occurred_at=T0, known_at=known
        )


def test_migration_window_constants_equal_the_service():
    from juli_backend.services.product_history.attribution import JULI_FIELDS

    mig = _migration()
    assert mig.LOOKBACK == JULI_WRITE_LOOKBACK
    assert mig.LOOKAHEAD == JULI_WRITE_LOOKAHEAD
    assert mig.JULI_FIELDS == JULI_FIELDS
