"""P100 redesign: Thực hiện / Đo lường states derived from fill jobs and card events. SQLite,
synthetic shop."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select, update

from juli_backend.models.card_events import (
    ACTOR_SYSTEM,
    EVENT_EXECUTED,
    EVENT_IMPACT_FINAL,
    EVENT_MISMATCH,
    EVENT_VERIFIED,
    CardEvent,
)
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.models.shopee_fill import ShopeeFillJob
from juli_backend.services.shopee_recommendations import execution_state as es
from tests.support.api import authenticate, build_app, client_for
from tests.unit import test_p97_fill_queue as fq
from tests.unit.test_shopee_reco_routes import NOW

T0 = datetime(2026, 11, 10, 8, 0)
shop = fq.shop
flag_on = fq._flag_on
_approve = fq._approve


def _job(status, kind="ads_edit"):
    return {"status": status, "kind": kind}


# ------------------------------------------------------------------ pure derivation


def test_nothing_filled_is_cho_dien_with_the_approval_step_done():
    out = es.derive_state([_job("queued"), _job("opened")], [])
    assert (out["state"], out["completed"]) == (es.STATE_WAITING, 1)
    assert out["jobs"] == {"total": 2, "filled": 0, "saved": 0, "failed": 0}


def test_filled_jobs_are_da_dien_and_count_n_of_m():
    out = es.derive_state([_job("filled"), _job("filled"), _job("filled"), _job("opened")], [])
    assert (out["state"], out["completed"]) == (es.STATE_FILLED, 2)
    assert (out["jobs"]["filled"], out["jobs"]["total"], out["noun"]) == (3, 4, "chiến dịch")


def test_a_saved_page_or_a_done_mark_moves_the_save_step():
    assert es.derive_state([_job("saved")], [])["completed"] == 3
    out = es.derive_state([_job("filled")], [(EVENT_EXECUTED, T0, {})])
    assert (out["state"], out["completed"], out["executed_at"]) == (
        es.STATE_FILLED,
        3,
        "2026-11-10T08:00:00Z",
    )


def test_cancelled_jobs_do_not_count():
    out = es.derive_state([_job("cancelled"), _job("filled")], [])
    assert out["jobs"]["total"] == 1


def test_a_verified_read_is_khop_and_gives_the_measurement_start():
    ev = [
        (EVENT_EXECUTED, T0, {}),
        (EVENT_VERIFIED, T0 + timedelta(hours=5), {"observed_at": "2026-11-10T13:00:00Z"}),
    ]
    out = es.derive_state([_job("captured")], ev)
    assert (out["state"], out["completed"], out["verified_at"]) == (
        es.STATE_MATCH,
        4,
        "2026-11-10T13:00:00Z",
    )


def test_a_mismatch_names_the_field_and_both_values():
    ev = [
        (EVENT_EXECUTED, T0, {}),
        (
            EVENT_MISMATCH,
            T0 + timedelta(hours=48),
            {
                "expected": {"daily_budget": 80_000, "roas_target": 5},
                "observed": {"daily_budget": 100_000, "roas_target": 5},
            },
        ),
    ]
    out = es.derive_state([_job("saved")], ev)
    assert (out["state"], out["completed"], out["bad"]) == (es.STATE_MISMATCH, 3, 3)
    assert out["mismatch"] == {"field": "daily_budget", "observed": 100_000, "expected": 80_000}


def test_an_outcome_before_the_last_execution_is_ignored():
    ev = [
        (EVENT_MISMATCH, T0, {"expected": {"a": 1}, "observed": {"a": 2}}),
        (EVENT_EXECUTED, T0 + timedelta(hours=1), {}),
    ]
    assert es.derive_state([_job("saved")], ev)["state"] == es.STATE_FILLED


def test_verdict_bands():
    assert es.verdict_of(0.02, 0.05, 0.15) == es.VERDICT_BELOW
    assert es.verdict_of(0.10, 0.05, 0.15) == es.VERDICT_INSIDE
    assert es.verdict_of(0.30, 0.05, 0.15) == es.VERDICT_ABOVE
    assert es.verdict_of(None, 0.05, 0.15) == es.VERDICT_NONE


def _card(metric="ctr"):
    return {
        "metric": {"key": metric},
        "measurement_plan": {"planned_days": 30},
        "predicted": {
            "lift": {"lift": {"p10": 0.05, "p50": 0.10, "p90": 0.15}},
            "money_per_month": {
                "days": 30,
                "total": {
                    q: {"dprofit": v}
                    for q, v in (("p10", 1_000_000), ("p50", 2_000_000), ("p90", 3_000_000))
                },
            },
        },
    }


def test_measurement_row_running_has_no_verdict_and_counts_days():
    row = es.measurement_row(
        _card(),
        started=datetime(2026, 11, 4),
        today=date(2026, 11, 13),
        window_days=None,
        window_closed=False,
        reading=None,
        final=False,
    )
    assert (row["verdict"], row["days_measured"], row["days"], row["done"]) == (
        es.VERDICT_RUNNING,
        9,
        30,
        False,
    )
    assert row["band"] == {"p10": 1_000_000.0, "p50": 2_000_000.0, "p90": 3_000_000.0}
    assert row["metrics"] == [] and row["ends"] == "2026-12-04"


def test_measurement_row_final_scales_profit_and_judges_against_the_band():
    row = es.measurement_row(
        _card(),
        started=datetime(2026, 10, 1),
        today=date(2026, 11, 13),
        window_days=30,
        window_closed=True,
        reading={"impact_pct": 0.20},
        final=True,
    )
    assert (row["verdict"], row["done"], row["days_measured"]) == (es.VERDICT_ABOVE, True, 30)
    assert row["actual"] == pytest.approx(4_000_000)
    assert row["metrics"] == [{"metric": "ctr", "change_pct": 0.20}]


def test_measurement_row_period_follows_the_window():
    row = es.measurement_row(
        _card(),
        started=datetime(2026, 10, 1),
        today=date(2026, 11, 13),
        window_days=15,
        window_closed=True,
        reading={"impact_pct": 0.10},
        final=True,
    )
    assert row["band"]["p50"] == pytest.approx(1_000_000) and row["verdict"] == es.VERDICT_INSIDE


# ------------------------------------------------------------------ rows


async def _event(session, shop_id, card_id, event_type, at, payload):
    session.add(
        CardEvent(
            id=uuid.uuid4(),
            card_id=card_id,
            shop_id=shop_id,
            workflow_key="shopee_reco",
            subject_type="item",
            subject_id="1001",
            event_type=event_type,
            actor=ACTOR_SYSTEM,
            occurred_at=at,
            source="live",
            payload=payload,
            schema_version=1,
            dedup_key=f"{event_type}:{card_id}:{at.isoformat()}",
        )
    )
    await session.flush()


async def test_a_card_walks_cho_dien_da_dien_khop(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[1])  # ads_budget -> one ads_edit job
    out = await es.execution_states(session, seeded.shop_id, now=NOW)
    (row,) = [c for c in out["cards"] if c["card_id"] == str(ids[1])]
    assert row["state"] == es.STATE_WAITING and row["jobs"]["total"] == 1
    assert row["open_job"]["open_path"].startswith("/portal/")
    assert out["connector"]["version"] is None and out["connector"]["connected"] is False

    await session.execute(
        update(ShopeeFillJob).where(ShopeeFillJob.proposal_id == ids[1]).values(status="filled")
    )
    await session.commit()
    out = await es.execution_states(session, seeded.shop_id, now=NOW)
    assert [c["state"] for c in out["cards"] if c["card_id"] == str(ids[1])] == [es.STATE_FILLED]

    await _event(
        session,
        seeded.shop_id,
        ids[1],
        EVENT_EXECUTED,
        T0,
        {"change": {"change_kind": "daily_budget"}},
    )
    await _event(
        session,
        seeded.shop_id,
        ids[1],
        EVENT_VERIFIED,
        T0 + timedelta(hours=4),
        {"observed_at": "2026-11-10T12:00:00"},
    )
    await session.commit()
    out = await es.execution_states(session, seeded.shop_id, now=NOW)
    (row,) = [c for c in out["cards"] if c["card_id"] == str(ids[1])]
    assert (row["state"], row["measure_start"]) == (es.STATE_MATCH, "2026-11-10")
    assert out["counts"][es.STATE_MATCH] == 1


async def test_a_mismatch_row_carries_the_detail(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[1])
    await _event(session, seeded.shop_id, ids[1], EVENT_EXECUTED, T0, {})
    await _event(
        session,
        seeded.shop_id,
        ids[1],
        EVENT_MISMATCH,
        T0 + timedelta(hours=48),
        {"expected": {"daily_budget": 80_000}, "observed": {"daily_budget": 100_000}},
    )
    await session.commit()
    out = await es.execution_states(session, seeded.shop_id, now=NOW)
    (row,) = [c for c in out["cards"] if c["card_id"] == str(ids[1])]
    assert row["state"] == es.STATE_MISMATCH and row["mismatch"]["observed"] == 100_000


async def test_measurements_list_a_verified_card_running_then_finished(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[1])
    await _event(
        session,
        seeded.shop_id,
        ids[1],
        EVENT_EXECUTED,
        T0,
        {"change": {"change_kind": "daily_budget"}},
    )
    await _event(session, seeded.shop_id, ids[1], EVENT_VERIFIED, T0 + timedelta(hours=4), {})
    await session.commit()
    await session.execute(
        update(ShopProposal).where(ShopProposal.id == ids[1]).values(status="executed")
    )
    await session.commit()
    out = await es.measurement_states(session, seeded.shop_id, now=NOW)
    (row,) = [c for c in out["cards"] if c["card_id"] == str(ids[1])]
    assert (row["verdict"], row["done"]) == (es.VERDICT_RUNNING, False)
    await _event(
        session,
        seeded.shop_id,
        ids[1],
        EVENT_IMPACT_FINAL,
        T0 + timedelta(days=30),
        {"impact_pct": 0.5, "post_days": 30},
    )
    await session.commit()
    out = await es.measurement_states(session, seeded.shop_id, now=NOW)
    (row,) = [c for c in out["cards"] if c["card_id"] == str(ids[1])]
    assert row["done"] is True and row["verdict"] != es.VERDICT_RUNNING


# ------------------------------------------------------------------ routes


async def test_the_seller_routes_answer_and_do_not_read_as_a_card_id(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[1])
    app = build_app(session)
    authenticate(app, user=seeded.user, shop=seeded.shop)
    async with client_for(app) as client:
        r = await client.get("/v1/demo/shopee/recommendations/execution")
        assert r.status_code == 200
        body = r.json()
        body = body.get("data", body)
        assert [c["state"] for c in body["cards"]] == ["cho_dien"]
        m = await client.get("/v1/demo/shopee/recommendations/measurements")
        assert m.status_code == 200
    app.dependency_overrides.clear()


def test_field_progress_counts_n_of_m_and_a_partial_fill_is_da_dien():
    jobs = [
        {"status": "opened", "kind": "combo", "progress": {"filled": 3, "total": 4}},
        _job("queued"),
    ]
    out = es.derive_state(jobs, [])
    assert (out["state"], out["completed"]) == (es.STATE_FILLED, 2)
    assert out["fields"] == {"filled": 3, "total": 5}


async def test_the_connector_progress_is_stored_and_shown(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[1])
    job = (
        await session.scalars(select(ShopeeFillJob).where(ShopeeFillJob.proposal_id == ids[1]))
    ).one()
    await fq.fill_queue.report(
        session, seeded.shop_id, job.id, status="opened", progress={"filled": 1, "total": 2}
    )
    await session.commit()
    out = await es.execution_states(session, seeded.shop_id, now=NOW)
    (row,) = [c for c in out["cards"] if c["card_id"] == str(ids[1])]
    assert (row["state"], row["fields"]) == (es.STATE_FILLED, {"filled": 1, "total": 2})
