"""batch-1118e R7, migration 135 on real Postgres: the fill-job lease and per-computer state.

- ``shopee_connector_token_state`` has row-level security and gives ``juli_app`` SELECT, INSERT,
  UPDATE (no DELETE); a shop sees only its own rows;
- two tokens of one shop, as ``juli_app`` under the shop's scope: the first poll claims the open
  jobs, the second gets none; while the first poll's transaction holds them the second skips them
  (``SKIP LOCKED``) instead of waiting; an expired lease moves to the second token; a report from
  the non-holder is refused;
- the per-token heartbeat and reader blocks aggregate on the shop row (newest version, union);
- last: ``downgrade`` to 133 drops the table and the columns, ``upgrade head`` restores them.

Synthetic tenants only.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.shopee_connector import ShopeeConnectorState
from juli_backend.services.shop_proposals.cycle import ProposalError
from juli_backend.services.shopee_recommendations import connector_state as cs
from juli_backend.services.shopee_recommendations import fill_queue
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE")
TABLE = "shopee_connector_token_state"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _verbs(conn, role: str, table: str) -> set[str]:
    return {
        verb
        for verb in VERBS
        if conn.execute(
            text("SELECT has_table_privilege(:r, :t, :v)"),
            {"r": role, "t": f"public.{table}", "v": verb},
        ).scalar()
    }


def _token(conn, shop_id: uuid.UUID) -> uuid.UUID:
    token_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO public.ingest_tokens (id, shop_id, token_hash, platform, client_label, "
            "created_at, expires_at) VALUES (:id, :shop, :hash, 'shopee', 'Juli Connector', "
            "now(), now() + interval '90 days')"
        ),
        {"id": token_id, "shop": shop_id, "hash": uuid.uuid4().hex + uuid.uuid4().hex},
    )
    return token_id


def _job(conn, shop_id: uuid.UUID) -> uuid.UUID:
    proposal_id, job_id = uuid.uuid4(), uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO public.shop_proposals (id, shop_id, platform, cycle, kind, "
            "subject_type, subject_label, change_before, change_after, reason) "
            "VALUES (:id, :shop, 'shopee', '2026-11 Đợt 1', 'voucher', 'shop', 'Mẫu', "
            "'{}'::jsonb, CAST(:after AS jsonb), 'synthetic')"
        ),
        {"id": proposal_id, "shop": shop_id, "after": json.dumps({"v": 1})},
    )
    conn.execute(
        text(
            "INSERT INTO public.shopee_fill_jobs (id, shop_id, proposal_id, version, kind, target, "
            "target_key, seq, payload, status, created_at, updated_at) VALUES (:id, :shop, :p, 1, "
            "'voucher', '{}'::jsonb, 'shop', 0, '{}'::jsonb, 'queued', now(), now())"
        ),
        {"id": job_id, "shop": shop_id, "p": proposal_id},
    )
    return job_id


@pytest.fixture(scope="module")
def computers(owner_engine, shopee_tenants):
    """Shop A with two tokens and one open job; shop B with one token."""
    a, b = shopee_tenants
    with owner_engine.begin() as conn:
        first, second = _token(conn, a.shop_id), _token(conn, a.shop_id)
        other = _token(conn, b.shop_id)
    return a, b, first, second, other


def test_the_table_has_row_level_security_and_the_right_grants(owner_engine):
    with owner_engine.connect() as conn:
        rls = conn.execute(
            text("SELECT relrowsecurity FROM pg_class WHERE oid = to_regclass(:t)"),
            {"t": f"public.{TABLE}"},
        ).scalar()
        assert rls is True
        assert _verbs(conn, RUNTIME_ROLE, TABLE) == {"SELECT", "INSERT", "UPDATE"}
        cols = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT table_name || '.' || column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name = ANY(:c)"
                ),
                {"c": ["claimed_by_token_id", "lease_until", "install_id"]},
            )
        }
        assert {
            "shopee_fill_jobs.claimed_by_token_id",
            "shopee_fill_jobs.lease_until",
            "ingest_tokens.install_id",
        } <= cols


async def test_two_computers_never_get_the_same_job(owner_engine, computers):
    a, _, first, second, _ = computers
    with owner_engine.begin() as conn:
        job_id = _job(conn, a.shop_id)
    now = _now()

    async def poll(token_id):
        async with juli_app_session() as session:
            async with with_shop_scope(session, a.shop_id):
                got = await fill_queue.jobs_for_shop(session, a.shop_id, token_id=token_id, now=now)
            await session.commit()
            return [j["id"] for j in got]

    assert str(job_id) in await poll(first)
    assert str(job_id) not in await poll(second)
    assert str(job_id) in await poll(first)  # the holder is served again

    # A report from the non-holder is refused.
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            with pytest.raises(ProposalError) as refused:
                await fill_queue.report(
                    session, a.shop_id, job_id, status="opened", now=now, token_id=second
                )
        await session.rollback()
    assert refused.value.code == fill_queue.ERROR_JOB_LEASED and refused.value.status == 409

    # The lease expires: the other computer takes it.
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE public.shopee_fill_jobs SET lease_until = :t WHERE id = :id"),
            {"t": now - timedelta(seconds=1), "id": job_id},
        )
    assert str(job_id) in await poll(second)
    with owner_engine.connect() as conn:
        holder = conn.execute(
            text("SELECT claimed_by_token_id FROM public.shopee_fill_jobs WHERE id = :id"),
            {"id": job_id},
        ).scalar()
    assert holder == second


async def test_a_concurrent_poll_skips_the_rows_being_claimed(owner_engine, computers):
    """While one poll's transaction holds the claim, the other returns at once without them."""
    a, _, first, second, _ = computers
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE public.shopee_fill_jobs SET status = 'cancelled' WHERE shop_id = :s"),
            {"s": a.shop_id},
        )
        job_id = _job(conn, a.shop_id)
    now = _now()
    async with juli_app_session() as holder:
        async with with_shop_scope(holder, a.shop_id):
            mine = await fill_queue.jobs_for_shop(holder, a.shop_id, token_id=first, now=now)
            assert [j["id"] for j in mine] == [str(job_id)]
            async with juli_app_session() as rival:
                async with with_shop_scope(rival, a.shop_id):
                    theirs = await asyncio.wait_for(
                        fill_queue.jobs_for_shop(rival, a.shop_id, token_id=second, now=now),
                        timeout=10,
                    )
                await rival.rollback()
            assert theirs == []
        await holder.commit()


