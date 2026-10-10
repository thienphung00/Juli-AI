"""Fast track D24.21 (owner, 2026-10-10): P14 integration choices.

(1) strict 7-day return after Từ chối / Không thực hiện / Hoàn tác -- see
    ``test_p10a_card_reasons_edits`` (Optimize Product) and
    ``test_decision_emission_budget`` (legacy workflows, (3)); content cards here.
(2) "Số thẻ mở cùng lúc" 5..30, default 30 -- ``test_shop_rules``.
(4) fixed daily slots -- ``test_p14_card_limits``; the per-type top 30 and the
    content cards' own priority here.
(5) "Giọng văn" (``content_tone``) and "Từ không được dùng" (``banned_terms``):
    the content runs read exactly these keys; listing writes reject the terms.
Also: the content cards' ≤ 5 / week sub-limit counts in the shop's week.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.models.models import RunConfirmation
from juli_backend.models.run_changes import ShopRule
from juli_backend.services import shop_rules
from juli_backend.services.content_cards import emission
from juli_backend.services.content_cards.candidates import (
    LIVE,
    VIDEO,
    ContentCandidate,
    merge_ranked,
)
from juli_backend.services.content_cards.driver import load_rules
from juli_backend.services.optimize_product.decision_cards import (
    SELLER_CENTER_ANGLES,
    keep_top_per_type,
)
from tests.support.builders import make_tenant
from tests.unit.test_p10a_card_reasons_edits import (  # noqa: F401 -- fixture
    _post_confirmation,
    _waiting_run,
    enqueued,
)

# =========================================================================== (5) rules


@pytest.mark.asyncio
async def test_content_runs_read_exactly_the_validated_keys(session):
    user, shop = await make_tenant(session)
    # Old alias keys (never validated) are no longer read.
    for key, value in (("tone", "Giọng cũ"), ("banned_words", ["cũ"])):
        session.add(
            ShopRule(
                shop_id=shop.id,
                rule_key=key,
                scope_ref="",
                value=value,
                set_by="seller",
                set_at=datetime(2026, 10, 10),
            )
        )
    await session.commit()
    empty = await load_rules(session, shop.id, discount_cap_pct=None)
    assert empty.tone is None and empty.banned_terms == ()

    for key, value in (
        ("content_tone", "Vui vẻ, xưng mình"),
        ("banned_terms", ["rẻ nhất", "cam kết 100%"]),
        ("protected_terms", ["Fujiwa"]),
    ):
        await shop_rules.set_rule(
            session,
            shop.id,
            rule_key=key,
            scope_ref=None,
            value=value,
            set_by="seller",
            set_by_user_id=user.id,
        )
    await session.commit()
    rules = await load_rules(session, shop.id, discount_cap_pct=10.0)
    assert rules.tone == "Vui vẻ, xưng mình"
    assert rules.banned_terms == ("rẻ nhất", "cam kết 100%")
    assert rules.protected_terms == ("Fujiwa",)
    assert rules.discount_cap_pct == 10.0


def test_a_listing_edit_with_a_banned_term_is_refused():
    proposed = {"description": "<p>Mô tả Juli viết</p>"}
    with pytest.raises(shop_rules.ListingEditViolation, match='"rẻ nhất"'):
        shop_rules.validate_listing_edits(
            {"description": "<p>Son Rẻ Nhất thị trường</p>"},
            proposed=proposed,
            current=None,
            protected_terms=[],
            banned_terms=["rẻ nhất"],
        )
    # Whole words only: "rẻ nhấtt" is not the banned term.
    assert shop_rules.validate_listing_edits(
        {"description": "<p>giá tốt</p>"},
        proposed=proposed,
        current=None,
        protected_terms=[],
        banned_terms=["rẻ nhất"],
    ) == {"description": "<p>giá tốt</p>"}


async def _ban(session, shop, user, terms):
    await shop_rules.set_rule(
        session,
        shop.id,
        rule_key="banned_terms",
        scope_ref=None,
        value=terms,
        set_by="seller",
        set_by_user_id=user.id,
    )
    await session.commit()


@pytest.mark.asyncio
async def test_approving_juli_proposal_with_a_banned_term_is_refused(session, enqueued):  # noqa: F811
    """The write itself is checked: Juli's own proposal cannot carry the term."""
    user, shop = await make_tenant(session)
    run, _card, _product = await _waiting_run(session, shop)
    await _ban(session, shop, user, ["Juli viết"])

    resp = await _post_confirmation(
        session, user, shop, run, {"decision": "approve", "option_id": "1"}
    )

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "rule_violation" and detail["field"] == "description"
    assert '"Juli viết"' in detail["message"]
    confirmation = (await session.execute(select(RunConfirmation))).scalar_one()
    assert confirmation.status == "pending"
    assert enqueued.calls == []


