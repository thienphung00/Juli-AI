"""P91 D-13: the four listing kinds (description first line, variation restructure, hide,
relist), their execution sheets and their read-back verification. SQLite; synthetic."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from juli_backend.models.card_events import EVENT_MISMATCH, EVENT_VERIFIED
from juli_backend.models.platform_data import PlatformItem
from juli_backend.services.card_events import verification as vf
from juli_backend.services.shopee_recommendations import kinds
from juli_backend.services.shopee_recommendations import listing as lst
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.evaluate import evaluate
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.model import Candidate
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_card_verification import (
    AFTER,
    T0,
    _executed,
    _naive,
    _outcomes,
    _shop,
    _snapshot,
)

NOW = datetime(2026, 10, 9, 3, 0)
VARIATIONS = [
    {"name": "Hộp 5 cái", "price": 90000, "sku": "G-5", "stock": 40},
    {"name": "Hộp 10 cái", "price": 160000, "sku": "G-10", "stock": 25},
]


@pytest.fixture
async def env(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    e = await load_env(session, seeded.shop_id, as_of=AS_OF)
    assert e is not None
    return e


def _cand(kind, inputs=None, extra=None, item="1001") -> Candidate:
    return Candidate(kind=kind, items=(item,), inputs=inputs or {}, extra=extra or {})


def _card(env, cand):
    card = build_card(env, cand, now=NOW)
    assert card is not None, evaluate(env, cand).refusal
    return card


# --------------------------------------------------------------------------- the kinds


def test_the_four_kinds_are_listing_family_with_a_read_back_and_the_edit_page():
    for key, verify in (
        ("description_first_line", "description_first_line"),
        ("variation_restructure", "variations"),
        ("listing_hide", "listing_status"),
        ("listing_relist", "listing_status"),
    ):
        s = kinds.spec(key)
        assert s.family == "listing" and s.subject_type == "item" and s.verify_kind == verify
        assert s.page.item_path == "/portal/product/{item_id}"
    assert kinds.PLANNED_LISTING_KINDS == (
        "title",
        "description_first_line",
        "cover_image",
        "variation_restructure",
        "listing_hide",
        "listing_relist",
    )
    # only the description has a prior; hide / relist / restructure say "không ước tính"
    assert kinds.spec("description_first_line").target_metric == "ctor"
    assert {kinds.spec(k).target_metric for k in kinds.PLANNED_LISTING_KINDS[3:]} == {"none"}


# ---------------------------------------------------------------------- sheets (with env)


async def test_a_description_card_fixes_one_line_and_reads_it_back_by_hand(env):
    card = _card(env, _cand("description_first_line", {"first_line": "Gói 5 cái, dùng một lần"}))
    sheet = card["execution_sheet"]
    assert card["family"] == "listing" and card["certain"]["traffic_lever"] is True
    assert sheet["steps"][0]["after"] == "Gói 5 cái, dùng một lần"
    assert sheet["steps"][0]["copy"] == "Gói 5 cái, dùng một lần"
    assert sheet["changes"] == [
        {
            "change_kind": "description_first_line",
            "target": {"item_id": "1001"},
            "expected": {"first_line": "Gói 5 cái, dùng một lần"},
        }
    ]
    assert "xác nhận bằng tay" in sheet["readback"]["note"]
    page = sheet["page"]
    assert page["item_deep_link"] == "https://banhang.shopee.vn/portal/product/1001"
    assert page["item_link_verified"] is False and page["verified"] is True
    assert sheet["revert_steps"][0]["after"] is None  # no "before" known: nothing to copy back


async def test_a_variation_card_lists_target_rows_dependencies_and_the_listings_to_hide(env):
    cand = _cand(
        "variation_restructure",
        {"variations": VARIATIONS, "hide_items": ["1002", "1003"], "depends_on": ["CB3"]},
    )
    card = _card(env, cand)
    sheet = card["execution_sheet"]
    assert [s["field"] for s in sheet["steps"]] == [
        "Phân loại 1",
        "Phân loại 2",
        sheet["steps"][2]["field"],
    ]
    assert "Hộp 5 cái — giá 90.000đ — SKU G-5 — tồn 40" == sheet["steps"][0]["after"]
    assert sheet["steps"][2]["after"] == "1002, 1003"
    assert sheet["dependencies"] == [{"ref": "CB3", "text": "Chỉ làm sau khi CB3 đã chạy xong."}]
    (change,) = sheet["changes"]
    assert change["change_kind"] == "variations"
    assert [v["name"] for v in change["expected"]["variations"]] == ["Hộp 10 cái", "Hộp 5 cái"]
    assert card["predicted"]["money_per_month"]["certain"]["dprofit"] == 0.0
    assert any("Không ước tính" in n for n in card["notes"])


async def test_hide_and_relist_are_status_changes_relist_adds_stock(env):
    hide = _card(env, _cand("listing_hide"))
    assert hide["execution_sheet"]["changes"] == [
        {
            "change_kind": "listing_status",
            "target": {"item_id": "1001"},
            "expected": {"status": "unlisted"},
        }
    ]
    assert hide["execution_sheet"]["steps"][0]["after"] == "Ẩn (không xoá)"
    relist = _card(env, _cand("listing_relist", {"stock": 80}))
    kinds_ = [c["change_kind"] for c in relist["execution_sheet"]["changes"]]
    assert kinds_ == ["listing_status", "stock"]
    assert relist["execution_sheet"]["changes"][1]["expected"] == {"stock": 80}
    assert relist["execution_sheet"]["revert_steps"][0]["after"] == "Đang ẩn"
    for card in (hide, relist):
        assert set(card["execution_sheet"]["readback"]["kinds"]) <= set(vf.CHANGE_KINDS)


@pytest.mark.parametrize(
    ("kind", "inputs", "why"),
    [
        ("description_first_line", {"first_line": "  "}, "description_empty"),
        ("description_first_line", {"first_line": "a\nb"}, "description_too_long"),
        ("variation_restructure", {"variations": []}, "variations_invalid:count"),
        (
            "variation_restructure",
            {"variations": [{"name": "A", "price": 0}]},
            "variations_invalid:row1:price",
        ),
        (
            "variation_restructure",
            {"variations": [{"name": "A", "price": 5}, {"name": "a", "price": 6}]},
            "variations_invalid:duplicate",
        ),
        ("listing_relist", {"stock": -1}, "stock_invalid"),
    ],
)
async def test_unusable_inputs_are_refused(env, kind, inputs, why):
    assert evaluate(env, _cand(kind, inputs)).refusal == why


def test_a_banned_term_in_the_description_is_refused():
    assert lst.check_planned(
        "description_first_line", {"first_line": "hàng cam kết số 1"}, ["số 1"]
    ) == ("banned_term")


# ------------------------------------------------------------------- verification (pure)


def _change(kind, expected, target=None):
    return vf.ExecutedChange(
        shop_id=uuid.uuid4(),
        card_id=uuid.uuid4(),
        execution_ref="x",
        change_kind=kind,
        target=target or {"item_id": "1001"},
        expected=expected,
        executed_at=T0,
    )


def test_a_variation_set_matches_row_by_row_on_the_fields_it_fixes():
    expected = {
        "variations": [{"name": "Hộp 10 cái", "price": 160000}, {"name": "Hộp 5 cái", "stock": 40}]
    }
    seen = {
        "variations": [
            {"name": "Hộp 10 cái", "price": Decimal("160000.00"), "sku": "G-10", "stock": 25},
            {"name": "Hộp 5 cái", "price": Decimal(90000), "stock": 40},
        ]
    }
    assert vf.matches(expected, seen)
    assert not vf.matches(expected, {"variations": seen["variations"][:1]})  # one still missing
    extra = {"variations": [*seen["variations"], {"name": "Hộp 1 cái", "price": 1}]}
    assert not vf.matches(expected, extra)  # an old variation is still listed
    wrong = {"variations": [{**seen["variations"][0], "price": 150000}, seen["variations"][1]]}
    assert not vf.matches(expected, wrong)


def test_a_listing_status_and_a_description_are_compared_like_any_field():
    assert vf.matches({"status": "unlisted"}, {"status": "unlisted"})
    assert not vf.matches({"status": "unlisted"}, {"status": "listed"})
    obs = [vf.Observation({"status": "unlisted"}, AFTER)]
    v = vf.evaluate(_change("listing_status", {"status": "unlisted"}), obs, AFTER)
    assert v.outcome == EVENT_VERIFIED


# ----------------------------------------------------------------- verification (database)


def _catalog(shop, variation_id, name, sku, seen, at):
    return PlatformItem(
        shop_id=shop.id,
        platform="shopee",
        item_id="1001",
        variation_id=variation_id,
        name="Sản phẩm mẫu" if not variation_id else None,
        variation_name=name,
        seller_sku=sku,
        source="extension",
        source_rank=2,
        source_version="t",
        captured_at=_naive(at),
        updated_at=_naive(at),
        first_seen_on=date(2026, 10, 1),
        last_seen_on=seen,
        extra={},
    )


async def test_a_hide_is_verified_by_the_unlisted_tag_in_the_next_snapshot(session):
    shop = await _shop(session)
    await _executed(session, shop, "listing_status", {"item_id": "1001"}, {"status": "unlisted"})
    session.add_all(
        [
            _snapshot(shop, T0 - timedelta(days=1), stock=5),
            _snapshot(shop, AFTER, stock=5, status="unlisted"),
        ]
    )
    await session.flush()
    counts = await vf.verify_shop(session, shop.id, AFTER + timedelta(hours=1))
    assert counts.verified == 1
    (event,) = await _outcomes(session, shop)
    assert event.event_type == EVENT_VERIFIED and event.payload["observed"] == {
        "status": "unlisted"
    }


async def test_a_listing_that_stays_listed_is_a_mismatch_at_the_deadline(session):
    shop = await _shop(session)
    await _executed(session, shop, "listing_status", {"item_id": "1001"}, {"status": "unlisted"})
    session.add(_snapshot(shop, AFTER, stock=5, status=None))
    await session.flush()
    counts = await vf.verify_shop(session, shop.id, T0 + vf.VERIFY_WINDOW + timedelta(minutes=1))
    assert counts.mismatch == 1
    (event,) = await _outcomes(session, shop)
    assert event.event_type == EVENT_MISMATCH and event.payload["observed"] == {"status": "listed"}


async def test_a_variation_restructure_reads_the_variations_still_in_the_list(session):
    shop = await _shop(session)
    expected = {
        "variations": [
            {"name": "Hộp 10 cái", "price": 160000, "sku": "G-10", "stock": 25},
            {"name": "Hộp 5 cái", "price": 90000},
        ]
    }
    await _executed(session, shop, "variations", {"item_id": "1001"}, expected)
    after_day = AFTER.date()
    session.add_all(
        [
            _catalog(shop, "", None, None, after_day, AFTER),
            _catalog(shop, "11", "Hộp 5 cái", "G-5", after_day, AFTER),
            _catalog(shop, "12", "Hộp 10 cái", "G-10", after_day, AFTER),
            # an old variation that the list no longer shows: not re-seen since the restructure
            _catalog(shop, "13", "Hộp 1 cái", "G-1", date(2026, 10, 20), AFTER),
        ]
    )
    for vid, price, stock in (("11", 90000, 40), ("12", 160000, 25), ("13", 20000, 3)):
        session.add(
            _snapshot(
                shop,
                T0 - timedelta(days=3),
                variation_id=vid,
                list_price=Decimal(price),
                current_price=Decimal(price),
                stock=stock,
            )
        )
    await session.flush()
    counts = await vf.verify_shop(session, shop.id, AFTER + timedelta(hours=1))
    assert (counts.checked, counts.verified) == (1, 1)


async def test_imported_executions_and_the_description_are_not_read_back(session):
    shop = await _shop(session)
    await _executed(
        session, shop, "description_first_line", {"item_id": "1001"}, {"first_line": "x"}
    )
    card = await _executed(
        session, shop, "listing_status", {"item_id": "1001"}, {"status": "unlisted"}
    )
    from sqlalchemy import select

    from juli_backend.models.card_events import CardEvent

    ev = await session.scalar(select(CardEvent).where(CardEvent.card_id == card.id))
    ev.payload = {**ev.payload, "readback": False, "imported": True}
    await session.flush()
    pending = await vf.pending_changes(session, shop.id, T0 + timedelta(days=1))
    assert pending == []  # no false "không thấy" for a field no reader posts
    assert vf.DESCRIPTION_READBACK_ACTIVE is False
