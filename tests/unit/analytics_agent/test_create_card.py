"""J10 "tạo thẻ" and J11 fallback. Fake parser output only: no paid runs."""

from __future__ import annotations

from datetime import date
from typing import Any, cast

from juli_backend.services.analytics_agent import AskRequest, create_card, run
from tests.unit.analytics_agent.fakes import (
    FakeCardEngine,
    FakeData,
    FakeJev,
    FakeLLM,
    ListSink,
    engine_card,
    shop_rows,
)
from tests.unit.analytics_agent.test_cards import ch
from tests.unit.analytics_agent.test_engine import SHOP, L, full
from tests.unit.analytics_agent.test_routing import intent

YDAY = date(2026, 11, 22)  # today Monday 23/11 (VN)
SLOTS = {
    "card_type": "voucher",
    "from_date": "2026-11-24",
    "to_date": "2026-11-25",
    "amount": None,
    "amount_unit": None,
    "min_spend": None,
    "quantity": None,
    "name": None,
}


def _engine() -> FakeCardEngine:
    suggestion = {**engine_card(), "inputs": {"value": 20000, "min_spend": 150000}}
    return FakeCardEngine(per_kind={"min_spend_voucher": {"ok": True, "card": suggestion}})


async def _run(
    req: AskRequest, llm: FakeLLM, eng: FakeCardEngine, data: FakeData
) -> tuple[Any, Any]:
    sink = ListSink()
    res = await run(
        req,
        llm=llm,
        jev=FakeJev(lambda s, q: full()),
        sink=sink,
        labels=L,
        data=data,
        card_engine=eng,
    )
    return sink, res


def _data(cards: list[dict[str, Any]] | None = None) -> FakeData:
    return FakeData(shop_rows(date(2026, 9, 1), YDAY, gmv=1000.0, orders=3.0), cards=cards)


def _llm(**kw: Any) -> FakeLLM:
    it = intent(
        question_type="create_card", metric_phrase=None, time_phrase=None, **{**SLOTS, **kw}
    )
    return FakeLLM({"restated_vi": "Lập voucher ngày 24 và 25 tháng 11", "intents": [it]})


TEXT = "Tôi muốn lập voucher cho ngày 24 và ngày 25 tháng 11"


async def test_voucher_request_asks_for_the_amount_and_minimum_then_drafts() -> None:
    eng = _engine()
    sink, res = await _run(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text=TEXT), _llm(), eng, _data()
    )
    nc = sink.of("needs_choice")[0]
    assert "mức giảm" in nc["question_vi"] and "đơn tối thiểu" in nc["question_vi"]
    assert nc["options"][0]["value"] == "amount=20000;unit=vnd;min_spend=150000"
    assert "Juli gợi ý" in nc["options"][0]["label_vi"]  # the shop's own estimate
    assert not sink.of("card") and res.stop_reasons == ["needs_choice"]
    # the seller taps the suggestion: the answer fills the slots in `pending`, then it drafts
    sink2, res2 = await _run(
        AskRequest(
            shop_id=SHOP,
            platform="shopee",
            as_of=YDAY,
            choice={"item": "chain", "value": nc["options"][0]["value"]},
            pending=nc["pending"],
        ),
        FakeLLM(None),
        eng,
        _data(),
    )
    card = sink2.of("card")[0]
    assert card["kind_vi"] == "Mã Giảm Giá · Voucher toàn Shop · đơn tối thiểu"
    assert card["window_vi"] == "24/11 00:00–25/11 23:59"
    spec = cast(Any, eng).custom_calls[0]
    assert (
        spec["kind"] == "voucher" and spec["start"] == "2026-11-24" and spec["end"] == "2026-11-25"
    )
    assert spec["value"] == 20000.0 and spec["min_spend"] == 150000 and spec["scope"] == "shop"
    assert card["draft_ref"].startswith("d_") and [c["kind"] for c in res2.cards] == [
        "min_spend_voucher"
    ]


