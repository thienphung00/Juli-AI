"""E6 numbers check: every number >= 3 digits and every % in the explanation traces to a value the
writer was given (rounded or re-expressed allowed); card figures are never allowed. Synthetic
numbers shaped like the eval's untraced cases."""

from __future__ import annotations

from typing import Any

import pytest

from juli_backend.services.analytics_agent import facts, writer
from juli_backend.services.analytics_agent.labels import shopee_labels
from tests.unit.analytics_agent.fakes import FakeLLM

L = shopee_labels()
FIRST = "Đang tìm hiểu: vì sao GMV giảm"


def chain() -> dict[str, Any]:
    """A GMV chain: AOV 183.755đ -> 150.000đ, a product 748.312đ -> 300.000đ, CTR 3,07 % -> 2,5%."""

    def f(level: str, node: str, now: float, before: float, share: float | None) -> dict[str, Any]:
        return {
            "level": level,
            "node": node,
            "node_vi": node,
            "now": now,
            "before": before,
            "contribution_pct": share,
            "flags": [],
            "evidence_ref": "",
        }

    return {
        "chain": "gmv_change",
        "metric": "gmv",
        "stop_reason": "explained",
        "explained_share": 0.8,
        "window": {
            "label_vi": "12/10–18/10 so với 05/10–11/10",
            "cur": ["2026-10-12", "2026-10-18"],
            "prev": ["2026-10-05", "2026-10-11"],
            "same_weekday": [],
            "flags": [],
        },
        "findings": [
            f("shop", "gmv", 1_050_000.0, 1_286_285.0, None),
            f("formula", "aov", 150_000.0, 183_755.0, 60.0),
            f("product", "Sản phẩm A", 300_000.0, 748_312.0, 80.0),
            f("formula", "ctr", 0.025, 0.0307, 20.0),
        ],
        "events": [],
    }


def check(text: str, card: list[float] | None = None) -> list[str]:
    _, fa = facts.writer_input(chain(), L)
    return facts.numbers_check(text, fa, card_figures=card or [])


@pytest.mark.parametrize(
    "text",
    [
        "AOV giảm từ 183.755đ xuống 150.000đ.",  # exact
        "AOV trước đó khoảng 183.800đ.",  # 183.755 rounded to the hundred
        "AOV trước đó khoảng 184 nghìn.",  # re-expressed
        "Sản phẩm A từ 748 nghìn xuống 300 nghìn.",  # 748.312 -> "748 nghìn"
        "CTR từ 3,07% xuống 2,5%.",  # 0,0307 -> 3,07%
        "Sản phẩm A đóng góp 80% mức giảm.",  # contribution
        "AOV giảm 18,4%.",  # pre-computed % change
        "Từ 05/10 đến 11/10 năm 2026, 7 ngày, 3 sản phẩm.",  # dates, small numbers: unchecked
    ],
)
def test_traced_numbers_are_allowed(text: str) -> None:
    assert check(FIRST + ".\n" + text) == []


@pytest.mark.parametrize(
    "text",
    [
        "Doanh thu tăng +194% so với kỳ trước.",
        "AOV giảm còn 91.234đ.",
        "Lượt xem là 5.678.",
        "CTR giảm 40%.",
    ],
)
def test_untraced_numbers_and_percentages_fail(text: str) -> None:
    assert check(FIRST + ".\n" + text), text


def test_card_figures_are_never_allowed_in_the_text() -> None:
    bad = check(FIRST + ".\nΔGMV P50 27.827đ nếu giảm giá.", card=[27_827.0])
    assert any("card" in b for b in bad)
    # even a value that is also a given fact is blocked when it is a card figure
    assert any("card" in b for b in check(FIRST + ".\nThêm 150.000đ.", card=[150_000.0]))
    assert any("card" in b for b in check(FIRST + ".\nP50 là gì đó.", card=[]))


def test_the_restated_first_line_is_not_checked() -> None:
    assert check("Đang tìm hiểu: vì sao 12.345 đơn giảm 99%\nAOV giảm từ 183.755đ.") == []


def test_writer_input_is_precomputed_and_preformatted() -> None:
    inp, fa = facts.writer_input(chain(), L)
    flat = str(inp)
    assert "183.755đ" in flat and "3,07%" in flat  # app format
    assert "giảm 18,4%" in flat and "giảm 59,9%" in flat  # % change per step, precomputed
    assert "trung_bình_ngày" in flat  # daily averages for the writer
    assert 183_755.0 in fa.plain and any(abs(p - 3.07) < 1e-9 for p in fa.pct)


