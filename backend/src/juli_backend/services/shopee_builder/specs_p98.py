"""P98 S7-S9: the request models of the combo, KOL and ads builders (hard bounds, no I/O).

Every model refuses unknown keys and every number has a bound, so a typo is a 422 at the door.
Money is whole đồng, a percent is 0-100. The builders only validate and return inputs and measured
facts; turning them into an ``OptionResult`` is the engine's job (W2-F / W3-H).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from juli_backend.services.shopee_builder.combo_options import Packs as _Packs
from juli_backend.services.shopee_builder.combo_options import PriceRule, config
from juli_backend.services.shopee_builder.combo_options import Rules as _Rules
from juli_backend.services.shopee_builder.combo_options.models import BundleSpec
from juli_backend.services.shopee_builder.specs import (
    ADS_MIN_BUDGET,
    MAX_MONEY,
    ItemId,
    VariationId,
)

MAX_COMBO_PRODUCTS = 10
MAX_PACK_SIZES = 10
MAX_BUNDLES = 10
MAX_BUNDLE_ITEMS = 5
MAX_OPTIONS_CAP = 200
MAX_OVERRIDES = 200
MAX_LADDER_TIERS = 10
MAX_KOLS = 20
MAX_KOL_ITEMS = 20
MAX_SAMPLE_QTY = 50
MAX_COMMISSION_PCT = 50
MAX_ADS_SETUPS = 10
MAX_ADS_ITEMS = 50
MAX_ROAS = 50
MAX_ADS_DAYS = 365
ROUND_STEPS = (100, 500, 1000, 5000, 10_000)
ADS_BUDGET_FLOOR = ADS_MIN_BUDGET  # Shopee's minimum daily budget (specs.ADS_MIN_BUDGET)


class BuilderInputError(ValueError):
    """A request that validates but names something the shop does not have (HTTP ``status``)."""

    def __init__(self, code: str, message: str, status: int = 422, **more: object) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.more = code, message, status, more


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------------------ combo builder


class ProductPick(_Body):
    """A product and the variations of it that go into the combos (at least one)."""

    item_id: ItemId
    variation_ids: list[VariationId] = Field(min_length=1, max_length=50)


class BundleItem(_Body):
    item_id: ItemId
    quantity: int = Field(ge=1, le=config.MAX_PACK)


class BundleBody(_Body):
    """One bundle of several products: ``(item, quantity)`` pairs."""

    items: list[BundleItem] = Field(min_length=2, max_length=MAX_BUNDLE_ITEMS)

    @model_validator(mode="after")
    def _distinct(self) -> BundleBody:
        ids = [i.item_id for i in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("a bundle holds each product once")
        return self


class LadderTier(_Body):
    units: int = Field(ge=config.MIN_PACK, le=config.MAX_PACK)
    discount_pct: float = Field(ge=0, le=90)


class RulesBody(_Body):
    same_variation: bool = True
    sold_only: bool = True
    max_options: int = Field(default=config.DEFAULT_MAX_OPTIONS, ge=1, le=MAX_OPTIONS_CAP)
    shop_code: str = Field(default=config.DEFAULT_SHOP_CODE, min_length=1, max_length=12)
    unit: str = Field(default=config.DEFAULT_UNIT, min_length=1, max_length=20)


class PriceRuleBody(_Body):
    """``ladder`` (discount by boxes), ``target_margin`` (lowest price reaching Biên cuối) or
    ``per_box`` (a fixed price a box)."""

    kind: Literal["ladder", "target_margin", "per_box"] = "ladder"
    ladder: list[LadderTier] | None = Field(default=None, max_length=MAX_LADDER_TIERS)
    target_margin_pct: float | None = Field(default=None, gt=0, lt=100)
    box_price: int | None = Field(default=None, ge=1, le=MAX_MONEY)
    round_to: int = config.DEFAULT_ROUND_TO
    ending_9: bool = False

    @model_validator(mode="after")
    def _check(self) -> PriceRuleBody:
        if self.round_to not in ROUND_STEPS:
            raise ValueError(f"round_to is one of {list(ROUND_STEPS)}")
        if self.kind == "target_margin" and self.target_margin_pct is None:
            raise ValueError("target_margin needs target_margin_pct")
        if self.kind == "per_box" and self.box_price is None:
            raise ValueError("per_box needs box_price")
        if self.ladder and len({t.units for t in self.ladder}) != len(self.ladder):
            raise ValueError("ladder tiers are different from each other")
        return self

    def to_rule(self) -> PriceRule:
        ladder = (
            {t.units: Decimal(str(t.discount_pct)) / 100 for t in self.ladder}
            if self.ladder
            else dict(config.DEFAULT_LADDER)
        )
        return PriceRule(
            kind=self.kind,
            ladder=ladder,
            target_margin_pct=None
            if self.target_margin_pct is None
            else Decimal(str(self.target_margin_pct)),
            box_price=None if self.box_price is None else Decimal(self.box_price),
            round_to=self.round_to,
            ending_9=self.ending_9,
        )


class ComboRequest(_Body):
    """POST .../combo/options: products + variations + pack sizes / bundles + rules + price rule."""

    products: list[ProductPick] = Field(min_length=1, max_length=MAX_COMBO_PRODUCTS)
    pack_sizes: list[int] = Field(
        default_factory=lambda: [3, 5, 10],
        max_length=MAX_PACK_SIZES,
        description="multi-pack sizes (boxes); empty = bundles only",
    )
    bundles: list[BundleBody] = Field(default_factory=list, max_length=MAX_BUNDLES)
    rules: RulesBody = Field(default_factory=RulesBody)
    price_rule: PriceRuleBody = Field(default_factory=PriceRuleBody)
    floor_pct: float | None = Field(default=None, ge=0, le=100)
    #: option key -> manual price (that row is recomputed around it)
    overrides: dict[Annotated[str, Field(max_length=400)], int] = Field(
        default_factory=dict, max_length=MAX_OVERRIDES
    )
    as_of: date | None = None

    @model_validator(mode="after")
    def _check(self) -> ComboRequest:
        ids = [p.item_id for p in self.products]
        if len(set(ids)) != len(ids):
            raise ValueError("products are different from each other")
        if not self.pack_sizes and not self.bundles:
            raise ValueError("pack_sizes or bundles")
        if any(not config.MIN_PACK <= n <= config.MAX_PACK for n in self.pack_sizes):
            raise ValueError(f"pack size outside {config.MIN_PACK}..{config.MAX_PACK}")
        for b in self.bundles:
            if any(i.item_id not in ids for i in b.items):
                raise ValueError("a bundle holds only the picked products")
        if any(not 0 < v <= MAX_MONEY for v in self.overrides.values()):
            raise ValueError(f"an override price is 1..{MAX_MONEY}")
        return self

    def packs(self) -> _Packs:
        return _Packs(
            sizes=tuple(self.pack_sizes),
            bundles=tuple(
                BundleSpec(tuple((i.item_id, i.quantity) for i in b.items)) for b in self.bundles
            ),
        )

    def combo_rules(self) -> _Rules:
        r = self.rules
        return _Rules(
            same_variation=r.same_variation,
            sold_only=r.sold_only,
            max_options=r.max_options,
            shop_code=r.shop_code,
            unit=r.unit,
        )

    def picks(self) -> dict[str, list[str]]:
        return {p.item_id: list(p.variation_ids) for p in self.products}


# ----------------------------------------------------------------------------- KOL builder


class SampleBody(_Body):
    """Sample sent to the KOL: the product, how many, and the shipping fee."""

    item_id: ItemId
    qty: int = Field(ge=1, le=MAX_SAMPLE_QTY)
    ship_fee: int = Field(default=0, ge=0, le=MAX_MONEY)


class KolSetup(_Body):
    """One KOL from the KOL report with the products and the commission offered."""

    kol_key: str = Field(min_length=1, max_length=128)
    item_ids: list[ItemId] = Field(min_length=1, max_length=MAX_KOL_ITEMS)
    commission_pct: float = Field(ge=0, le=MAX_COMMISSION_PCT)
    sample: SampleBody | None = None

    @model_validator(mode="after")
    def _check(self) -> KolSetup:
        if len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError("item_ids are different from each other")
        if self.sample is not None and self.sample.item_id not in self.item_ids:
            raise ValueError("the sample is one of the KOL's products")
        return self


class KolRequest(_Body):
    kols: list[KolSetup] = Field(min_length=1, max_length=MAX_KOLS)
    as_of: date | None = None

    @model_validator(mode="after")
    def _check(self) -> KolRequest:
        keys = [k.kol_key for k in self.kols]
        if len(set(keys)) != len(keys):
            raise ValueError("KOLs are different from each other")
        return self


# ----------------------------------------------------------------------------- ads builder


class RoasBody(_Body):
    """``system`` = optimised by Shopee; ``custom`` = a target ROAS."""

    mode: Literal["system", "custom"] = "system"
    target: float | None = Field(default=None, gt=0, le=MAX_ROAS)

    @model_validator(mode="after")
    def _check(self) -> RoasBody:
        if self.mode == "custom" and self.target is None:
            raise ValueError("custom needs a target")
        if self.mode == "system" and self.target is not None:
            raise ValueError("system takes no target")
        return self


class AdsSetup(_Body):
    """A new Dịch vụ Hiển thị Sản phẩm campaign: ``group`` (chiến dịch nhóm: several products) or
    ``single`` (chiến dịch đơn: one product)."""

    campaign: Literal["group", "single"]
    item_ids: list[ItemId] = Field(min_length=1, max_length=MAX_ADS_ITEMS)
    daily_budget: int = Field(ge=ADS_BUDGET_FLOOR, le=MAX_MONEY)
    roas: RoasBody = Field(default_factory=RoasBody)
    start_date: date
    end_date: date | None = None
    name: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def _check(self) -> AdsSetup:
        if len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError("item_ids are different from each other")
        if self.campaign == "single" and len(self.item_ids) != 1:
            raise ValueError("a single campaign holds one product")
        if self.end_date is not None:
            days = (self.end_date - self.start_date).days + 1
            if days < 1:
                raise ValueError("end_date is on or after start_date")
            if days > MAX_ADS_DAYS:
                raise ValueError(f"at most {MAX_ADS_DAYS} days")
        return self


class AdsRequest(_Body):
    setups: list[AdsSetup] = Field(min_length=1, max_length=MAX_ADS_SETUPS)
    as_of: date | None = None


__all__ = [
    "BuilderInputError",
    "ADS_BUDGET_FLOOR",
    "AdsRequest",
    "AdsSetup",
    "BundleBody",
    "BundleItem",
    "ComboRequest",
    "KolRequest",
    "KolSetup",
    "LadderTier",
    "PriceRuleBody",
    "ProductPick",
    "RoasBody",
    "RulesBody",
    "SampleBody",
    "VariationId",
]
