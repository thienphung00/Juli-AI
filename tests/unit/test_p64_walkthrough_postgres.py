"""P64 walkthrough fixes on real Postgres, as ``juli_app`` under RLS (D73.3).

- The reviewer's edited create_product consent lands: the run's pending call is bound to
  the edit and the confirmation row is approved (committed, read back owner-side).
- The forced sandbox quick scan leaves one surfaced listing card even when the week's
  emission budget is used up (the card write, the budget and the ledger under RLS).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.integrations.tiktok.merchant import TikTokCapability
from juli_backend.models.models import DecisionEmissionNoveltyLedger, WorkflowRun
from juli_backend.services.action_cards.emission_budget import (
    _shop_day_start_utc,
    shop_week_start,
)
from juli_backend.services.agent.runner import compute_params_sha
from juli_backend.services.agent_runs.confirmations import decide_confirmation
from juli_backend.services.onboarding import quick_scan as qs
from tests.support.postgres import (
    database_url,
    juli_app_async_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)
from tests.unit.test_quick_scan_orders import (
    SCAN_AT,
    FakeSandboxResources,
    _seed,
    _shop,
)

pytestmark = requires_postgres

PROPOSED = {
    "category_id": "605254",
    "title": "Bình Nước Thép Không Gỉ 750ml Dùng Hàng Ngày",
    "description": "Bình nước thép không gỉ 750ml.\n\nDùng hằng ngày.",
    "reason_vi": "Cùng danh mục.",
}


@pytest.fixture
async def owner_factory():
    engine = create_async_engine(async_database_url(database_url()))
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def test_an_edited_create_consent_lands_as_juli_app(owner_factory):
    async with owner_factory() as owner:
        shop = await _shop(owner, TikTokCapability.SANDBOX_WRITE)
        product_id = uuid.uuid4()
        await owner.execute(
            text(
                "INSERT INTO public.products (id, shop_id, tiktok_product_id, name, status, "
                "update_time, created_at, updated_at) VALUES (:id, :shop, 'p-src', 'src', "
                "'ACTIVATE', now(), now(), now())"
            ),
            {"id": product_id, "shop": shop.id},
        )
        run = WorkflowRun(
            shop_id=shop.id,
            product_id=product_id,
            workflow_key="create_product",
            subject_ref=str(product_id),
            status="waiting_approval",
            prompt_version="create_product.v1",
            prompt_sha256="0" * 64,
            state={
                "pending_confirmation": {
                    "call_id": "call-1",
                    "tool_name": "create_product",
                    "arguments": dict(PROPOSED),
                }
            },
        )
        owner.add(run)
        await owner.flush()
        await owner.execute(
            text(
                "INSERT INTO public.run_confirmations (id, workflow_run_id, tool_call_id, "
                "options, status, created_at, expires_at) VALUES (:id, :run, 'call-1', "
                "CAST(:options AS jsonb), 'pending', now(), :expires)"
            ),
            {
                "id": uuid.uuid4(),
                "run": run.id,
                "options": json.dumps(
                    [
                        {
                            "option_id": "1",
                            "proposed_change": PROPOSED,
                            "rationale": "x",
                            "params_sha": compute_params_sha(dict(PROPOSED)),
                        }
                    ]
                ),
                "expires": datetime.now(UTC) + timedelta(hours=4),
            },
        )
        await owner.commit()
        run_id, shop_id, owner_id = run.id, shop.id, shop.user_id

    edited = "Bình nước thép không gỉ 750ml, bản người duyệt sửa"
    async with juli_app_async_sessionmaker() as factory:
        async with factory() as session:
            async with with_shop_scope(session, shop_id):
                row = await session.get(WorkflowRun, run_id)
                assert row is not None
                outcome = await decide_confirmation(
                    session,
                    row,
                    tool_call_id="call-1",
                    decision="approve",
                    option_id="1",
                    # ADR-116 §6 (D76): a user who belongs to the shop decides.
                    decided_by_user_id=owner_id,
                    edited_values={"title": edited},
                )
                await session.commit()
    assert outcome.new_status == "approved"

    with owner_sync_engine() as engine, engine.connect() as conn:
        state = conn.execute(
            text("SELECT state FROM public.workflow_runs WHERE id = :id"), {"id": run_id}
        ).scalar_one()
        status = conn.execute(
            text("SELECT status FROM public.run_confirmations WHERE workflow_run_id = :id"),
            {"id": run_id},
        ).scalar_one()
    assert status == "approved"
    assert state["pending_confirmation"]["arguments"]["title"] == edited
    assert state["pending_confirmation"]["edited_fields"] == ["title"]


async def test_the_forced_sandbox_scan_shows_a_card_despite_the_budget(owner_factory):
    async with owner_factory() as owner:
        shop = await _shop(owner, TikTokCapability.SANDBOX_WRITE)
        listings = await _seed(owner, shop)
        for _ in range(25):
            owner.add(
                DecisionEmissionNoveltyLedger(
                    id=uuid.uuid4(),
                    shop_id=shop.id,
                    week_start=shop_week_start(SCAN_AT),
                    workflow_key=f"{uuid.uuid4().hex}@x",
                    first_surfaced_at=_shop_day_start_utc(SCAN_AT) + timedelta(minutes=1),
                )
            )
        await owner.commit()
        shop_id = shop.id

    async with juli_app_async_sessionmaker() as factory:
        result = await qs.run_quick_scan(
            session_factory=factory,
            shop_id=shop_id,
            app_key="app",
            app_secret="secret",
            create_resources=lambda _cfg: FakeSandboxResources(listings),
            now=SCAN_AT,
            force=True,
        )

    assert result.status == "done" and result.cards == 2 and result.shown, result
    with owner_sync_engine() as engine, engine.connect() as conn:
        surfaced = conn.execute(
            text(
                "SELECT count(*) FROM public.action_cards WHERE shop_id = :shop "
                "AND status = 'active' AND surfaced_at IS NOT NULL"
            ),
            {"shop": shop_id},
        ).scalar_one()
    assert surfaced == 1
