"""Shop diagnosis scripts (ADR-108 d.13): the read-only fetch and the offline build.

The fetch runs against a recording fake of the production-read resources — no
network, no credentials. The build runs on a synthetic snapshot.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

from tests.support.shop_diagnosis import (
    END,
    Block,
    DayRow,
    a34_row,
    window_days,
    write_snapshot,
)

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Analytics:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls

    def list_product_performance_all(self, *, start_date_ge: str, end_date_lt: str) -> list[dict]:
        self.calls.append(("a34", start_date_ge, end_date_lt))
        return [a34_row(DayRow("p1", card=Block(100, 10, 2, 1, 150_000)))]

    def list_live_performance_all(self, *, start_date_ge: str, end_date_lt: str) -> list[dict]:
        self.calls.append(("live", start_date_ge, end_date_lt))
        return [{"id": "L1", "title": "LIVE", "sales_performance": {"gmv": {"amount": "5"}}}]

    def get_live_products_performance(self, *, live_id: str) -> dict:
        self.calls.append(("live_products", live_id))
        return {"data": {"products": [{"id": "p1", "sales": {"sku_orders": 2}}]}}

    def list_video_performance_all(self, **kwargs: str) -> list[dict]:
        self.calls.append(("videos", kwargs["start_date_ge"], kwargs["end_date_lt"]))
        return []

    def get_video_products_performance(self, **kwargs: str) -> dict:
        raise AssertionError("no video was listed")


class _Promotion:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls

    def search_activities_all(self, *, status: str) -> list[dict]:
        self.calls.append(("activities", status))
        if status == "DEACTIVATED":
            raise ValueError("status not supported")
        return (
            [{"id": f"a-{status}", "begin_time": 1, "end_time": 0}] if status == "ONGOING" else []
        )

    def search_coupons_all(self) -> list[dict]:
        return [{"id": "c1"}]

    def get_activity(self, activity_id: str) -> dict:
        self.calls.append(("activity", activity_id))
        return {"data": {"products": [{"id": "p1"}]}}


class _Orders:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls

    def search_all(self, *, create_time_from: int, create_time_to: int) -> list[dict]:
        self.calls.append(("orders", create_time_from, create_time_to))
        return []


class _Products:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls

    def get_details(self, product_id: str) -> dict:
        self.calls.append(("product", product_id))
        return {"data": {"id": product_id, "title": "Sản phẩm"}}


class FakeResources:
    """Records every call; exposes only read methods, like the guarded client."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.analytics = _Analytics(self.calls)
        self.promotion = _Promotion(self.calls)
        self.orders = _Orders(self.calls)
        self.products = _Products(self.calls)


@pytest.fixture
def fetch() -> ModuleType:
    return _load("shop_diagnosis_fetch")


def test_fetch_writes_the_snapshot_and_skips_days_on_disk(tmp_path: Path, fetch) -> None:
    folder = tmp_path / "snap"
    end = date(2026, 10, 6)
    existing = folder / "daily" / f"a34_{end.isoformat()}.json"
    existing.parent.mkdir(parents=True)
    existing.write_text(json.dumps({"day": end.isoformat(), "products": []}))
    resources = FakeResources()

    meta = fetch.fetch_snapshot(resources, folder, end, "Shop A", sleep_s=0)

    a34_days = [c[1] for c in resources.calls if c[0] == "a34"]
    assert len(a34_days) == fetch.DAYS - 1
    assert end.isoformat() not in a34_days
    assert min(a34_days) == (end - timedelta(days=fetch.DAYS - 1)).isoformat()
    assert meta["new_daily_files"] == fetch.DAYS - 1
    assert len(list((folder / "daily").glob("a34_*.json"))) == fetch.DAYS
    # Orders by create time cover the 60 days in slices.
    order_calls = [c for c in resources.calls if c[0] == "orders"]
    assert order_calls and order_calls[0][1] < order_calls[-1][2]
    # One rejected activity status is recorded and the others are kept.
    assert (folder / "promotions" / "_error_deactivated.json").exists()
    activities = json.loads((folder / "promotions" / "activities.json").read_text())
    assert [a["id"] for a in activities["activities"]] == ["a-ONGOING"]
    assert ("activity", "a-ONGOING") in resources.calls
    assert (folder / "live" / "products" / "L1.json").exists()
    assert (folder / "products" / "p1.json").exists()
    assert json.loads((folder / "meta.json").read_text())["end"] == end.isoformat()

    again = FakeResources()
    assert fetch.fetch_snapshot(again, folder, end, "Shop A", sleep_s=0)["new_daily_files"] == 0
    assert not [c for c in again.calls if c[0] == "a34"]
    assert not [c for c in again.calls if c[0] == "product"]


def test_fetch_defaults(fetch) -> None:
    # 2026-10-07 18:00 UTC is already 2026-10-08 in UTC+7, so yesterday is 10-07.
    assert fetch.yesterday_local(datetime(2026, 10, 7, 18, tzinfo=UTC)) == date(2026, 10, 7)
    assert fetch.slug("Fujiwa Vietnam Store!") == "fujiwa-vietnam-store"
    assert str(fetch.SNAPSHOT_ROOT).startswith(str(Path.home()))


