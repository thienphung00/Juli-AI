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
    # the catalogue is read three times (start, title change, end): count each variation once
    catalog = list(
        {(r["item_id"], r.get("variation_id")): r for r in _rows(sample, "item_catalog")}.values()
    )
    items = {r["item_id"] for r in catalog}
    assert len(items) == 6
    for item in items:
        assert 1 <= len([r for r in catalog if r["item_id"] == item and r.get("variation_id")]) <= 3
    promos = [r for r in _rows(sample, "promotions") if r["promo_type"] != "Voucher"]
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


# ================================================== Quyết định: the decision-card history


def _post_rows(sample, dataset):
    return [
        (p.body["captured_at"], r)
        for p in sample.posts
        if p.dataset == dataset
        for r in p.body["rows"]
    ]


def test_the_title_changes_in_the_catalogue_reads_old_before_and_new_after(sample):
    change = sample.title_change
    assert change is not None and change.applied_on == END - timedelta(days=5)
    assert len(change.new) <= 100 and change.old != change.new
    names = [
        (at, r["item_name"])
        for at, r in _post_rows(sample, "item_catalog")
        if r["item_id"] == change.item_id and "variation_id" not in r
    ]
    assert [n for _, n in names] == [change.old, change.new, change.new]
    assert names[0][0] < names[1][0] < names[2][0]
    applied = datetime.fromisoformat(names[1][0]).date()
    assert applied == change.applied_on


def test_the_voucher_is_in_the_settings_and_the_results_and_its_window_closed_before_the_end(
    sample,
):
    v = sample.voucher
    assert v is not None and v.ends_on < END - timedelta(days=7)
    settings = _post_rows(sample, "voucher_settings")
    assert [r["current_usage"] for _, r in settings] == [0, v.used_orders]
    assert {r["voucher_id"] for _, r in settings} == {v.voucher_id}
    assert (
        settings[0][1]["min_spend"] == v.min_spend and settings[0][1]["discount_amount"] == v.value
    )
    ((_, result),) = [
        (at, r) for at, r in _post_rows(sample, "promotions") if r["promo_type"] == "Voucher"
    ]
    assert result["orders"] == v.used_orders and result["extra"]["usage_rate"] == round(
        v.usage_rate, 4
    )
    assert result["extra"]["voucher_cost"] == v.cost == v.used_orders * v.value


def test_the_orders_in_the_voucher_window_carry_the_voucher_and_nowhere_else(sample):
    v = sample.voucher
    assert v is not None and 0 < v.used_orders < v.qualifying_orders
    lines = [r for _, r in _post_rows(sample, "order_lines")]

    def day(r):
        return date.fromisoformat(r["ordered_at"][:10])

    in_window = [r for r in lines if v.starts_on < day(r) <= v.ends_on]
    shares = {r["order_ref"]: 0 for r in in_window}
    for r in in_window:
        shares[r["order_ref"]] += r["shop_voucher_share"]
    assert sum(1 for s in shares.values() if s == v.value) >= v.used_orders
    # the minimum is respected: a used voucher sits on an order of at least min_spend
    totals: dict[str, int] = defaultdict(int)
    for r in in_window:
        totals[r["order_ref"]] += r["original_price"] * r["qty"]
    assert all(totals[ref] >= v.min_spend for ref, s in shares.items() if s == v.value)


def test_the_keywords_the_title_audit_is_held_against_are_for_real_products(sample):
    from scripts.sample_shop.catalog import PRODUCTS

    assert sample.keywords and {i for i, _ in sample.keywords} <= {p.item_id for p in PRODUCTS}


