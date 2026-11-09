"""P98 S7: the combo builder's pure core (variations x pack sizes). See MODULE.md."""

from juli_backend.services.shopee_builder.combo_options.generate import (
    ComboInputError,
    count,
    generate,
    limit_warnings,
)
from juli_backend.services.shopee_builder.combo_options.models import (
    BundleSpec,
    ComboOption,
    Economics,
    Member,
    OptionCount,
    Packs,
    PricedRow,
    PriceRule,
    ProductIn,
    Rules,
    VariationIn,
)
from juli_backend.services.shopee_builder.combo_options.pricing import (
    PriceRuleError,
    price,
    reprice,
    round_price,
)

__all__ = [
    "BundleSpec",
    "ComboInputError",
    "ComboOption",
    "Economics",
    "Member",
    "OptionCount",
    "Packs",
    "PriceRule",
    "PriceRuleError",
    "PricedRow",
    "ProductIn",
    "Rules",
    "VariationIn",
    "count",
    "generate",
    "limit_warnings",
    "price",
    "reprice",
    "round_price",
]
