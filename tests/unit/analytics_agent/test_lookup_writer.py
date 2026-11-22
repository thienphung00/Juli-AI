"""E4 (data answers) and E6 (writer, alignment, sanitiser)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from juli_backend.services.analytics_agent import lookup, writer
from juli_backend.services.analytics_agent.chains import run_chain
from juli_backend.services.analytics_agent.labels import shopee_labels
from tests.unit.analytics_agent.fakes import (
    AS_OF,
    FakeData,
    FakeLLM,
    funnel_data,
    shop_rows,
    source_rows,
)

L = shopee_labels()
PRESET = "last_7d_vs_prev_7d"


# ------------------------------------------------------------------ E4


async def test_metric_total_with_direction_and_freshness() -> None:
    shop = shop_rows(
        AS_OF - timedelta(days=40),
        AS_OF,
        gmv=lambda d: 2_000_000.0 if d > AS_OF - timedelta(days=7) else 1_000_000.0,
    )
    out = await lookup.run_lookup(FakeData(shop), L, "metric_total", "gmv", PRESET, AS_OF)
    assert out["value"] == "14.000.000đ" and out["delta"] == {
        "dir": "up",
        "text_vi": "▲ 100,0%",
    }
    assert out["fresh_vi"] == f"Số liệu đến hết {AS_OF:%d/%m}"
    assert out["type"] == "data_answer" and out["kind"] == "metric_total"
    # the UI renders `value` as text: an object crashed the page (React #31, 22/11)
    assert isinstance(out["value"], str) and out["value_raw"] == 14_000_000.0


async def test_metric_total_money_chain_metric_comes_from_overview() -> None:
    shop = shop_rows(AS_OF - timedelta(days=40), AS_OF, orders=5.0)

    def ov(a: date, b: date) -> dict[str, Any]:
        return {"shop_profit": {"margin_pct": 42.8 if b >= AS_OF else 40.0}}

    out = await lookup.run_lookup(
        FakeData(shop, overview=ov), L, "metric_total", "margin", PRESET, AS_OF
    )
    assert out["value"] == "42,8%" and out["delta"]["dir"] == "up"


async def test_top_products_from_product_rows_top_five() -> None:
    shop = shop_rows(AS_OF - timedelta(days=20), AS_OF, orders=5.0)
    prods = [
        {"day": AS_OF, "item_id": f"p{i}", "gmv": 1000.0 * (i + 1), "orders": i + 1.0, "units": 1.0}
        for i in range(7)
    ]
    out = await lookup.run_lookup(
        FakeData(shop, products=prods, names={"p6": "Sản phẩm G"}),
        L,
        "top_products",
        "gmv",
        PRESET,
        AS_OF,
    )
    assert [r["item_id"] for r in out["rows"]] == ["p6", "p5", "p4", "p3", "p2"]
    assert out["rows"][0]["name"] == "Sản phẩm G" and out["rows"][0]["gmv_vi"] == "7.000đ"
    # the UI row contract (JuliDataRow): rows rendered blank without these keys (22/11)
    first = out["rows"][0]
    assert (first["label_vi"], first["value_vi"]) == ("Sản phẩm G", "7.000đ")
    assert first["link"] == {"kind": "product", "item_id": "p6"} and first["detail_vi"]


async def test_daily_trend_series() -> None:
    shop = shop_rows(AS_OF - timedelta(days=20), AS_OF, orders=lambda d: float(d.day))
    out = await lookup.run_lookup(FakeData(shop), L, "daily_trend", "orders", PRESET, AS_OF)
    assert len(out["series"]) == 7 and out["series"][-1]["value"] == float(AS_OF.day)
    assert out["series"][-1]["label_vi"] == f"{AS_OF:%d/%m}"


async def test_channel_breakdown_labels_and_thieu_du_lieu() -> None:
    shop = shop_rows(AS_OF - timedelta(days=20), AS_OF, orders=5.0)
    srcs = source_rows(AS_OF - timedelta(days=6), AS_OF, "video", views=100, clicks=10, orders=1.0)
    srcs += source_rows(
        AS_OF - timedelta(days=6),
        AS_OF - timedelta(days=4),
        "live",
        views=100,
        clicks=10,
        orders=1.0,
    )
    mv = {
        "channels": [
            {"key": "video", "now": 10.0},
            {"key": "live", "now": 3.0},
            {"key": "trang_shop", "now": None},
            {"key": "o:55", "now": 1.0},
        ]
    }
    out = await lookup.run_lookup(
        FakeData(shop, sources=srcs, mv=mv), L, "channel_breakdown", "orders", PRESET, AS_OF
    )
    rows = {r["channel"]: r for r in out["rows"]}
    assert rows["video"]["label_vi"] == "Video" and rows["video"]["note_vi"] is None
    assert rows["live"]["note_vi"] == "thiếu dữ liệu"  # live has 3 of 7 days
    assert rows["trang_shop"]["value_vi"] == "thiếu dữ liệu"
    assert rows["o:55"]["label_vi"] == "Khác"


async def test_no_shop_rows_is_data_missing() -> None:
    assert (await lookup.run_lookup(FakeData([]), L, "metric_total", "gmv", PRESET, AS_OF))[
        "stop"
    ] == "data_missing"


# ------------------------------------------------------------------ E6 sanitiser


@pytest.mark.parametrize(
    "leak",
    [
        "Tỷ lệ của the_san_pham_khac giảm mạnh",
        "Tỷ lệ chuyển đổi là 101,891404 hôm nay",
        "CTR đạt 0.079365 trong tuần",
        "Lỗi ở sản phẩm 26107129526 trong tuần",
        "hệ thống chưa chấp nhận thẻ này",
        "xem tại https://example.com/a/b",
        "lấy từ metric_view và channel split",
        'kết quả {"a": 1}',
        "the shop was down this week again",
        "Đang tìm hiểu: placeholder",
        "Tôi hiểu: placeholder",
    ],
)
def test_sanitiser_blocks_leaks(leak: str) -> None:
    _, issues = writer.sanitise(leak)
    assert issues, leak


def test_sanitiser_passes_clean_vietnamese_with_app_formats() -> None:
    txt = (
        "Đang tìm hiểu: vì sao đơn giảm. GMV giảm từ 15.251.700đ xuống 8.728.160đ, "
        "biên 42,8%, CTR 3,07%, 12/11–18/11."
    )
    assert writer.sanitise(txt)[1] == []


def test_sanitiser_allows_a_thousands_group_with_one_dot() -> None:
    assert writer.sanitise("AOV giảm từ 183.755đ xuống 150.000đ.")[1] == []


def test_sanitiser_swaps_ids_for_product_names() -> None:
    clean, issues = writer.sanitise(
        "sản phẩm 26107129526 bán chậm", {"26107129526": "Áo A"}, ["Áo A"]
    )
    assert clean == "sản phẩm Áo A bán chậm" and issues == []


async def test_placeholder_explanation_goes_through_rewrite_then_template() -> None:
    good = FIRST + ".\nĐơn giảm vì Video kém."
    for bad in ("Đang tìm hiểu: placeholder\nĐơn giảm.", "Tôi hiểu: placeholder\nĐơn giảm."):
        rec = _Rec()
        text, meta = await writer.write_explanation(
            FakeLLM(text=bad, rewrite=good), rec.d, rec.r, FIRST, [await _chain()], [], L, {}
        )
        assert text == good and meta["rewrites"] == 1 and rec.replaced == [good], bad
        rec2 = _Rec()
        text2, meta2 = await writer.write_explanation(
            FakeLLM(text=bad, rewrite=bad), rec2.d, rec2.r, FIRST, [await _chain()], [], L, {}
        )
        assert meta2["template"] and "placeholder" not in text2.lower()


# ------------------------------------------------------------------ E6 alignment + writer


def test_alignment_requires_product_and_lever_and_blocks_other_actions() -> None:
    acc = [{"ref": "D1", "kind": "voucher_cap", "item_name": "Áo thun cotton"}]
    assert writer.alignment("Nên xem voucher của Áo thun cotton.", acc) == []
    assert any("product" in i for i in writer.alignment("Nên xem voucher.", acc))
    assert any("lever" in i for i in writer.alignment("Áo thun cotton bán chậm.", acc))
    assert any(
        "quảng cáo" in i
        for i in writer.alignment("Áo thun cotton: voucher ổn. Bạn nên tăng quảng cáo.", acc)
    )


async def _chain() -> dict[str, Any]:
    shop, srcs = funnel_data()
    return (await run_chain(FakeData(shop, srcs), "orders_change", "orders", PRESET, AS_OF)).json(L)


class _Rec:
    def __init__(self) -> None:
        self.deltas: list[str] = []
        self.replaced: list[str] = []

    async def d(self, t: str) -> None:
        self.deltas.append(t)

    async def r(self, t: str) -> None:
        self.replaced.append(t)


FIRST = "Đang tìm hiểu: vì sao đơn hàng giảm"


async def test_writer_streams_clean_text_without_replace() -> None:
    llm = FakeLLM(deltas=[FIRST, ".\nĐơn giảm vì Video kém."])
    rec = _Rec()
    text, meta = await writer.write_explanation(
        llm, rec.d, rec.r, FIRST, [await _chain()], [], L, {}
    )
    assert (
        text.startswith("Đang tìm hiểu: ")
        and rec.deltas
        and not rec.replaced
        and not meta["template"]
    )
    assert (
        "ĐƠN" not in llm.stream_calls[0] and "orders_change" not in llm.stream_calls[0]
    )  # pre-formatted, no raw keys


async def test_writer_one_rewrite_via_text_replace_then_template() -> None:
    bad = FIRST + ".\nxem the_san_pham_khac"
    good = FIRST + ".\nĐơn giảm vì Video kém."
    rec = _Rec()
    text, meta = await writer.write_explanation(
        FakeLLM(text=bad, rewrite=good), rec.d, rec.r, FIRST, [await _chain()], [], L, {}
    )
    assert (
        text == good and meta["rewrites"] == 1 and rec.replaced == [good] and not meta["template"]
    )
    rec2 = _Rec()
    text2, meta2 = await writer.write_explanation(
        FakeLLM(text=bad, rewrite=bad), rec2.d, rec2.r, FIRST, [await _chain()], [], L, {}
    )
    assert meta2["template"] and text2.startswith(FIRST) and "the_san_pham_khac" not in text2
    assert "→" in text2 and rec2.replaced[-1] == text2  # metric-formatted template values


async def test_writer_with_accepted_card_needs_product_and_lever() -> None:
    acc = [
        {
            "ref": "D1",
            "kind": "ads_budget",
            "item_name": "Áo thun cotton",
            "kind_vi": "Ngân sách quảng cáo",
        }
    ]
    rec = _Rec()
    ok = FIRST + ".\nNgân sách quảng cáo của Áo thun cotton đang thấp."
    text, meta = await writer.write_explanation(
        FakeLLM(text=ok), rec.d, rec.r, FIRST, [await _chain()], acc, L, {}
    )
    assert text == ok and meta["rewrites"] == 0
