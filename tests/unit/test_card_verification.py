"""Read-back verification of an assisted execution (P90 plan, "Assisted execution" step 4),
migration 114 and the beat entry. SQLite; synthetic values."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from juli_backend.models.card_events import (
    EVENT_EXECUTED,
    EVENT_MISMATCH,
    EVENT_NOT_SEEN,
    EVENT_TYPES,
    EVENT_VERIFIED,
    CardEvent,
)
from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.models import ActionCard
from juli_backend.models.platform_data import PlatformItem, PlatformPromotion
from juli_backend.models.shopee_profit import PlatformItemSnapshot
from juli_backend.services.card_events import keys
from juli_backend.services.card_events.verification import (
    VERIFY_WINDOW,
    ExecutedChange,
    Observation,
    evaluate,
    matches,
    verify_shop,
)
from juli_backend.services.ingest.mapping import campaign_segment
from tests.support.builders import make_tenant

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
T0 = datetime(2026, 11, 4, 2, 0, tzinfo=UTC)  # the person clicked Save
AFTER = T0 + timedelta(hours=5)
DEADLINE = T0 + VERIFY_WINDOW


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


# -- pure ------------------------------------------------------------------------------


def _change(kind="price", expected=None, target=None) -> ExecutedChange:
    return ExecutedChange(
        shop_id=uuid.uuid4(),
        card_id=uuid.uuid4(),
        execution_ref="run_outcome:x",
        change_kind=kind,
        target=target or {"item_id": "1001"},
        expected=expected or {"current_price": 89000},
        executed_at=T0,
    )


def test_matching_compares_numbers_by_value_and_text_by_normal_form():
    assert matches({"current_price": 89000}, {"current_price": Decimal("89000.00")})
    assert matches({"title": "Áo  thun"}, {"title": "Áo thun"})
    assert matches({"image_urls": ["a", "b"]}, {"image_urls": ["a", "b"]})
    assert not matches({"image_urls": ["a", "b"]}, {"image_urls": ["b", "a"]})
    assert not matches({"current_price": 89000}, {"current_price": 90000})
    assert not matches({}, {"current_price": 1})  # an empty expectation proves nothing


def test_the_first_matching_observation_after_the_change_verifies_it():
    obs = [
        Observation({"current_price": 99000}, T0 - timedelta(hours=1)),  # before: ignored
        Observation({"current_price": 89000}, AFTER),
        Observation({"current_price": 89000}, AFTER + timedelta(hours=9)),
    ]
    verdict = evaluate(_change(), obs, AFTER + timedelta(hours=10))
    assert (verdict.outcome, verdict.observed_at) == (EVENT_VERIFIED, AFTER)
    assert verdict.observed == {"current_price": 89000}


def test_a_value_that_differs_stays_pending_until_the_deadline_then_is_a_mismatch():
    obs = [Observation({"current_price": 99000}, AFTER)]
    assert evaluate(_change(), obs, DEADLINE - timedelta(minutes=1)).outcome is None
    verdict = evaluate(_change(), obs, DEADLINE)
    assert (verdict.outcome, verdict.observed) == (EVENT_MISMATCH, {"current_price": 99000})


def test_nothing_seen_by_the_deadline_is_not_seen():
    assert evaluate(_change(), [], DEADLINE - timedelta(hours=1)).outcome is None
    assert evaluate(_change(), [], DEADLINE).outcome == EVENT_NOT_SEEN
    before = [Observation({"current_price": 89000}, T0 - timedelta(hours=1))]
    assert evaluate(_change(), before, DEADLINE).outcome == EVENT_NOT_SEEN


# -- migration 114 and the model -------------------------------------------------------


def _migration():
    import importlib.util

    path = MIGRATIONS / "versions/114_card_verification_events.py"
    spec = importlib.util.spec_from_file_location("mig114", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_114_widens_the_check_to_the_models_vocabulary_and_takes_the_tail():
    mig = _migration()
    assert mig.revision == "114_card_verification_events" and len(mig.revision) <= 32
    assert mig.down_revision == "113_shopee_orders_and_logs"
    assert mig.EVENT_TYPES == EVENT_TYPES
    assert set(mig.NEW_EVENT_TYPES) == {EVENT_VERIFIED, EVENT_MISMATCH, EVENT_NOT_SEEN}
    assert set(mig.EVENT_TYPES_112) == set(EVENT_TYPES) - set(mig.NEW_EVENT_TYPES)
    tail = (MIGRATIONS / "deferred/101_write_mode_backfill.py").read_text("utf-8")
    assert 'down_revision: str | None = "102_shop_members_backfill"' in tail


def test_migration_114_is_check_only_no_data_change_no_grant():
    text = (MIGRATIONS / "versions/114_card_verification_events.py").read_text("utf-8")
    for forbidden in ("UPDATE ", "DELETE ", "GRANT", "create_table", "drop_table"):
        assert forbidden not in text.replace("Revision", "")
    assert "NOT VALID" in text  # downgrade keeps rows already written with the new names


def test_the_beat_entry_and_the_task_are_registered():
    from juli_backend.workers.celery_app import celery_app
    from juli_backend.workers.tasks.card_change_verification import (
        CARD_CHANGE_VERIFICATION_TASK,
    )

    entry = celery_app.conf.beat_schedule["card-change-verification"]
    assert entry["task"] == CARD_CHANGE_VERIFICATION_TASK
    assert CARD_CHANGE_VERIFICATION_TASK in celery_app.tasks


# -- DB (SQLite) -----------------------------------------------------------------------


async def _shop(session):
    _, shop = await make_tenant(session, platform="shopee", tiktok_shop_id=None)
    return shop


async def _executed(session, shop, kind, target, expected) -> ActionCard:
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop.id,
        workflow_key=f"wk_{uuid.uuid4().hex[:8]}",
        subject_type="item",
        subject_id=str(target.get("item_id", "x")),
        revision=1,
        priority=1,
        severity="high",
        title="Sửa",
        description="Sửa",
        recommendation_payload=json.dumps({}),
        status="active",
        metadata_json=json.dumps({}),
        computed_at=_naive(T0),
    )
    session.add(card)
    await session.flush()
    session.add(
        CardEvent(
            id=uuid.uuid4(),
            card_id=card.id,
            shop_id=shop.id,
            workflow_key=card.workflow_key,
            subject_type="item",
            subject_id=card.subject_id,
            event_type=EVENT_EXECUTED,
            actor="seller",
            occurred_at=T0,
            source="live",
            payload={"change": {"change_kind": kind, "target": target, "expected": expected}},
            schema_version=1,
            dedup_key=f"assisted:{card.id}",
        )
    )
    await session.flush()
    return card


async def _outcomes(session, shop) -> list[CardEvent]:
    stmt = (
        select(CardEvent)
        .where(
            CardEvent.shop_id == shop.id,
            CardEvent.event_type.in_([EVENT_VERIFIED, EVENT_MISMATCH, EVENT_NOT_SEEN]),
        )
        .order_by(CardEvent.occurred_at)
    )
    return list((await session.execute(stmt)).scalars())


def _snapshot(shop, at: datetime, **fields) -> PlatformItemSnapshot:
    return PlatformItemSnapshot(
        shop_id=shop.id,
        platform="shopee",
        item_id="1001",
        captured_at=_naive(at),
        source="extension",
        source_rank=2,
        image_urls=[],
        image_hashes=[],
        category_path=[],
        **fields,
    )


async def test_a_price_seen_after_the_save_writes_verified_once(session):
    shop = await _shop(session)
    card = await _executed(session, shop, "price", {"item_id": "1001"}, {"current_price": 89000})
    session.add_all(
        [
            _snapshot(shop, T0 - timedelta(days=1), current_price=Decimal("99000")),
            _snapshot(shop, AFTER, current_price=Decimal("89000")),
        ]
    )
    await session.flush()
    counts = await verify_shop(session, shop.id, AFTER + timedelta(hours=1))
    assert (counts.checked, counts.verified, counts.pending) == (1, 1, 0)
    (event,) = await _outcomes(session, shop)
    assert event.card_id == card.id and event.event_type == EVENT_VERIFIED
    assert event.payload["observed"] == {"current_price": "89000.00"} or event.payload["observed"][
        "current_price"
    ] in (89000, "89000", "89000.00")
    assert event.payload["observed_at"].startswith("2026-11-04T07:00")
    assert event.dedup_key == keys.verification(f"assisted:{card.id}", EVENT_VERIFIED)
    # a second run finds nothing pending and writes nothing
    again = await verify_shop(session, shop.id, AFTER + timedelta(hours=2))
    assert again.checked == 0 and len(await _outcomes(session, shop)) == 1


async def test_a_title_is_read_from_the_catalogue_name(session):
    shop = await _shop(session)
    await _executed(session, shop, "title", {"item_id": "1001"}, {"title": "Áo thun cotton"})
    session.add(
        PlatformItem(
            shop_id=shop.id,
            platform="shopee",
            item_id="1001",
            variation_id="",
            name="Áo  thun cotton",
            source="extension",
            source_rank=2,
            source_version="t",
            captured_at=_naive(AFTER),
            updated_at=_naive(AFTER),
            first_seen_on=AFTER.date(),
            last_seen_on=AFTER.date(),
            extra={},
        )
    )
    await session.flush()
    counts = await verify_shop(session, shop.id, AFTER + timedelta(hours=1))
    assert counts.verified == 1


async def test_a_budget_that_never_changed_is_a_mismatch_at_the_deadline(session):
    shop = await _shop(session)
    target = {"campaign_id": "7001"}
    await _executed(session, shop, "daily_budget", target, {"daily_budget": 300000})
    session.add(
        PlatformDailyMetric(
            shop_id=shop.id,
            platform="shopee",
            dataset="ads_campaign_daily",
            day=AFTER.date(),
            item_id="",
            stream="ads",
            segment=campaign_segment("7001"),
            order_type="placed",
            extra={"daily_budget": 200000},
            source="extension",
            source_rank=2,
            source_version="t",
            confidence="high",
            captured_at=_naive(AFTER),
            updated_at=_naive(AFTER),
        )
    )
    await session.flush()
    early = await verify_shop(session, shop.id, DEADLINE - timedelta(hours=1))
    assert (early.pending, early.mismatch) == (1, 0) and not await _outcomes(session, shop)
    late = await verify_shop(session, shop.id, DEADLINE + timedelta(minutes=1))
    assert late.mismatch == 1
    (event,) = await _outcomes(session, shop)
    assert event.event_type == EVENT_MISMATCH and event.payload["observed"] == {
        "daily_budget": 200000
    }


async def test_a_voucher_never_read_again_is_not_seen_after_48_hours(session):
    shop = await _shop(session)
    await _executed(session, shop, "voucher", {"voucher_id": "55"}, {"min_spend": 150000})
    await session.flush()
    counts = await verify_shop(session, shop.id, DEADLINE + timedelta(hours=1))
    assert counts.not_seen == 1
    (event,) = await _outcomes(session, shop)
    assert event.event_type == EVENT_NOT_SEEN and event.payload["observed"] == {}


async def test_a_voucher_setting_read_back_verifies(session):
    shop = await _shop(session)
    await _executed(session, shop, "voucher", {"voucher_id": "55"}, {"min_spend": 150000})
    base = dict(
        shop_id=shop.id,
        platform="shopee",
        promo_type="voucher",
        program_name="V",
        starts_at=datetime(2026, 11, 1),
        ordinal=0,
        period_start=AFTER.date(),
        period_end=AFTER.date(),
        order_type="none",
        source="extension",
        source_rank=2,
        source_version="t",
        captured_at=_naive(AFTER),
        updated_at=_naive(AFTER),
    )
    session.add_all(
        [
            PlatformPromotion(**base, extra={"voucher_id": 56, "min_spend": 150000}),  # other
            PlatformPromotion(
                **{**base, "ordinal": 1}, extra={"voucher_id": 55, "min_spend": 150000}
            ),
        ]
    )
    await session.flush()
    assert (await verify_shop(session, shop.id, AFTER + timedelta(hours=1))).verified == 1


async def test_an_execution_without_a_known_kind_or_target_is_skipped_or_counted(session):
    shop = await _shop(session)
    await _executed(session, shop, "title", {}, {"title": "x"})  # no item_id: malformed
    await _executed(session, shop, "weather", {"item_id": "1"}, {"a": 1})  # unknown kind
    counts = await verify_shop(session, shop.id, DEADLINE)
    assert (counts.checked, counts.failed) == (1, 1) and not await _outcomes(session, shop)
