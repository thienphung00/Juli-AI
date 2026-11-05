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
#: Bump when a change to the evaluation (formulas, models, defaults) must refresh every stored card:
#: a card computed by another engine version is stale and the refresh job recomputes it.
ENGINE_VERSION = "2026-11-05.1"

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

# -- listing family (title / keyword / cover_image / price_display) ---------------------------
#: Longest product name a card proposes or accepts (owner, P91 D-4: 100, was 120). A title is cut to
#: it at a word boundary (``listing.cut_title``) and refused above it (what-if: 422).
MAX_TITLE_CHARS = 100
#: Characters of a title the search result shows (the product page counts keywords against it);
#: never above the longest title.
TITLE_VISIBLE_CHARS = min(100, MAX_TITLE_CHARS)
#: At most this many "Chính" keywords per product (ADR-120 d.11).
MAX_CORE_KEYWORDS = 5
#: A "Phụ" keyword is promoted over the weakest "Chính" one only when its monthly search
#: volume is at least this many times higher, and at least ``KEYWORD_MIN_VOLUME`` (ADR-119 s.5).
KEYWORD_SWAP_FACTOR = 1.5
KEYWORD_MIN_VOLUME = 100
#: A product must have at least this many days of Thẻ sản phẩm impressions to judge a CTR lever.
LISTING_MIN_IMPRESSIONS = 100
#: The title / keyword audit runs on this many of the shop's best-selling products even when no
#: critical metric asks for it.
LISTING_OPPORTUNITY_PRODUCTS = 10

# -- acceptance statistics --------------------------------------------------------------------
ACCEPTANCE_PRIOR = (1.0, 2.0)  # (accepted + a) / (shown + b)

# -- assisted execution -----------------------------------------------------------------------
VERIFY_WINDOW_HOURS = 48

# -- all cards per product, versions, codes (P91) --------------------------------------------
#: A card carries at most this many versions (the default + three alternatives).
MAX_VERSIONS = 4
#: Open statuses that hold a product's queue slot ahead of the score (the seller chose them).
QUEUE_IN_FLIGHT = ("approved", "executed")
#: Days the measurement window runs when a card has no plan (same default as the product lock).
QUEUE_DEFAULT_PLAN_DAYS = 14
#: ``shop_proposals.code``: ``JC-<yymm>-<seq4>``; versions append ``-V<n>``.
CODE_PREFIX = "JC"
CODE_SEQ_DIGITS = 4
#: ``action_cards.priority`` of a manual card that does not ask to lead its product's queue.
MANUAL_PRIORITY = 50

# -- the draft plan, change sets and the measurement window (P91 D-6, D-7, D-8, D-10) ---------
#: ``shop_reco_plans.code``: ``KH-<yymm>-<seq3>``, per shop, never reused.
PLAN_CODE_PREFIX = "KH"
PLAN_SEQ_DIGITS = 3
#: Most cards one plan holds (the joint re-evaluation runs once per card to price "bỏ thẻ này thì").
PLAN_MAX_CARDS = 30
#: A change set's measurement window: at least this many days, at most that many (custom 3-90).
WINDOW_MIN_DAYS, WINDOW_MAX_DAYS = 3, 90
#: Presets offered; the recommended one is the shortest whose MDE is within ``MDE_MAX``.
WINDOW_PRESETS = (7, 14, 28)
#: Executing on a product that is still being measured cuts the running measurement that day: with
#: at least this many days measured the result is kept ("đo được N ngày"), with fewer it is
#: "không kết luận".
CUT_MIN_DAYS = 3
#: A card that was one of several in a change set counts for its change_kind at this weight in the
#: calibration (never as a clean single-kind sample).
MULTI_CARD_WEIGHT = 0.25
#: A cut or short-window result is read at lower confidence: no calibration from it.
