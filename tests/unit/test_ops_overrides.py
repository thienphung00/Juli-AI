"""P16 (D25.4, D25.8): the per-shop Ops overrides are read by the emission budget,
the content-card emission, content drafting (model + monthly OpenAI cap) and the
agent runner; with no override nothing changes."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.core.config.decision_emission import DecisionEmissionConfig
from juli_backend.models.models import ActionCard
from juli_backend.models.ops import OpsShopSettings
from juli_backend.services.action_cards.emission_budget import (
    SUPPRESSED_REASON_OPS_DISABLED,
    apply_emission_budget,
)
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.status import WorkflowRunStatus
from juli_backend.services.content_cards import emission
from juli_backend.services.ops import overrides as ov
from juli_backend.workers.tasks.agent_workflow import _ops_llm_config
from tests.support.lever_flows import seed_shop
from tests.unit.test_p14_content_flow import (
    PRODUCT_ID,
    FakeAnalytics,
    FakeDrafter,
    SeoProducts,
    _content_run,
    _leg,
    _products,
    _reload,
    _resources,
    _row,
    _video_script,
    _video_table,
)

#: Thursday 2026-10-15, 09:00 in Vietnam.
START = datetime(2026, 10, 15, 2, 0, tzinfo=UTC)


def _card(shop_id, priority: int, lever: str = "title", key: str = "optimize_product_2"):
    return ActionCard(
        id=uuid.uuid4(),
        shop_id=shop_id,
        workflow_key=key,
        subject_type="product",
        subject_id=str(uuid.uuid4()),
        priority=priority,
        severity="warning",
        title=f"card {priority}",
        description="",
        recommendation_payload=json.dumps({"diagnosis": {"lever": {"code": lever}}}),
        status="active",
    )


async def _settings(session, shop_id, **values):
    session.add(OpsShopSettings(shop_id=shop_id, stage="trial", **values))
    await session.flush()


def test_emission_limits_replace_defaults_only_when_set():
    base = DecisionEmissionConfig()
    assert ov.emission_limits(base, ov.DEFAULT_OVERRIDES) == base
    out = ov.emission_limits(base, ov.ShopOverrides(card_daily_limit=2, card_open_limit=40))
    assert (out.daily_new_cap, out.weekly_new_cap, out.max_open) == (2, 25, 40)


async def test_default_shop_keeps_the_d24_17_limits(session):
    shop, _ = await seed_shop(session)
    for p in range(1, 8):
        session.add(_card(shop.id, p))
    await session.flush()
    outcome = await apply_emission_budget(session, shop.id, now=START)
    assert len(outcome.newly_surfaced) == 5


async def test_daily_limit_override_is_honoured(session):
    shop, _ = await seed_shop(session)
    await _settings(session, shop.id, card_daily_limit=2)
    for p in range(1, 8):
        session.add(_card(shop.id, p))
    await session.flush()
    outcome = await apply_emission_budget(session, shop.id, now=START)
    assert len(outcome.newly_surfaced) == 2


async def test_disabled_action_and_stream_are_suppressed(session):
    shop, _ = await seed_shop(session)
    await _settings(session, shop.id, enabled_actions=["title"])
    flash = _card(shop.id, 1, lever="flash_sale")
    title = _card(shop.id, 2, lever="title")
    session.add_all([flash, title])
    await session.flush()
    outcome = await apply_emission_budget(session, shop.id, now=START)
    assert outcome.newly_surfaced == [title]
    assert flash.suppressed_reason == SUPPRESSED_REASON_OPS_DISABLED

    shop2, _ = await seed_shop(session)
    await _settings(session, shop2.id, enabled_streams=["seller_video"])
    card = _card(shop2.id, 1)
    session.add(card)
    await session.flush()
    outcome = await apply_emission_budget(session, shop2.id, now=START)
    assert outcome.newly_surfaced == []


async def test_content_cards_off_writes_no_content_card(session):
    shop, _ = await seed_shop(session)
    await _products(session, shop, [("p-video", "MN-015")])
    await _settings(session, shop.id, content_cards_enabled=False)
    tables = {"video": _video_table([_row("v1", 0.019, 2249, -56_000, ["p-video"])])}
    await emission.emit_content_cards(session, shop.id, now=START, rankings=tables)
    rows = (
        (await session.execute(select(ActionCard).where(ActionCard.shop_id == shop.id)))
        .scalars()
        .all()
    )
    assert rows == []


async def test_video_stream_off_blocks_video_content_cards_only(session):
    overrides = ov.ShopOverrides(enabled_streams=frozenset({"seller_live", "product_card"}))
    assert ov.content_kind_enabled(overrides, "content_video") is False
    assert ov.content_kind_enabled(overrides, "content_live") is True


def test_promotion_api_default_off():
    assert ov.promotion_api_enabled(ov.DEFAULT_OVERRIDES) is False
    assert ov.promotion_api_enabled(ov.ShopOverrides(promotion_api_enabled=True)) is True


async def test_model_override_reaches_the_agent_runner(session):
    shop, _ = await seed_shop(session)
    assert (await _ops_llm_config(session, shop.id)).model == "gpt-5.4-nano"
    await _settings(session, shop.id, openai_model="gpt-5.4-nano-test")
    assert (await _ops_llm_config(session, shop.id)).model == "gpt-5.4-nano-test"


async def test_model_override_reaches_the_content_drafter(session):
    shop, product = await seed_shop(session)
    await _settings(session, shop.id, openai_model="gpt-5.4-mini")
    _, run = await _content_run(session, shop, product)
    drafter = FakeDrafter(_video_script())
    res = _resources(FakeAnalytics(), SeoProducts())
    await (await _leg(session, run.id, res, drafter, InMemoryEventSink())).run(
        run.id, product_ref=PRODUCT_ID
    )
    await session.commit()
    row = await _reload(session, run.id)
    assert row.state["content_run"]["drafts"][0]["model"] == "gpt-5.4-mini"


async def test_over_the_monthly_cap_stops_drafting(session, caplog):
    shop, product = await seed_shop(session)
    await _settings(session, shop.id, openai_monthly_cap_usd=Decimal("1.00"))
    _, earlier = await _content_run(session, shop, product)
    earlier.cost_usd = Decimal("1.5")
    earlier.status = "completed"
    await session.commit()
    cap = await ov.openai_cap_status(session, shop.id)
    assert cap.reached is True and cap.spent_usd == Decimal("1.5")

    _, run = await _content_run(session, shop, product, first=False)
    drafter = FakeDrafter(_video_script())
    res = _resources(FakeAnalytics(), SeoProducts())
    with caplog.at_level("WARNING"):
        result = await (await _leg(session, run.id, res, drafter, InMemoryEventSink())).run(
            run.id, product_ref=PRODUCT_ID
        )
    await session.commit()
    assert drafter.calls == []
    assert result.status != WorkflowRunStatus.WAITING_EXTERNAL
    row = await _reload(session, run.id)
    assert row.state["content_run"]["error"] == "openai_cap_reached"
    assert any(r.message == "ops_openai_cap_reached" for r in caplog.records)


async def test_no_cap_means_no_limit(session):
    shop, _ = await seed_shop(session)
    cap = await ov.openai_cap_status(session, shop.id)
    assert cap.reached is False and cap.cap_usd is None


def test_month_start_is_the_shops_local_month():
    # 2026-10-31 20:00 UTC is 2026-11-01 03:00 in Vietnam.
    assert ov.month_start_utc(datetime(2026, 10, 31, 20, 0, tzinfo=UTC)) == datetime(
        2026, 10, 31, 17, 0
    )


@pytest.mark.parametrize("model", ["gpt-5.4-nano"])
def test_allowed_models_are_priced(model):
    assert model in ov.allowed_openai_models()
