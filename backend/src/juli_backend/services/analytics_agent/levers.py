"""The finding -> lever table (decision #52): DATA, not rules.

A *finding* is something a tool can surface; its *levers* are the card kinds (ids from
`shopee_recommendations.kinds.KINDS`) the model may choose to act on it. The table is used for
three things only: the `emit_plan` lever enum, the tags a tool result carries, and the check that
a chosen lever is a real card kind. Code never decides which lever answers a finding (#53): the
model chooses, the schema and `advisor.render` validate.

`levers == ()` means the finding goes to the lead line, never to the action list.
Labels hold no digits (they sit in the tool results, which are the fact set for the number check).
"""

from __future__ import annotations

from dataclasses import dataclass

from juli_backend.services.shopee_recommendations.kinds import KINDS

#: Out of the lever set (owner #53): the builder dropped hide / relist / listing combo.
OUT_LEVERS: frozenset[str] = frozenset({"listing_hide", "listing_relist", "listing_combo"})
#: A lever that is an action but not a card: label by lever id. Exempt from the card check.
NON_CARD_LEVERS: dict[str, str] = {"nhap_gia_von": "Nhập giá vốn"}
CARD_EXEMPT: frozenset[str] = frozenset(NON_CARD_LEVERS)


@dataclass(frozen=True)
class Finding:
    key: str
    label_vi: str
    levers: tuple[str, ...]  # () = lead line only
    tools: tuple[str, ...]  # the tools whose result may carry this finding


def _f(key: str, label: str, tools: str, *levers: str) -> Finding:
    return Finding(key, label, tuple(levers), tuple(t.strip() for t in tools.split(",")))


