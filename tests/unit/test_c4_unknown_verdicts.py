"""C4: an unknown value is never a verdict and never 0. Synthetic data only."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

from juli_backend.services.analytics_agent import writer
from juli_backend.services.analytics_agent.data_service import _product_break_even
from juli_backend.services.analytics_agent.entities import (
    campaign_row,
    product_loss_row,
    run_entity,
)
from tests.unit.analytics_agent.fakes import FakeEntityData, shop_rows

AS_OF = date(2026, 11, 22)


def _camp(name: str, roas: Any, be: Any, profit: Any) -> dict[str, Any]:
    return {
        "key": name, "name": name, "spend": 100.0, "gmv": 300.0, "roas": roas,
        "break_even": be, "profit_after_ads": profit,
    }  # fmt: skip


def _data(**entity: Any) -> FakeEntityData:
    return FakeEntityData(shop_rows(date(2026, 11, 1), date(2026, 11, 21)), entity=entity)


async def _ask(data: FakeEntityData, phrase: str, kind: str) -> dict[str, Any]:
    out = await run_entity(
        kind,
        data,
        {"question_type": "status", "entity_phrase": kind, "metric_phrase": phrase},
        None,
        "last_week",
        AS_OF,
    )
    return out[0]


async def test_no_loss_sentence_while_a_campaign_is_unknown() -> None:
    camps = [_camp("A", 5.0, 3.0, 50.0), _camp("U", None, None, None)]
    ans = await _ask(_data(campaigns=camps), "which campaigns lose money", "campaign")
    assert "Chưa có chiến dịch nào lỗ" not in ans["title_vi"]
    assert "chưa rõ" in ans["title_vi"]
    verdicts = {r["label_vi"]: r["value_vi"] for r in ans["rows"]}
    assert verdicts["U"].startswith("Chưa rõ")


async def test_no_loss_sentence_is_kept_when_every_campaign_is_known() -> None:
    camps = [_camp("A", 5.0, 3.0, 50.0)]
    ans = await _ask(_data(campaigns=camps), "which campaigns lose money", "campaign")
    assert ans["title_vi"] == "Chưa có chiến dịch nào lỗ"


async def test_losing_campaigns_listed_with_the_unknown_ones_named() -> None:
    camps = [_camp("L", 2.0, 3.0, -20.0), _camp("U", None, None, None)]
    ans = await _ask(_data(campaigns=camps), "which campaigns lose money", "campaign")
    assert ans["title_vi"].startswith("Chiến dịch đang lỗ")
    assert "1 chiến dịch chưa rõ" in ans["title_vi"]
    assert [r["label_vi"] for r in ans["rows"]] == ["L", "U"]


async def test_no_loss_product_sentence_while_a_product_is_unknown() -> None:
    rows = [
        {"item_id": "1", "name": "P1", "profit": 50.0, "contribution_before_ads": 80.0},
        {"item_id": "2", "name": "P2", "profit": None, "contribution_before_ads": None},
    ]
    ans = await _ask(_data(product_rows=rows), "which products lose money", "product_loss")
    assert ans["title_vi"] != "Chưa có sản phẩm nào lỗ sau quảng cáo"
    assert "chưa tính" in ans["title_vi"]


def test_unknown_contribution_is_not_zero() -> None:
    row = product_loss_row(
        {
            "item_id": "9",
            "name": "P",
            "profit": -10.0,
            "contribution_before_ads": None,
            "ad_spend": 123.0,
            "break_even_roas": None,
        }  # fmt: skip
    )
    assert "0đ" not in row["detail_vi"] and "chưa tính" in row["detail_vi"]


def test_service_marks_contribution_unknown_when_no_line_is_costed() -> None:
    none_costed = SimpleNamespace(
        buyer_paid=Decimal(500), buyer_paid_covered=Decimal(0), contribution=Decimal(0),
        profit=Decimal(-30), break_even_roas=None, gmv_net=Decimal(500), gmv_known_net=Decimal(0),
        ads_known=True,  # b7791d17: the one gate also reads whether any ad data is known
    )  # fmt: skip
    got = _product_break_even(none_costed)
    assert got["contribution_before_ads"] is None


def test_unknown_campaign_money_is_not_zero() -> None:
    row = campaign_row({"name": "U", "spend": None, "gmv": None, "roas": None, "break_even": None})
    assert "0đ" not in row["detail_vi"]
    assert row["value_vi"].startswith("Chưa rõ")


def test_internal_metric_key_never_reaches_the_seller() -> None:
    text, issues = writer.sanitise("Mức roas_break_even của shop là 3,00.")
    assert "roas_break_even" not in text and "ROAS hoà vốn" in text
    assert not issues


def _warn(current: str | None, new: float) -> list[str]:
    from juli_backend.services.shopee_builder.translate import _ads_warnings

    setting = SimpleNamespace(
        roas_target=None if current is None else Decimal(current), roas_changes_7d=0
    )
    ctx = SimpleNamespace(env=SimpleNamespace(setting_for=lambda _k: setting))
    spec = SimpleNamespace(lever="roas", roas_target=new, campaign_key="c1")
    return [w["code"] for w in _ads_warnings(cast(Any, spec), cast(Any, ctx))]


def test_target_hint_warning_hidden_when_current_target_is_already_above() -> None:
    assert _warn("4.0", 5.0) == []
    assert _warn("3.0", 5.0) == ["ads_roas_above_hint"]
    assert _warn(None, 5.0) == ["ads_roas_above_hint"]
