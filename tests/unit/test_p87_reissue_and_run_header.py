"""P87: the sandbox-only forced re-issue, and the run header that never says "Unknown".

1. ``shop_quick_scan(force=True, reissue=True)`` (operator, own sandbox shop only): a
   (product, lever) whose card already WROTE to TikTok -- still inside the 7-day
   cooldown, so ``active_card_exists`` -- gets a NEW card; the old card keeps its row.
2. The runs list names a run's subject: a promotion / create run bound to a product row
   that is unnamed ("Unknown" or blank) is named from its own card, never "Unknown".
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from juli_backend.integrations.tiktok.merchant import TikTokCapability
from juli_backend.models.models import ActionCard, ToolExecution
from juli_backend.services.agent_runs.listing import _run_product_name
from juli_backend.services.onboarding import quick_scan as qs
from juli_backend.workers.tasks.shop_quick_scan import shop_quick_scan
from tests.support.builders import make_product, make_workflow_run
from tests.unit import test_p67_forced_scan_listing_card as p67
from tests.unit import test_quick_scan_orders as qso

session_factory = qso.session_factory
_quick_scan_env = qso._quick_scan_env


async def _recent_written_state(session, shop):
    """The P67 sandbox, with every confirmed edit only 2 days old (inside the cooldown)."""
    listings = await p67._seed_live_state(session, shop)
    recent = qso.SCAN_AT.replace(tzinfo=None) - timedelta(days=2)
    for execution in (await session.execute(select(ToolExecution))).scalars():
        execution.updated_at = recent
    await session.commit()
    return qso.FakeSandboxResources(listings)


async def _scan(session_factory, shop, resources, **kwargs):
    return await qs.run_quick_scan(
        session_factory=session_factory,
        shop_id=shop.id,
        app_key="app",
        app_secret="secret",
        create_resources=lambda _cfg: resources,
        now=qso.SCAN_AT,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_sandbox_without_reissue_is_unchanged(session, session_factory):
    shop = await qso._shop(session, TikTokCapability.SANDBOX_WRITE)
    resources = await _recent_written_state(session, shop)

    result = await _scan(session_factory, shop, resources, force=True)

    assert not result.shown and result.cards == 0, result
    assert result.reasons[f"{p67.BOTTLE}/title"] == "active_card_exists"


@pytest.mark.asyncio
async def test_sandbox_reissue_writes_a_new_card_for_a_product_whose_card_already_wrote(
    session, session_factory, caplog
):
    shop = await qso._shop(session, TikTokCapability.SANDBOX_WRITE)
    resources = await _recent_written_state(session, shop)
    old_ids = {c.id for c in await qso._cards(session, shop.id)}

    with caplog.at_level(logging.INFO, logger="juli_backend.services.onboarding.quick_scan"):
        result = await _scan(session_factory, shop, resources, force=True, reissue=True)

    assert result.shown and result.cards >= 1, result
    cards = await qso._cards(session, shop.id)
    fresh = [c for c in cards if c.id not in old_ids]
    assert fresh and all(c.supersedes_card_id in old_ids for c in fresh)
    # The August cards keep their row and status: the measurement history is untouched.
    kept = [c for c in cards if c.id in old_ids]
    assert kept and all(c.status == "approved" for c in kept)
    assert any(v == "reissued" for v in result.reasons.values()), result.reasons
    line = next(r.getMessage() for r in caplog.records if "shop_quick_scan_done" in r.getMessage())
    assert "=reissued" in line
    payload = json.loads(qso._shown(cards)[0].recommendation_payload)
    assert payload["diagnosis"]["tiktok_product_id"] in {p67.BOTTLE, p67.HOT_POT}


@pytest.mark.asyncio
async def test_reissue_is_ignored_for_a_non_sandbox_shop(session, session_factory, caplog):
    real = await qso._shop(session, TikTokCapability.SELLER_CONNECT)
    await qso._mark_done_with_full_cards(session, real)

    with caplog.at_level(logging.INFO, logger="juli_backend.services.onboarding.quick_scan"):
        result = await _scan(
            session_factory, real, qso.FakeSandboxResources({}), force=True, reissue=True
        )

    assert result.skipped_reason == "already_ran" and result.cards == 0
    assert any("shop_quick_scan_reissue_ignored" in r.getMessage() for r in caplog.records)


def test_the_celery_task_passes_reissue_only_with_force(monkeypatch):
    seen: list[dict] = []

    async def fake_task(shop_id, **kwargs):
        seen.append(kwargs["scan_kwargs"])

    monkeypatch.setenv("TIKTOK_APP_KEY", "k")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "s")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:1/0")
    import juli_backend.workers.tasks.shop_quick_scan as task

    monkeypatch.setattr(task, "run_quick_scan_task", fake_task)
    monkeypatch.setattr("redis.from_url", lambda _url: object())
    monkeypatch.setattr(
        "juli_backend.database.database.ensure_worker_session_factory", lambda _url: None
    )
    monkeypatch.setattr(task, "get_async_database_url", lambda: "sqlite://")
    monkeypatch.setattr(
        "juli_backend.services.shop_diagnosis_daily.shared_rate_limiter", lambda _c: None
    )
    monkeypatch.setattr(
        "juli_backend.workers.services.polling.shop_lock.RedisShopIngestLock", lambda _c: None
    )

    shop_quick_scan.run(str(uuid.uuid4()))
    shop_quick_scan.run(str(uuid.uuid4()), force=True)
    shop_quick_scan.run(str(uuid.uuid4()), force=True, reissue=True)

    assert seen == [None, {"force": True, "reissue": False}, {"force": True, "reissue": True}]


# -- 2. the run header -------------------------------------------------------------------


def test_the_run_subject_name_ladder():
    assert _run_product_name("Bình nước", None, None) == "Bình nước"
    assert _run_product_name("Unknown", "Bình giữ nhiệt", None) == "Bình giữ nhiệt"
    assert _run_product_name("Unknown", "Unknown", "Tạo khuyến mãi giảm giá cho SKU BN-500") == (
        "SKU BN-500"
    )
    assert _run_product_name("", None, "Tạo sản phẩm mới từ Nồi lẩu") == "Nồi lẩu"
    assert _run_product_name("Unknown", None, "Tạo khuyến mãi giảm giá cho Unknown") == ""
    assert _run_product_name("Unknown", None, None) == ""


async def _card(session, shop, title: str) -> ActionCard:
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop.id,
        workflow_key="create_promotion",
        subject_type="product",
        subject_id=str(uuid.uuid4()),
        revision=1,
        priority=0,
        severity="medium",
        title=title,
        description="",
        status="approved",
        computed_at=datetime(2026, 11, 2),
        surfaced_at=datetime(2026, 11, 2),
    )
    session.add(card)
    await session.commit()
    return card


@pytest.mark.parametrize("stored", ["Unknown", ""])
@pytest.mark.parametrize(
    "workflow_key, card_title, expected",
    [
        ("create_promotion", "Tạo khuyến mãi giảm giá cho SKU BN-500", "SKU BN-500"),
        ("create_product", "Tạo sản phẩm mới từ Nồi lẩu điện", "Nồi lẩu điện"),
    ],
)
async def test_a_promotion_or_create_run_on_an_unnamed_product_is_named_from_its_card(
    auth_client, session, shop, stored, workflow_key, card_title, expected
):
    product = await make_product(session, shop, name=stored, title=stored)
    card = await _card(session, shop, card_title)
    await make_workflow_run(
        session,
        shop,
        product=product,
        workflow_key=workflow_key,
        action_card_id=card.id,
        status="running",
    )

    data = (await auth_client.get("/v1/demo/runs")).json()["data"]

    assert data[0]["product_name"] == expected
    assert "Unknown" not in json.dumps(data)


async def test_an_optimize_run_with_a_product_keeps_the_product_name(auth_client, session, shop):
    product = await make_product(session, shop, name="Bình nước thể thao")
    card = await _card(session, shop, "Tối ưu tiêu đề")
    await make_workflow_run(session, shop, product=product, action_card_id=card.id)

    data = (await auth_client.get("/v1/demo/runs")).json()["data"]

    assert data[0]["product_name"] == "Bình nước thể thao"
