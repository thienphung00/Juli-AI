"""P64 walkthrough: the sandbox reviewer's Quyết định (D73.3).

- A rule-pipeline ``optimize_product_2`` card stored before its "Lý do" became Vietnamese
  is not shown to the sandbox reviewer (its signals are not stored, so it cannot be
  re-rendered); a seller's own list is unchanged.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from juli_backend.models.models import ActionCard
from juli_backend.services.demo_decisions import read
from tests.support.builders import make_tenant

ENGLISH_WHY = "CTR fell 30% vs prior period · opportunity: scale winners (traffic-less proxy)"
VIETNAMESE_WHY = "CTR giảm 30% so với kỳ trước · Cơ hội: đẩy sản phẩm bán tốt"


def _legacy(shop_id: uuid.UUID, why: str) -> ActionCard:
    now = datetime.now(UTC)
    return ActionCard(
        id=uuid.uuid4(),
        shop_id=shop_id,
        workflow_key="optimize_product_2",
        subject_type="shop",
        subject_id=uuid.uuid4().hex,
        revision=1,
        priority=1,
        severity="medium",
        title="Optimize product",
        description=why,
        recommendation_payload=json.dumps(
            {"workflow_name": "Tối ưu sản phẩm", "rationale": why, "reasoning": {"why": why}}
        ),
        status="active",
        computed_at=now,
        surfaced_at=now,
    )


def test_only_a_stored_english_rule_card_is_stale():
    shop = uuid.uuid4()
    assert read.stale_english_rule_card(_legacy(shop, ENGLISH_WHY))
    assert not read.stale_english_rule_card(_legacy(shop, VIETNAMESE_WHY))
    adr106 = _legacy(shop, ENGLISH_WHY)
    adr106.recommendation_payload = json.dumps({"diagnosis": {"lever": {}}, "rationale": "x"})
    assert not read.stale_english_rule_card(adr106)


async def test_the_sandbox_reviewer_does_not_see_the_stale_english_card(session):
    _user, shop = await make_tenant(session)
    english, vietnamese = _legacy(shop.id, ENGLISH_WHY), _legacy(shop.id, VIETNAMESE_WHY)
    session.add_all([english, vietnamese])
    await session.commit()

    reviewer = await read.list_surfaced_decisions(session, shop.id, include_reviewer_cards=True)
    seller = await read.list_surfaced_decisions(session, shop.id)

    assert [c.id for c in reviewer] == [vietnamese.id]
    assert {c.id for c in seller} == {english.id, vietnamese.id}  # real shops: unchanged
    with pytest.raises(read.DecisionNotFound):
        await read.get_surfaced_decision(session, shop.id, english.id, include_reviewer_cards=True)
    assert (await read.get_surfaced_decision(session, shop.id, english.id)).id == english.id