async def test_untraced_number_triggers_one_rewrite_then_the_template_and_is_recorded() -> None:
    bad = FIRST + ".\nDoanh thu tăng +194%."
    good = FIRST + ".\nAOV giảm từ 183.755đ xuống 150.000đ."
    sent: list[str] = []

    async def d(t: str) -> None:
        sent.append(t)

    rep: list[str] = []

    async def r(t: str) -> None:
        rep.append(t)

    _, fa = facts.writer_input(chain(), L)
    text, meta = await writer.write_explanation(
        FakeLLM(text=bad, rewrite=good), d, r, FIRST, [chain()], [], L, {}, card_figures=[]
    )
    assert text == good and meta["rewrites"] == 1 and rep == [good]
    assert any("194" in n for n in meta["numbers_failed"])
    rep2: list[str] = []

    async def r2(t: str) -> None:
        rep2.append(t)

    text2, meta2 = await writer.write_explanation(
        FakeLLM(text=bad, rewrite=bad), d, r2, FIRST, [chain()], [], L, {}, card_figures=[]
    )
    assert meta2["template"] and "194" not in text2 and rep2[-1] == text2
    assert meta2["numbers_failed"]


async def test_card_figure_in_the_writers_text_is_blocked() -> None:
    bad = FIRST + ".\nΔGMV P50 27.827đ."
    good = FIRST + ".\nAOV giảm."
    _, fa = facts.writer_input(chain(), L)

    async def noop(t: str) -> None:
        return None

    text, meta = await writer.write_explanation(
        FakeLLM(text=bad, rewrite=good),
        noop,
        noop,
        FIRST,
        [chain()],
        [],
        L,
        {},
        card_figures=[27_827.0],
    )
    assert text == good and any("card" in n for n in meta["numbers_failed"])


# ---- A3: product names are shown verbatim -------------------------------------------------

NAME = "[Deal 15.11] Combo Gia Dụng An Toàn (3 hộp)"


def _name_chain() -> dict[str, Any]:
    c = chain()
    c["findings"].append(
        {
            "level": "product",
            "node": NAME,
            "node_vi": NAME,
            "now": 100_000.0,
            "before": 400_000.0,
            "contribution_pct": 70.0,
            "flags": [],
            "evidence_ref": "product:777",
        }
    )
    return c


def test_a_product_name_with_a_dot_and_brackets_is_not_split_into_source_and_metric() -> None:
    from datetime import date

    from juli_backend.services.analytics_agent.chains import ChainResult, Finding
    from juli_backend.services.analytics_agent.windows import build_windows

    r = ChainResult(
        "gmv_change",
        "gmv",
        build_windows("last_7d_vs_prev_7d", date(2026, 10, 25)),
        "explained",
        [Finding("product", NAME, 1.0, 2.0, 70.0)],
        [],
    )
    assert r.node_vi(NAME, L) == NAME
    assert r.json(L)["findings"][0]["node_vi"] == NAME
    assert r.node_vi("video.orders", L) == "Video (Đơn hàng)"  # real source.metric still splits
    assert r.node_vi("trang_shop", L) == "Trang shop"


def test_path_labels_and_the_writer_text_keep_the_name_while_leaks_stay_blocked() -> None:
    from datetime import date

    from juli_backend.services.analytics_agent import present
    from juli_backend.services.analytics_agent.chains import ChainResult, Finding
    from juli_backend.services.analytics_agent.windows import build_windows

    r = ChainResult(
        "gmv_change",
        "gmv",
        build_windows("last_7d_vs_prev_7d", date(2026, 10, 25)),
        "explained",
        [
            Finding("shop", "gmv", 1.0, 2.0),
            Finding("product", NAME, 1.0, 2.0, 70.0, evidence_ref="product:777"),
        ],
        [],
    )
    labels_in_path = [s["label_vi"] for s in present.path_steps(r, L)]
    assert NAME in labels_in_path
    clean, issues = writer.sanitise(f"Đang tìm hiểu: x\n{NAME} bán chậm.", {"777": NAME}, [NAME])
    assert NAME in clean and issues == []
    assert writer.sanitise(f"Đang tìm hiểu: x\n{NAME} và the_san_pham_khac", {}, [NAME])[1] == [
        "snake_case"
    ]
    assert "banned" not in str(writer.sanitise(f"{NAME}", {}, [NAME])[1])


async def test_a_findings_product_name_with_brackets_survives_the_writer_without_a_rewrite() -> (
    None
):
    from tests.unit.analytics_agent.fakes import FakeLLM

    text = f"{FIRST}.\nSản phẩm {NAME} giảm mạnh."

    async def noop(t: str) -> None:
        return None

    out, meta = await writer.write_explanation(
        FakeLLM(text=text), noop, noop, FIRST, [_name_chain()], [], L, {}, card_figures=[]
    )
    assert out == text and meta["rewrites"] == 0 and meta["issues"] == []


async def test_numbers_inside_a_product_name_are_not_claims() -> None:
    from tests.unit.analytics_agent.fakes import FakeLLM

    c = _name_chain()
    c["findings"][-1]["node_vi"] = "Combo 1000 miếng 25.000 đ"
    c["findings"][-1]["node"] = "Combo 1000 miếng 25.000 đ"
    text = f"{FIRST}.\nSản phẩm Combo 1000 miếng 25.000 đ giảm mạnh."

    async def noop(t: str) -> None:
        return None

    out, meta = await writer.write_explanation(
        FakeLLM(text=text), noop, noop, FIRST, [c], [], L, {}, card_figures=[]
    )
    assert out == text and meta["numbers_failed"] == []
