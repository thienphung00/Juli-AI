"""Prompt templates of the content drafts (D24.19).

Adapted from the juli-content-engine's generic rules — ``content/strategy/
voice.md`` (the hook-pattern table, "Do" / "Don't", on-screen text) and
``PLAYBOOK.md`` Part 4 (the HOOK / SETUP / VALUE / CTA script frame) — and
rewritten for the SELLER's product and voice: the seller's tone and banned
words (Quy tắc) and the shop's own best-performing videos / LIVE sessions as
examples. Never Juli's founder voice, ICP or any other shop's data: the only
facts in the prompt are this shop's product and numbers, read in this run.

The model writes words only. It never produces a number of its own: every
number it may use is listed under DỮ LIỆU, and ``guardrails`` rejects a price,
stock count or discount that is not there.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from juli_backend.services.content_cards.constants import VIDEO, ContentKind
from juli_backend.services.content_cards.guardrails import (
    MAX_HOOK_WORDS,
    PRODUCT_ON_SCREEN_BY_S,
    ContentRules,
    DraftFacts,
)

PROMPT_VERSION = "p15-content-prompt-v2"

_COMMON_RULES = """\
Bạn viết kịch bản cho NGƯỜI BÁN trên TikTok Shop Việt Nam, bằng giọng của chính người bán đó.
Bạn chỉ viết chữ. Trả về đúng một tài liệu JSON theo schema được yêu cầu, không thêm gì khác.

Giọng văn (áp dụng cho mọi kịch bản):
- Mở bằng một khẳng định, một con số có trong DỮ LIỆU hoặc một vấn đề người xem gặp
  — không mở bằng "Xin chào mọi người".
- Mỗi câu một ý. Câu ngắn, đọc to được, đọc lướt được.
- Giữ nguyên các từ tiếng Anh người bán vẫn dùng (CTR, voucher, flash sale, combo, sale).
- Một hành động duy nhất ở cuối.
- Tối đa ba ý cho một kịch bản. Ba ý, hoặc một ý.
- Không hứa lượt xem, không hứa doanh số, không nói "thuật toán".
- Không "các bạn ơi", "hãy follow để không bỏ lỡ", "cảm ơn các bạn đã theo dõi", "hẹn gặp lại".
- Không nói về Juli, không nói về công cụ, không xưng là người xây phần mềm.
- Không dùng lời quảng cáo bị cấm: cam kết 100 %, tốt nhất, số 1, rẻ nhất, chữa khỏi,
  trị dứt điểm, thần kỳ.
- Chỉ dùng con số có trong DỮ LIỆU (giá, số lượng tồn, trần giảm giá). Không tự đặt con số mới.
- Viết đúng chính tả từng từ trong "từ bảo vệ" của người bán, không đổi cách viết.
- Không dùng từ nào trong "từ cấm" của người bán.

Mẫu hook (chọn mẫu hợp với sản phẩm, đừng xoay vòng máy móc):
| Mẫu | Hình dạng |
|---|---|
| Lỗi thường gặp | "Đừng … khi …" — một lỗi người mua hay mắc với loại sản phẩm này |
| Trước / sau | Kết quả nhìn thấy được, cùng ánh sáng, cùng góc máy |
| Câu hỏi đúng nỗi đau | "… mà vẫn …?" — gọi đúng vấn đề người xem đang có |
| Con số cụ thể | Một con số có trong DỮ LIỆU (giá, dung tích, thời gian dùng) |
| Thử N ngày | Dùng thật trong vài ngày, mỗi ngày một cảnh ngắn |
| So sánh | Đặt cạnh một lựa chọn khác người xem quen, không nêu tên thương hiệu khác |
"""

_VIDEO_FRAME = f"""\
Kịch bản VIDEO ngắn 25–35 giây, khung bốn nhịp (mỗi nhịp là một hoặc hai cảnh trong "scenes"):
- HOOK (0–3 giây): một khẳng định, xem không tiếng vẫn hiểu. Chữ trên màn hình (on_screen) bắt buộc.
- SETUP (3–9 giây): gọi tên vấn đề, làm nó thành vấn đề của người xem.
- VALUE (9–25 giây): điều thật sự có giá trị, 1–3 điểm cụ thể, sản phẩm trong tay.
- CTA (25–30 giây): một hành động — bấm giỏ hàng vàng.
Quy tắc:
- "hook_options": đúng 2 phương án mở đầu khác nhau, mỗi phương án ≤ {MAX_HOOK_WORDS} từ.
- "scenes": bắt đầu từ t_from = 0, liên tục, kết thúc trong 25–35 giây.
- "on_screen" là bản rút gọn, không lặp nguyên câu "voiceover".
- "voiceover" là đúng lời người bán sẽ nói.
- Sản phẩm (và giỏ hàng) xuất hiện trước giây {PRODUCT_ON_SCREEN_BY_S:g}:
  đặt "product_on_screen_by_s" ≤ {PRODUCT_ON_SCREEN_BY_S:g}.