async def test_every_decision_tab_has_a_card_after_the_load_and_a_rerun_adds_none(engine):
    from juli_backend.database.tenant_context import with_shop_scope
    from juli_backend.models.card_events import EVENT_IMPACT_FINAL, CardEvent
    from juli_backend.services.shopee_recommendations import service

    factory, first = await _load(engine)
    assert first.decisions is not None and not first.decisions.skipped

    async def cards():
        async with factory() as session:
            async with with_shop_scope(session, first.shop_id):
                out = await service.list_cards(
                    session, first.shop_id, audience="seller", queue="all", now=NOW
                )
                finals = (
                    (
                        await session.execute(
                            select(CardEvent).where(CardEvent.event_type == EVENT_IMPACT_FINAL)
                        )
                    )
                    .scalars()
                    .all()
                )
                return out["cards"], finals

    listed, finals = await cards()
    open_kinds = {c["change_kind"] for c in listed if c["status"] == "sent"}
    assert {"title", "cover_image", "min_spend_voucher"} <= open_kinds
    assert [c["change_kind"] for c in listed if c["status"] == "approved"] == ["cover_image"]
    running = [c for c in listed if c["status"] == "executed"]
    assert [c["change_kind"] for c in running] == ["title"]
    assert running[0]["verification"]["state"] == "verified"
    measured = [c for c in listed if c["status"] == "measured"]
    assert [c["change_kind"] for c in measured] == ["min_spend_voucher"]
    assert len(finals) == 1 and finals[0].payload["impact_pct"] is not None
    again = await loader.load(factory, generate(END), now=NOW)
    assert again.decisions is not None and again.decisions.skipped
    assert len((await cards())[0]) == len(listed)


# -- P100 S2-G: the decision seeding lives in the backend (no backend import of scripts/) ---------


def test_the_backend_plan_is_the_generators_plan(sample):
    from juli_backend.services.sample_shop.seed import plan_for
    from scripts.sample_shop.decisions import plan_of

    assert plan_for(END) == plan_of(sample)
    assert plan_for(END, days=10).voucher is None


def test_the_backend_never_imports_scripts():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "backend" / "src" / "juli_backend"
    offenders = [
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if re.search(r"^\s*(from|import)\s+scripts\b", p.read_text(encoding="utf-8"), re.M)
    ]
    assert offenders == []


async def test_seeding_in_one_transaction_after_the_late_reads_makes_the_loaders_cards(engine):
    """``seed.seed_all`` (one session, the Connector's later reads already in) gives the cards the
    loader's step-by-step run gives: the base of a future in-app "Đặt lại dữ liệu mẫu"."""
    from unittest import mock

    from juli_backend.database.tenant_context import with_shop_scope
    from juli_backend.models.card_events import EVENT_IMPACT_FINAL, CardEvent
    from juli_backend.services.sample_shop.seed import plan_for, seed_all
    from juli_backend.services.shopee_recommendations import service
    from scripts.sample_shop import decisions

    async def late_only(*_args, ingest_late, **_kwargs):
        await ingest_late()
        return decisions.DecisionsReport(skipped=True)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    with mock.patch.object(decisions, "run", late_only):
        report = await loader.load(factory, generate(END), now=NOW)
    async with factory() as session:
        async with with_shop_scope(session, report.shop_id):
            shop = await session.get(Shop, report.shop_id)
            assert shop is not None
            made = await seed_all(
                session, report.shop_id, plan_for(END), user_id=shop.user_id, now=NOW
            )
            await session.commit()
    assert not made.skipped and made.approved == 1 and made.measured == 1
    async with factory() as session:
        async with with_shop_scope(session, report.shop_id):
            listed = (
                await service.list_cards(
                    session, report.shop_id, audience="seller", queue="all", now=NOW
                )
            )["cards"]
            finals = (
                (
                    await session.execute(
                        select(CardEvent).where(CardEvent.event_type == EVENT_IMPACT_FINAL)
                    )
                )
                .scalars()
                .all()
            )
    assert {"title", "cover_image", "min_spend_voucher"} <= {
        c["change_kind"] for c in listed if c["status"] == "sent"
    }
    assert [c["change_kind"] for c in listed if c["status"] == "approved"] == ["cover_image"]
    running = [c for c in listed if c["status"] == "executed"]
    assert [c["change_kind"] for c in running] == ["title"]
    assert running[0]["verification"]["state"] == "verified"
    assert [c["change_kind"] for c in listed if c["status"] == "measured"] == ["min_spend_voucher"]
    assert len(finals) == 1 and finals[0].payload["impact_pct"] is not None