class _RateLimited(Exception):
    """Shaped like the client's API error: TikTok code 36009002, "Too many requests"."""

    code = 36009002

    def __init__(self) -> None:
        super().__init__("[36009002] Too many requests")


class _CouponsFlaky(_Promotion):
    """Coupon search throttles ``failures`` times, then answers."""

    def __init__(self, calls: list[tuple], failures: int) -> None:
        super().__init__(calls)
        self.failures = failures

    def search_coupons_all(self) -> list[dict]:
        self.calls.append(("coupons",))
        if self.failures > 0:
            self.failures -= 1
            raise _RateLimited()
        return [{"id": "c1"}]


def _promotions(fetch, resources, folder: Path, sleeps: list[float]) -> None:
    fetch.fetch_promotions(
        resources,
        folder,
        "2026-08-08",
        "2026-10-07",
        sleep_s=0,
        backoff_sleep=sleeps.append,
    )


def test_throttled_coupons_do_not_stop_activities_or_details(tmp_path: Path, fetch) -> None:
    resources = FakeResources()
    resources.promotion = _CouponsFlaky(resources.calls, failures=99)
    sleeps: list[float] = []

    _promotions(fetch, resources, tmp_path, sleeps)

    target = tmp_path / "promotions"
    assert sleeps == [2, 4, 8]
    assert (target / "_error_coupons.json").exists()
    assert not (target / "coupons.json").exists()
    assert json.loads((target / "activities.json").read_text())["activities"]
    assert "a-ONGOING" in json.loads((target / "activity_details.json").read_text())
    assert not (target / "_error_activities.json").exists()
    assert not (target / "_error_details.json").exists()


def test_a_throttled_call_is_retried_with_exponential_backoff(tmp_path: Path, fetch) -> None:
    resources = FakeResources()
    resources.promotion = _CouponsFlaky(resources.calls, failures=2)
    sleeps: list[float] = []

    _promotions(fetch, resources, tmp_path, sleeps)

    target = tmp_path / "promotions"
    assert sleeps == [2, 4]
    assert json.loads((target / "coupons.json").read_text()) == {"coupons": [{"id": "c1"}]}
    assert not (target / "_error_coupons.json").exists()


def test_failures_other_than_throttling_are_not_retried(tmp_path: Path, fetch) -> None:
    class Broken(_Promotion):
        def search_coupons_all(self) -> list[dict]:
            raise ValueError("bad request")

    resources = FakeResources()
    resources.promotion = Broken(resources.calls)
    sleeps: list[float] = []

    _promotions(fetch, resources, tmp_path, sleeps)

    assert sleeps == []
    assert (tmp_path / "promotions" / "_error_coupons.json").exists()
    assert (tmp_path / "promotions" / "activity_details.json").exists()


def test_a_failing_activity_detail_does_not_lose_the_others(tmp_path: Path, fetch) -> None:
    class OneBadDetail(_Promotion):
        def search_activities_all(self, *, status: str) -> list[dict]:
            if status == "ONGOING":
                return [{"id": "a1", "begin_time": 1, "end_time": 0}, {"id": "a2", "begin_time": 1}]
            return []

        def get_activity(self, activity_id: str) -> dict:
            if activity_id == "a1":
                raise ValueError("gone")
            return {"data": {"products": []}}

    resources = FakeResources()
    resources.promotion = OneBadDetail(resources.calls)

    _promotions(fetch, resources, tmp_path, [])

    target = tmp_path / "promotions"
    assert list(json.loads((target / "activity_details.json").read_text())) == ["a2"]
    assert (target / "_error_details.json").exists()


def _snapshot(folder: Path) -> Path:
    daily = {
        day: [DayRow(f"p{n}", card=Block(100, 10, 2, 1 + n, 100_000 * (n + 1))) for n in range(6)]
        for day in window_days()
    }
    return write_snapshot(folder, daily, orders=[])


def test_build_writes_three_files_with_the_given_ranking(tmp_path: Path) -> None:
    build = _load("shop_diagnosis_report")
    snapshot = _snapshot(tmp_path / "snap")

    def no_prompt(_: str) -> str:
        raise AssertionError("--ranking was given; nothing should be asked")

    assert build.main([str(snapshot), "--ranking", "30d", "--end", END.isoformat()], no_prompt) == 0

    data = json.loads((snapshot / "report.json").read_text())
    assert data["ranking"] == "30d"
    assert "Bước 1" in (snapshot / "report.html").read_text()
    assert (snapshot / "message.md").read_text().startswith("# Gửi")


def test_build_asks_the_ranking_and_defaults_to_sixty_days(tmp_path: Path) -> None:
    build = _load("shop_diagnosis_report")
    snapshot = _snapshot(tmp_path / "snap")
    out = tmp_path / "out"
    prompts: list[str] = []

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return ""

    assert build.main([str(snapshot), "--out", str(out)], answer) == 0
    assert len(prompts) == 1 and "60 ngày" in prompts[0]
    assert json.loads((out / "report.json").read_text())["ranking"] == "60d"
    assert build.ask_ranking(lambda _: "2") == "30d"