FINDINGS: tuple[Finding, ...] = (
    _f(
        "camp_below_break_even",
        "Chiến dịch ROAS dưới ROAS hoà vốn (lỗ sau quảng cáo)",
        "campaigns",
        "ads_roas_target",
        "ads_budget",
        "ads_pause",
    ),
    _f(
        "camp_thin",
        "Chiến dịch lãi nhưng ROAS sát ROAS hoà vốn",
        "campaigns",
        "ads_roas_target",
        "ads_budget",
    ),
    _f(
        "camp_clear_profit",
        "Chiến dịch lãi rõ, ROAS cao hơn hoà vốn nhiều",
        "campaigns",
        "ads_budget",
        "ads_roas_target",
        "ads_purpose",
    ),
    _f(
        "product_loss_after_ads",
        "Sản phẩm lỗ sau quảng cáo",
        "product_profit, product_margins",
        "ads_remove_product",
        "ads_pause",
    ),
    _f(
        "product_ads_no_contribution",
        "Sản phẩm còn chi quảng cáo nhưng đóng góp trước quảng cáo bằng không hoặc deal đã hết hạn",
        "product_profit, product_margins",
        "ads_remove_product",
        "title",
    ),
    _f(
        "idle_budget_days",
        "Ngày chi dưới ngân sách và không có đơn quảng cáo",
        "idle_budget_days",
        "ads_budget",
        "ads_roas_target",
    ),
    _f(
        "budget_far_from_spend",
        "Ngân sách ngày đặt xa chi thực tế (không nên tăng)",
        "campaigns, idle_budget_days",
        "ads_budget",
    ),
    _f(
        "title_names_ended_deal", "Tên sản phẩm còn ghi deal đã hết hạn", "product_margins", "title"
    ),
    _f(
        "ended_deal_price_running",
        "Giá deal hoặc giảm giá đã qua ngày sale vẫn còn chạy",
        "product_margins, product_profit",
        "price",
        "product_discount",
    ),
    _f(
        "big_product_margin_drop",
        "Sản phẩm chiếm tỉ trọng GMV lớn và biên giảm mạnh",
        "product_margins",
        "price",
        "product_discount",
        "bundle_deal",
    ),
    _f(
        "cogs_gap",
        "Thiếu giá vốn đáng kể so với GMV (lợi nhuận không đáng tin)",
        "cogs_gaps",
        "nhap_gia_von",
    ),
    _f(
        "organic_drop",
        "Lượt xem hoặc GMV Organic giảm",
        "traffic_sources",
        "title",
        "keyword",
        "cover_image",
    ),
    _f(
        "product_card_channel_grows",
        "Thẻ sản phẩm là kênh lớn và đang tăng",
        "traffic_sources",
        "ads_new_campaign",
        "ads_add_product",
    ),
    _f(
        "affiliate_low",
        "Tiếp thị liên kết thấp so với Thẻ sản phẩm",
        "traffic_sources",
        "affiliate_commission",
        "affiliate_target_campaign",
        "affiliate_invite",
        "affiliate_sample",
    ),
    _f(
        "affiliate_pending_on_loss",
        "Hoa hồng liên kết đang chờ trên sản phẩm lỗ hoặc deal hết hạn",
        "open_cards, product_profit",
        "affiliate_commission",
    ),
    _f("ads_channel_no_baseline", "Kênh Quảng cáo không có số so sánh", "traffic_sources"),
    _f(
        "low_aov",
        "Giá trị đơn thấp hoặc đơn một món",
        "metric_view",
        "min_spend_voucher",
        "bundle_deal",
        "add_on",
        "variation_set",
    ),
    _f(
        "low_ctor",
        "Nhiều lượt xem, ít chốt đơn (CTOR thấp)",
        "metric_view",
        "review_voucher",
        "product_discount",
        "description_first_line",
        "cover_image",
    ),
    _f(
        "low_ctr",
        "CTR thấp (ảnh bìa, giá hiển thị, tên)",
        "metric_view",
        "cover_image",
        "price_display",
        "title",
    ),
    _f(
        "sale_day_ahead",
        "Sắp tới ngày sale trong lịch hoặc mega sale",
        "week_summary",
        "flash_sale",
        "program_registration",
        "mega_sale",
        "min_spend_voucher",
    ),
    _f(
        "sale_day_in_window",
        "Kỳ này có ngày sale kéo GMV (không dùng làm nền so sánh)",
        "week_summary",
    ),
    _f("gmv_concentration", "GMV tập trung vào một sản phẩm (rủi ro phụ thuộc)", "product_margins"),
    _f(
        "combo_opportunity",
        "Cơ hội combo: sản phẩm hay mua cùng nhau",
        "metric_view, open_cards",
        "bundle_deal",
        "combo_multi",
        "add_on",
    ),
    _f("open_card_duplicate", "Có thẻ Đề xuất đang mở trùng việc cần làm", "open_cards"),
    _f(
        "data_too_thin",
        "Dữ liệu thiếu hoặc không đủ căn cứ (chi quảng cáo rất nhỏ, chưa có hoà vốn)",
        "campaigns, product_profit",
    ),
)
FINDING_BY_KEY: dict[str, Finding] = {f.key: f for f in FINDINGS}


def lever_enum(available: object = None) -> list[str]:
    """The levers `emit_plan` accepts: `kinds.py` kinds minus the out-set (limited to the kinds
    the platform's label table knows when given), plus the non-card actions. Stable order."""
    allowed = None if available is None else set(available)  # type: ignore[call-overload]
    cards = [k for k in KINDS if k not in OUT_LEVERS and (allowed is None or k in allowed)]
    return [*cards, *NON_CARD_LEVERS]


def card_kinds(available: object = None) -> list[str]:
    """The kinds `draft_card` may create (the lever enum without the non-card actions)."""
    return [k for k in lever_enum(available) if k not in NON_CARD_LEVERS]


def tags_for(tool: str) -> list[dict[str, object]]:
    """The finding tags a tool result carries: what may be found there and the levers the table
    allows for it. A finding with no lever says so (it belongs in the lead line)."""
    out: list[dict[str, object]] = []
    for f in FINDINGS:
        if tool in f.tools:
            out.append(
                {"phát_hiện": f.label_vi, "lever": list(f.levers)}
                if f.levers
                else {"phát_hiện": f.label_vi, "lever": "không có: chỉ ghi ở lead"}
            )
    return out


def check_table() -> list[str]:
    """Problems in the table: a lever that is neither a kind nor a non-card action, or one in
    the out-set. Used by a test (and cheap enough to call at import)."""
    bad = []
    for f in FINDINGS:
        for lv in f.levers:
            if lv in OUT_LEVERS or (lv not in KINDS and lv not in NON_CARD_LEVERS):
                bad.append(f"{f.key}:{lv}")
    return bad
