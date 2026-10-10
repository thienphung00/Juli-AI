"""P14-E content cards — the pure parts (contract ``fasttrack/contracts/p14-content-cards.md``).

- candidates from the stored ADR-109 d.5 rankings (video CTR / LIVE CTOR rows
  below the stream's prior rate, enough volume, loss shared per product);
- the structured-output schemas and the guardrails (banned words, protected
  terms, facts, discount cap, length, product on screen by 3 s);
- the prompt templates (seller voice, never Juli's founder voice);
- the adapter's ``text.format`` json_schema request;
- the run's script blocks and the measurement arithmetic (progress, stages).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from juli_backend.services.agent.llm.blocks import Usage
from juli_backend.services.agent.llm.config import LLMConfig
from juli_backend.services.agent.llm.openai_adapter import (
    JsonSchemaFormat,
    OpenAIResponsesAdapter,
    _build_request_body,
)
from juli_backend.services.content_cards import (
    candidates,
    copy,
    guardrails,
    prompts,
    run_state,
    schemas,
)
from juli_backend.services.content_cards import measurement as content_measurement
from juli_backend.services.content_cards import poll as content_poll
from juli_backend.services.content_cards.drafter import (
    ERROR_CHECKS,
    ERROR_SCHEMA,
    DraftInputs,
    OpenAIContentDrafter,
    outcome_from_text,
)

# --- candidates ------------------------------------------------------------------------


def _video_table(rows: list[dict[str, Any]], prior: float = 0.032) -> dict[str, Any]:
    return {
        "stream": "seller_video",
        "metric": "ctr",
        "stream_prior": prior,
        "windows": {"prior": ["2026-08-11", "2026-09-09"], "last": ["2026-09-10", "2026-10-09"]},
        "down": rows,
        "up": [],
        "closing": {},
    }


def _row(rid, rate, quantity, gmv, products, name="Video"):
    return {
        "id": rid,
        "name": name,
        "gmv_per_day": gmv,
        "confidence": "Rõ",
        "prior": 0.032,
        "last": rate,
        "quantity_prior": None,
        "quantity_last": quantity,
        "date": "2026-09-27",
        "product_ids": products,
    }


def test_a_falling_video_ctr_makes_a_video_card_with_d22_expected_gmv():
    # 2 249 clicks at 1,9 % = 118 368 impressions; loss 56 000 ₫/day.
    table = _video_table([_row("v1", 0.019, 2249, -56_000, ["p1"], "Trước và sau")])
    (card,) = candidates.candidates_from_ranking(table, "video")
    assert card.tiktok_product_id == "p1"
    assert card.current == pytest.approx(0.019)
    assert card.target == pytest.approx(0.032)
    assert card.volume == pytest.approx(118_368, rel=1e-3)
    assert card.recoverable_gmv_per_day == pytest.approx(56_000)
    assert card.as_of == "2026-10-09"
    assert "118k lượt hiển thị" in copy.reason_full(card)
    assert "CTR 1,9 % so với 3,2 %" in copy.reason_full(card)


def test_too_few_impressions_rows_above_the_prior_and_gains_make_no_card():
    table = _video_table(
        [
            _row("small", 0.01, 5, -100, ["p1"]),  # 500 impressions < 1 000
            _row("above", 0.04, 500, -10, ["p2"]),  # rate above the prior
            _row("gain", 0.02, 500, 5_000, ["p3"]),  # not a loss
            _row("no-product", 0.02, 500, -5_000, []),
        ]
    )
    assert candidates.candidates_from_ranking(table, "video") == []


def test_a_row_shared_by_two_products_splits_its_loss_and_rows_aggregate_per_product():
    table = _video_table(
        [
            _row("v1", 0.02, 400, -10_000, ["p1", "p2"]),
            _row("v2", 0.01, 200, -30_000, ["p1"]),
        ]
    )
    cards = {c.tiktok_product_id: c for c in candidates.candidates_from_ranking(table, "video")}
    assert cards["p1"].recoverable_gmv_per_day == pytest.approx(35_000)
    assert cards["p2"].recoverable_gmv_per_day == pytest.approx(5_000)
    # p1: (400 + 200) clicks over (20 000 + 20 000) impressions.
    assert cards["p1"].current == pytest.approx(600 / 40_000)
    assert [r.row_id for r in cards["p1"].rows] == ["v1", "v2"]
    ranked = candidates.candidates_from_ranking(table, "video")
    assert [c.tiktok_product_id for c in ranked] == ["p1", "p2"]


def test_a_live_ctor_row_makes_a_live_card_from_orders_and_ctor():
    table = {
        "stream": "seller_live",
        "metric": "ctor",
        "stream_prior": 0.075,
        "down": [_row("s1", 0.059, 30, -30_000, ["p9"], "LIVE xả kho")],  # 508 clicks
        "up": [],
    }
    (card,) = candidates.candidates_from_ranking(table, "live")
    assert card.kind == "live" and card.spec.lever_code == "live_script"
    assert card.volume == pytest.approx(30 / 0.059)
    assert "CTOR 5,9 % so với 7,5 %" in copy.reason_full(card)


def test_a_table_of_the_wrong_stream_or_without_a_prior_is_ignored():
    assert (
        candidates.candidates_from_ranking({"stream": "seller_live", "stream_prior": 0.1}, "video")
        == []
    )
    assert (
        candidates.candidates_from_ranking(
            {"stream": "seller_video", "stream_prior": None}, "video"
        )
        == []
    )
    assert candidates.candidates_from_ranking(None, "video") == []


def test_product_rate_reads_the_products_current_rate_for_withdrawal():
    table = _video_table([_row("v1", 0.02, 400, -10_000, ["p1"])])
    assert candidates.product_rate(table, "p1") == pytest.approx(0.02)
    assert candidates.product_rate(table, "nope") is None


# --- schemas and guardrails ---------------------------------------------------------------

FACTS = guardrails.DraftFacts(
    product_label="MN-015",
    product_title="Mặt nạ đất sét 100g",
    prices_vnd=(69_000,),
    inventory=50,
    basket_skus=("SM-012", "MN-015", "TN-021"),
)
RULES = guardrails.ContentRules(
    tone="thân thiện, xưng mình",
    banned_terms=("đắt",),
    protected_terms=("Hoa Mai",),
    discount_cap_pct=10,
)


def _video(**over: Any) -> dict[str, Any]:
    script = {
        "hook_options": [
            "Lỗ chân lông to sau 1 tuần dùng cái này",
            "Mình thử mặt nạ 69k này 7 ngày",
        ],
        "scenes": [
            {
                "t_from": 0,
                "t_to": 3,
                "visual": "Cận mặt",
                "voiceover": "Lỗ chân lông to?",
                "on_screen": "7 ngày",
            },
            {
                "t_from": 3,
                "t_to": 15,
                "visual": "Đắp mặt nạ",
                "voiceover": "Đắp 10 phút.",
                "on_screen": "10 phút",
            },
            {
                "t_from": 15,
                "t_to": 28,
                "visual": "Rửa mặt",
                "voiceover": "So sánh trước sau.",
                "on_screen": "Trước / sau",
            },
        ],
        "cta": "Bấm giỏ vàng, giá 69k hôm nay",
        "hashtags": ["#matnadatset", "#skincare"],
        "music_hint": "nhạc nhẹ, nhịp vừa",
        "product_on_screen_by_s": 2,
    }
    script.update(over)
    return script


def _live(**over: Any) -> dict[str, Any]:
    plan = {
        "opening": "Màu đỏ ruby đang hết hàng, hôm nay shop còn 50 thỏi",
        "show": "Thoa trên môi và tay dưới 2 loại ánh sáng",
        "close": "Chốt trong 10 phút, ghim ngay lúc nói giá",
        "offer": {
            "type": "flash_sale",
            "discount_pct": 8,
            "text": "Flash sale trong LIVE giảm 8 %",
        },
        "basket_order": [
            {"position": 1, "sku": "SM-012", "pin_at": "khi nói giá"},
            {"position": 2, "sku": "MN-015", "pin_at": ""},
        ],
    }
    plan.update(over)
    return plan


def _video_verdict(script: dict[str, Any], rules=RULES, facts=FACTS):
    return guardrails.check_video(schemas.VideoScript.model_validate(script), facts, rules)


def test_the_json_schemas_are_strict_structured_output_shapes():
    for schema in (schemas.VIDEO_SCRIPT_SCHEMA, schemas.LIVE_PLAN_SCHEMA):
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
    assert set(schemas.VIDEO_SCRIPT_SCHEMA["required"]) == {
        "hook_options",
        "scenes",
        "cta",
        "hashtags",
        "music_hint",
        "product_on_screen_by_s",
    }
    assert set(schemas.LIVE_PLAN_SCHEMA["required"]) == {
        "opening",
        "show",
        "close",
        "offer",
        "basket_order",
    }
    scene = schemas.VIDEO_SCRIPT_SCHEMA["properties"]["scenes"]["items"]
    assert set(scene["required"]) == {"t_from", "t_to", "visual", "voiceover", "on_screen"}


def test_a_good_video_script_passes_every_check():
    verdict = _video_verdict(_video())
    assert verdict.ok, verdict.to_json()
    assert [c["label"] for c in verdict.to_json()] == [
        "không có từ cấm",
        "giữ từ bảo vệ của bạn",
        "đúng thông tin sản phẩm",
        "trong trần giảm giá",
        "độ dài phù hợp",
    ]


@pytest.mark.parametrize(
    ("over", "failed"),
    [
        ({"cta": "Cam kết 100 % hết mụn, bấm giỏ"}, "banned"),
        ({"cta": "Không hề đắt, bấm giỏ"}, "banned"),  # the seller's banned word
        ({"cta": "Shop hoa mai bán chính hãng"}, "protected"),  # respelled protected term
        ({"cta": "Giá chỉ 59k hôm nay"}, "facts"),  # a price the product does not have
        ({"cta": "Giảm 30 % hôm nay"}, "discount"),  # over the 10 % cap
        ({"product_on_screen_by_s": 6}, "length"),
        ({"hook_options": ["Chỉ một hook"]}, "length"),
        ({"hashtags": ["không có dấu thăng"]}, "length"),
    ],
)
def test_a_video_script_that_breaks_a_rule_fails_that_check(over, failed):
    verdict = _video_verdict(_video(**over))
    assert not verdict.ok
    assert failed in {c.key for c in verdict.failures()}


def test_a_hook_over_twelve_words_and_a_too_long_video_fail():
    long_hook = " ".join(["từ"] * 13)
    assert not _video_verdict(_video(hook_options=[long_hook, "ngắn"])).ok
    scenes = _video()["scenes"]
    scenes[-1] = {**scenes[-1], "t_to": 90}
    assert "length" in {c.key for c in _video_verdict(_video(scenes=scenes)).failures()}


def test_the_live_plan_offer_stays_within_the_cap_and_the_basket_puts_the_product_first():
    facts = guardrails.DraftFacts(
        product_label="SM-012",
        product_title="Son môi số 12",
        prices_vnd=(199_000,),
        inventory=50,
        basket_skus=("SM-012", "MN-015"),
    )
    ok = guardrails.check_live(schemas.LivePlan.model_validate(_live()), facts, RULES)
    assert ok.ok, ok.to_json()
    over = _live(offer={"type": "flash_sale", "discount_pct": 15, "text": "Giảm 15 %"})
    assert "discount" in {
        c.key
        for c in guardrails.check_live(
            schemas.LivePlan.model_validate(over), facts, RULES
        ).failures()
    }
    no_cap = guardrails.ContentRules(discount_cap_pct=None)
    assert not guardrails.check_live(schemas.LivePlan.model_validate(_live()), facts, no_cap).ok
    wrong_first = _live(basket_order=[{"position": 1, "sku": "MN-015", "pin_at": ""}])
    assert "length" in {
        c.key
        for c in guardrails.check_live(
            schemas.LivePlan.model_validate(wrong_first), facts, RULES
        ).failures()
    }
    stock = _live(opening="Hôm nay shop còn 500 thỏi")  # more than the inventory
    assert "facts" in {
        c.key
        for c in guardrails.check_live(
            schemas.LivePlan.model_validate(stock), facts, RULES
        ).failures()
    }


def test_the_drafter_rejects_non_json_and_unchecked_drafts_before_the_seller_sees_them():
    inputs = DraftInputs(facts=FACTS, rules=RULES)
    bad = outcome_from_text("video", "not json", inputs, version=1, model="m", usage=Usage(1, 1))
    assert bad.error == ERROR_SCHEMA and bad.script is None
    extra = outcome_from_text(
        "video", json.dumps({**_video(), "x": 1}), inputs, version=1, model="m", usage=Usage(1, 1)
    )
    assert extra.error == ERROR_SCHEMA
    breaks = outcome_from_text(
        "video",
        json.dumps(_video(cta="Rẻ nhất thị trường")),
        inputs,
        version=1,
        model="m",
        usage=Usage(1, 1),
    )
    assert breaks.error == ERROR_CHECKS and breaks.script is None
    good = outcome_from_text(
        "video", json.dumps(_video()), inputs, version=1, model="m", usage=Usage(1, 1)
    )
    assert good.ok and good.script["hook_options"][0].startswith("Lỗ chân lông")


# --- prompts ---------------------------------------------------------------------------


def test_the_prompts_carry_the_frame_and_the_sellers_voice_never_juli_s():
    system = prompts.system_prompt("video", RULES)
    for needle in ("HOOK (0–3 giây)", "SETUP", "VALUE", "CTA", "thân thiện, xưng mình", "Mẫu hook"):
        assert needle in system
    assert "Không nói về Juli" in system
    for founder in ("tôi xây Juli", "mình xây Juli", "founder", "Fujiwa", "ICP"):
        assert founder not in system
    live = prompts.system_prompt("live", guardrails.ContentRules())
    assert "ASBC" in live and "chưa đặt giọng văn" in live
    user = prompts.user_prompt(
        "live",
        FACTS,
        RULES,
        performance={"hiện_tại": "5,9 %"},
        product={"description": "x"},
        seo_words=["son lì"],
        examples=[{"tiêu_đề": "LIVE tốt nhất"}],
    )
    data = json.loads(user.split("\n\n", 1)[1].split("\n\nĐây là BẢN 2")[0])
    assert data["sản_phẩm"]["giá_vnd"] == [69_000]
    assert data["quy_tắc_người_bán"]["từ_bảo_vệ"] == ["Hoa Mai"]
    assert data["các_mã_được_dùng_trong_giỏ"] == ["SM-012", "MN-015", "TN-021"]
    second = prompts.user_prompt(
        "video",
        FACTS,
        RULES,
        performance={},
        product={},
        seo_words=[],
        examples=[],
        previous={"cta": "x"},
    )
    assert "BẢN 2" in second


# --- the adapter's structured output ----------------------------------------------------


def test_the_adapter_sends_text_format_json_schema_only_when_asked():
    plain = _build_request_body(
        model="m", messages=[], system="s", tools=[], max_output_tokens=10, temperature=0.2
    )
    assert "text" not in plain
    body = _build_request_body(
        model="m",
        messages=[],
        system="s",
        tools=[],
        max_output_tokens=10,
        temperature=0.2,
        response_format=JsonSchemaFormat(name="video_script", schema=schemas.VIDEO_SCRIPT_SCHEMA),
    )
    assert body["text"] == {
        "format": {
            "type": "json_schema",
            "name": "video_script",
            "schema": schemas.VIDEO_SCRIPT_SCHEMA,
            "strict": True,
        }
    }


@pytest.mark.asyncio
async def test_the_openai_drafter_makes_one_structured_call_and_counts_its_tokens(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(_video())}],
                    }
                ],
                "usage": {"input_tokens": 1200, "output_tokens": 400},
            },
        )

    drafter = OpenAIContentDrafter(OpenAIResponsesAdapter(transport=httpx.MockTransport(handler)))
    outcome = await drafter.draft(
        kind="video",
        inputs=DraftInputs(facts=FACTS, rules=RULES),
        version=1,
        previous=None,
        config=LLMConfig(model="gpt-5.4-nano"),
    )
    assert outcome.ok and outcome.usage == Usage(1200, 400)
    assert len(seen) == 1
    assert seen[0]["model"] == "gpt-5.4-nano"
    assert seen[0]["text"]["format"]["type"] == "json_schema"
    assert seen[0]["tools"] == []
    assert seen[0]["max_output_tokens"] >= 2500


# --- the run's script blocks and measurement arithmetic ---------------------------------


def test_the_video_script_becomes_the_artboards_four_blocks():
    blocks = run_state.script_blocks("video", _video(), "MN-015")
    assert [b["label"] for b in blocks] == [
        "Hook (0–3 giây)",
        "Cảnh 2 (3–15 giây)",
        "Cảnh 3 (15–28 giây)",
        "Kêu gọi + gợi ý",
    ]
    assert blocks[0]["text"].startswith("“Lỗ chân lông to sau 1 tuần dùng cái này” · Cận mặt")
    assert "Phương án 2" in blocks[0]["text"]
    assert "#matnadatset #skincare · nhạc nhẹ" in blocks[-1]["text"]
    live = run_state.script_blocks("live", _live(), "SM-012")
    assert [b["label"] for b in live] == [
        "Mở (A · Attention)",
        "Trình diễn (S · Show)",
        "Chốt (B · Benefit + C · Close)",
        "Thứ tự giỏ",
    ]
    assert live[-1]["text"] == "1. SM-012 (ghim khi nói giá) · 2. MN-015"


def test_progress_and_stages_follow_the_p10_labels():
    assert content_measurement.progress_pct(0.019, 0.032, 0.032) == 100
    assert content_measurement.progress_pct(0.019, 0.028, 0.032) == 69
    assert content_measurement.progress_pct(0.019, None, 0.032) is None
    readings = content_poll.apply_video_reading({}, {"days": 3, "new_rate": 0.02})
    assert content_measurement.video_stage(readings) == "waiting"
    readings = content_poll.apply_video_reading(readings, {"days": 8, "new_rate": 0.028})
    assert content_measurement.video_stage(readings) == "day7"
    frozen = readings["day7"]
    readings = content_poll.apply_video_reading(readings, {"days": 14, "new_rate": 0.03})
    assert readings["day7"] == frozen and content_measurement.video_stage(readings) == "final"
    assert content_measurement.live_stage({"sessions": [{}]}) == "day7"
    assert content_measurement.live_stage({"sessions": [{}, {}, {}]}) == "final"
    assert content_measurement.live_totals(
        {"sessions": [{"clicks": 100, "orders": 7}, {"clicks": 50, "orders": 4}]}
    ) == (150, 11, pytest.approx(11 / 150))
