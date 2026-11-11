"""P100 S2-A: the synthetic "Dữ liệu mẫu" shop generator, its safety rules and its path through
the real gateway -> materialize -> Shopee analytics read model (SQLite; the Postgres run is
``tests/integration/test_sample_shop_postgres.py``)."""

from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.models.models import Shop
from juli_backend.models.shopee_metrics import (
    RESIDUAL_ITEM,
    ShopeeProductMetricsDaily,
    ShopeeShopMetricsDaily,
)
from juli_backend.services.ingest.gateway import validate_rows
from juli_backend.services.ingest.mapping import dataset_spec
from juli_backend.services.ingest.schemas import IngestBody
from juli_backend.services.shopee_analytics import queries
from scripts.sample_shop import loader
from scripts.sample_shop.catalog import (
    SAMPLE_SHOPEE_SHOP_ID,
    SAMPLE_SHOPEE_SHOP_ID_MAX,
    SAMPLE_SHOPEE_SHOP_ID_MIN,
)
from scripts.sample_shop.generator import DAYS, generate

END = date(2026, 11, 10)
NOW = datetime(2026, 11, 11, 3, 0)  # naive UTC = 10:00 GMT+7 the day after END
FUJIWA = uuid.UUID("2b1da87b-d0a8-46a6-b3c6-2132be0b5f4f")
SANDBOX = uuid.UUID("1862f13b-de2c-4fae-a4ad-70298cead913")


@pytest.fixture(scope="module")
def sample():
    return generate(END)


def _rows(sample, dataset: str, order_type: str | None = None) -> list[dict]:
    return [
        r
        for p in sample.posts
        if p.dataset == dataset and (order_type is None or p.body.get("order_type") == order_type)
        for r in p.body["rows"]
    ]


def _days(rows: list[dict]) -> set[date]:
    return {date.fromisoformat(r["date"]) for r in rows}


EXPECTED_DAYS = {END - timedelta(days=i) for i in range(DAYS)}


# ======================================================================== generator


def test_the_same_end_date_gives_byte_identical_posts():
    first = json.dumps([(p.dataset, p.body) for p in generate(END).posts], sort_keys=True)
    second = json.dumps([(p.dataset, p.body) for p in generate(END).posts], sort_keys=True)
    assert first == second


def test_thirty_days_end_on_the_end_date_and_every_day_is_present(sample):
    assert DAYS == 30 and sample.end_date == END and sample.start_date == END - timedelta(days=29)
    for dataset, order_type in (
        ("shop_overview", "confirmed"),
        ("shop_traffic", None),
        ("traffic_overview", "confirmed"),
        ("traffic_overview", "placed"),
        ("item_traffic_sources", "confirmed"),
        ("ads_campaign_daily", "placed"),
    ):
        assert _days(_rows(sample, dataset, order_type)) == EXPECTED_DAYS, dataset
    lines = {date.fromisoformat(r["ordered_at"][:10]) for r in _rows(sample, "order_lines")}
    assert lines == EXPECTED_DAYS
    per_item = defaultdict(set)
    for r in _rows(sample, "item_traffic_sources"):
        per_item[r["item_id"]].add(date.fromisoformat(r["date"]))
    assert len(per_item) == 6 and all(d == EXPECTED_DAYS for d in per_item.values())
    for campaign in {r["campaign_id"] for r in _rows(sample, "ads_campaign_daily")}:
        days = {
            date.fromisoformat(r["date"])
            for r in _rows(sample, "ads_campaign_daily")
            if r["campaign_id"] == campaign
        }
        assert days == EXPECTED_DAYS


def test_every_post_passes_the_gateways_own_validation(sample):
    for post in sample.posts:
        spec = dataset_spec("shopee", post.dataset)
        assert spec is not None
        validate_rows(spec, IngestBody.model_validate(post.body), NOW)


def test_six_products_with_one_to_three_variations_and_a_running_two_tier_combo(sample):
    catalog = _rows(sample, "item_catalog")
    items = {r["item_id"] for r in catalog}
    assert len(items) == 6
    for item in items:
        assert 1 <= len([r for r in catalog if r["item_id"] == item and r.get("variation_id")]) <= 3
    promos = _rows(sample, "promotions")
    assert len(promos) == 1 and promos[0]["promo_type"] == "Combo Khuyến Mãi"
    assert promos[0]["extra"]["tier_count"] == 2
    assert datetime.fromisoformat(promos[0]["ends_at"]).date() > END  # still running


