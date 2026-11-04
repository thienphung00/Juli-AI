"""The vocabulary of a recommendation card: families, change kinds and what each one means.

Contract section 12 (families) and section 8 (critical metric -> allowed kinds). One
:class:`KindSpec` per ``change_kind`` says which family it belongs to, which metric it is
predicted to move, which ADR-118 proposal kind / read-back kind / simulation kind it maps to,
and which Seller Centre page carries it (assisted execution, p90-plan "Assisted execution").

Nothing here computes a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FAMILIES: tuple[str, ...] = (
    "ads",
    "promotion",
    "voucher",
    "sale",
    "combo",
    "affiliate",
    "listing",
    "mega_sale",
)
FAMILY_LABELS: dict[str, str] = {
    "ads": "Quảng cáo",
    "promotion": "Khuyến mãi / giá",
    "voucher": "Voucher",
    "sale": "Flash Sale / chương trình Shopee",
    "combo": "Combo / mua kèm",
    "affiliate": "Tiếp thị liên kết",
    "listing": "Tên, từ khoá, ảnh bìa",
    "mega_sale": "Chiến dịch lớn (mega sale)",
}

#: Target metrics a lift is predicted on. ``ads_gmv`` = direct revenue of the ad (placed
#: orders, labelled so); ``none`` = no volume effect is predicted (the certain layer alone).
METRICS: tuple[str, ...] = ("views", "ctr", "ctor", "aov", "orders", "ads_gmv", "roas", "none")


@dataclass(frozen=True)
class Page:
    """Where in Seller Centre the change is made (a person clicks Shopee's own Save)."""

    label: str
    path: str | None  # ``/portal/...`` as recon-verified; None = not verified yet
    verified: bool = True


@dataclass(frozen=True)
class Slider:
    """One what-if input the seller can move. ``default`` is the generator's choice; the
    acceptance statistics may move it (never an effect estimate)."""

    key: str
    label: str
    unit: str  # "vnd" | "pct" | "count" | "days" | "roas"
    minimum: float
    maximum: float
    step: float


@dataclass(frozen=True)
class KindSpec:
    key: str
    family: str
    label: str
    proposal_kind: str  # shop_proposals.KINDS
    subject_type: str  # item | shop | campaign
    target_metric: str
    page: Page
    #: ``card_events.verification`` change kind, None when no reader exists yet.
    verify_kind: str | None = None
    #: ``juli-sim/priors/v1`` change kind, None when the simulation does not cover it.
    sim_kind: str | None = None
    #: (P10, P90) relative lift on ``target_metric`` for a "medium" gap.
    prior: tuple[float, float] = (0.02, 0.10)
    #: True: the prior is per 1 % price change (price levers), not a flat range.
    price_scaled: bool = False
    sliders: tuple[Slider, ...] = field(default=())


_ADS = Page("Marketing › Quảng cáo Shopee", "/portal/marketing/pas/index")
_VOUCHER = Page("Marketing › Voucher của tôi", "/portal/marketing/vouchers/list")
_DISCOUNT = Page("Marketing › Chương trình giảm giá", "/portal/marketing/list/discount")
_FLASH = Page("Marketing › Flash Sale của shop", "/portal/marketing/shop-flash-sale/list")
_AFFILIATE = Page("Tiếp thị liên kết", "/portal/web-seller-affiliate/homepage")
_PRODUCT = Page("Sản phẩm › Tất cả sản phẩm", "/portal/product/list/all")
_COMBO = Page("Marketing › Combo khuyến mãi", None, verified=False)
_ADD_ON = Page("Marketing › Mua kèm deal sốc", None, verified=False)
_PROGRAMME = Page("Marketing › Chương trình của Shopee", None, verified=False)
#: Keyword roles are Juli's own key list (ADR-120 d.11), kept in Juli Ops, not in Seller Centre.
_JULI_KEYWORDS = Page("Juli › Từ khoá của sản phẩm", None, verified=False)

_S = Slider
KINDS: dict[str, KindSpec] = {
    # ---- ads
    "ads_budget": KindSpec(
        "ads_budget",
        "ads",
        "Đổi ngân sách ngày",
        "ads",
        "campaign",
        "ads_gmv",
        _ADS,
        verify_kind="daily_budget",
        prior=(0.03, 0.25),
        sliders=(_S("daily_budget", "Ngân sách / ngày", "vnd", 0, 100_000_000, 10_000),),
    ),
    "ads_roas_target": KindSpec(
        "ads_roas_target",
        "ads",
        "Đổi ROAS mục tiêu",
        "ads",
        "campaign",
        "roas",
        _ADS,
        verify_kind="roas_target",
        prior=(0.02, 0.15),
        sliders=(_S("roas_target", "ROAS mục tiêu", "roas", 1, 50, 0.1),),
    ),
    "ads_purpose": KindSpec(
        "ads_purpose",
        "ads",
        "Đặt mục đích chiến dịch",
        "ads",
        "campaign",
        "none",
        _ADS,
        prior=(0, 0),
    ),
    "ads_pause": KindSpec(
        "ads_pause",
        "ads",
        "Tạm dừng chiến dịch",
        "ads",
        "campaign",
        "ads_gmv",
        _ADS,
        prior=(-0.9, -0.4),
    ),
    "ads_add_product": KindSpec(
        "ads_add_product",
        "ads",
        "Thêm sản phẩm vào chiến dịch nhóm",
        "ads",
        "item",
        "ads_gmv",
        _ADS,
        prior=(0.02, 0.15),
    ),
    "ads_remove_product": KindSpec(
        "ads_remove_product",
        "ads",
        "Gỡ sản phẩm khỏi chiến dịch nhóm",
        "ads",
        "item",
        "ads_gmv",
        _ADS,
        prior=(-0.9, -0.4),
    ),
    # ---- promotion
    "product_discount": KindSpec(
        "product_discount",
        "promotion",
        "Giảm giá sản phẩm",
        "price",
        "item",
        "ctor",
        _DISCOUNT,
        verify_kind="price",
        sim_kind="product_discount",
        price_scaled=True,
        sliders=(_S("discount_pct", "Mức giảm", "pct", 0, 60, 1),),
    ),
    "price": KindSpec(
        "price",
        "promotion",
        "Đổi giá niêm yết",
        "price",
        "item",
        "ctor",
        _PRODUCT,
        verify_kind="price",
        sim_kind="product_discount",
        price_scaled=True,
        sliders=(_S("new_price_pct", "Giá mới so với giá hiện tại", "pct", 50, 150, 1),),
    ),
    # ---- voucher
    "min_spend_voucher": KindSpec(
        "min_spend_voucher",
        "voucher",
        "Voucher đơn tối thiểu",
        "voucher",
        "shop",
        "aov",
        _VOUCHER,
        verify_kind="voucher",
        sim_kind="voucher_min_spend",
        prior=(0.03, 0.12),
        sliders=(
            _S("value", "Giá trị voucher", "vnd", 1_000, 500_000, 1_000),
            _S("max_value", "Mức giảm tối đa", "vnd", 1_000, 500_000, 1_000),
            _S("min_spend", "Đơn tối thiểu", "vnd", 0, 5_000_000, 10_000),
            _S("quantity", "Số lượng voucher", "count", 1, 100_000, 1),
            _S("days", "Số ngày", "days", 1, 90, 1),
        ),
    ),
    "review_voucher": KindSpec(
        "review_voucher",
        "voucher",
        "Voucher tri ân / đánh giá",
        "voucher",
        "shop",
        "ctor",
        _VOUCHER,
        verify_kind="voucher",
        sim_kind="voucher_min_spend",
        prior=(0.01, 0.06),
        sliders=(
            _S("value", "Giá trị voucher", "vnd", 1_000, 500_000, 1_000),
            _S("min_spend", "Đơn tối thiểu", "vnd", 0, 5_000_000, 10_000),
            _S("quantity", "Số lượng voucher", "count", 1, 100_000, 1),
            _S("days", "Số ngày", "days", 1, 90, 1),
        ),
    ),
    "voucher_cap": KindSpec(
        "voucher_cap",
        "voucher",
        "Giảm giá trị / mức tối đa voucher",
        "voucher",
        "shop",
        "ctor",
        _VOUCHER,
        verify_kind="voucher",
        sim_kind="voucher_min_spend",
        prior=(-0.05, 0.0),
        sliders=(
            _S("value", "Giá trị voucher", "vnd", 1_000, 500_000, 1_000),
            _S("quantity", "Số lượng voucher", "count", 1, 100_000, 1),
        ),
    ),
    # ---- sale
    "flash_sale": KindSpec(
        "flash_sale",
        "sale",
        "Đăng ký Flash Sale của shop",
        "flash_sale",
        "item",
        "orders",
        _FLASH,
        sim_kind="flash_sale",
        price_scaled=True,
        sliders=(
            _S("discount_pct", "Mức giảm", "pct", 0, 70, 1),
            _S("units", "Số lượng suất", "count", 1, 100_000, 1),
        ),
    ),
    "program_registration": KindSpec(
        "program_registration",
        "sale",
        "Đăng ký chương trình Shopee",
        "program",
        "item",
        "orders",
        _PROGRAMME,
        price_scaled=True,
        sliders=(
            _S("discount_pct", "Mức giảm", "pct", 0, 70, 1),
            _S("units", "Số lượng", "count", 1, 100_000, 1),
        ),
    ),
    # ---- combo
    "bundle_deal": KindSpec(
        "bundle_deal",
        "combo",
        "Combo khuyến mãi (các bậc)",
        "bundle",
        "item",
        "aov",
        _COMBO,
        sim_kind="combo_pack",
        prior=(0.03, 0.12),
        sliders=(
            _S("tier2_pct", "Giảm khi mua 2", "pct", 0, 50, 1),
            _S("tier3_pct", "Giảm khi mua 3", "pct", 0, 60, 1),
        ),
    ),
    "add_on": KindSpec(
        "add_on",
        "combo",
        "Mua kèm deal sốc",
        "bundle",
        "item",
        "aov",
        _ADD_ON,
        sim_kind="combo_pack",
        prior=(0.02, 0.08),
        sliders=(_S("addon_discount_pct", "Giảm cho món mua kèm", "pct", 0, 60, 1),),
    ),
    "gift": KindSpec(
        "gift",
        "combo",
        "Quà tặng kèm",
        "bundle",
        "item",
        "ctor",
        _ADD_ON,
        sim_kind="combo_pack",
        prior=(0.01, 0.06),
        sliders=(_S("min_spend", "Đơn tối thiểu nhận quà", "vnd", 0, 5_000_000, 10_000),),
    ),
    "variation_set": KindSpec(
        "variation_set",
        "combo",
        "Bộ / quy cách nhiều món",
        "bundle",
        "item",
        "aov",
        _PRODUCT,
        sim_kind="combo_pack",
        prior=(0.03, 0.10),
        sliders=(_S("set_size", "Số món / bộ", "count", 2, 12, 1),),
    ),
    # ---- affiliate
    "affiliate_commission": KindSpec(
        "affiliate_commission",
        "affiliate",
        "Đổi hoa hồng chiến dịch mở",
        "other",
        "item",
        "views",
        _AFFILIATE,
        prior=(0.03, 0.20),
        sliders=(_S("commission_pct", "Hoa hồng", "pct", 0, 50, 0.5),),
    ),
    "affiliate_target_campaign": KindSpec(
        "affiliate_target_campaign",
        "affiliate",
        "Chiến dịch liên kết chỉ định (KOL)",
        "other",
        "item",
        "views",
        _AFFILIATE,
        prior=(0.02, 0.15),
        sliders=(_S("commission_pct", "Hoa hồng", "pct", 0, 50, 0.5),),
    ),
    # ---- P91 D-9 KOL cards (``kol_cards``): one creator, one pitched product
    "affiliate_sample": KindSpec(
        "affiliate_sample",
        "affiliate",
        "Gửi mẫu cho KOL",
        "other",
        "item",
        "orders",
        _AFFILIATE,
        prior=(0.0, 0.0),
        sliders=(
            _S("qty", "Số lượng mẫu", "count", 1, 50, 1),
            _S("commission_pct", "Hoa hồng cho KOL", "pct", 0, 50, 0.5),
        ),
    ),
    "affiliate_invite": KindSpec(
        "affiliate_invite",
        "affiliate",
        "Mời KOL",
        "other",
        "item",
        "orders",
        _AFFILIATE,
        prior=(0.0, 0.0),
        sliders=(_S("commission_pct", "Hoa hồng cho KOL", "pct", 0, 50, 0.5),),
    ),
    # ---- listing (traffic levers: no certain layer, a predicted range only)
    "title": KindSpec(
        "title",
        "listing",
        "Sửa tên sản phẩm",
        "title",
        "item",
        "views",
        _PRODUCT,
        verify_kind="title",
        prior=(0.03, 0.15),
    ),
    "keyword": KindSpec(
        "keyword",
        "listing",
        "Đổi từ khoá Chính",
        "other",
        "item",
        "views",
        _JULI_KEYWORDS,
        prior=(0.02, 0.10),
    ),
    "cover_image": KindSpec(
        "cover_image",
        "listing",
        "Đổi ảnh bìa",
        "images",
        "item",
        "ctr",
        _PRODUCT,
        verify_kind="images",
        prior=(0.02, 0.12),
    ),
    "price_display": KindSpec(
        "price_display",
        "listing",
        "Ghi đơn giá trên ảnh bìa",
        "images",
        "item",
        "ctr",
        _PRODUCT,
        verify_kind="images",
        prior=(0.01, 0.06),
    ),
    # ---- mega sale (composite)
    "mega_sale": KindSpec(
        "mega_sale",
        "mega_sale",
        "Chiến dịch lớn (nhiều thay đổi, một ngân sách)",
        "program",
        "shop",
        "orders",
        _PROGRAMME,
        prior=(0.05, 0.30),
        sliders=(_S("budget_cap_per_day", "Trần chi / ngày", "vnd", 0, 1_000_000_000, 10_000),),
    ),
    # p91 D-3: a combo of 2-3 different products (calculator in ``combo.py``)
    "combo_multi": KindSpec(
        "combo_multi",
        "combo",
        "Combo nhiều sản phẩm",
        "bundle",
        "item",
        "aov",
        _COMBO,
        sim_kind="combo_pack",
        prior=(0.03, 0.12),
    ),
}

#: Contract section 8. Keyed by the critical metric (``services/shopee_analytics/critical.py``
#: ``CHANGE_KINDS``); the generators emit only kinds the metric allows, and the card carries
#: the key it came from. Section 8 names every kind; the generators emit the ones in
#: :data:`KINDS` (the listing family -- title, keyword, cover_image, price_display -- is
#: wired to Lượt xem and CTR).
WIRING: dict[str, tuple[str, ...]] = {
    "views": ("title", "keyword", "ads_budget", "affiliate_commission"),
    "ctr": ("cover_image", "title", "price_display"),
    "ctor": ("product_discount", "min_spend_voucher", "review_voucher", "price"),
    "aov": ("bundle_deal", "add_on", "min_spend_voucher", "variation_set"),
    "bien": ("price", "voucher_cap", "ads_roas_target", "ads_pause"),
    "roas": ("ads_roas_target", "ads_pause", "ads_purpose"),
    "lien_ket": ("affiliate_commission", "affiliate_target_campaign"),
    # not in section 8 (no critical metric of their own): the sale / combo families reach the
    # shop through the same CTOR / AOV metrics plus the explicit sale calendar
    "sale": ("flash_sale", "program_registration"),
}


def spec(kind: str) -> KindSpec:
    try:
        return KINDS[kind]
    except KeyError:
        raise ValueError(f"unknown change_kind {kind!r}") from None


def allowed_for_metric(metric: str) -> tuple[str, ...]:
    """Section 8: the kinds a critical metric may be answered with."""
    return WIRING.get(metric, ())


def kinds_of(family: str) -> tuple[str, ...]:
    return tuple(k for k, s in KINDS.items() if s.family == family)
