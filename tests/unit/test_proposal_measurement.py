"""ADR-118 §3 (D81.3): the measurement job over executed proposals, on the unit substrate.

- a conclusive verdict on the targeted metric moves ``executed`` → ``measured``; an
  inconclusive one leaves it ``executed``;
- a new result row per metric is written only when ``data_through`` advances (append-only);
  a re-run with nothing new writes nothing and reads no item rows (the egress rule);
- ``force`` ("Tính lại") also writes when restated data changes the numbers;
- only executed item proposals with a verified execution are measured;
- the fleet helper isolates shops: one failing never stops the others, and logs carry the
  exception type only;
- the Ops route: audited, operator only, executed proposals only; the list carries results.

Synthetic data only. The Postgres proof is ``tests/integration/test_proposal_measurement_db.py``.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, func, select, update

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.ops import OpsAuditLog
from juli_backend.models.platform_data import PlatformItem
from juli_backend.models.shop_proposals import ShopProposal, ShopProposalResult
from juli_backend.services import shop_proposals as cycle
from juli_backend.services.shop_proposals import measurement
from tests.support.builders import make_shop, make_tenant

DAY0 = date(2026, 3, 10)
NOW = datetime(2026, 3, 25, 3, 0)
DAY0_AT_NINE = datetime.combine(DAY0, datetime.min.time()) + timedelta(hours=9)
WEEKLY = [100, 104, 98, 102, 96, 110, 106, 100]  # clicks per day, oldest week first; max 110


async def _shop(session):
    user, shop = await make_tenant(session)
    shop.platform = "shopee"
    session.add(
        PlatformItem(
            id=uuid.uuid4(),
            shop_id=shop.id,
            platform="shopee",
            item_id="1001",
            name="Synthetic item",
            source="file",
            source_rank=2,
            source_version="test",
            captured_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()
    return user, shop


def _metric(shop_id, day, clicks, *, item_id="1001") -> PlatformDailyMetric:
    return PlatformDailyMetric(
        shop_id=shop_id,
        platform="shopee",
        dataset="item_performance",
        day=day,
        item_id=item_id,
        stream="total",
        segment="all",
        order_type="confirmed",
        impressions=Decimal(2000),
        clicks=Decimal(clicks),
        extra={},
        source="file",
        source_rank=2,
        source_version="synthetic",
        confidence="high",
        captured_at=NOW,
        updated_at=NOW,
    )


def _history(session, shop_id, *, post_days: int, post_clicks: int = 120) -> None:
    """8 synthetic weeks before day 0 and ``post_days`` days after it."""
    for index, clicks in enumerate(WEEKLY):
        week = 8 - index
        for offset in range(7):
            day = DAY0 - timedelta(7 * week) + timedelta(offset)
            session.add(_metric(shop_id, day, clicks))
    for offset in range(1, post_days + 1):
        session.add(_metric(shop_id, DAY0 + timedelta(offset), post_clicks))


async def _executed(session, shop, *, kind="title", verified=True, **draft):
    staff = uuid.uuid4()
    values = {
        "cycle": "2026-03 Đợt 1",
        "kind": kind,
        "subject_type": "item",
        "item_id": "1001",
        "subject_label": "Synthetic item",
        "change_after": {"text": "New"},
        "reason": "Synthetic reason.",
    }
    values.update(draft)
    proposal = await cycle.create(
        session, shop.id, "shopee", cycle.ProposalDraft(**values), staff_id=staff, now=NOW
    )
    await cycle.send(session, proposal, now=NOW)
    await cycle.record_approval(
        session,
        proposal,
        decision="approved",
        channel="email",
        decided_at=NOW,
        now=NOW,
        recorded_by_staff_id=staff,
        evidence_ref="mail:synthetic",
    )
    execution = await cycle.record_execution(
        session,
        proposal,
        executed_at=DAY0_AT_NINE,
        executor_role="client_representative",
        channel="ops",
        now=NOW,
        recorded_by_staff_id=staff,
    )
    if verified:
        await cycle.verify_execution(
            session,
            shop.id,
            execution.id,
            verified_how="export_readback",
            verified_state={},
            verified_at=NOW,
        )
    return proposal


async def _results(session, proposal_id):
    r = ShopProposalResult
    return (
        await session.execute(
            select(r.metric, r.verdict, r.data_through, r.value, r.job_version)
            .where(r.proposal_id == proposal_id)
            .order_by(r.computed_at, r.metric)
        )
    ).all()


def test_the_target_is_ctr_for_listing_changes_and_clicks_otherwise_unless_named():
    assert measurement.target_metric("title", {"text": "x"}) == "ctr"
    assert measurement.target_metric("images", {}) == "ctr"
    assert measurement.target_metric("voucher", {}) == "clicks"
    assert measurement.target_metric("title", {"target_metric": "clicks"}) == "clicks"
    assert measurement.target_metric("price", {"target_metric": "orders"}) == "clicks"


async def test_a_conclusive_verdict_moves_the_proposal_to_measured(session):
    _, shop = await _shop(session)
    proposal = await _executed(session, shop)
    _history(session, shop.id, post_days=7)
    await session.flush()

    counts = await measurement.measure_shop_proposals(session, shop.id, now=NOW)

    assert (counts.considered, counts.written, counts.measured) == (1, 3, 1)
    rows = await _results(session, proposal.id)
    assert {m for m, *_ in rows} == {"impressions", "clicks", "ctr"}
    by_metric = {m: v for m, v, *_ in rows}
    assert by_metric["ctr"] == "dat" and by_metric["clicks"] == "chua_ket_luan"  # ctr is the target
    assert {r[2] for r in rows} == {DAY0 + timedelta(7)}
    assert {r[4] for r in rows} == {"self_baseline_v1"}
    await session.refresh(proposal)
    assert proposal.status == "measured"


async def test_an_inconclusive_verdict_leaves_the_proposal_executed_until_data_advances(session):
    _, shop = await _shop(session)
    proposal = await _executed(session, shop, kind="voucher")  # target: clicks
    _history(session, shop.id, post_days=3)
    await session.flush()

    first = await measurement.measure_shop_proposals(session, shop.id, now=NOW)
    assert (first.written, first.measured) == (3, 0)
    await session.refresh(proposal)
    assert proposal.status == "executed"

    # Nothing new: no rows written, and the second run is not even a candidate.
    again = await measurement.measure_shop_proposals(session, shop.id, now=NOW + timedelta(hours=1))
    assert (again.written, again.unchanged) == (0, 1)

    # Two more days of export: data_through advances, so a new row per metric is appended.
    for offset in (4, 5):
        session.add(_metric(shop.id, DAY0 + timedelta(offset), 120))
    await session.flush()
    advanced = await measurement.measure_shop_proposals(
        session, shop.id, now=NOW + timedelta(days=1)
    )
    assert (advanced.written, advanced.measured) == (3, 0)
    rows = await _results(session, proposal.id)
    assert len(rows) == 6
    assert {r[2] for r in rows} == {DAY0 + timedelta(3), DAY0 + timedelta(5)}

    # The full week lands: conclusive, so the proposal is measured and stops being a candidate.
    for offset in (6, 7):
        session.add(_metric(shop.id, DAY0 + timedelta(offset), 120))
    await session.flush()
    done = await measurement.measure_shop_proposals(session, shop.id, now=NOW + timedelta(days=2))
    assert (done.written, done.measured) == (3, 1)
    assert len(await _results(session, proposal.id)) == 9
    await session.refresh(proposal)
    assert proposal.status == "measured"
    assert (await measurement.measure_shop_proposals(session, shop.id, now=NOW)).considered == 0


async def test_a_run_with_nothing_new_reads_no_item_rows(session):
    _, shop = await _shop(session)
    await _executed(session, shop, kind="voucher")
    _history(session, shop.id, post_days=3)
    await session.flush()
    await measurement.measure_shop_proposals(session, shop.id, now=NOW)

    seen: list[str] = []

    def spy(conn, cursor, statement, *args):
        seen.append(statement)

    engine = session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", spy)
    try:
        await measurement.measure_shop_proposals(session, shop.id, now=NOW + timedelta(hours=1))
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    item_reads = [s for s in seen if "platform_daily_metrics.clicks" in s]
    cheap = [s for s in seen if "max(platform_daily_metrics.day)" in s]
    assert item_reads == [] and len(cheap) == 1


async def test_force_writes_again_only_when_restated_data_changes_the_numbers(session):
    _, shop = await _shop(session)
    proposal = await _executed(session, shop, kind="voucher")
    _history(session, shop.id, post_days=3)
    await session.flush()
    await measurement.measure_shop_proposals(session, shop.id, now=NOW)

    same = await measurement.measure_shop_proposals(
        session, shop.id, now=NOW, proposal_id=proposal.id, force=True
    )
    assert same.written == 0

    await session.execute(
        update(PlatformDailyMetric)
        .where(PlatformDailyMetric.day == DAY0 + timedelta(1))
        .values(clicks=Decimal(5000))
    )
    restated = await measurement.measure_shop_proposals(
        session, shop.id, now=NOW + timedelta(hours=2), proposal_id=proposal.id, force=True
    )
    assert restated.written >= 1
    newest = await session.scalar(select(func.max(ShopProposalResult.computed_at)))
    assert newest == NOW + timedelta(hours=2)


async def test_only_executed_verified_item_proposals_are_measured(session):
    _, shop = await _shop(session)
    await _executed(session, shop, verified=False)
    campaign = await _executed(
        session, shop, kind="program", subject_type="shop", item_id=None, subject_label="Shop"
    )
    _history(session, shop.id, post_days=7)
    await session.flush()

    counts = await measurement.measure_shop_proposals(session, shop.id, now=NOW)

    assert counts.considered == 0 and counts.written == 0
    assert await _results(session, campaign.id) == []


async def test_an_item_without_any_rows_is_counted_not_written(session):
    _, shop = await _shop(session)
    proposal = await _executed(session, shop)
    session.add(_metric(shop.id, DAY0 + timedelta(2), 10, item_id="other-item"))  # export exists
    await session.flush()

    counts = await measurement.measure_shop_proposals(session, shop.id, now=NOW)

    assert (counts.no_data, counts.written) == (1, 0)
    assert await _results(session, proposal.id) == []


async def test_a_shop_never_sees_another_shops_item_rows(session):
    user, shop = await _shop(session)
    other = await make_shop(session, user)
    other.platform = "shopee"
    proposal = await _executed(session, shop)
    _history(session, other.id, post_days=7)  # same item id, another shop's exports
    await session.flush()

    counts = await measurement.measure_shop_proposals(session, shop.id, now=NOW)

    assert counts.written == 0
    assert await _results(session, proposal.id) == []


# =========================================================================== the fleet


def _factory(session):
    @asynccontextmanager
    async def open_session():
        yield session

    return open_session


async def test_the_fleet_run_isolates_shops_and_logs_the_exception_type_only(
    session, monkeypatch, caplog
):
    user, first = await _shop(session)
    second = await make_shop(session, user)
    second.platform = "shopee"
    await session.flush()
    real = measurement.measure_shop_proposals

    async def flaky(sess, shop_id, **kw):
        if shop_id == first.id:
            raise ValueError("secret-metric-value-123")
        return await real(sess, shop_id, **kw)

    monkeypatch.setattr(measurement, "measure_shop_proposals", flaky)
    with caplog.at_level(logging.INFO):
        summary = await measurement.measure_all(_factory(session), now=NOW)

    assert (summary.shops, summary.failed) == (2, 1)
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "ValueError" in text and "secret-metric-value-123" not in text
    assert str(first.id) in text


async def test_the_fleet_run_measures_every_shopee_shop(session):
    _, shop = await _shop(session)
    proposal = await _executed(session, shop)
    _history(session, shop.id, post_days=7)
    await session.flush()

    summary = await measurement.measure_all(_factory(session), now=NOW)

    assert (summary.failed, summary.counts.measured) == (0, 1)
    await session.refresh(proposal)
    assert proposal.status == "measured"


# =========================================================================== the Ops route


async def _client(session, monkeypatch, role):
    from juli_backend.api.routes.ops import get_ops_user
    from juli_backend.core.security import get_current_user
    from juli_backend.models.ops import OpsStaff
    from tests.support.api import build_app
    from tests.support.builders import make_user

    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    email = f"{role}-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role=role, active=True))
    await session.flush()
    app = build_app(session)

    async def current():
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current
    app.dependency_overrides[get_ops_user] = current
    return app


async def test_an_operator_recomputes_a_result_and_the_list_carries_it(session, monkeypatch):
    from tests.support.api import client_for

    _, shop = await _shop(session)
    proposal = await _executed(session, shop)
    _history(session, shop.id, post_days=7)
    shop_id, proposal_id = shop.id, proposal.id
    await session.commit()
    app = await _client(session, monkeypatch, "operator")
    base = f"/v1/ops/shops/{shop_id}/proposals"
    async with client_for(app) as client:
        done = await client.post(f"{base}/{proposal_id}/measure")
        listed = await client.get(base)
    app.dependency_overrides.clear()

    assert done.status_code == 200, done.text
    assert done.json()["measured"] == 1
    [row] = listed.json()["proposals"]
    assert row["status"] == "measured"
    ctr = next(r for r in row["results"] if r["metric"] == "ctr")
    assert ctr["verdict"] == "dat" and ctr["data_through"] == "2026-03-17"
    assert ctr["value"] == pytest.approx(0.06) and ctr["comparison"] == pytest.approx(0.0515)
    actions = set(
        (
            await session.scalars(select(OpsAuditLog.action).where(OpsAuditLog.shop_id == shop_id))
        ).all()
    )
    assert "proposal_measure" in actions


async def test_a_viewer_cannot_recompute_and_a_proposal_not_executed_is_refused(
    session, monkeypatch
):
    from tests.support.api import client_for

    _, shop = await _shop(session)
    draft = await cycle.create(
        session,
        shop.id,
        "shopee",
        cycle.ProposalDraft(
            cycle="c",
            kind="title",
            subject_type="item",
            item_id="1001",
            subject_label="s",
            change_after={"text": "x"},
            reason="r",
        ),
        staff_id=None,
        now=NOW,
    )
    shop_id, draft_id = shop.id, draft.id
    await session.commit()
    url = f"/v1/ops/shops/{shop_id}/proposals/{draft_id}/measure"
    viewer_app = await _client(session, monkeypatch, "viewer")
    async with client_for(viewer_app) as client:
        refused = await client.post(url)
    viewer_app.dependency_overrides.clear()
    operator_app = await _client(session, monkeypatch, "operator")
    async with client_for(operator_app) as client:
        wrong_state = await client.post(url)
    operator_app.dependency_overrides.clear()

    assert refused.status_code == 403
    assert wrong_state.status_code == 409
    assert (await session.get(ShopProposal, draft_id)).status == "draft"
