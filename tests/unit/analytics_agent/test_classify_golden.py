"""Golden routing of the 20-question check (chat-eval/questions.txt): a fake parser output and a
fake Jev per question, `classify()` outcomes pinned. No data reads, no paid calls."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from juli_backend.services.analytics_agent import routing
from tests.unit.analytics_agent.fakes import FakeJev, FakeLLM
from tests.unit.analytics_agent.test_cards import ch, nl
from tests.unit.analytics_agent.test_routing import ans, intent

TODAY = date(2026, 11, 23)
CREATE = {
    "card_type": None,
    "from_date": None,
    "to_date": None,
    "amount": None,
    "amount_unit": None,
    "min_spend": None,
    "quantity": None,
    "name": None,
}


def it(**kw: Any) -> dict[str, Any]:
    return intent(**{**CREATE, **kw})


# (question, parser intent, jev answers, expected subset of the classify row)
ROWS: list[tuple[str, Any, Any, Any]] = [
    (
        "Tôi muốn lập voucher cho ngày 24 và 25/11.",
        it(
            question_type="create_card",
            metric_phrase=None,
            card_type="voucher",
            from_date="2026-11-24",
            to_date="2026-11-25",
        ),
        {},
        {"mode": "create", "outcome": "go", "card_type": "voucher"},
    ),
    (
        "Tuần trước doanh thu bao nhiêu?",
        it(
            question_type="status",
            metric_phrase="doanh thu (revenue)",
            time_phrase="tuần trước (last week)",
        ),
        ans(fits=nl(0.55), mode=ch("lookup"), metric=ch("gmv")),
        {
            "outcome": "go",
            "mode": "lookup",
            "metric": "gmv",
            "window": "last_full_week_vs_week_before",
        },
    ),
    (
        "Vì sao đơn hàng tuần trước giảm?",
        it(question_type="why_changed", metric_phrase="orders", time_phrase="last week"),
        ans(),
        {
            "outcome": "go",
            "mode": "why",
            "chain": "orders_change",
            "window": "last_full_week_vs_week_before",
        },
    ),
    (
        "Chi phí quảng cáo tuần trước là bao nhiêu?",
        it(question_type="status", metric_phrase="chi phí quảng cáo", time_phrase="tuần trước"),
        ans(fits=nl(0.66), mode=ch("lookup")),
        {
            "outcome": "go",
            "mode": "lookup",
            "metric": "ads_spend",
            "window": "last_full_week_vs_week_before",
        },
    ),
    (
        "Chiến dịch quảng cáo nào đang lỗ?",
        it(
            question_type="status",
            metric_phrase="which ad campaigns are losing money",
            entity_phrase="ad campaign",
            time_phrase=None,
            raw_text="Chiến dịch quảng cáo nào đang lỗ?",
        ),
        ans(fits=nl(0.6), mode=ch("lookup")),
        {"outcome": "go", "entity": "campaign"},
    ),
    (
        "Tuần này có bao nhiêu đơn dùng voucher?",
        it(
            question_type="status",
            metric_phrase="orders",
            entity_phrase="voucher",
            time_phrase="this week",
        ),
        ans(mode=ch("lookup")),
        {
            "outcome": "go",
            "entity": "voucher",
            "metric": "orders",
            "window": "this_week_vs_same_days_last_week",
        },
    ),
    (
        "Đơn từ tiếp thị liên kết 7 ngày qua là bao nhiêu?",
        it(
            question_type="status",
            metric_phrase="orders",
            source_phrase="Tiếp thị liên kết",
            time_phrase="last 7 days",
        ),
        ans(mode=ch("lookup")),
        {"outcome": "go", "entity": "affiliate", "window": "last_7d_vs_prev_7d"},
    ),
    (
        "Lợi nhuận của găng tay siêu dai tháng này?",
        it(
            question_type="status",
            metric_phrase="profit",
            product_phrase="găng tay siêu dai",
            time_phrase="this month",
        ),
        ans(mode=ch("lookup"), scope=ch("product"), product_named=nl(0.9)),
        {"outcome": "go", "metric": "profit", "window": "mtd_vs_same_days_last_month"},
    ),
    (
        "Sản phẩm nào giảm mạnh nhất tuần trước và vì sao?",
        [  # the parser splits "what" and "why" into two intents (prompt rule)
            it(
                question_type="status",
                metric_phrase=None,
                ranking="decline",
                time_phrase="last week",
            ),
            it(question_type="why_changed", metric_phrase="revenue", time_phrase="last week"),
        ],
        lambda st, q: (
            ans(fits=nl(0.5), mode=ch("lookup"), lookup=ch("top_products"))
            if st["intent"]["question_type"] == "status"
            else ans()
        ),
        [
            {"outcome": "go", "lookup": "top_decliners", "window": "last_full_week_vs_week_before"},
            {"outcome": "go", "window": "last_full_week_vs_week_before"},
        ],
    ),
    (
        "Chi phí quảng cáo tuần trước là bao nhiêu? (parser wrote a Vietnamese phrase)",
        it(
            question_type="status",
            metric_phrase="Quảng cáo",
            metric_key="cost_ads",
            time_phrase="tuần trước",
        ),
        ans(fits=nl(0.43), mode=ch("lookup")),
        {"outcome": "go", "mode": "lookup", "metric": "ads_spend"},
    ),
    (
        "Sản phẩm nào bán chạy nhất tuần trước?",
        it(
            question_type="status",
            metric_phrase="Sản phẩm bán",
            metric_key="units",
            ranking="top",
            claimed_direction="up",
            time_phrase="last week",
        ),
        ans(fits=nl(0.66), mode=ch("lookup"), lookup=ch("top_products")),
        {"outcome": "go", "lookup": "top_products", "window": "last_full_week_vs_week_before"},
    ),
    (
        "Sản phẩm nào giảm mạnh nhất tuần trước và vì sao? (one intent)",
        it(
            question_type="status",
            metric_phrase=None,
            ranking="decline",
            asks_why=True,
            time_phrase="last week",
        ),
        ans(fits=nl(0.5), mode=ch("lookup"), lookup=ch("top_products")),
        {"outcome": "go", "lookup": "top_decliners", "window": "last_full_week_vs_week_before"},
    ),
    (
        "Tuần sau shop nên làm gì?",
        it(question_type="plan", metric_phrase=None, time_phrase=None),
        {},
        {"outcome": "go", "mode": "analysis"},
    ),
    (
        "Tạo flash sale cho túi vải đay khung 21h ngày 28/11 giảm 15%.",
        it(
            question_type="create_card",
            metric_phrase=None,
            card_type="flash_sale",
            product_phrase="túi vải đay",
            from_date="2026-11-28",
            start_hour=21,
            amount=15,
            amount_unit="pct",
        ),
        {},
        {"mode": "create", "outcome": "go", "card_type": "flash_sale"},
    ),
    (
        "Tăng ngân sách quảng cáo CDN/01 lên 150 nghìn mỗi ngày.",
        it(question_type="other", metric_phrase="change the ads budget"),  # parser: not a card
        ans(fits=nl(0.1)),
        {"outcome": "unsupported"},  # no builder card for ads: the J11 fallback
    ),
    (
        "ROAS hoà vốn của shop là bao nhiêu?",
        it(
            question_type="status",
            metric_phrase="break-even ROAS",
            time_phrase=None,
            raw_text="ROAS hoà vốn của shop là bao nhiêu?",
        ),
        ans(fits=nl(0.58), mode=ch("lookup")),
        {"outcome": "go", "entity": None, "metric": "roas_break_even", "mode": "lookup"},
    ),
    (
        "Phí cố định của Shopee tính thế nào?",
        it(question_type="other", metric_phrase="Shopee fixed fee"),
        ans(fits=nl(0.1)),
        {"outcome": "unsupported"},
    ),
    (
        "Đối thủ bán hộp bento giá bao nhiêu?",
        it(question_type="other", metric_phrase="competitor price"),
        ans(fits=nl(0.05)),
        {"outcome": "unsupported"},
    ),
    (
        "So sánh GMV tháng 11 với tháng 10.",
        it(question_type="compare", metric_phrase="GMV", named_month="2026-11", time_phrase=None),
        ans(mode=ch("lookup"), window=ch("named_month_vs_previous"), metric=ch("gmv")),
        {"outcome": "go", "mode": "lookup", "metric": "gmv", "window": "named_month_vs_previous"},
    ),
    (
        "Tỉ lệ chuyển đổi hôm qua thế nào?",
        it(question_type="status", metric_phrase="tỉ lệ chuyển đổi", time_phrase="hôm qua"),
        ans(fits=nl(0.73), mode=ch("lookup")),
        {"outcome": "go", "metric": "ctor", "window": "yesterday_vs_same_weekday"},
    ),
    (
        "Tạo combo mua 3 giảm 5% cho nước rửa chén.",
        it(
            question_type="create_card",
            metric_phrase=None,
            card_type="combo",
            product_phrase="nước rửa chén",
            amount=5,
            amount_unit="pct",
            quantity=3,
        ),
        {},
        {"mode": "create", "outcome": "go", "card_type": "combo"},
    ),
    (
        "Làm sao để tăng lượt xem cho sản phẩm mới?",
        it(question_type="other", metric_phrase="how to increase views"),
        ans(fits=nl(0.2)),
        {"outcome": "unsupported"},
    ),
    (
        "Đổi tên sản phẩm găng tay TPE cho dễ tìm hơn.",
        it(
            question_type="create_card",
            metric_phrase=None,
            card_type="title",
            product_phrase="găng tay TPE",
        ),
        {},
        {"mode": "create", "outcome": "go", "card_type": "title"},
    ),
]


def test_the_twenty_questions_are_all_here() -> None:
    assert len(ROWS) == 23


@pytest.mark.parametrize("row", ROWS, ids=[r[0][:40] for r in ROWS])
async def test_classify_routes_each_question(
    row: tuple[str, Any, Any, Any],
) -> None:
    text, parsed, jev_answers, expected = row
    parsed_list = parsed if isinstance(parsed, list) else [parsed]
    llm = FakeLLM({"restated_vi": f"Đang tìm hiểu: {text}", "intents": parsed_list})
    out = await routing.classify(text, TODAY, llm, FakeJev(jev_answers))
    wanted = expected if isinstance(expected, list) else [expected]
    assert len(out["intents"]) == len(wanted), out
    for got, exp in zip(out["intents"], wanted, strict=True):
        for k, v in exp.items():
            assert got[k] == v, (text, k, got)
        assert got["outcome"] != "needs_choice", (text, got)  # the picker never fires on these