async def test_no_minimum_label_and_only_the_missing_slot_is_asked() -> None:
    llm = _llm(amount=10.0, amount_unit="pct")
    sink, _ = await _run(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text=TEXT), llm, _engine(), _data()
    )
    nc = sink.of("needs_choice")[0]
    assert "mức giảm" not in nc["question_vi"] and "đơn tối thiểu" in nc["question_vi"]
    assert nc["options"][-1] == {"label_vi": "Không đơn tối thiểu", "value": "min_spend=0"}
    sink2, _ = await _run(
        AskRequest(
            shop_id=SHOP,
            platform="shopee",
            as_of=YDAY,
            choice={"item": "chain", "value": "min_spend=0"},
            pending=nc["pending"],
        ),
        FakeLLM(None),
        _engine(),
        _data(),
    )
    assert sink2.of("card")[0]["kind_vi"] == "Mã Giảm Giá · Voucher toàn Shop · không đơn tối thiểu"


def test_limits_dates_names_and_flash_sale_window() -> None:
    today = date(2026, 11, 23)
    s = create_card.slots_of({**SLOTS, "from_date": "2026-11-20", "to_date": "2026-11-19"})
    assert "Ngày bắt đầu không được ở quá khứ." in create_card.validate(s, today)
    assert "Ngày kết thúc phải sau ngày bắt đầu." in create_card.validate(s, today)
    long = create_card.slots_of({**SLOTS, "from_date": "2026-11-24", "to_date": "2027-03-30"})
    assert any("tối đa 90 ngày" in p for p in create_card.validate(long, today))
    combo = create_card.slots_of({"card_type": "combo", "name": "x" * 26})
    assert any("25 ký tự" in p for p in create_card.validate(combo, today))
    prog = create_card.slots_of({"card_type": "product_discount", "name": "x" * 151})
    assert any("150 ký tự" in p for p in create_card.validate(prog, today))
    ok = create_card.slots_of({"card_type": "product_discount", "name": "x" * 150})
    assert create_card.validate(ok, today) == []
    far = create_card.slots_of({"card_type": "flash_sale", "from_date": "2026-12-20"})
    assert any("Flash Sale" in p for p in create_card.validate(far, today))
    soon = create_card.slots_of({"card_type": "flash_sale", "from_date": "2026-11-28"})
    assert create_card.validate(soon, today) == []


async def test_past_date_is_explained_and_nothing_is_drafted() -> None:
    sink, res = await _run(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text=TEXT),
        _llm(
            from_date="2026-11-20", to_date="2026-11-21", amount=5.0, amount_unit="pct", min_spend=0
        ),
        _engine(),
        _data(),
    )
    assert "quá khứ" in "".join(e["text"] for e in sink.of("text_delta"))
    assert not sink.of("card")


async def test_an_open_card_with_the_same_change_says_already_exists() -> None:
    eng = _engine()
    open_card = {
        "kind": "min_spend_voucher",
        "item_id": None,
        "status": "sent",
        "code": "JC-0042",
        "change_after": "Mã giảm giá cho cả shop",  # what the fake builder titles the draft
    }
    sink, _ = await _run(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text=TEXT),
        _llm(amount=20000.0, amount_unit="vnd", min_spend=150000),
        eng,
        _data([open_card]),
    )
    nc = sink.of("no_card")[0]
    assert nc["existing_card_code"] == "JC-0042" and nc["reason_vi"] == "Đã có thẻ JC-0042"
    assert not sink.of("card")


async def test_unknown_type_asks_one_question_with_the_card_types() -> None:
    sink, _ = await _run(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text="tạo giúp tôi một thẻ"),
        _llm(card_type=None),
        _engine(),
        _data(),
    )
    nc = sink.of("needs_choice")[0]
    assert nc["question_vi"] == "Bạn muốn tạo loại thẻ nào?"
    assert {o["value"] for o in nc["options"]} >= {"card_type=voucher", "card_type=title"}


