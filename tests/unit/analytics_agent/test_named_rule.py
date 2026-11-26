"""#112(1b): a clear question -- a named metric or entity with a named period -- is answered,
never sent to `needs_choice`, whatever the router's split votes say.

The root causes these pin (paraphrased live questions): split intents lost the message (`raw_text`
only on a single intent), so "which campaign is losing" / "how much commission" named no entity;
a split mode / scope / window vote asked even when the seller named the metric and the period;
"this week compared with last week" matched "last week" first; a best / worst list with the
ranking slot left empty asked "which number"; unaccented words matched nothing.
"""

from __future__ import annotations

from typing import Any

import pytest

from juli_backend.services.analytics_agent import routing, shopee_labels
from juli_backend.services.analytics_agent.engine import _more_item
from juli_backend.services.analytics_agent.windows import fold, window_from_phrase
from tests.unit.analytics_agent.test_routing import ans, ch, intent, nl


def split(a: str, b: str) -> dict[str, Any]:
    return {"type": "choice", "choice": a, "probabilities": {a: 0.5, b: 0.45}}


def status(**kw: Any) -> dict[str, Any]:
    return intent(question_type="status", claimed_direction="none", **kw)


@pytest.mark.parametrize(
    ("phrase", "preset"),
    [
        ("this week compared with last week", "this_week_vs_same_days_last_week"),
        ("tuần này so với tuần trước", "this_week_vs_same_days_last_week"),
        ("tuan nay so voi tuan truoc", "this_week_vs_same_days_last_week"),
        ("last week", "last_full_week_vs_week_before"),
        ("tuan truoc", "last_full_week_vs_week_before"),
        ("tháng này so với tháng trước", "mtd_vs_same_days_last_month"),
        ("thang truoc", "last_month_vs_month_before"),
    ],
)
def test_the_current_period_wins_and_accents_are_optional(phrase: str, preset: str) -> None:
    assert window_from_phrase(phrase) == preset


def test_fold_drops_accents_and_case() -> None:
    assert fold("Tiếp Thị Liên Kết · Đơn") == "tiep thi lien ket · don"


@pytest.mark.parametrize(
    "answers",
    [
        ans(mode=split("lookup", "why")),
        ans(mode=ch("lookup"), scope=split("shop", "product")),
        ans(mode=ch("lookup"), window=split("last_7d_vs_prev_7d", "last_30d_vs_prev_30d")),
        ans(mode=split("why", "lookup"), metric_named=nl(0.2), fits=nl(0.6)),
        ans(chain=split("ads_change", "cost_change"), metric=split("ads_spend", "roas")),
    ],
)
def test_a_named_metric_with_a_named_period_goes(answers: dict[str, Any]) -> None:
    it = status(metric_phrase="ad spend", metric_key="cost_ads", time_phrase="last week")
    dec = routing.decide(it, answers)
    assert dec["outcome"] == "go", dec
    assert dec["metric"] == "ads_spend" and dec["window"] == "last_full_week_vs_week_before"
    assert dec.get("scope", "shop") == "shop"


def test_a_split_mode_on_a_status_question_is_a_lookup() -> None:
    it = status(metric_phrase="ROAS", metric_key="roas", time_phrase="this week")
    dec = routing.decide(it, ans(mode=split("why", "lookup")))
    assert dec["outcome"] == "go" and dec["mode"] == "lookup"
    assert dec["window"] == "this_week_vs_same_days_last_week"


def test_a_named_metric_without_a_period_may_still_ask_the_window() -> None:
    it = status(metric_phrase="GMV", metric_key="gmv", time_phrase=None)
    dec = routing.decide(
        it, ans(mode=ch("lookup"), window=split("last_7d_vs_prev_7d", "last_30d_vs_prev_30d"))
    )
    assert dec["outcome"] == "needs_choice" and dec["remaining"][0][0] == "window"


def test_no_metric_and_no_entity_still_asks() -> None:
    it = status(metric_phrase="how is it going", time_phrase="last week")
    dec = routing.decide(it, ans(fits=nl(0.55), metric_named=nl(0.2)))
    assert dec["outcome"] == "needs_choice"


MSG_ADS = "Quảng cáo tuần trước: chi phí, ROAS và chiến dịch nào lỗ?"
MSG_AFF = "Tiếp thị liên kết tuần trước mang về bao nhiêu đơn và tốn bao nhiêu hoa hồng?"


def test_the_message_is_context_for_a_split_intent_entity() -> None:
    camp = status(metric_phrase="which campaigns are losing money", time_phrase="last week")
    assert routing.entity_kind(camp) is None  # alone it names no ad campaign
    assert routing.entity_kind({**camp, "msg_text": MSG_ADS}) == "campaign"
    spend = status(metric_phrase="ad spend", metric_key="cost_ads", time_phrase="last week")
    assert routing.entity_kind({**spend, "msg_text": MSG_ADS}) is None  # its own words decide
    comm = status(metric_phrase="commission cost", time_phrase="last week")
    assert routing.entity_kind({**comm, "msg_text": MSG_AFF}) == "affiliate"
    fee = status(metric_phrase="phí hoa hồng", time_phrase="last week")
    assert routing.entity_kind({**fee, "msg_text": MSG_AFF}) is None  # a Shopee fee


def test_a_campaign_intent_of_a_split_message_goes() -> None:
    camp = status(
        metric_phrase="which campaigns are losing money", time_phrase="last week", msg_text=MSG_ADS
    )
    dec = routing.decide(
        camp, ans(fits=nl(0.55), metric_named=nl(0.25), mode=split("lookup", "why"))
    )
    assert dec["outcome"] == "go" and dec["mode"] == "lookup"


@pytest.mark.parametrize(
    ("phrase", "lookup"),
    [
        ("best selling product", "top_products"),
        ("sản phẩm bán chạy nhất", "top_products"),
        ("product with the biggest decline", "top_decliners"),
        ("san pham giam manh nhat", "top_decliners"),
    ],
)
def test_a_ranking_in_words_is_a_list_never_which_number(phrase: str, lookup: str) -> None:
    it = status(metric_phrase=phrase, time_phrase="this week compared with last week")
    dec = routing.decide(
        it, ans(mode=ch("lookup"), lookup=split("metric_total", lookup), metric_named=nl(0.2))
    )
    assert dec["outcome"] == "go" and dec["lookup"] == lookup
    assert dec["window"] == "this_week_vs_same_days_last_week"


@pytest.mark.parametrize(
    ("words", "kind"),
    [
        ("ma giam gia tuan truoc", "voucher"),
        ("don tu tiep thi lien ket", "affiliate"),
        ("chien dich quang cao nao lo", "campaign"),
    ],
)
def test_unaccented_entity_words(words: str, kind: str) -> None:
    assert routing.entity_kind(status(metric_phrase=None, raw_text=words)) == kind


def test_the_more_buttons_are_vietnamese() -> None:
    labels = shopee_labels()
    item = _more_item(
        {"metric_phrase": "ad spend", "metric_key": "cost_ads", "time_phrase": "last week"}, labels
    )
    assert item == {
        "label_vi": labels.metric("ads_spend"),
        "text": f"{labels.metric('ads_spend')} tuần trước",
    }
    assert _more_item({"metric_phrase": "something"}, labels)["label_vi"] == "Câu hỏi tiếp"