# -- P100 S2-D: the pre-written titles, banners and style profile ---------------------------------


async def test_the_load_seeds_the_card_content_and_every_title_passes_the_live_screen(engine):
    """One style profile, 3 titles per product, a banner per open voucher / cover card -- all
    ``seeded``, no LLM; each stored title passes ``drafts.screen_titles`` against the product's
    facts with its "Chính" keyword ticked; a re-load adds none."""
    from juli_backend.database.tenant_context import with_shop_scope
    from juli_backend.models.card_content_specs import (
        SOURCE_SEEDED,
        SPEC_BANNER,
        SPEC_STYLE_PROFILE,
        SPEC_TITLE,
        CardContentSpec,
    )
    from juli_backend.services.sample_shop.catalog import KEYWORDS, PRODUCTS
    from juli_backend.services.shopee_builder import drafts
    from juli_backend.services.shopee_builder import service as builder
    from juli_backend.services.shopee_recommendations import store

    factory, first = await _load(engine)
    assert first.decisions is not None and first.decisions.content_specs == 1 + 6 + 3

    async def specs():
        async with factory() as session:
            async with with_shop_scope(session, first.shop_id):
                return (await session.execute(select(CardContentSpec))).scalars().all()

    rows = await specs()
    assert {r.source for r in rows} == {SOURCE_SEEDED} and {r.shop_id for r in rows} == {
        first.shop_id
    }
    assert all(r.llm_call_id is None and len(r.inputs_hash) == 64 for r in rows)
    by_type: dict[str, list[CardContentSpec]] = defaultdict(list)
    for r in rows:
        by_type[r.spec_type].append(r)
    (profile,) = by_type[SPEC_STYLE_PROFILE]
    assert profile.item_id is None and profile.proposal_id is None
    palette = set(profile.spec["palette"])
    assert 3 <= len(palette) <= 5
    assert {c["item_id"] for c in profile.spec["covers_seen"]} == {p.item_id for p in PRODUCTS}

    titles = {r.item_id: r for r in by_type[SPEC_TITLE]}
    assert set(titles) == {p.item_id for p in PRODUCTS}
    kws = {PRODUCTS[i].item_id: kw for i, kw in KEYWORDS}
    async with factory() as session:
        async with with_shop_scope(session, first.shop_id):
            for item_id, row in titles.items():
                _, facts = await builder.draft_facts(
                    session, first.shop_id, item_id, as_of=END, now=NOW
                )
                ticked = [kws[item_id]] if item_id in kws else []
                items = [{"title": c["title"]} for c in row.spec["candidates"]]
                passed, dropped = drafts.screen_titles(items, facts, ticked)
                assert len(passed) == 3, (item_id, dropped)
            open_cards = {
                p.id: c["change_kind"]
                for p, c in await store.list_cards(
                    session, first.shop_id, statuses=["sent", "approved"]
                )
                if c["change_kind"] in ("cover_image", "min_spend_voucher")
            }

    banners = by_type[SPEC_BANNER]
    assert {r.proposal_id for r in banners} == set(open_cards)
    positions = {"ngang": {"top"}, "goc": {"top_left", "top_right"},
                 "the": {"middle_right", "bottom_right"}}  # fmt: skip
    for r in banners:
        assert r.spec["size_px"] == 1200 and len(r.spec["banners"]) <= 3
        for b in r.spec["banners"]:
            assert b["position"] in positions[b["shape"]] and b["colour"] in palette
            assert set(b["sources"]) == set(b["values"])
            assert all(v is not None for v in b["values"].values())
        if open_cards[r.proposal_id] == "min_spend_voucher":
            (voucher,) = [b for b in r.spec["banners"] if b["kind"] == "voucher"]
            assert isinstance(voucher["values"]["value"], int)
            assert isinstance(voucher["values"]["min_spend"], int)
            assert all(s["card_id"] == str(r.proposal_id) for s in voucher["sources"].values())

    again = await loader.load(factory, generate(END), now=NOW)
    assert again.decisions is not None and again.decisions.content_specs == 0
    assert len(await specs()) == len(rows)