def test_product_figures_never_exceed_the_shops_on_any_day(sample):
    shop = {date.fromisoformat(r["date"]): r for r in _rows(sample, "shop_overview")}
    by_day = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for r in _rows(sample, "item_traffic_sources"):
        if r["l2"] != "total":
            continue
        day = date.fromisoformat(r["date"])
        for field in ("orders", "sales", "product_clicks"):
            by_day[(day, r["item_id"])][r["l1"]][field] += r[field]
    streams = {
        (date.fromisoformat(r["date"]), r["source"]): r
        for r in _rows(sample, "traffic_overview", "confirmed")
        if "sub_source" not in r
    }
    l1 = {
        "product_card": "psd_label_product_card",
        "video": "psd_label_seller_video",
        "affiliate": "psd_label_affiliate",
    }
    for (day, _item), per_stream in by_day.items():
        assert sum(s["orders"] for s in per_stream.values()) <= shop[day]["orders"]
        assert sum(s["sales"] for s in per_stream.values()) <= shop[day]["sales"]
        assert sum(s["product_clicks"] for s in per_stream.values()) <= shop[day]["product_clicks"]
        for stream, s in per_stream.items():
            top = streams[(day, l1[stream])]
            assert s["orders"] <= top["orders"] and s["sales"] <= top["sales"]


def test_order_lines_traffic_and_overview_agree_on_orders_and_gmv(sample):
    lines = defaultdict(lambda: {"gmv": 0, "orders": set()})
    for r in _rows(sample, "order_lines"):
        day = date.fromisoformat(r["ordered_at"][:10])
        lines[day]["gmv"] += r["deal_price"] * r["qty"]
        lines[day]["orders"].add(r["order_ref"])
    streams = defaultdict(lambda: {"sales": 0, "orders": 0})
    for r in _rows(sample, "traffic_overview", "confirmed"):
        if "sub_source" not in r:
            day = date.fromisoformat(r["date"])
            streams[day]["sales"] += r["sales"]
            streams[day]["orders"] += r["orders"]
    for r in _rows(sample, "shop_overview"):
        day = date.fromisoformat(r["date"])
        assert r["sales"] == lines[day]["gmv"] == streams[day]["sales"]
        assert r["orders"] == len(lines[day]["orders"]) == streams[day]["orders"]
        assert r["sales_per_order"] == round(r["sales"] / r["orders"])


def test_ads_campaigns_add_up_to_the_shop_ads_row_and_roas_is_sane(sample):
    shop = {date.fromisoformat(r["date"]): r for r in _rows(sample, "traffic_overview", "placed")}
    sums = defaultdict(lambda: defaultdict(int))
    for r in _rows(sample, "ads_campaign_daily"):
        day = date.fromisoformat(r["date"])
        for field, key in (
            ("cost", "ads_expense"),
            ("broad_gmv", "sales"),
            ("broad_order", "orders"),
        ):
            sums[day][key] += r[field]
        assert 3.0 <= r["broad_roi"] <= 12.0
    for day, row in shop.items():
        for key in ("ads_expense", "sales", "orders"):
            assert row[key] == sums[day][key]
        assert 3.0 <= row["sales"] / row["ads_expense"] <= 12.0
    period = _rows(sample, "ads_campaign_period")
    assert sum(r["ads_expense"] for r in period) == sum(r["ads_expense"] for r in shop.values())


def test_units_and_shapes_follow_what_the_connector_posts(sample):
    shop = _rows(sample, "shop_overview")
    for r in shop:
        assert isinstance(r["sales"], int) and 0 < r["conversion_rate"] <= 1
        assert 60_000 <= r["sales_per_order"] <= 450_000  # VND, not thousands
    assert 80_000 <= sum(r["sales"] for r in shop) / sum(r["orders"] for r in shop) <= 280_000
    for r in _rows(sample, "item_traffic_sources"):
        if r["l1"] == "product_card" and r["l2"] == "total":
            assert r["product_impressions"] >= r["product_clicks"] >= r["orders"]
    day_views = defaultdict(int)
    for r in _rows(sample, "item_traffic_sources"):
        if r["l2"] == "total":
            day_views[(r["item_id"], r["date"])] += r["product_impressions"]
    assert all(300 <= v <= 2_000 for v in day_views.values())
    for r in _rows(sample, "traffic_overview", "confirmed"):
        if "ctr" in r:
            assert 0 < r["ctr"] < 1  # a fraction, never a percentage
    assert set(sample.costs) and all(c > 0 for c in sample.costs.values())


