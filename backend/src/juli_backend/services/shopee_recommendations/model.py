"""Plain data the generators, evaluators and the card assembly pass around."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_profit.money import ZERO


@dataclass
class Candidate:
    """A change a generator proposes, before any number is computed.

    ``inputs`` are the what-if knobs (the card's sliders); everything else the evaluator
    needs to find the scope in the environment. ``critical`` is the Phân tích item that
    asked for it (None for an opportunity card the sale / combo / affiliate families add).
    """

    kind: str
    items: tuple[str, ...] = ()
    inputs: dict[str, Any] = field(default_factory=dict)
    campaign_key: str | None = None
    critical: dict[str, Any] | None = None
    reason: str = ""
    #: metric key of section 8 that asked for this kind (a key of ``kinds.WIRING``)
    wiring_key: str | None = None
    #: how far below its reference the metric is, percent (None unknown) -> prior bucket
    gap_pct: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def item(self) -> str | None:
        return self.items[0] if self.items else None


@dataclass
class ProfitModel:
    """Everything the predicted-range conversion needs, per DAY of the effect period.

    A relative lift ``L`` on the card's target metric changes the scope's GMV by
    ``base_gmv_per_day * L``; the profit of that extra GMV is ``profit_per_gmv`` per đồng
    (the scenario's own contribution rate); ``extra_cost_per_day`` is the certain extra spend
    (negative = saving) and ``certain_dgmv_per_day`` the certain GMV change at the same volume.
    ``effect_days`` is how long the change runs (a persistent change counts 30).
    """

    effect_days: int = 30
    base_gmv_per_day: Decimal = ZERO
    base_orders_per_day: Decimal = ZERO
    aov: Decimal | None = None
    profit_per_gmv: Decimal | None = None
    extra_cost_per_day: Decimal = ZERO
    certain_dgmv_per_day: Decimal = ZERO
    #: marketing spend this card adds per day (chi, for the daily cap and number 2)
    dchi_per_day: Decimal = ZERO
    #: cap on extra units a slot can sell (Flash Sale quantity); None = no cap
    max_extra_units: Decimal | None = None
    base_label: str = "gmv_xac_nhan"  # or "gmv_quang_cao_don_da_dat"


@dataclass
class Evaluation:
    """The certain layer of one candidate at one set of inputs."""

    certain: dict[str, Any]
    five: dict[str, Any] | None
    breaches: list[dict[str, Any]]
    profit: ProfitModel
    before: dict[str, Any]
    after: dict[str, Any]
    #: ``{"item_id" | "campaign_id" | "voucher_id" | ...}`` the change lands on
    target: dict[str, Any]
    #: marketing spend per day of the whole shop after the card (for the cap check), if known
    spend_check: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)
    #: floor could not be judged for these SKUs (missing cost inputs)
    floor_unknown_skus: list[str] = field(default_factory=list)
    #: set when the candidate cannot be evaluated at all (no data); the card is not built
    refusal: str | None = None
