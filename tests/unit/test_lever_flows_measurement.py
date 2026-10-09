"""AC-10.2 (fast track P10-B), contract §6: ``GET /v1/demo/runs/{id}/measurement``.

- stages follow the impact reader's readings for a listing run (waiting / day7
  / final) and the calendar for a verified promotion run;
- target and bands: the card's own current → reference rate; bands only from the
  seller's ``stability_band`` rules (none -> ``bands = []``,
  ``day7.within_band = null``, never a default ±3 %);
- day 7: rows with verdict/tone, ``within_band`` true/false, P8-C's question id;
- day 14: each final label (dat / gan_dat / khong_dat / chua_ket_luan, both for
  thin data and for another change on the product); the per-lever calibration
  starts at 0.5 and moves, except for chua_ket_luan; the verdict is stored once;
- not measurable -> 409, another shop's run -> 404.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from juli_backend.models.lever_flows import LeverCalibration, RunLeverFlow, RunMeasurementFinal
from juli_backend.models.models import (
    AnalyticsPerformanceInterval,
    ImpactReading,
    ToolExecution,
)
from juli_backend.models.run_changes import RunRevertQuestion, RunWriteValue
from juli_backend.services import lever_flows, shop_rules
from tests.support.lever_flows import PRODUCT_ID, api_client, seed_run, seed_shop

T = date(2026, 9, 20)
AFTER_DAY14 = T + timedelta(days=15)


async def _listing_run(session, label="a", *, status="completed"):
    shop, product = await seed_shop(session, label)
    run = await seed_run(session, shop, product, lever="description", status=status)
    execution = ToolExecution(
        shop_id=shop.id,
        approval_id=str(uuid.uuid4()),
        tool_name="update_product_listing",
        payload_json="{}",
        status="succeeded",
        workflow_run_id=run.id,
        tool_call_id="c1",
        updated_at=datetime(T.year, T.month, T.day, 4, 0),
    )
    session.add(execution)
    session.add(
        RunWriteValue(
            shop_id=shop.id,
            workflow_run_id=run.id,
            tool_call_id="c1",
            tool_name="update_product_listing",
            tiktok_product_id=PRODUCT_ID,
            field="description",
            before_value="cũ",
            after_value="mới",
            after_source="read_back",
            recorded_at=datetime(T.year, T.month, T.day, 4, 0),
        )
    )
    await session.flush()
    return shop, product, run, execution


async def _reading(session, run, execution, kind, confidence="trung_binh"):
    session.add(
        ImpactReading(
            run_id=run.id,
            tool_execution_id=execution.id,
            metric="conversion_rate",
            kind=kind,
            confidence=confidence,
            control_set_json="{}",
            computed_at=datetime.now(UTC),
            series_source="measured",
        )
    )
    await session.flush()


def _day(shop_id, day: date, *, impressions=10000, clicks=450, orders=24, gmv=3_840_000):
    return AnalyticsPerformanceInterval(
        shop_id=shop_id,
        snapshot_key=f"product:{PRODUCT_ID}:{day.isoformat()}",
        grain="product",
        start_date=day,
        tiktok_product_id=PRODUCT_ID,
        impressions=impressions,
        clicks=clicks,
        sku_orders=orders,
        items_sold=orders,
        gmv=gmv,
        update_time=datetime(2026, 10, 9),
    )


async def _series(session, shop_id, *, post: dict, post_days: int = 14, pre: dict | None = None):
    for offset in range(1, 15):
        session.add(_day(shop_id, T - timedelta(days=offset), **(pre or {})))
    for offset in range(1, post_days + 1):
        session.add(_day(shop_id, T + timedelta(days=offset), **post))
    await session.flush()


async def _bands(session, shop_id, **bands):
    for metric, value in bands.items():
        await shop_rules.set_rule(
            session,
            shop_id,
            rule_key=shop_rules.STABILITY_BAND,
            scope_ref=metric,
            value=value,
            set_by="seller",
            set_by_user_id=None,
        )


# --- stages, target, bands --------------------------------------------------------------


@pytest.mark.asyncio
async def test_waiting_shows_the_target_and_the_sellers_bands_and_no_rows(session):
    shop, _product, run, _execution = await _listing_run(session)
    await _series(session, shop.id, post={}, post_days=3)
    await _bands(session, shop.id, impressions=3, ctr=3, gmv_per_order=3)

    body = await lever_flows.measure_run(session, shop.id, run, today=T + timedelta(days=3))

    assert body["stage"] == "waiting"
    assert body["dates"] == {"day7": "2026-09-27", "day14": "2026-10-04"}
    assert body["target"] == {
        "label": "CTOR Thẻ sản phẩm",
        "current": 0.054,
        "target": 0.059,
        "progress_from": 0.055,
        "unit": "ratio",
    }
    assert body["expected_gmv_per_day"] == 70000
    assert [b["key"] for b in body["bands"]] == ["ctr", "gmv_per_order", "impressions"]
    impressions = next(b for b in body["bands"] if b["key"] == "impressions")
    assert impressions == {
        "key": "impressions",
        "label": "Lượt hiển thị/ngày",
        "before": 10000,
        "band_pct": 3,
        "low": 9700,
        "high": 10300,
        "unit": "count",
    }
    assert body["rows"] == []
    assert body["day7"] == {"within_band": None, "question_id": None}
    assert body["final"] is None


@pytest.mark.asyncio
async def test_no_band_set_means_no_bands_and_within_band_null_never_a_default(session):
    shop, _product, run, execution = await _listing_run(session)
    await _series(session, shop.id, post={"orders": 26}, post_days=7)
    await _reading(session, run, execution, "preliminary")

    body = await lever_flows.measure_run(session, shop.id, run)

    assert body["stage"] == "day7"
    assert body["bands"] == []
    assert body["day7"]["within_band"] is None
    assert [r["key"] for r in body["rows"]] == ["ctor", "gmv_per_day"]


@pytest.mark.asyncio
async def test_day7_within_the_band_with_rows_and_tones(session):
    shop, _product, run, execution = await _listing_run(session)
    await _series(session, shop.id, post={"orders": 26, "gmv": 3_900_000}, post_days=7)
    await _reading(session, run, execution, "preliminary")
    await _bands(session, shop.id, impressions=3, ctr=3)

    body = await lever_flows.measure_run(session, shop.id, run)

    assert body["stage"] == "day7"
    assert body["day7"] == {"within_band": True, "question_id": None}
    main = body["rows"][0]
    assert main["key"] == "ctor" and main["label"] == "CTOR (chỉ số chính)"
    assert main["expected"] == "5,9 %"
    assert main["actual"] == pytest.approx(26 / 450, abs=1e-6)
    assert (main["verdict"], main["tone"]) == ("Đang tăng", "ok")
    band_rows = {r["key"]: r for r in body["rows"][1:-1]}
    assert band_rows["impressions"]["expected"] == "9.700 – 10.300"
    assert (band_rows["impressions"]["verdict"], band_rows["impressions"]["tone"]) == (
        "Ổn định",
        "muted",
    )
    gmv = body["rows"][-1]
    assert (gmv["key"], gmv["expected"], gmv["actual"], gmv["verdict"]) == (
        "gmv_per_day",
        "+70k ₫",
        60000,
        "Sơ bộ",
    )
    assert body["final"] is None


@pytest.mark.asyncio
async def test_day7_outside_the_band_links_the_revert_question(session):
    shop, _product, run, execution = await _listing_run(session)
    await _series(session, shop.id, post={"impressions": 9000, "clicks": 405}, post_days=7)
    await _reading(session, run, execution, "preliminary")
    await _bands(session, shop.id, impressions=3)
    question = RunRevertQuestion(
        shop_id=shop.id,
        workflow_run_id=run.id,
        breaches=[{"metric": "impressions", "impact_pct": -10.0, "band_pct": 3.0}],
        status="open",
    )
    session.add(question)
    await session.flush()

    body = await lever_flows.measure_run(session, shop.id, run)

    assert body["day7"] == {"within_band": False, "question_id": str(question.id)}
    impressions = next(r for r in body["rows"] if r["key"] == "impressions")
    assert (impressions["verdict"], impressions["tone"]) == ("Ngoài khoảng", "warn")


# --- day 14 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("post", "label", "pct", "calibration"),
    [
        ({"orders": 27, "gmv": 3_920_000}, "dat", 114, (0.5, 0.66)),
        ({"orders": 26, "gmv": 3_897_000}, "gan_dat", 81, (0.5, 0.58)),
        ({"orders": 24, "gmv": 3_834_000}, "khong_dat", -9, (0.5, 0.38)),
        # 100 % of the GMV but the CTOR target missed: gần đạt, not đạt.
        ({"orders": 26, "gmv": 3_910_000}, "gan_dat", 100, (0.5, 0.63)),
    ],
)
@pytest.mark.asyncio
async def test_each_conclusive_final_label_and_its_calibration(
    session, post, label, pct, calibration
):
    shop, _product, run, execution = await _listing_run(session)
    await _series(session, shop.id, post=post)
    await _reading(session, run, execution, "preliminary")
    await _reading(session, run, execution, "final")

    body = await lever_flows.measure_run(session, shop.id, run)

    assert body["stage"] == "final"
    final = body["final"]
    assert (final["label"], final["pct_of_expected"]) == (label, pct)
    assert final["calibration"] == {
        "lever": "description",
        "from": calibration[0],
        "to": calibration[1],
    }
    assert body["rows"][0]["verdict"] == lever_flows.LABELS_VI[label]
    stored = (await session.execute(select(LeverCalibration))).scalar_one()
    assert (stored.lever, stored.readings) == ("description", 1)


@pytest.mark.asyncio
async def test_too_little_data_is_chua_ket_luan_and_leaves_the_calibration(session):
    shop, _product, run, execution = await _listing_run(session)
    await _series(session, shop.id, post={"orders": 1, "gmv": 4_200_000})
    await _reading(session, run, execution, "final")

    final = (await lever_flows.measure_run(session, shop.id, run))["final"]

    assert final["label"] == "chua_ket_luan"
    assert final["calibration"] == {"lever": "description", "from": 0.5, "to": 0.5}
    assert (await session.execute(select(LeverCalibration))).scalars().all() == []


@pytest.mark.asyncio
async def test_another_change_on_the_product_is_chua_ket_luan(session):
    shop, product, run, execution = await _listing_run(session)
    await _series(session, shop.id, post={"orders": 27, "gmv": 3_920_000})
    await _reading(session, run, execution, "final")
    other = await seed_run(
        session, shop, product, lever="title", status="completed", subject_ref="second-run"
    )
    session.add(
        RunWriteValue(
            shop_id=shop.id,
            workflow_run_id=other.id,
            tool_call_id="o1",
            tool_name="update_product_listing",
            tiktok_product_id=PRODUCT_ID,
            field="title",
            before_value="a",
            after_value="b",
            after_source="read_back",
            recorded_at=datetime(2026, 9, 25, 4, 0),
        )
    )
    await session.flush()

    final = (await lever_flows.measure_run(session, shop.id, run))["final"]
    assert final["label"] == "chua_ket_luan"


@pytest.mark.asyncio
async def test_the_final_verdict_is_stored_once_and_calibrates_once(session):
    shop, _product, run, execution = await _listing_run(session)
    await _series(session, shop.id, post={"orders": 26, "gmv": 3_897_000})
    await _reading(session, run, execution, "final")

    first = await lever_flows.measure_run(session, shop.id, run)
    second = await lever_flows.measure_run(session, shop.id, run)

    assert first["final"] == second["final"]
    assert len((await session.execute(select(RunMeasurementFinal))).scalars().all()) == 1
    assert (await session.execute(select(LeverCalibration))).scalar_one().readings == 1


@pytest.mark.asyncio
async def test_a_verified_promotion_is_measured_from_its_start_date(session):
    shop, product = await seed_shop(session)
    run = await seed_run(
        session, shop, product, lever="product_discount", flow_kind="promotion", status="completed"
    )
    flow = (
        await session.execute(select(RunLeverFlow).where(RunLeverFlow.workflow_run_id == run.id))
    ).scalar_one()
    flow.measurement_start = T
    await session.flush()
    await _series(session, shop.id, post={"orders": 27, "gmv": 3_920_000})

    stages = [
        (await lever_flows.measure_run(session, shop.id, run, today=day))["stage"]
        for day in (T + timedelta(days=6), T + timedelta(days=7), T + timedelta(days=14))
    ]
    assert stages == ["waiting", "day7", "final"]
    final = (await lever_flows.measure_run(session, shop.id, run, today=AFTER_DAY14))["final"]
    assert final["label"] == "dat"


# --- not measurable, and the route ---------------------------------------------------------


@pytest.mark.asyncio
async def test_runs_that_changed_nothing_are_not_measurable(session):
    shop, product = await seed_shop(session)
    nothing = await seed_run(session, shop, product, lever="title", status="completed")
    with pytest.raises(lever_flows.NotMeasurable) as raised:
        await lever_flows.measure_run(session, shop.id, nothing)
    assert raised.value.code == "nothing_written"

    other_shop, other_product = await seed_shop(session, "b")
    unverified = await seed_run(
        session, other_shop, other_product, lever="flash_sale", flow_kind="promotion"
    )
    with pytest.raises(lever_flows.NotMeasurable) as raised:
        await lever_flows.measure_run(session, other_shop.id, unverified)
    assert raised.value.code == "not_verified"


@pytest.mark.asyncio
async def test_the_route_serves_its_own_shops_runs_only(engine, session):
    shop_a, _product, run_a, execution = await _listing_run(session, "a")
    await _series(session, shop_a.id, post={"orders": 26}, post_days=7)
    await _reading(session, run_a, execution, "preliminary")
    shop_b, product_b = await seed_shop(session, "b")
    run_b = await seed_run(session, shop_b, product_b, lever="title", status="completed")
    await session.commit()

    async with api_client(engine, shop_a) as client:
        own = await client.get(f"/v1/demo/runs/{run_a.id}/measurement")
    async with api_client(engine, shop_b) as client:
        foreign = await client.get(f"/v1/demo/runs/{run_a.id}/measurement")
        not_measurable = await client.get(f"/v1/demo/runs/{run_b.id}/measurement")

    assert own.status_code == 200, own.text
    assert own.json()["stage"] == "day7"
    assert foreign.status_code == 404
    assert not_measurable.status_code == 409
    assert not_measurable.json()["detail"]["code"] == "nothing_written"