async def test_per_token_state_aggregates_on_the_shop_row(computers):
    a, _, first, second, _ = computers
    now = _now()
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            await cs.record_heartbeat(
                session, a.shop_id, seller_centre_open=True, ack=None, now=now,
                version="0.3.25", token_id=first,
            )  # fmt: skip
            await cs.record_reader_blocks(
                session, a.shop_id, {"traffic": "blocked:login"}, now=now, token_id=first
            )
            await cs.record_heartbeat(
                session, a.shop_id, seller_centre_open=None, ack=None, now=now,
                version="0.3.24", token_id=second,
            )  # fmt: skip
            await cs.record_reader_blocks(
                session, a.shop_id, {"traffic": "done:traffic_overview=posted"}, now=now,
                token_id=second,
            )  # fmt: skip
            row = await session.get(ShopeeConnectorState, a.shop_id)
            assert row is not None
            assert row.connector_version == "0.3.25" and row.seller_centre_open is True
            assert row.reader_blocks == [
                {"section": "phan_tich_ban_hang", "reason": "login", "readers": ["traffic"]}
            ]
            out = await cs.read(session, a.shop_id, now=now)
            assert len(out["computers"]) == 2
        await session.commit()


async def test_a_shop_sees_only_its_own_token_state(computers):
    a, b, _, _, other = computers
    async with juli_app_session() as session:
        async with with_shop_scope(session, b.shop_id):
            await cs.record_heartbeat(
                session, b.shop_id, seller_centre_open=False, ack=None, now=_now(),
                token_id=other,
            )  # fmt: skip
            seen = (
                await session.execute(
                    text("SELECT shop_id FROM public.shopee_connector_token_state")
                )
            ).all()
        await session.commit()
    assert {r[0] for r in seen} == {b.shop_id}
    assert a.shop_id not in {r[0] for r in seen}


def test_zz_downgrade_drops_and_upgrade_restores(owner_engine):
    """Last in the module: downgrade to 133, then back to head."""
    from alembic import command
    from alembic.config import Config

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))

    def present() -> tuple[bool, bool, bool]:
        with owner_engine.connect() as conn:
            table = conn.execute(text(f"SELECT to_regclass('public.{TABLE}')")).scalar()

            def col(t: str, c: str) -> bool:
                return (
                    conn.execute(
                        text(
                            "SELECT 1 FROM information_schema.columns WHERE table_schema = "
                            "'public' AND table_name = :t AND column_name = :c"
                        ),
                        {"t": t, "c": c},
                    ).scalar()
                    is not None
                )

            return (
                table is not None,
                col("shopee_fill_jobs", "lease_until"),
                col("ingest_tokens", "install_id"),
            )

    assert present() == (True, True, True)
    command.downgrade(cfg, "133_fleet_draws_real_shops")
    try:
        assert present() == (False, False, False)
    finally:
        command.upgrade(cfg, "head")
    assert present() == (True, True, True)
