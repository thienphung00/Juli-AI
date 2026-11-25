"""Per-platform label tables (U10b). Shopee is a table; TikTok's sources come from the metric
registry."""

from __future__ import annotations

from juli_backend.services.analytics_agent.types import LabelTable

SHOPEE_SOURCES = {
    "the_san_pham_khac": "Thẻ sản phẩm",
    "trang_shop": "Trang shop",
    "video": "Video",
    "live": "LIVE",
    "lien_ket": "Tiếp thị liên kết",
    "chenh_lech_nguon": "Chênh lệch nguồn",
    "ads": "Quảng cáo",
    "ads_product": "Dịch vụ hiển thị Sản phẩm",
    "ads_shop": "Dịch vụ hiển thị Shop+",
    "the_san_pham": "Thẻ sản phẩm",
}
METRICS_VI = {
    "gmv": "GMV",
    "orders": "Đơn hàng",
    "aov": "AOV",
    "units": "Sản phẩm bán",
    "views": "Lượt xem",
    "clicks": "Lượt click",
    "ctr": "CTR",
    "ctor": "CTOR",
    "profit": "Lợi nhuận",
    "margin": "Biên lợi nhuận",
    "ads_spend": "Chi phí quảng cáo",
    "roas": "ROAS",
    "roas_break_even": "ROAS hoà vốn",
    "product_profit": "Lợi nhuận sản phẩm",
    "ads_no_order_days": "Quảng cáo ngày không có đơn",
    "other_marketing": "Marketing khác",
    "net_revenue": "Doanh thu thực",
    "ads_gmv": "GMV quảng cáo",
    "cost_ratio": "Tổng chi phí / doanh thu thực",
    "cost_total": "Tổng chi phí",
    "cost_ads": "Quảng cáo",
    "cost_affiliate": "Tiếp thị liên kết",
    "cost_offers": "Ưu đãi",
}
KINDS_VI = {
    "product_discount": "Chương Trình Của Shop",
    "price": "Giá",
    "min_spend_voucher": "Mã Giảm Giá",
    "review_voucher": "Mã Giảm Giá",
    "voucher_cap": "Giới hạn voucher",
    "flash_sale": "Flash Sale Của Shop",
    "program_registration": "Chương trình Shopee",
    "bundle_deal": "Combo Khuyến Mãi",
    "add_on": "Mua Kèm Deal Sốc",
    "gift": "Mua Để Nhận Quà",
    "variation_set": "Phân loại hàng",
    "ads_budget": "Ngân sách quảng cáo",
    "ads_roas_target": "ROAS mục tiêu quảng cáo",
    "ads_pause": "Tạm dừng quảng cáo",
    "ads_purpose": "Mục tiêu quảng cáo",
    "ads_add_product": "Thêm sản phẩm vào quảng cáo",
    "ads_remove_product": "Gỡ sản phẩm khỏi chiến dịch nhóm",
    "ads_new_campaign": "Chiến dịch quảng cáo mới",
    "ads_keywords": "Từ khoá và giá thầu quảng cáo",
    "title": "Tên sản phẩm",
    "description_first_line": "Mô tả sản phẩm",
    "keyword": "Từ khoá",
    "cover_image": "Ảnh bìa",
    "price_display": "Hiển thị giá",
    "affiliate_commission": "Hoa hồng tiếp thị liên kết",
    "affiliate_target_campaign": "Chiến dịch tiếp thị liên kết mục tiêu",
    "affiliate_invite": "Mời KOL",
    "affiliate_sample": "Gửi mẫu cho KOL",
    "combo_multi": "Combo Khuyến Mãi nhiều sản phẩm",
    "mega_sale": "Chiến dịch lớn",
    "variation_restructure": "Gom lại phân loại",
}


def shopee_labels() -> LabelTable:
    return LabelTable("shopee", dict(SHOPEE_SOURCES), dict(METRICS_VI), dict(KINDS_VI))


def tiktok_labels() -> LabelTable:
    """Only the traffic sources the registry says TikTok has; anything else renders "Khác"."""
    from juli_backend.services.metrics.registry import TRAFFIC_SOURCES, Platform

    keep = {k for k, spec in TRAFFIC_SOURCES.items() if Platform.tiktok in spec.available_on}
    sources = {k: v for k, v in SHOPEE_SOURCES.items() if k in keep}
    return LabelTable("tiktok", sources, dict(METRICS_VI), dict(KINDS_VI))


def labels_for(platform: str) -> LabelTable:
    return tiktok_labels() if platform == "tiktok" else shopee_labels()
