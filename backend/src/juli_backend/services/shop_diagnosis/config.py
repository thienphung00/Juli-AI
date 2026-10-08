"""Every threshold of the shop diagnosis report, in one place — ADR-108.

No module of :mod:`juli_backend.services.shop_diagnosis` carries a literal
threshold; each reads this object. The defaults are ADR-108's: 30 + 30 days
(d.2), the 10 % / 30-order decision-tree gate (d.7), the 90 % interval and the
10 / 30 order floors of the confidence label (d.11), the voucher classes and
the flash-sale flags (d.10), the 7-day rolling timeline (d.9) and the 50 % top-5
coverage warning (d.6).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ShopDiagnosisConfig:
    """Tunable inputs of the shop diagnosis report (CONTEXT.md → Shop diagnosis report)."""

    #: d.2: each comparison window, in days; the snapshot holds two of them.
    window_days: int = 30

    #: d.6: hero products per shop, and the GMV share under which the page says
    #: "shop phân tán, top 5 chưa đại diện".
    hero_count: int = 5
    hero_min_gmv_share: float = 0.50
    #: Listings whose title matches one of these are gifts, never heroes.
    exclude_title_patterns: tuple[str, ...] = field(
        default=("quà tặng", "hàng tặng", "không bán", "không tham gia")
    )

    #: d.7 step 1: a GMV change under this share either way is *Ổn định*.
    stable_gmv_change: float = 0.10
    #: d.7 step 1: under this many SKU orders in a window → *Chưa đủ dữ liệu*.
    min_orders_for_story: int = 30

    #: d.11: two-sided interval level (z for 90 %), and the order floors.
    z_value: float = 1.6449
    clear_min_orders: int = 30
    reference_min_orders: int = 10

    #: The seller message calls a factor "gần như không đổi" when it is not *Rõ* and its
    #: relative change is under this share either way.
    noise_relative_change: float = 0.05

    #: d.8 part 3: channel tags on a hero product's funnel.
    low_impressions_per_day: float = 50.0
    impressions_surge: float = 0.50
    #: d.8 part 3: "CTR down in nearly every channel" means at least this many
    #: of the channels that have data.
    ctr_down_nearly_all_share: float = 0.75

    #: d.9: rolling window of the event timeline.
    rolling_days: int = 7

    #: d.10 vouchers: Chốt đơn when the threshold is at or below the value that
    #: this share of single-item orders reach (the 25th percentile for 0.75);
    #: Đơn nhiều món from this multiple of giá một món phổ biến.
    closing_order_share: float = 0.75
    multi_item_multiple: float = 1.8
    #: Total claims 1–3 → *Cá nhân / bù khách*.
    personal_max_claims: int = 3
    #: "share of orders within 15 % below the threshold".
    near_threshold_band: float = 0.15
    #: Days on each side of a voucher's start for the before / after order mix.
    voucher_mix_days: int = 14

    #: d.10 flash sales: a flash day is at least this covered.
    flash_day_coverage: float = 0.50
    #: *Flash gần như liên tục*: 30-day coverage above this, or any week above the next.
    flash_continuous_window: float = 0.50
    flash_continuous_week: float = 0.80
    #: *Flash quá nông*: true depth under this.
    flash_shallow_depth: float = 0.05
    #: A day-group cell needs this many days and SKU orders, else *Chưa đủ dữ liệu*.
    day_group_min_days: int = 5
    day_group_min_orders: int = 30

    #: d.8 parts 6: LIVE sessions and videos listed per hero product.
    appearances_listed: int = 5
    #: Shop-level "sản phẩm cần theo dõi": products outside the top five whose
    #: GMV moved at least this share with at least ``watch_min_orders`` SKU
    #: orders in one window; at most ``watch_max_products`` are listed.
    watch_gmv_change: float = 0.30
    watch_min_orders: int = 10
    watch_max_products: int = 5

    #: ADR-109 d.5 metric rankings: Lượt hiển thị sản phẩm is labelled on
    #: impressions with this floor per window (instead of the 10 / 30 order floors);
    #: at most ``ranking_max_rows`` rows per direction; rows under
    #: ``ranking_fold_share`` of the stream's GMV change fold into "Các … khác".
    ranking_impressions_floor: int = 1_000
    ranking_max_rows: int = 10
    ranking_fold_share: float = 0.01