async def test_the_sample_shop_holds_the_llm_consent_and_a_reload_restores_it(engine):
    """P100 S2-D2: the one live AI title draft passes the LLM gate (``llm_processing``); a shop
    loaded before S2-D2 (``service`` only) gets the grant on its next load."""
    from juli_backend.services.consent import has_consent
    from juli_backend.services.consent.grants import revoke_consent

    factory, first = await _load(engine)
    async with factory() as session:
        for scope in loader.SAMPLE_CONSENT_SCOPES:
            assert await has_consent(session, first.shop_id, scope), scope
        await revoke_consent(session, first.shop_id, "llm_processing", revoked_at=NOW)
        await session.commit()
        assert not await has_consent(session, first.shop_id, "llm_processing")
    again = await loader.load(factory, generate(END), now=NOW)
    assert again.shop_id == first.shop_id and not again.created
    async with factory() as session:
        assert await has_consent(session, first.shop_id, "llm_processing")
        assert await has_consent(session, first.shop_id, "service")


async def test_the_s2_d2_strategies_evaluate_on_the_sample_shop(engine):
    """P100 S2-D2 (owner option B): the real Tự tạo works on the sample shop's data -- Combo Khuyến
    Mãi, Deal Sốc (Mua kèm / Mua để nhận quà), Dịch vụ hiển thị (a new campaign and an edit of a
    running one, P100 B.15) and Affiliate each give a result, and "Chọn" saves a card."""
    from juli_backend.database.tenant_context import with_shop_scope
    from juli_backend.services.sample_shop.catalog import PRODUCTS
    from juli_backend.services.shopee_builder import service as builder
    from juli_backend.services.shopee_recommendations.manual import Actor
    from tests.unit.test_shopee_builder import S

    factory, report = await _load(engine)
    actor = Actor("seller", uuid.uuid4())
    a, b = PRODUCTS[0].item_id, PRODUCTS[1].item_id
    async with factory() as session:
        async with with_shop_scope(session, report.shop_id):
            camps = await builder.ads_campaigns(session, report.shop_id, as_of=END, now=NOW)
            assert camps["campaigns"], "the sample shop has running Dịch vụ hiển thị campaigns"
            key = camps["campaigns"][0]["campaign_key"]
            versions = {
                "combo": {
                    "kind": "combo",
                    "item_ids": [a, b],
                    "discount_type": "pct",
                    "tiers": [{"qty": 2, "value": 5}, {"qty": 3, "value": 8}],
                },
                "add_on": {
                    "kind": "add_on",
                    "main_item_id": a,
                    "addons": [{"item_id": b, "pct": 10}],
                },
                "gift": {
                    "kind": "gift",
                    "gift": {"unit_cost": 5000},
                    "trigger": {"type": "buy_item", "item_id": a},
                },
                "ads_new": {
                    "kind": "ads_new",
                    "campaign": "single",
                    "item_ids": [a],
                    "daily_budget": 100_000,
                    "start": END.isoformat(),
                },
                "ads_edit": {
                    "kind": "ads",
                    "lever": "budget",
                    "campaign_key": key,
                    "daily_budget": 300_000,
                },
                "affiliate": {"kind": "affiliate", "item_id": a, "commission_pct": 8},
            }
            saved_kinds: dict[str, str] = {}
            for name, version in versions.items():
                out = await builder.evaluate_versions(
                    session, report.shop_id, [S(**version)], as_of=END, now=NOW
                )
                v = out["versions"][0]
                assert v["ok"], (name, v.get("refusal"))
                assert v["result"] is not None and v["result"]["days"] >= 1, name
                # "Chọn" saves the card the reviewer then approves, like a real seller
                async with session.begin_nested() as nested:
                    saved = await builder.choose(
                        session, report.shop_id, [S(**version)], 0, primary=False,
                        acknowledge_breaches=True, actor=actor, as_of=END, now=NOW,
                    )  # fmt: skip
                    saved_kinds[name] = saved["card"]["change_kind"]
                    await nested.rollback()
            assert saved_kinds["ads_edit"] == "ads_budget"
            assert saved_kinds["ads_new"] == "ads_new_campaign"
