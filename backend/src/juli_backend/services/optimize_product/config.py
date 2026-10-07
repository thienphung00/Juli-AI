"""Every parameter of the stage diagnosis, in one place — ADR-106 decision 4.

Nothing in :mod:`juli_backend.services.optimize_product.diagnosis` carries a
literal threshold; it reads this object. The defaults are ADR-106's: volume
floors reuse ADR-077 decision 4, the gap threshold is 0.20 for both gap
kinds, the shop median needs three peers above the floor (ADR-106 amendment
2026-10-06, after the Fujiwa live scan — ADR-077's own control minimum), own-trend needs 42
days of product age, and a shop holds at most five open cards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class StageDiagnosisConfig:
    """Tunable inputs of the stage diagnosis (CONTEXT.md → Stage diagnosis)."""

    #: Length of the current window, in days. The funnel values are summed
    #: over it; floors below are per day of this window.
    current_window_days: int = 14
    #: Length of the prior window, in days, ending where the current begins.
    prior_window_days: int = 28

    #: ADR-077 d.4 floors, per day, over the current window.
    min_impressions_per_day: Decimal = Decimal("50")
    min_clicks_per_day: Decimal = Decimal("20")
    min_orders_per_day: Decimal = Decimal("1")

    #: A factor acts only when its gap is at least this. One per gap kind.
    gap_threshold_median: Decimal = Decimal("0.20")
    gap_threshold_trend: Decimal = Decimal("0.20")

    #: The shop median counts only products above the floor and needs this
    #: many of them; fewer and ``gap_median`` is not computed for anyone.
    #: Three is ADR-077 d.3's control-pool minimum; the first live scan
    #: (Fujiwa, 37 listings, 4 real sellers) never reached the original five.
    min_peers_for_median: int = 3
    #: Below this many peers the card says "so với N sản phẩm đủ dữ liệu của
    #: shop" instead of "so với trung bình shop".
    full_median_peers: int = 5
    #: Products younger than this cannot have a prior window; ``gap_trend``
    #: is not computed for them.
    min_age_days_for_trend: int = 42

    #: Decision 6: open Optimize Product cards per shop.
    max_open_cards_per_shop: int = 5

    #: Decision 5 (Amendment 3): BMSM threshold from the real basket. With
    #: at least ``bmsm_min_orders_for_histogram`` orders of the product the
    #: threshold is ``median quantity + 1`` and the card is emitted only when
    #: at least ``bmsm_min_share_at_threshold`` of those orders already buy
    #: that many; otherwise ``floor(mean items per order) + 1``, never below
    #: ``bmsm_min_threshold_items``.
    bmsm_min_orders_for_histogram: int = 20
    bmsm_min_share_at_threshold: Decimal = Decimal("0.05")
    bmsm_min_threshold_items: int = 2
    #: Amendment 3: below this star rating no demand lever is proposed.
    min_rating_for_demand_levers: Decimal = Decimal("4.0")
    #: Decision 5: BMSM percentage is bounded by the seller's maximum
    #: discount (OP-FR-4). When the scan does not know the cap it proposes
    #: this value and labels it an estimate.
    bmsm_percent_default: int = 10

    #: Listings whose title matches one of these (case-insensitive substring)
    #: are not diagnosed: gift / not-for-sale listings carry no real funnel
    #: (the same pollution the FastMoss probe found in VN top-GMV lists).
    exclude_title_patterns: tuple[str, ...] = field(
        default=("quà tặng", "hàng tặng", "không bán", "không tham gia")
    )

    #: VN "Rest of World" diagnosis thresholds from the Partner Center
    #: listing-quality reference, used to derive *local* evidence when the
    #: diagnosis endpoint has not been captured (ADR-090 d.3 degraded mode).
    title_min_chars: int = 40
    description_min_chars: int = 500
    main_images_min_count: int = 5
    first_image_min_side_px: int = 600

    #: Traffic-source check (ADR-106 amendment 4, owner-approved defaults,
    #: adjustable). A channel qualifies when its impressions reach this many in
    #: *each* 30-day window; fewer is noise, not a verdict.
    traffic_min_channel_impressions: int = 200
    #: A channel "spikes" when impressions per day, current window over the
    #: previous one, reach this ratio.
    traffic_spike_ratio: Decimal = Decimal("1.5")
    #: A channel's CTR "drops" when it falls by at least this share of its
    #: previous value (relative, not percentage points).
    traffic_ctr_drop: Decimal = Decimal("0.15")
    #: A channel's CTR is "stable" within plus or minus this relative change.
    traffic_ctr_stable: Decimal = Decimal("0.10")

    #: The platform- or seller-discount share is quoted on a card once at
    #: least this share of the product's order lines carry that discount.
    platform_discount_note_share: Decimal = Decimal("0.5")
    #: Below this many non-gift order lines in a window the share is not shown.
    platform_discount_min_lines: int = 10