# ------------------------------------------------------------------ J11 fallback
async def test_nothing_fits_offers_the_closest_action_and_logs_the_unmet_request() -> None:
    llm = FakeLLM(
        {
            "restated_vi": "Phí cố định của Shopee tính thế nào",
            "intents": [intent(question_type="other", metric_phrase="Shopee fixed fee")],
        }
    )
    sink = ListSink()
    res = await run(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text="Phí cố định tính thế nào?"),
        llm=llm,
        jev=FakeJev(lambda s, q: full(fits={"type": "noul", "noul": 0.1})),
        sink=sink,
        labels=L,
        data=_data(),
        card_engine=_engine(),
    )
    u = sink.of("unsupported")[0]
    assert "chưa hỗ trợ" not in u["text_vi"] and u["text_vi"].startswith("Juli có thể")
    assert len(u["templates"]) == 5  # still reachable, no longer the refusal screen
    assert sink.of("restated")  # Juli restates the request first
    log = next(r for r in res.routing if r.get("step") == "unmet_request")
    assert len(log["text_hash"]) == 16 and log["restated"] and "raw_text" not in log["parsed"]
    assert not sink.of("data_answer")  # never a number


def test_flash_sale_slots_and_builder_limits() -> None:
    today = date(2026, 11, 23)
    ok = create_card.slots_of(
        {"card_type": "flash_sale", "from_date": "2026-11-28", "start_hour": 21}
    )
    assert create_card.validate(ok, today) == []
    bad = create_card.slots_of(
        {"card_type": "flash_sale", "from_date": "2026-11-28", "start_hour": 20}
    )
    assert any("Khung giờ" in p for p in create_card.validate(bad, today))
    assert create_card.missing(create_card.slots_of({"card_type": "flash_sale"}))[:3] == [
        "from_date",
        "start_hour",
        "quantity",
    ] or "start_hour" in create_card.missing(create_card.slots_of({"card_type": "flash_sale"}))
    from juli_backend.services.shopee_builder import specs as sp

    assert (
        create_card.name_limit("voucher")
        == sp.VoucherSpec.model_fields["label"].metadata[0].max_length
    )
    assert create_card.name_limit("combo") == sp.MAX_COMBO_NAME
    assert create_card.max_days("voucher") == sp.MAX_VOUCHER_DAYS


async def test_shop_roas_break_even_is_the_registry_metric_over_the_overview() -> None:
    data = FakeData(
        shop_rows(date(2026, 9, 1), YDAY, gmv=1000.0, orders=3.0),
        overview=lambda a, b: {"profit": {"break_even_roas": 4.0, "contribution_before_ads": 2500}},
    )
    llm = FakeLLM(
        {
            "restated_vi": "ROAS hoà vốn của shop",
            "intents": [intent(question_type="status", metric_phrase="break-even ROAS")],
        }
    )
    sink = ListSink()
    await run(
        AskRequest(
            shop_id=SHOP, platform="shopee", as_of=YDAY, text="ROAS hoà vốn của shop là bao nhiêu?"
        ),
        llm=llm,
        jev=FakeJev(lambda s, q: full(mode=ch("lookup"), fits={"type": "noul", "noul": 0.58})),
        sink=sink,
        labels=L,
        data=data,
        card_engine=_engine(),
    )
    da = sink.of("data_answer")[0]
    assert (
        da["title_vi"] == "ROAS hoà vốn" and da["value"] == "4,00"
    )  # overview `profit.break_even_roas`


def test_registry_reads_give_real_numbers_not_none() -> None:
    from juli_backend.services.analytics_agent.registry_reads import roas_break_even, roas_direct

    assert roas_break_even(10000, 2500) == 4.0 and roas_break_even(10000, 0) is None
    assert roas_direct(900, 300) == 3.0 and roas_direct(None, 3) is None


def test_parse_prompt_lists_the_registry_metric_names() -> None:
    from juli_backend.services.analytics_agent import routing
    from juli_backend.services.metrics.registry import METRICS

    assert "ROAS hoà vốn" in routing.PARSE_SYSTEM
    for m in METRICS.values():
        assert m.label_vi in routing.PARSE_SYSTEM or "{" in m.label_vi


