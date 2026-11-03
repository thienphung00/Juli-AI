"""Numbers the recommendation package decides with, in one place (each is a config, not a rule).

Priors are Juli's conservative placeholders (as ``optimize_product/prediction.py`` says of its
own): the Academy and Shopee publish no lift figures. They exist to be replaced by ORY's own
measurements through the calibration job (``learning``), and are labelled "dự kiến" wherever a
seller sees them.
"""

from __future__ import annotations

from collections.abc import Mapping

MODEL_VERSION = "shopee-reco-v1"
#: ``card_events.model_version`` for a frozen proposal (amendment 2026-10-20 section 3).
RULES_VERSION = "rules:ADR-121:shopee-reco-v1"
SCHEMA = "shopee_reco/v1"

DAYS_PER_MONTH = 30
#: History window the certain layer is computed on (the last N days ending on ``as_of``).
HISTORY_DAYS = 30

# -- prediction (port of optimize_product/prediction.py) --------------------------------------
#: A shop needs this many measured results per (change_kind, metric) for its own factor to count.
MIN_SHOP_RESULTS = 5
#: Shrinkage strength: ``n / (n + K)`` of the shop's evidence is trusted.
SHRINKAGE_K = 5.0
FACTOR_MIN, FACTOR_MAX = 0.25, 2.0
#: z of the 80 % central interval (P10-P90) of a normal.
Z_P90 = 1.2815515655446004
Z_P75 = 0.6744897501960817

#: Prior (low, high) = P10 / P90 of the relative lift on the kind's target metric, by gap bucket.
#: Buckets follow ``optimize_product``: wider and higher when the metric is far from its
#: reference, near zero when it is already close.
GAP_BUCKET_SCALE: Mapping[str, float] = {"large": 1.5, "medium": 1.0, "small": 0.4, "unknown": 0.8}
#: Large / medium gap = the metric is this far (percent) below its reference.
GAP_LARGE_PCT, GAP_MEDIUM_PCT = 30.0, 10.0
DEFAULT_PRIOR: tuple[float, float] = (0.02, 0.10)
#: Price levers are scaled by the size of the change: relative orders lift (a fraction) per
#: 1 % price cut (P10, P90): 0.5 % to 2 % more orders. A price rise uses the same range with
#: the opposite sign.
PRICE_ELASTICITY_PER_PCT: tuple[float, float] = (0.005, 0.02)

# -- coverage (ADR-121 d.4) -------------------------------------------------------------------
COVERAGE_TARGET = 0.8  # a P10-P90 range should hold 80 % of results
COVERAGE_MIN_RESULTS = 5
COVERAGE_WIDEN_BELOW = 0.7
COVERAGE_NARROW_ABOVE = 0.95
RANGE_SCALE_MIN, RANGE_SCALE_MAX = 0.85, 2.0

# -- measurement plan (ADR-107 decision 7) ----------------------------------------------------
MDE_MAX = 0.30
MDE_ALPHA = 0.05
MDE_POWER = 0.80
PLAN_PRE_DAYS = 28
PLAN_DAYS = (14, 28)
Z_ALPHA_2 = 1.959963984540054
Z_POWER = 0.8416212335729143

# -- ranking (contract 11) --------------------------------------------------------------------
DEFAULT_TOP_N = 10
KPI_ORDER = ("gmv", "orders", "aov", "bien")

# -- voucher / ads / promotion generators -----------------------------------------------------
VOUCHER_DAYS = 14
VOUCHER_MIN_SPEND_STEP = 10_000
ADS_BUDGET_STEP_PCT = 20
ROAS_TARGET_MARGIN = 1.1  # raise the ROAS target to break-even x this
DISCOUNT_TRY_PCT = (5, 10)
#: A stock-out guard: voucher / flash-sale quantity never above this share of stock.
STOCK_SHARE_CAP = 0.5
#: Product has at least this many confirmed orders in the history window to get a card.
MIN_PRODUCT_ORDERS = 3

# -- acceptance statistics --------------------------------------------------------------------
ACCEPTANCE_PRIOR = (1.0, 2.0)  # (accepted + a) / (shown + b)

# -- assisted execution -----------------------------------------------------------------------
VERIFY_WINDOW_HOURS = 48