@pytest.mark.asyncio
async def test_the_seller_can_edit_the_banned_term_out_and_approve(session, enqueued):  # noqa: F811
    user, shop = await make_tenant(session)
    run, _card, _product = await _waiting_run(session, shop)
    await _ban(session, shop, user, ["Juli viết"])

    bad = await _post_confirmation(
        session,
        user,
        shop,
        run,
        {
            "decision": "approve",
            "option_id": "1",
            "edited_values": {"description": "<p>Bản sửa vẫn có Juli viết</p>"},
        },
    )
    assert bad.status_code == 422, bad.text
    good = await _post_confirmation(
        session,
        user,
        shop,
        run,
        {
            "decision": "approve",
            "option_id": "1",
            "edited_values": {"description": "<p>Mô tả người bán tự viết</p>"},
        },
    )
    assert good.status_code == 202, good.text
    assert enqueued.calls == [(run.id, True)]


# =========================================================================== (4) ranking


def _candidate(kind, product, gmv):
    return ContentCandidate(
        kind=kind, tiktok_product_id=product, current=0.01, target=0.02,
        recoverable_gmv_per_day=gmv, volume=1000.0,
    )  # fmt: skip


def test_content_priority_is_gmv_times_the_levers_history():
    video = [_candidate(VIDEO, "v", 100.0)]
    live = [_candidate(LIVE, "l", 80.0)]
    assert [c.tiktok_product_id for c in merge_ranked(video, live)] == ["v", "l"]
    # A rejected video script (penalty 0.6) ranks below the LIVE card now.
    weighted = merge_ranked(video, live, weights={"video_script": 0.6})
    assert [c.tiktok_product_id for c in weighted] == ["l", "v"]


def test_each_executor_type_keeps_its_own_top_k():
    """A shop whose best cards are all Juli cards still keeps Seller Center ones."""
    from juli_backend.services.optimize_product import decision_cards
    from juli_backend.services.optimize_product.diagnosis import Angle

    def proposal(index: int, lever: Angle) -> decision_cards.CardProposal:
        return decision_cards.CardProposal(
            rank=0,
            product_id=f"p{index}",
            title="t",
            status="rule",
            label=next(iter(decision_cards.Label)),
            stage=decision_cards.Branch.CARD,
            lever=lever,
            trigger=next(iter(decision_cards.Trigger)),
            gap=Decimal("0.3"),
            main_kpi_value="",
            main_kpi_raw=None,
            reason="",
            action="",
            lever_detail="",
            lever_confirmed=True,
        )

    ordered = [proposal(i, Angle.TIEU_DE) for i in range(5)] + [
        proposal(i, Angle.FLASH_SALE) for i in range(5, 8)
    ]
    kept = keep_top_per_type(ordered, 2)
    assert [p.product_id for p in kept] == ["p0", "p1", "p5", "p6"]
    assert [p.rank for p in kept] == [1, 2, 3, 4]
    assert sum(1 for p in kept if p.lever in SELLER_CENTER_ANGLES) == 2


# =========================================================================== content week


def test_the_content_week_is_the_shops_week():
    # Sunday 18:00 UTC is Monday 01:00 in Vietnam: a new shop week.
    sunday_evening = datetime(2026, 10, 18, 18, 0, tzinfo=UTC)
    assert emission.week_of(sunday_evening) == datetime(2026, 10, 19).date()
    start = emission._week_start(sunday_evening)
    assert start == datetime(2026, 10, 18, 17, 0, tzinfo=UTC)
    # Monday 01:00 UTC is still Monday in Vietnam.
    assert emission._week_start(start + timedelta(hours=8)) == start