def test_voucher_labels_match_track_s_strings() -> None:
    assert (
        create_card.voucher_label(False, True) == "Mã Giảm Giá · Voucher toàn Shop · đơn tối thiểu"
    )
    assert (
        create_card.voucher_label(True, False)
        == "Mã Giảm Giá · Voucher sản phẩm · không đơn tối thiểu"
    )


# ------------------------------------------------- create_not_estimable_silent (owner, 26/11)
#: the card types the engine cannot estimate from chat (bank rule `create_not_estimable_silent`)
NOT_ESTIMABLE_TYPES = (
    "combo",
    "add_on",
    "gift",
    "variation_set",
    "title",
    "cover_image",
    "description_first_line",
    "price_display",
)
ALL_SLOTS = {
    "from_date": "2026-11-24",
    "to_date": "2026-11-25",
    "start_hour": 12,
    "amount": 10.0,
    "amount_unit": "pct",
    "min_spend": 100_000,
    "quantity": 20,
    "name": "SYN thẻ",
    "item_id": "p1",
    "item_name": "Sản phẩm A",
}


def _unestimable_card() -> dict[str, Any]:
    from tests.unit.analytics_agent.fakes import version

    return {
        "title": "Combo cho sản phẩm A",
        "versions": [version("Nhẹ", None, None, False), version("Vừa", None, None, False)],
    }


async def _create(card_type: str, eng: FakeCardEngine) -> tuple[Any, Any]:
    return await _run(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text=f"Tạo thẻ {card_type}"),
        _llm(card_type=card_type, **ALL_SLOTS),
        eng,
        _data(),
    )


def _assert_not_estimable_card(sink: Any, res: Any, kind_ok: bool = True) -> dict[str, Any]:
    from juli_backend.services.shopee_recommendations.result_store import NOT_ESTIMABLE_TEXT

    assert not sink.of("no_card"), "an unestimable card must not end in a no_card box"
    (card,) = sink.of("card")
    assert card["recommendation_vi"] == NOT_ESTIMABLE_TEXT  # the card, not an empty notice
    assert card["estimable"] is False
    assert all(v["estimable"] is False for v in card["versions"])
    assert [c["draft_ref"] for c in res.cards] == [card["draft_ref"]]
    return card


async def test_an_unestimable_engine_card_is_still_drafted_and_reads_chua_uoc_tinh_duoc() -> None:
    """Rule 7 (#110) hides a no_card box; a card the engine cannot estimate was one, so the seller
    got nothing. The draft is shown; its forecast is the NOT_ESTIMABLE text."""
    for ct in ("combo", "add_on", "gift", "variation_set"):
        eng = FakeCardEngine(result={"ok": True, "card": _unestimable_card()})
        sink, res = await _create(ct, eng)
        card = _assert_not_estimable_card(sink, res)
        assert card["title_vi"] == "Combo cho sản phẩm A" and len(card["versions"]) == 2


async def test_a_kind_the_engine_has_no_option_for_is_still_drafted_without_numbers() -> None:
    """A title / cover / description / price display card (no measured uplift) or any kind whose
    generator finds nothing: still a draft card the seller sees, reading "Chưa ước tính được"."""
    for ct in NOT_ESTIMABLE_TYPES:
        for reason in (
            "generator_returned_none",
            "engine_refused",
            "no_generator_for_kind",
            "generator_error:ValueError",
        ):
            eng = FakeCardEngine(result={"ok": False, "reason": reason})
            sink, res = await _create(ct, eng)
            card = _assert_not_estimable_card(sink, res)
            assert card["versions"] == [] and card["item_id"] == "p1"
            assert card["title_vi"] == card["kind_vi"]


async def test_no_shopee_data_still_says_so() -> None:
    """Not an estimate gap: the shop has no Shopee rows at all, which the seller is told."""
    eng = FakeCardEngine(result={"ok": False, "reason": "no_shopee_data"})
    sink, _ = await _create("combo", eng)
    assert not sink.of("card")
    assert sink.of("no_card") or sink.of("text_delta")
