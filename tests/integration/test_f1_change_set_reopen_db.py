"""batch-1118f F1.1 / F1.2 on real Postgres, as ``juli_app`` under the shop's scope.

- execute card A, revert it, execute card B on the same product and day: the day's change set is
  re-opened (one row per shop / product / day, ``uq_shop_reco_change_sets_product_day``), status
  measuring, B in ``card_ids``, A kept out as history (was a 500 on POST /executed);
- the fill queue's claim never leases a queued job whose card is withdrawn.

Synthetic tenants only."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.shopee_recommendations import change_sets, fill_queue
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.integration.test_shopee_reco_db import NOW, _save, stub_card
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres, pytest.mark.migration_heavy]


async def _approved(session, shop_id, user_id, item: str):
    cid = await _save(session, shop_id, stub_card(item))
    await reco.publish(session, shop_id, [cid], now=NOW)
    await reco.decide(session, shop_id, cid, decision="approve", user_id=user_id, now=NOW)
    return cid


async def test_executing_after_a_revert_reuses_the_days_set_on_postgres(
    owner_engine, shopee_tenants
):
    a, _ = shopee_tenants
    item = f"f1-{uuid.uuid4().hex[:8]}"
    later = NOW + timedelta(hours=1)
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            first = await _approved(session, a.shop_id, a.user_id, item)
            second = await _approved(session, a.shop_id, a.user_id, item)
            await reco.mark_executed(
                session, a.shop_id, first, now=later, executed_at=later, user_id=a.user_id
            )
            await reco.mark_reverted(session, a.shop_id, first, now=later, user_id=a.user_id)
            await session.commit()
        async with with_shop_scope(session, a.shop_id):
            await reco.mark_executed(
                session, a.shop_id, second, now=later, executed_at=later, user_id=a.user_id
            )  # a second set for (shop, product, day) used to raise the unique violation
            await session.commit()
    with owner_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT status, card_ids, cut_at FROM public.shop_reco_change_sets "
                "WHERE shop_id = :s AND product_id = :p"
            ),
            {"s": a.shop_id, "p": item},
        ).all()
    assert len(rows) == 1
    status, card_ids, cut_at = rows[0]
    assert status == change_sets.SET_MEASURING and cut_at is None
    assert card_ids == [str(second)]


async def test_a_withdrawn_cards_queued_job_is_not_claimed_on_postgres(
    owner_engine, shopee_tenants
):
    a, _ = shopee_tenants
    item = f"f1-{uuid.uuid4().hex[:8]}"
    token_id, job_id = uuid.uuid4(), uuid.uuid4()
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            card = await _approved(session, a.shop_id, a.user_id, item)
            await session.commit()
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.ingest_tokens (id, shop_id, token_hash, platform, "
                "client_label, created_at, expires_at) VALUES (:id, :shop, :hash, 'shopee', "
                "'Juli Connector', now(), now() + interval '90 days')"
            ),
            {"id": token_id, "shop": a.shop_id, "hash": uuid.uuid4().hex + uuid.uuid4().hex},
        )
        conn.execute(
            text(
                "INSERT INTO public.shopee_fill_jobs (id, shop_id, proposal_id, version, kind, "
                "target, target_key, seq, payload, status, created_at, updated_at) VALUES "
                "(:id, :shop, :p, 1, 'voucher', '{}'::jsonb, 'shop', 0, '{}'::jsonb, 'queued', "
                "now(), now())"
            ),
            {"id": job_id, "shop": a.shop_id, "p": card},
        )
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            served = await fill_queue.jobs_for_shop(session, a.shop_id, token_id=token_id)
            assert str(job_id) in {j["id"] for j in served}  # approved: served (and leased)
        await session.rollback()
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE public.shop_proposals SET status = 'withdrawn' WHERE id = :p"),
            {"p": card},
        )
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            served = await fill_queue.jobs_for_shop(session, a.shop_id, token_id=token_id)
            assert str(job_id) not in {j["id"] for j in served}
        await session.commit()
    with owner_engine.connect() as conn:
        status, holder = conn.execute(
            text("SELECT status, claimed_by_token_id FROM public.shopee_fill_jobs WHERE id = :j"),
            {"j": job_id},
        ).one()
    assert status == "queued"