def test_no_real_shop_name_or_id_is_in_the_data(sample):
    text = json.dumps([(p.dataset, p.body) for p in sample.posts], ensure_ascii=False).casefold()
    assert not re.search(r"\bory\b|fujiwa|stahaus|1862f13b|2b1da87b", text)


# ======================================================================== safety


def test_the_reserved_range_is_twelve_digits_above_any_real_shopee_id():
    assert SAMPLE_SHOPEE_SHOP_ID_MIN <= SAMPLE_SHOPEE_SHOP_ID <= SAMPLE_SHOPEE_SHOP_ID_MAX
    assert SAMPLE_SHOPEE_SHOP_ID_MIN > 9_999_999_999


@pytest.mark.parametrize("shop_id", [FUJIWA, SANDBOX])
def test_fujiwa_and_the_sandbox_shop_are_refused_by_id(shop_id):
    with pytest.raises(loader.SampleShopRefused, match="never written"):
        loader.check_target(
            shop_id,
            platform="shopee",
            shopee_shop_id=str(SAMPLE_SHOPEE_SHOP_ID),
            has_credentials=False,
        )


@pytest.mark.parametrize(
    ("platform", "shopee_id", "creds", "why"),
    [
        ("tiktok", str(SAMPLE_SHOPEE_SHOP_ID), False, "not a Shopee"),
        ("shopee", "123456789", False, "outside the reserved"),
        ("shopee", None, False, "outside the reserved"),
        ("shopee", str(SAMPLE_SHOPEE_SHOP_ID), True, "holds a credential"),
    ],
)
def test_a_shop_the_loader_did_not_create_is_refused(platform, shopee_id, creds, why):
    with pytest.raises(loader.SampleShopRefused, match=why):
        loader.check_target(
            uuid.uuid4(), platform=platform, shopee_shop_id=shopee_id, has_credentials=creds
        )
    loader.check_target(
        uuid.uuid4(),
        platform="shopee",
        shopee_shop_id=str(SAMPLE_SHOPEE_SHOP_ID),
        has_credentials=False,
    )


def test_a_remote_database_host_needs_the_explicit_flag():
    loader.require_local("postgresql://u:p@127.0.0.1/db", False)
    loader.require_local("postgresql://u:p@localhost/db", False)
    with pytest.raises(loader.SampleShopRefused, match="refusing database host"):
        loader.require_local("postgresql://u:p@db.example.supabase.co/postgres", False)
    loader.require_local("postgresql://u:p@db.example.supabase.co/postgres", True)


def test_the_cli_refuses_a_remote_database_and_writes_nothing(capsys):
    code = loader.main(
        ["--end-date", "2026-11-10", "--database-url", "postgresql://u:p@db.example.com/postgres"]
    )
    assert code == 2 and "refusing database host" in capsys.readouterr().out


def test_dry_run_writes_one_jsonl_file_per_dataset(tmp_path, capsys):
    out = tmp_path / "sample"
    assert loader.main(["--end-date", "2026-11-10", "--dry-run", "--out", str(out)]) == 0
    names = {p.stem for p in out.glob("*.jsonl")}
    assert {
        "order_lines",
        "order_income",
        "shop_overview",
        "item_catalog",
        "promotions",
        "ads_campaign_daily",
        "item_traffic_sources",
        "traffic_overview",
    } <= names
    first = json.loads((out / "shop_overview.jsonl").read_text().splitlines()[0])
    assert first["period"]["end"] == "2026-11-10" and len(first["rows"]) == 30
    assert (out / "shop_inputs_sku_cost.json").exists()


# ================================================== gateway -> materialize -> read model


