"""The Shopee KPI job behind Juli Ops (services/shopee_kpi/job.py, ADR-117 step 3).

- The job reads each KPI flow from its exact ``platform_daily_metrics`` key, confirmed
  orders, shop level: ``shop_page`` is its own flow and never adds into the product
  card total (G3); placed orders, other datasets and item rows are ignored.
- An operator run stores ``kpi_forecasts`` (expected move: flow x metric x milestone x
  trend weight; GLM band: milestone 0) under one ``run_at`` / ``inputs_sha256``, writes
  the contract version's ``kpi_targets`` once, and is audited. A proposal run on another
  ``measure_start`` writes no targets.
- A viewer reads the KPI table and the newest run but cannot run the job; a shop with no
  contract is 404, a contract with no start date 409.

Synthetic shops and numbers only.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.kpi_contracts import KpiContract, KpiForecast, KpiTarget, LeverPlan
from juli_backend.models.ops import OpsAuditLog
from juli_backend.services import shopee_kpi
from juli_backend.services.shopee_kpi.job import load_series
from tests.support.builders import make_shop, make_user

START = date(2026, 6, 20)
FIRST, LAST = START - timedelta(120), START + timedelta(20)
NOW = datetime(2026, 7, 11, 3, 0)


def _row(shop_id, day, dataset, stream, segment, order_type, imp, clk, ordr, gmv, item=""):
    return PlatformDailyMetric(
        shop_id=shop_id,
        platform="shopee",
        dataset=dataset,
        day=day,
        item_id=item,
        stream=stream,
        segment=segment,
        order_type=order_type,
        impressions=Decimal(imp),
        clicks=Decimal(clk),
        orders=Decimal(ordr),
        gmv=Decimal(gmv),
        extra={},
        source="file",
        source_rank=2,
        source_version="test",
        confidence="high",
        captured_at=NOW,
        updated_at=NOW,
    )


async def _seed(session, *, measure_start: date | None = START) -> uuid.UUID:
    owner = await make_user(session, email=f"owner-{uuid.uuid4().hex[:6]}@example.com")
    shop = await make_shop(session, owner, platform="shopee")
    d = FIRST
    while d <= LAST:
        session.add_all(
            [
                _row(
                    shop.id,
                    d,
                    "traffic_overview",
                    "product_card",
                    "all",
                    "confirmed",
                    2000,
                    60,
                    6,
                    600_000,
                ),
                _row(
                    shop.id,
                    d,
                    "traffic_overview",
                    "product_card",
                    "shop_page",
                    "confirmed",
                    300,
                    12,
                    1,
                    100_000,
                ),
                _row(
                    shop.id,
                    d,
                    "traffic_overview",
                    "product_card",
                    "search",
                    "confirmed",
                    900,
                    30,
                    3,
                    300_000,
                ),
                _row(
                    shop.id,
                    d,
                    "traffic_overview",
                    "product_card",
                    "all",
                    "placed",
                    2000,
                    60,
                    9,
                    900_000,
                ),
                _row(
                    shop.id,
                    d,
                    "traffic_overview",
                    "product_card",
                    "all",
                    "confirmed",
                    50,
                    5,
                    1,
                    1,
                    item="123",
                ),
                _row(
                    shop.id, d, "shop_overview", "total", "all", "confirmed", 0, 400, 20, 3_000_000
                ),
            ]
        )
        d += timedelta(1)
    session.add(
        KpiContract(
            shop_id=shop.id,
            contract_ref="01/2026/TEST",
            version=1,
            status="sent",
            measure_start=measure_start,
            params={
                "pass": 0.035,
                "target": 0.05,
                "flows": {
                    "the_san_pham": {"metrics": ["impressions", "ctr"]},
                    "trang_shop": {"metrics": ["impressions", "ctr"]},
                    "ca_shop": {"metrics": ["ctor", "aov"], "role": "theo_doi"},
                },
            },
        )
    )
    session.add(
        LeverPlan(
            shop_id=shop.id,
            lever_key="W1",
            wave=1,
            name="Synthetic cover image",
            starts_on=START,
            lag_days=0,
            flow="the_san_pham",
            metric="ctr",
            low=Decimal("0"),
            high=Decimal("0.08"),
        )
    )
    await session.commit()
    return shop.id


def test_flow_sources_use_the_ingest_mapping_names():
    from juli_backend.services.ingest import mapping, schemas

    card = shopee_kpi.FLOW_SOURCES["the_san_pham"]
    assert (card.stream, card.segment) == (mapping.STREAM_PRODUCT_CARD, "all")
    page = shopee_kpi.FLOW_SOURCES["trang_shop"]
    assert (page.stream, page.segment) == (mapping.STREAM_PRODUCT_CARD, "shop_page")
    assert shopee_kpi.FLOW_SOURCES["video"].stream == mapping.STREAM_SELLER_VIDEO
    assert shopee_kpi.FLOW_SOURCES["live"].stream == mapping.STREAM_SELLER_LIVE
    assert shopee_kpi.FLOW_SOURCES["ca_shop"].stream == mapping.STREAM_TOTAL
    assert "shop_page" in schemas.SHOPEE_L2_SOURCES["psd_label_product_card"].values()


async def test_shop_page_is_its_own_flow_and_never_adds_into_the_card_total(session):
    shop_id = await _seed(session)
    series = await load_series(session, shop_id)
    assert set(series) == {"the_san_pham", "trang_shop", "ca_shop"}
    # the L1 total row only: not + shop_page (300) + search (900), not the item row,
    # not the placed-orders sheet
    assert series["the_san_pham"][START] == (2000.0, 60.0, 6.0, 600_000.0)
    assert series["trang_shop"][START] == (300.0, 12.0, 1.0, 100_000.0)
    assert series["ca_shop"][START] == (0.0, 400.0, 20.0, 3_000_000.0)


async def _ops_client(session, monkeypatch, role):
    from juli_backend.api.routes.ops import get_ops_user
    from juli_backend.core.security import get_current_user
    from juli_backend.models.ops import OpsStaff
    from tests.support.api import build_app

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


async def test_an_operator_run_stores_forecasts_and_targets_once(session, monkeypatch):
    from tests.support.api import client_for

    shop_id = await _seed(session)
    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        first = await client.post(f"/v1/ops/shops/{shop_id}/shopee-kpi/run", json={})
        second = await client.post(
            f"/v1/ops/shops/{shop_id}/shopee-kpi/run", json={"as_of": "2026-07-05"}
        )
        read = await client.get(f"/v1/ops/shops/{shop_id}/shopee-kpi")
    app.dependency_overrides.clear()

    assert first.status_code == 200, first.text
    body = first.json()
    assert body["targets_written"] == 6 and second.json()["targets_written"] == 0
    kpi = body["kpi"]
    assert kpi["as_of"] == LAST.isoformat() and kpi["measure_start"] == START.isoformat()
    card = next(f for f in kpi["flows"] if f["flow"] == "the_san_pham")
    imp = next(m for m in card["metrics"] if m["metric"] == "impressions")
    assert imp["baseline"] == 2000 and imp["d_pct"] == 0.05 and imp["window_days"] == 28
    assert kpi["acceptance"]["eligible"] == 4  # card + shop page; whole shop is tracking

    targets = (await session.execute(select(KpiTarget))).scalars().all()
    assert len(targets) == 6
    t_imp = next(t for t in targets if (t.flow, t.metric) == ("the_san_pham", "impressions"))
    assert t_imp.baseline == Decimal("2000") and t_imp.role == "kpi"
    assert {t.role for t in targets if t.flow == "ca_shop"} == {"tracking"}

    runs = (
        await session.execute(
            select(KpiForecast.run_at, func.count())
            .where(KpiForecast.shop_id == shop_id)
            .group_by(KpiForecast.run_at)
        )
    ).all()
    assert len(runs) == 2
    rows = read.json()["forecasts"]["rows"]
    em_rows = [r for r in rows if r["method_version"] == "expected_move_v1"]
    glm_rows = [r for r in rows if r["method_version"] == "flow_glm_v2"]
    # 6 metrics x 3 milestones x 2 trend weights + 2 flows' GMV x 3 x 2
    assert len(em_rows) == 6 * 3 * 2 + 2 * 3 * 2
    assert {r["window_end"] for r in em_rows} == {"2026-07-19", "2026-08-19", "2026-09-19"}
    lever_t1 = next(
        r
        for r in em_rows
        if (r["flow"], r["metric"], r["milestone"], r["trend_weight"])
        == ("the_san_pham", "ctr", 1, 0.0)
    )
    assert lever_t1["expected"] == round(0.03 * 1.04, 6)  # constant history + the 0–8 % lever
    # above the 3,000 / 100 floor: card CTR + CTOR, shop-page CTR, whole-shop CTOR;
    # shop-page CTOR has 12 clicks a day (< 3,000 over the history), whole shop no impressions
    assert {(r["flow"], r["metric"]) for r in glm_rows} == {
        ("the_san_pham", "ctr"),
        ("the_san_pham", "ctor"),
        ("trang_shop", "ctr"),
        ("ca_shop", "ctor"),
    }
    assert all(r["milestone"] == 0 and r["p_pass"] is None for r in glm_rows)

    actions = (
        (await session.execute(select(OpsAuditLog.action).where(OpsAuditLog.shop_id == shop_id)))
        .scalars()
        .all()
    )
    assert actions.count("shopee_kpi_run") == 2


async def test_a_proposal_run_on_another_start_writes_no_targets(session, monkeypatch):
    from tests.support.api import client_for

    shop_id = await _seed(session)
    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        res = await client.post(
            f"/v1/ops/shops/{shop_id}/shopee-kpi/run", json={"measure_start": "2026-06-01"}
        )
    app.dependency_overrides.clear()
    assert res.status_code == 200, res.text
    assert res.json()["targets_written"] == 0
    assert res.json()["kpi"]["measure_start"] == "2026-06-01"
    assert (await session.execute(select(func.count()).select_from(KpiTarget))).scalar_one() == 0


async def test_a_viewer_reads_but_cannot_run(session, monkeypatch):
    from tests.support.api import client_for

    shop_id = await _seed(session)
    app = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        refused = await client.post(f"/v1/ops/shops/{shop_id}/shopee-kpi/run", json={})
        read = await client.get(f"/v1/ops/shops/{shop_id}/shopee-kpi")
    app.dependency_overrides.clear()
    assert refused.status_code == 403
    assert read.status_code == 200, read.text
    assert read.json()["forecasts"] == {"run_at": None, "inputs_sha256": None, "rows": []}
    assert read.json()["contract"]["version"] == 1


async def test_no_contract_is_404_and_no_start_date_is_409(session, monkeypatch):
    from tests.support.api import client_for

    owner = await make_user(session, email="bare@example.com")
    bare = (await make_shop(session, owner, platform="shopee")).id
    undated = await _seed(session, measure_start=None)
    await session.commit()
    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        none = await client.get(f"/v1/ops/shops/{bare}/shopee-kpi")
        no_start = await client.post(f"/v1/ops/shops/{undated}/shopee-kpi/run", json={})
    app.dependency_overrides.clear()
    assert none.status_code == 404 and none.json()["detail"]["code"] == "no_kpi_contract"
    assert no_start.status_code == 409
    assert no_start.json()["detail"]["code"] == "measure_start_missing"
