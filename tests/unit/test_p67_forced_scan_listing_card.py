"""P67 (D75 Q1): the operator-forced sandbox quick scan leaves the reviewer a listing card.

Live state (production, after P66): the sandbox's two best sellers by paid orders (the
bottle and the hot-pot) each had their title AND description edited by the team's August
agent runs; a third product (created by the reviewer today) has no order. The forced
scan surfaced no title / description card.

Root cause: an agent run leaves its card ``approved`` and never stamps ``executed_at``;
``persist._card_still_stands`` reads such a row as in flight forever, so all four
(product, lever) chains answered ``active_card_exists`` and the scan had nothing to
write. A completed run whose write TikTok confirmed now counts as executed at that
moment: the chain reopens after the 7-day cooldown.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from juli_backend.integrations.tiktok.merchant import TikTokCapability
from juli_backend.models.models import ActionCard, Product, ToolExecution, WorkflowRun
from juli_backend.services.action_cards.subjects import (
    SUBJECT_TYPE_PRODUCT_LEVER,
    product_lever_subject_id,
)
from juli_backend.services.demo_decisions.card_view import build_card_block
from juli_backend.services.demo_decisions.read import list_surfaced_decisions
from tests.unit import test_quick_scan_orders as qso

session_factory = qso.session_factory
_quick_scan_env = qso._quick_scan_env

BOTTLE = "1736405947247986307"
HOT_POT = "1736363193934775939"
NEW_HOT_POT = "1738157559581542019"
AUGUST = datetime(2026, 8, 20, 9, 0)


def _sandbox_listings() -> dict[str, dict]:
    bottle = qso._listing(BOTTLE, "Bình nước thể thao 750ml", "Bình nhựa. Nắp kín.")
    hot_pot = qso._listing(HOT_POT, "Nồi lẩu điện mini 1.5L có nắp kính", "Nồi nhỏ. Nấu nhanh.")
    new = qso._listing(
        NEW_HOT_POT,
        "Nồi lẩu điện mini 1.5L có nắp kính, tay cầm tiện dụng (dùng nấu lẩu, mì, súp)",
    )
    return {BOTTLE: bottle, HOT_POT: hot_pot, NEW_HOT_POT: new}


async def _seed_live_state(session, shop) -> dict[str, dict]:
    listings = _sandbox_listings()
    for product_id, listing in listings.items():
        await qso._product(session, shop, product_id, listing["title"])
    # Paid orders only for the first two (the reviewer's new listing has none).
    await qso._paid_order(session, shop, "o-1", BOTTLE, 6, 150_000, "confirmed")
    await qso._paid_order(session, shop, "o-2", HOT_POT, 1, 450_000, "delivered")
    products = {
        str(p.tiktok_product_id): p
        for p in (await session.execute(select(Product).where(Product.shop_id == shop.id)))
        .scalars()
        .all()
    }
    # The team's August runs: title and description edited on both best sellers.
    for revision, (tiktok_id, lever) in enumerate(
        [(BOTTLE, "title"), (BOTTLE, "description"), (HOT_POT, "title"), (HOT_POT, "description")],
        start=1,
    ):
        await _august_edit(session, shop, products[tiktok_id], lever, revision)
    await session.commit()
    return listings


async def _august_edit(session, shop, product: Product, lever: str, n: int) -> None:
    card = ActionCard(
        id=uuid.uuid4(), shop_id=shop.id, workflow_key=qso.OPTIMIZE_PRODUCT_WORKFLOW_KEY,
        subject_type=SUBJECT_TYPE_PRODUCT_LEVER,
        subject_id=product_lever_subject_id(str(product.id), lever), revision=1, priority=1,
        severity="warning", title=f"August {lever}", description="",
        recommendation_payload=json.dumps({"diagnosis": {"lever": {"code": lever}}}),
        status="approved", surfaced_at=AUGUST, approved_at=AUGUST,
    )  # fmt: skip
    session.add(card)
    await session.flush()
    run = WorkflowRun(
        shop_id=shop.id, product_id=product.id, action_card_id=card.id,
        workflow_key=qso.OPTIMIZE_PRODUCT_WORKFLOW_KEY, subject_type="product",
        subject_ref=f"{product.id}#{n}", state={}, status="completed", stop_reason="final_response",
        prompt_version="v", prompt_sha256="a" * 64, created_at=AUGUST,
    )  # fmt: skip
    session.add(run)
    await session.flush()
    session.add(
        ToolExecution(
            shop_id=shop.id,
            approval_id=f"run-{n}",
            tool_name="update_product_listing",
            payload_json="{}",
            status="succeeded",
            workflow_run_id=run.id,
            tool_call_id=f"call-{n}",
            operation="update_product_listing",
            outcome_json=json.dumps({lever: "after"}),
            updated_at=AUGUST + timedelta(minutes=5),
        )  # fmt: skip
    )


@pytest.mark.asyncio
async def test_the_forced_scan_surfaces_a_listing_card_over_the_august_edits(
    session, session_factory, caplog
):
    shop = await qso._shop(session, TikTokCapability.SANDBOX_WRITE)
    resources = qso.FakeSandboxResources(await _seed_live_state(session, shop))
    await qso._mark_done_with_full_cards(session, shop)

    with caplog.at_level(logging.INFO, logger="juli_backend.services.onboarding.quick_scan"):
        result = await qso._forced(session_factory, shop, resources)

    assert result.shown, result
    shown = qso._shown(await qso._cards(session, shop.id))
    assert len(shown) >= 1
    payload = json.loads(shown[0].recommendation_payload)
    assert payload["diagnosis"]["tiktok_product_id"] in {BOTTLE, HOT_POT}
    assert payload["diagnosis"]["lever"]["code"] in {"title", "description"}
    # The reviewer's Quyết định lists it, executable by Juli.
    listed = await list_surfaced_decisions(session, shop.id, include_reviewer_cards=True)
    assert shown[0].id in {card.id for card in listed}
    block = build_card_block(shown[0], payload, None)
    assert block is not None and block["lever"]["executor"] == "juli"
    # The operator sees the outcome on one log line.
    assert any("shop_quick_scan_forced_outcome" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_recent_confirmed_edit_still_holds_its_chain_for_seven_days(
    session, session_factory, caplog
):
    """The cooldown after a confirmed write is kept: an edit 2 days ago blocks its lever,
    and the forced scan says why on its outcome line."""
    shop = await qso._shop(session, TikTokCapability.SANDBOX_WRITE)
    resources = qso.FakeSandboxResources(await _seed_live_state(session, shop))
    recent = qso.SCAN_AT.replace(tzinfo=None) - timedelta(days=2)
    for execution in (await session.execute(select(ToolExecution))).scalars():
        execution.updated_at = recent
    await session.commit()

    with caplog.at_level(logging.INFO, logger="juli_backend.services.onboarding.quick_scan"):
        result = await qso._forced(session_factory, shop, resources)

    assert not result.shown and result.cards == 0, result
    assert result.reasons[f"{BOTTLE}/title"] == "active_card_exists"
    line = next(
        r.getMessage() for r in caplog.records if "shop_quick_scan_forced_outcome" in r.getMessage()
    )
    assert f"{BOTTLE}/title=active_card_exists" in line


@pytest.mark.asyncio
async def test_a_refused_write_never_reopens_the_chain(session, session_factory):
    """``ok: false`` (TikTok refused, P64 D10) is not an executed card."""
    shop = await qso._shop(session, TikTokCapability.SANDBOX_WRITE)
    resources = qso.FakeSandboxResources(await _seed_live_state(session, shop))
    for execution in (await session.execute(select(ToolExecution))).scalars():
        execution.outcome_json = json.dumps({"ok": False})
    await session.commit()

    result = await qso._forced(session_factory, shop, resources)

    assert not result.shown and result.cards == 0, result


@pytest.mark.asyncio
async def test_a_listing_with_no_reason_is_named_on_the_outcome(session, session_factory):
    shop = await qso._shop(session, TikTokCapability.SANDBOX_WRITE)
    listings = _sandbox_listings()
    listings[BOTTLE] = {
        **listings[BOTTLE],
        "title": "Bình nước thể thao 750ml JuliWear Trắng Đen chính hãng nắp kín",
        "description": "<p>" + "x" * 600 + "</p><p>y</p>",
    }
    await qso._product(session, shop, BOTTLE, listings[BOTTLE]["title"])
    await qso._paid_order(session, shop, "o-1", BOTTLE, 1, 100_000, "confirmed")

    result = await qso._forced(session_factory, shop, qso.FakeSandboxResources(listings))

    assert result.reasons == {BOTTLE: "no_listing_reason"}
    assert result.skipped_reason == "no_candidate"