async def _load(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return factory, await loader.load(factory, generate(END), now=NOW)


async def test_loaded_shop_renders_thirty_days_with_product_within_shop_and_known_profit(engine):
    factory, report = await _load(engine)
    assert report.created and report.days_materialized == DAYS
    async with factory() as session:
        shop = await session.get(Shop, report.shop_id)
        assert shop is not None
        assert (shop.platform, shop.shop_name, shop.shopee_shop_id) == (
            "shopee",
            "Dữ liệu mẫu",
            str(SAMPLE_SHOPEE_SHOP_ID),
        )
        body = await queries.overview(session, report.shop_id, period="30d")
        assert body["data"]["shop_totals"] == {"basis": "daily", "days_covered": 30}
        assert body["data"]["traffic"]["days_covered"] == 30
        sm = body["shop_metrics"]
        assert sm["read_from"] == "tables" and sm["profit"] is not None
        assert sm["profit_is_partial"] is False and sm["margin_pct"] > 0
        assert 3 <= sm["ads_roas_placed"] <= 12
        assert body["flows"]["adds_up"] is True

        days = (
            (
                await session.execute(
                    select(ShopeeShopMetricsDaily).where(
                        ShopeeShopMetricsDaily.shop_id == report.shop_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(days) == 30 and all(d.complete for d in days)
        assert all(d.profit is not None for d in days)
        shop_gmv = {d.day: d.gmv for d in days}
        products = (
            (
                await session.execute(
                    select(ShopeeProductMetricsDaily).where(
                        ShopeeProductMetricsDaily.shop_id == report.shop_id,
                        ShopeeProductMetricsDaily.item_id != RESIDUAL_ITEM,
                    )
                )
            )
            .scalars()
            .all()
        )
        per_day: dict[date, Decimal] = defaultdict(Decimal)
        for p in products:
            per_day[p.day] += p.gmv
            assert p.profit is not None
        assert set(per_day) == set(shop_gmv)
        assert all(per_day[d] <= shop_gmv[d] for d in per_day)

        matrix = await queries.matrix(session, report.shop_id, period="30d")
        assert len(matrix["products"]) == 6
        assert all(p["profit"]["profit"] is not None for p in matrix["products"])
        page = await queries.product_page(
            session, report.shop_id, matrix["products"][0]["product_id"], period="30d"
        )
        assert page["header"]["title"] and page["kpi_by_period"]["7d"]["gmv"]["value"]
        critical = await queries.critical(session, report.shop_id, period="30d")
        assert critical["items"]


async def test_the_screens_hide_the_comparison_when_there_is_no_earlier_period(engine):
    factory, report = await _load(engine)
    async with factory() as session:
        body = await queries.overview(session, report.shop_id, period="30d")
    assert [w["code"] for w in body["warnings"]] == ["previous_period_thin"]
    assert body["kpi_strip"]["gmv"]["previous"] is None
    assert body["kpi_strip"]["gmv"]["change_pct"] is None


async def test_loading_again_is_idempotent(engine):
    factory, first = await _load(engine)
    async with factory() as session:
        before = await queries.overview(session, first.shop_id, period="30d")
        count_before = await session.scalar(
            select(func.count()).select_from(ShopeeProductMetricsDaily)
        )
    second = await loader.load(factory, generate(END), now=NOW)
    assert second.shop_id == first.shop_id and not second.created
    assert set(second.outcome) == {"duplicate"}
    async with factory() as session:
        after = await queries.overview(session, first.shop_id, period="30d")
        assert await session.scalar(select(func.count()).select_from(Shop)) == 1
        assert (
            await session.scalar(select(func.count()).select_from(ShopeeProductMetricsDaily))
            == count_before
        )
    assert after["shop_metrics"]["gmv"] == before["shop_metrics"]["gmv"]
    assert after["shop_metrics"]["profit"] == before["shop_metrics"]["profit"]


async def test_an_existing_shop_that_is_not_a_sample_shop_is_never_written(engine, tenant):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    other = await _shop_with_shopee_id(factory, "123456789")
    with pytest.raises(loader.SampleShopRefused, match="outside the reserved"):
        await loader.load(factory, generate(END), shop_id=other, now=NOW)
    for forbidden in (FUJIWA, SANDBOX):
        with pytest.raises(loader.SampleShopRefused, match="never written"):
            await loader.load(factory, generate(END), shop_id=forbidden, now=NOW)


async def test_a_future_end_date_is_refused_before_anything_is_written(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    with pytest.raises(loader.SampleShopRefused, match="future"):
        await loader.load(factory, generate(date(2026, 11, 20)), now=NOW)
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Shop)) == 0


async def _shop_with_shopee_id(factory, shopee_id: str) -> uuid.UUID:
    from juli_backend.database import User
    from juli_backend.services.ingest import connect_shopee_shop

    async with factory() as session:
        user = User(id=uuid.uuid4(), phone=None)
        session.add(user)
        await session.flush()
        shop = await connect_shopee_shop(
            session, user_id=user.id, shop_name="Cửa hàng khác", shopee_shop_id=shopee_id
        )
        await session.commit()
        return shop.id
