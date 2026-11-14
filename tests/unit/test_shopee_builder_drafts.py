"""P92 B-4 / B-6: the keyword table of a product and the LLM drafts (titles, cover overlays,
description first lines). The model is always a fake: no test here reaches a real one."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal as D

import pytest

from juli_backend.models.market import MarketKeywordMetric, MarketListingSnapshot
from juli_backend.services.shopee_builder import drafts, keywords, llm
from juli_backend.services.shopee_builder import service as builder
from tests.support.shopee_analytics import CUR_END, CUR_START, keyword, period_row
from tests.support.shopee_reco import AS_OF, seed_reco_shop

NOW = datetime(2026, 10, 8, 3, 0)


class FakeLLM:
    """What the production client returns, scripted; records what it was asked."""

    model = "fake-model"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    async def complete_json(self, *, system, user, schema_name, schema):
        self.calls.append({"system": system, "user": user, "schema": schema_name})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


FACTS = drafts.ProductFacts(
    item_id="1001",
    title="Găng tay tự hủy sinh học STAHAUS",
    variations=(
        {
            "variation_id": "v3",
            "name": "Combo 3 hộp",
            "list_price": 300_000,
            "selling_price": 270_000,
            "price_per_unit": 90_000,
            "pack_count": 3,
        },
        {
            "variation_id": "v1",
            "name": "Hộp lẻ",
            "list_price": 100_000,
            "selling_price": 100_000,
            "price_per_unit": 100_000,
            "pack_count": 1,
        },
    ),
    unit_price_line="3.000đ / chiếc",
    voucher_text="Voucher giảm 10K đơn từ 150K",
    voucher_amount_vnd=10_000,
    banned_terms=("rẻ vô địch",),
)


# ======================================================================================= titles


async def test_titles_keep_every_ticked_keyword_and_stay_within_100_characters():
    client = FakeLLM(
        {
            "drafts": [
                {
                    "title": "Găng tay tự hủy sinh học STAHAUS hộp 100 chiếc dùng một lần",
                    "note": "a",
                },
                {"title": "STAHAUS găng tay tự hủy sinh học bền, sạch", "note": "b"},
                {"title": "Găng tay " + "rất dài " * 20, "note": "too long"},
                {"title": "Túi rác tự hủy sinh học STAHAUS", "note": "no keyword"},
                {
                    "title": "Găng tay tự hủy sinh học STAHAUS hộp 100 chiếc dùng một lần",
                    "note": "dup",
                },
            ]
        }
    )
    out = await drafts.draft_titles(client, FACTS, ["găng tay", "tự hủy sinh học"], count=3)
    titles = [d["title"] for d in out["drafts"]]
    assert titles == [
        "Găng tay tự hủy sinh học STAHAUS hộp 100 chiếc dùng một lần",
        "STAHAUS găng tay tự hủy sinh học bền, sạch",
    ]
    assert all(d["chars"] <= 100 and d["keywords"]["missing"] == [] for d in out["drafts"])
    reasons = {d["reason"].split(":")[0] for d in out["dropped"]}
    assert any(r.startswith("dài") for r in reasons) and "thiếu từ khoá" in reasons
    assert out["max_chars"] == 100 and out["warnings"] == []
    # the ticked keywords and the 100-character limit are in the prompt
    assert (
        "100" in client.calls[0]["system"]
        and "găng tay, tự hủy sinh học" in client.calls[0]["user"]
    )


async def test_a_title_never_claims_a_certification_or_an_ingredient_it_was_not_given():
    client = FakeLLM(
        {
            "drafts": [
                {"title": "Găng tay tự hủy sinh học STAHAUS đạt chuẩn FDA", "note": ""},
                {"title": "Găng tay tự hủy sinh học STAHAUS chiết xuất lô hội", "note": ""},
                {"title": "Găng tay tự hủy sinh học STAHAUS giá 12.345đ", "note": ""},
                {"title": "Găng tay tự hủy sinh học STAHAUS rẻ vô địch", "note": ""},
                {"title": "Găng tay tự hủy sinh học STAHAUS giá 100.000đ", "note": ""},
            ]
        }
    )
    out = await drafts.draft_titles(client, FACTS, ["găng tay"])
    assert [d["title"] for d in out["drafts"]] == ["Găng tay tự hủy sinh học STAHAUS giá 100.000đ"]
    why = " | ".join(d["reason"] for d in out["dropped"])
    assert "fda" in why and "chiết xuất" in why and "12345" in why and "từ không được dùng" in why
    assert out["warnings"]  # only one title passed


async def test_a_claim_word_the_product_already_states_is_allowed():
    facts = drafts.ProductFacts(item_id="1", title="Nước rửa chén hữu cơ Ory 500ml")
    client = FakeLLM({"drafts": [{"title": "Nước rửa chén hữu cơ Ory 500ml êm tay", "note": ""}]})
    out = await drafts.draft_titles(client, facts, ["nước rửa chén"])
    assert out["drafts"][0]["title"] == "Nước rửa chén hữu cơ Ory 500ml êm tay"


async def test_nothing_valid_is_an_error_with_the_reasons_and_a_bad_answer_is_llm_trouble():
    client = FakeLLM({"drafts": [{"title": "Túi rác", "note": ""}]})
    with pytest.raises(drafts.NoValidDraft) as none:
        await drafts.draft_titles(client, FACTS, ["găng tay"])
    assert none.value.dropped[0]["reason"].startswith("thiếu từ khoá")
    with pytest.raises(llm.LLMUnavailable) as bad:
        await drafts.draft_titles(FakeLLM({"nope": 1}), FACTS, ["găng tay"])
    assert bad.value.reason == llm.REASON_BAD_OUTPUT
    off = FakeLLM(llm.LLMUnavailable(llm.REASON_PROVIDER, "timeout"))
    with pytest.raises(llm.LLMUnavailable):
        await drafts.draft_titles(off, FACTS, [])


# ======================================================================================== covers


async def test_cover_overlays_take_their_numbers_from_the_facts_not_the_model():
    client = FakeLLM(
        {
            "concepts": [
                {
                    "layout": "banner_bottom",
                    "variation_id": "v3",
                    "use_voucher": True,
                    "use_unit_price": False,
                    "hook_text": "Dùng một lần",
                    "pack_text": "Combo 3 hộp",
                    "rationale": "đơn giá thấp nhất",
                },
                {
                    "layout": "corner_tag",
                    "variation_id": "v1",
                    "use_voucher": False,
                    "use_unit_price": True,
                    "hook_text": "",
                    "pack_text": "",
                    "rationale": "gọn",
                },
                {
                    "layout": "banner_top",
                    "variation_id": "v3",
                    "use_voucher": True,
                    "use_unit_price": True,
                    "hook_text": "Chứng nhận FDA",
                    "pack_text": "Thùng 50 hộp",
                    "rationale": "claims",
                },
            ]
        }
    )
    out = await drafts.draft_overlays(client, FACTS, count=3)
    first, second = out["concepts"][0]["overlay"], out["concepts"][1]["overlay"]
    assert first == {
        "layout": "banner_bottom",
        "price_vnd": 270_000,
        "original_price_vnd": 300_000,
        "discount_pct": 10,
        "voucher_text": "Voucher giảm 10K đơn từ 150K",
        "pack_text": "Combo 3 hộp",
        "hook_text": "Dùng một lần",
    }
    # a single box: no strike-through (list = selling), no unit-price line for a pack of 1
    assert second == {"layout": "corner_tag", "price_vnd": 100_000}
    assert len(out["concepts"]) == 2 and out["dropped"][0]["reason"].startswith("hook có tuyên bố")
    assert out["layouts"] == ["banner_top", "banner_bottom", "corner_tag"]
    assert "không đổi ảnh" in out["note"].lower() or "giữ nguyên" in out["note"].lower()


async def test_the_unit_price_line_and_the_hook_rules():
    client = FakeLLM(
        {
            "concepts": [
                {
                    "layout": "corner_tag",
                    "variation_id": "v3",
                    "use_voucher": False,
                    "use_unit_price": True,
                    "hook_text": "",
                    "pack_text": "không có trong tên",
                    "rationale": "",
                },
                {
                    "layout": "banner_bottom",
                    "variation_id": "missing",
                    "use_voucher": True,
                    "use_unit_price": False,
                    "hook_text": "x" * 41,
                    "pack_text": "",
                    "rationale": "",
                },
            ]
        }
    )
    out = await drafts.draft_overlays(client, FACTS)
    assert out["concepts"][0]["overlay"]["pack_text"] == "Chỉ 90.000đ/món"
    assert out["dropped"][0]["reason"].startswith("hook dài 41")
    with pytest.raises(drafts.NoValidDraft):
        await drafts.draft_overlays(FakeLLM({"concepts": []}), FACTS)
    with pytest.raises(drafts.NoValidDraft):
        await drafts.draft_overlays(FakeLLM(), drafts.ProductFacts(item_id="1", title="x"))


# ================================================================================== descriptions


async def test_description_first_lines_pass_the_same_checks():
    client = FakeLLM(
        {
            "drafts": [
                {
                    "first_line": "Găng tay tự hủy sinh học, chỉ 90.000đ mỗi hộp khi mua Combo 3.",
                    "note": "",
                },
                {"first_line": "Găng tay tự hủy sinh học giảm 50% hôm nay.", "note": ""},
                {"first_line": "Dòng một\nDòng hai", "note": ""},
                {"first_line": "Găng tay chống khuẩn tuyệt đối.", "note": ""},
                {"first_line": "", "note": ""},
            ]
        }
    )
    out = await drafts.draft_descriptions(client, FACTS)
    assert [d["first_line"] for d in out["drafts"]] == [
        "Găng tay tự hủy sinh học, chỉ 90.000đ mỗi hộp khi mua Combo 3."
    ]
    why = " | ".join(d["reason"] for d in out["dropped"])
    assert "50%" in why and "description_too_long" in why and "chống" in why


# ============================================================================== the kill switch


async def test_the_model_is_off_without_a_key_a_consent_or_when_the_switch_is_off(
    session, monkeypatch
):
    seeded = await seed_reco_shop(session)
    await session.commit()
    monkeypatch.setenv("SHOPEE_BUILDER_LLM", "off")
    with pytest.raises(llm.LLMUnavailable) as off:
        await llm.gated_client(session, seeded.shop_id)
    assert off.value.reason == llm.REASON_SWITCH and "LLM tắt" in str(off.value)
    monkeypatch.setenv("SHOPEE_BUILDER_LLM", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(llm.LLMUnavailable) as nokey:
        await llm.gated_client(session, seeded.shop_id)
    assert nokey.value.reason == llm.REASON_NOT_CONFIGURED
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")
    with pytest.raises(llm.LLMUnavailable) as noconsent:
        await llm.gated_client(session, seeded.shop_id)  # no llm_processing consent on the shop
    assert noconsent.value.reason == llm.REASON_CONSENT


def test_the_switch_reads_the_environment_at_call_time(monkeypatch):
    monkeypatch.delenv("SHOPEE_BUILDER_LLM", raising=False)
    assert llm.switch_on() is True
    for value in ("0", "false", "No", "OFF"):
        monkeypatch.setenv("SHOPEE_BUILDER_LLM", value)
        assert llm.switch_on() is False


# ================================================================================== keyword table


def test_competitor_phrases_need_most_of_the_top_titles():
    titles = [
        "Găng tay nitrile dùng một lần hộp 100",
        "Găng tay nitrile y tế hộp 100 cái",
        "Hộp 100 găng tay nitrile xanh",
        "Bao tay nitrile loại dày",
        "Găng tay cao su rửa chén",
    ]
    got = dict(keywords.competitor_phrases(titles))
    assert got["găng tay nitrile"] == 3 and got["tay nitrile"] == 4
    assert "một lần" not in got and "rửa chén" not in got  # in fewer than 2 of 5... below the bar
    assert keywords.competitor_phrases(titles[:2]) == []
    assert keywords.ngrams("Găng tay A", 2) == ["Găng", "tay", "A", "Găng tay", "tay A"]


async def _market(session, shop_id):
    def metric(keyword_, seed, volume, difficulty, cpc=(500, 900), day=date(2026, 10, 5)):
        return MarketKeywordMetric(
            id=uuid.uuid4(), platform="shopee", source="shopeeanalytics", keyword=keyword_,
            seed=seed, collected_on=day, status="ok", volume=volume, difficulty=D(difficulty),
            cpc_min=D(cpc[0]), cpc_max=D(cpc[1]),
        )  # fmt: skip

    session.add_all(
        [
            metric("găng tay", "găng tay", 5000, 40),
            metric("găng tay dùng một lần", "găng tay", 1200, 25),  # a suggestion
            metric("găng tay nitrile", "găng tay", 900, 30),
            metric("găng tay y tế", "găng tay", 700, 55),
            metric("tự hủy sinh học", "tự hủy sinh học", 300, 10),
        ]
    )
    for i, title in enumerate(
        [
            "Găng tay nitrile dùng một lần hộp 100",
            "Găng tay nitrile y tế hộp 100 cái",
            "Hộp 100 găng tay nitrile xanh",
            "Găng tay nitrile cao cấp bền",
        ]
    ):
        session.add(
            MarketListingSnapshot(
                id=uuid.uuid4(),
                platform="shopee",
                keyword="găng tay",
                sort="relevancy",
                page=1,
                pos=i + 1,
                collected_at=datetime(2026, 10, 5, 8, 0),
                platform_item_id=str(900 + i),
                title=title,
                collector="test",
            )  # fmt: skip
        )
    session.add(keyword(shop_id, "găng tay", "chinh"))
    session.add(keyword(shop_id, "tự hủy sinh học", "phu"))
    session.add(
        period_row(
            shop_id,
            "ads_keyword_period",
            CUR_START,
            CUR_END,
            item_id="1001",
            stream="ads",
            segment="k1",
            order_type="placed",
            platform_source="Chiến dịch nhóm › găng tay y tế",
            clicks=D(40),
            orders=D(3),
            gmv=D(270_000),
            extra={"ads_expense": 90_000},
        )  # fmt: skip
    )
    await session.commit()


async def test_the_keyword_table_joins_title_suggestions_competitors_and_the_ads_report(session):
    seeded = await seed_reco_shop(session)
    await _market(session, seeded.shop_id)
    out = await keywords.keyword_table(
        session, seeded.shop_id, "1001", title="Găng tay tự hủy sinh học STAHAUS", as_of=AS_OF
    )
    by = {r["keyword"]: r for r in out["keywords"]}
    seed = by["găng tay"]
    assert seed["sources"] == ["title", "competitor"] and seed["volume"] == 5000
    assert seed["difficulty"] == 40
    assert (seed["cpc_min"], seed["cpc_max"]) == (500, 900)
    assert seed["in_title"] is True and seed["role"] == "chinh" and seed["volume_status"] == "ok"
    assert by["tự hủy sinh học"]["in_title"] is True and by["tự hủy sinh học"]["role"] == "phu"
    sug = by["găng tay dùng một lần"]
    assert sug["sources"] == ["suggestion"] and sug["in_title"] is False and sug["volume"] == 1200
    assert (
        "suggestion" in by["găng tay nitrile"]["sources"]
        and "competitor" in by["găng tay nitrile"]["sources"]
    )
    assert by["găng tay nitrile"]["competitor_titles"] == 4
    ads = by["găng tay y tế"]
    assert "ads" in ads["sources"] and ads["ads"]["spend"] == 90_000 and ads["ads"]["roas"] == 3.0
    assert ads["volume"] == 700  # its numbers come from the market table
    volumes = [r["volume"] for r in out["keywords"] if r["volume"] is not None]
    assert volumes == sorted(volumes, reverse=True)  # highest volume first
    assert {s["key"]: s["present"] for s in out["sources"]} == {
        "title": True, "suggestion": True, "competitor": True, "ads": True,
    }  # fmt: skip
    assert out["max_title_chars"] == 100 and out["title_chars"] == len(out["title"])


async def test_a_source_that_is_not_stored_comes_back_absent_with_its_reason(session):
    seeded = await seed_reco_shop(session)
    out = await keywords.keyword_table(
        session, seeded.shop_id, "1001", title="Găng tay tự hủy sinh học STAHAUS", as_of=AS_OF
    )
    assert out["keywords"] == []  # nothing is invented
    reasons = {s["key"]: s["reason"] for s in out["sources"]}
    assert not any(s["present"] for s in out["sources"])
    assert "từ khoá gốc" in reasons["title"] and "lượt tra" in reasons["suggestion"]
    assert "tiêu đề tìm kiếm" in reasons["competitor"] and "quảng cáo" in reasons["ads"]
    # a keyword never looked up keeps volume None, "chưa tra", not 0
    seeded2 = await seed_reco_shop(session)
    session.add(keyword(seeded2.shop_id, "chưa tra bao giờ", "phu"))
    await session.commit()
    again = await keywords.keyword_table(
        session, seeded2.shop_id, "1001", title="Găng tay", as_of=AS_OF
    )
    row = again["keywords"][0]
    assert (row["volume"], row["volume_status"]) == (None, "chua_tra")


async def test_draft_facts_use_the_shops_own_numbers_only(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    env, facts = await builder.draft_facts(session, seeded.shop_id, "1001", as_of=AS_OF, now=NOW)
    assert facts.title == "Găng tay tự hủy sinh học STAHAUS" and facts.item_id == "1001"
    row = facts.variations[0]
    assert row["selling_price"] == 90_000 and row["list_price"] == 100_000
    assert facts.prices() >= {90_000, 100_000} and facts.discount_pcts() == {10}
    assert facts.voucher_text is None and facts.tone is None
    with pytest.raises(LookupError):
        await builder.draft_facts(session, seeded.shop_id, "nope", as_of=AS_OF, now=NOW)
    assert env.as_of == AS_OF


# ============================================================================ the gated client


class _Adapter:
    def __init__(self, result):
        self.result = result
        self.seen = None

    async def complete(self, **kwargs):
        self.seen = kwargs
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _client(result):
    from juli_backend.services.agent.llm.config import LLMConfig

    return llm.GatedLLMClient(_Adapter(result), LLMConfig(model="m"))


async def test_the_gated_client_parses_the_structured_answer_and_maps_every_failure():
    from juli_backend.services.agent.llm.blocks import AssistantTurn, FinalResponse, Usage
    from juli_backend.services.agent.llm.openai_adapter import LLMGateRefusedError, LLMProviderError
    from juli_backend.services.llm_gate import GateRefused

    turn = AssistantTurn(
        blocks=(FinalResponse(structured_output=None, content='{"drafts": []}'),),
        usage=Usage(10, 5),
    )
    ok = _client(turn)
    assert await ok.complete_json(system="s", user="u", schema_name="n", schema={}) == {
        "drafts": []
    }
    assert ok.model == "m" and ok.adapter.seen["response_format"].name == "n"
    assert ok.adapter.seen["tools"] == [] and ok.adapter.seen["system"] == "s"
    refused = _client(LLMGateRefusedError(GateRefused("consent_llm_processing", purpose="x")))
    with pytest.raises(llm.LLMUnavailable) as consent:
        await refused.complete_json(system="s", user="u", schema_name="n", schema={})
    assert consent.value.reason == llm.REASON_CONSENT
    with pytest.raises(llm.LLMUnavailable) as provider:
        await _client(LLMProviderError("503")).complete_json(
            system="s", user="u", schema_name="n", schema={}
        )
    assert provider.value.reason == llm.REASON_PROVIDER
    junk = AssistantTurn(
        blocks=(FinalResponse(structured_output=None, content="not json"),), usage=Usage(1, 1)
    )
    arr = AssistantTurn(
        blocks=(FinalResponse(structured_output=None, content="[1]"),), usage=Usage(1, 1)
    )
    for bad in (junk, arr):
        with pytest.raises(llm.LLMUnavailable) as out:
            await _client(bad).complete_json(system="s", user="u", schema_name="n", schema={})
        assert out.value.reason == llm.REASON_BAD_OUTPUT


def test_tiny_discounts_are_not_put_on_a_cover_concept():
    tiny = {"variation_id": "v", "name": "Hộp", "list_price": 100_000, "selling_price": 99_000}
    real = {"variation_id": "v", "name": "Hộp", "list_price": 100_000, "selling_price": 90_000}
    facts = drafts.ProductFacts(item_id="1", title="x", variations=(tiny,))
    concept = {"layout": "corner_tag"}
    overlay, _ = drafts._build_overlay(facts, tiny, concept, "")
    assert overlay is not None and "discount_pct" not in overlay
    assert overlay["price_vnd"] == 99_000 and "original_price_vnd" not in overlay
    assert facts.discount_pcts() == set()
    overlay, _ = drafts._build_overlay(facts, real, concept, "")
    assert overlay is not None and overlay["discount_pct"] == 10