- "hashtags": 2–5 hashtag bắt đầu bằng #, không dấu cách, gần với từ khoá trong DỮ LIỆU.
- "music_hint": gợi ý kiểu nhạc (nhịp, cảm giác), không nêu tên bài hát cụ thể.
Kịch bản này nhằm tăng CTR: người xem bấm vào sản phẩm từ video.
"""

_LIVE_FRAME = """\
Kịch bản HOST cho một phiên LIVE, khung ASBC, cho đúng sản phẩm trong DỮ LIỆU:
- "opening" (A · Attention): câu mở giữ người xem ở lại khi sản phẩm được ghim.
- "show" (S · Show): cách trình diễn sản phẩm trước camera, có so sánh giá hoặc so sánh dùng thử.
- "close" (B · Benefit + C · Close): lợi ích chính, ưu đãi, giới hạn thời gian hoặc số lượng
  (chỉ số lượng có trong DỮ LIỆU), lời chốt đơn.
- "offer": ưu đãi trong LIVE. "discount_pct" không vượt "trần giảm giá"; nếu người bán
  chưa đặt trần giảm giá thì "discount_pct" = null và "type" là "gift", "voucher"
  (không giảm %) hoặc "none".
- "basket_order": thứ tự giỏ, vị trí 1 là sản phẩm chính trong DỮ LIỆU, chỉ dùng mã trong
  "các mã được dùng trong giỏ"; "pin_at" là thời điểm ghim (ví dụ "khi nói giá", "phút đầu").
Kịch bản này nhằm tăng CTOR: người xem đã bấm vào sản phẩm thì chốt đơn.
"""


def system_prompt(kind: ContentKind, rules: ContentRules) -> str:
    """The instructions: generic voice rules + the kind's frame + the seller's own tone."""
    tone = rules.tone.strip() if rules.tone and rules.tone.strip() else None
    seller = (
        f"\nGiọng riêng của người bán (Quy tắc): {tone}\n"
        if tone
        else "\nNgười bán chưa đặt giọng văn: viết thân thiện, rõ ràng, như người bán tự nói.\n"
    )
    frame = _VIDEO_FRAME if kind == VIDEO else _LIVE_FRAME
    return f"{_COMMON_RULES}\n{frame}{seller}"


def _clip(text: str | None, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def user_prompt(
    kind: ContentKind,
    facts: DraftFacts,
    rules: ContentRules,
    *,
    performance: Mapping[str, Any],
    product: Mapping[str, Any],
    seo_words: Sequence[str],
    examples: Sequence[Mapping[str, Any]],
    previous: Mapping[str, Any] | None = None,
    analyses: Sequence[Mapping[str, Any]] = (),
) -> str:
    """The data: this shop's product, numbers, rules and its own best content.

    ``analyses`` (P15): what Juli found in the seller's own uploaded videos of
    this product -- the best and the weakest by TikTok's rate. Added only when
    there is one, so a shop without uploads gets the P14 prompt unchanged.
    """
    data: dict[str, Any] = {
        "sản_phẩm": {
            "tên": facts.product_title,
            "mã": facts.product_label,
            "mô_tả_rút_gọn": _clip(product.get("description"), 600),
            "giá_vnd": list(facts.prices_vnd),
            "tồn_kho": facts.inventory,
        },
        "từ_khoá_tiktok": list(seo_words)[:10],
        "số_liệu": dict(performance),
        "nội_dung_tốt_nhất_của_shop": list(examples)[:3],
        "quy_tắc_người_bán": {
            "từ_cấm": list(rules.banned_terms),
            "từ_bảo_vệ": list(rules.protected_terms),
            "trần_giảm_giá_pct": rules.discount_cap_pct,
        },
    }
    if kind != VIDEO:
        data["các_mã_được_dùng_trong_giỏ"] = list(facts.basket_skus)
    if analyses:
        data["phân_tích_video_của_người_bán"] = [dict(a) for a in analyses][:2]
    parts = [
        "DỮ LIỆU (chỉ dùng những gì có ở đây):",
        json.dumps(data, ensure_ascii=False, indent=1),
    ]
    if analyses:
        parts.append(
            'Dựa vào "phân_tích_video_của_người_bán": giữ điều video tốt nhất đã làm được, '
            "sửa đúng các vấn đề của video yếu nhất (mở đầu, lúc sản phẩm xuất hiện, lời kêu "
            "gọi, nhịp cắt)."
        )
    if previous:
        parts.append(
            "Đây là BẢN 2. Người bán muốn một hướng khác bản 1 dưới đây: đổi mẫu hook và cách "
            "trình bày, giữ đúng dữ liệu.\nBản 1:\n" + json.dumps(previous, ensure_ascii=False)
        )
    return "\n\n".join(parts)


__all__ = ["PROMPT_VERSION", "system_prompt", "user_prompt"]
