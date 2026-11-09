"""Limits and defaults of the combo builder.

Every ``SHOPEE_*`` constant is UNCONFIRMED: it is the figure the Seller Centre showed when the
builder was designed, not a verified rule. Confirm each at recon (P98 S7) before the UI treats it
as a hard stop; until then breaching one only warns (see ``generate.limit_warnings``).
"""

from __future__ import annotations

from decimal import Decimal

# --- Shopee per-listing limits: CONFIRM AT RECON (unconfirmed) -----------------------------------
SHOPEE_MAX_VARIATION_GROUPS = 2  # confirm at recon: "nhóm phân loại" per listing
SHOPEE_MAX_OPTIONS_PER_GROUP = 50  # confirm at recon: options inside one group
SHOPEE_MAX_TOTAL_VARIATIONS = 50  # confirm at recon: group-1 x group-2 combinations per listing
SHOPEE_MAX_OPTION_NAME_CHARS = 20  # confirm at recon: length of one option name
SHOPEE_MAX_SKU_CHARS = 100  # confirm at recon: seller SKU length
# the listing title limit is the builder's own (specs.MAX_TITLE_CHARS); re-exported for callers
# ------------------------------------------------------------------------------------------------

DEFAULT_MAX_OPTIONS = 50
MIN_PACK = 2
MAX_PACK = 100
DEFAULT_UNIT = "hộp"
DEFAULT_SHOP_CODE = "SHOP"

DEFAULT_LADDER: dict[int, Decimal] = {3: Decimal("0.05"), 5: Decimal("0.08"), 10: Decimal("0.12")}
DEFAULT_ROUND_TO = 1000
STOCK_NOTE = "không tự đồng bộ"
NOT_COUNTED = "chưa tính"
