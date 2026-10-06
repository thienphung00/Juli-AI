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

    #: Decision 5: BMSM threshold = ceil(mean items per SKU order) + this.
    bmsm_threshold_plus: int = 1
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
