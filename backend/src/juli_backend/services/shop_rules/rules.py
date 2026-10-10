"""The per-shop rule store (fast track P8-C, ADR-109 d.12).

Everything in the video's "Quy tắc do bạn đặt" is set by the seller (or, in the
operator phase, by the Juli team on the seller's behalf), never chosen by Juli.
Each value is one ``shop_rules`` row with ``set_by`` ('team' | 'seller'),
``set_by_user_id`` and ``set_at``.

- ``stability_band`` (scope: metric key) -- ± %, 0 < v ≤ 100. Unset: no day-7
  question for that metric.
- ``product_cost`` (scope: TikTok product id) -- VND per unit, ≥ 0. Unset:
  revenue ranking.
- ``min_margin_pct`` (shop-wide) -- %, 0 ≤ v < 100. Unset: no price
  recommendation.
- ``max_discount_pct`` (scope: TikTok SKU id) -- %, 0 ≤ v ≤ 100. Unset: no price
  recommendation.
- ``max_open_cards`` (shop-wide) -- int 1..5. Unset: 5.
- ``auto_levers`` (shop-wide) -- subset of title / description / attributes /
  image. Unset: all four.
- ``protected_terms`` (shop-wide) -- list of non-empty strings. Unset: none.

Price is never an auto-executable lever (D13): ``"price"`` is rejected.

Fast track P14-F (contract ``fasttrack/contracts/p14-rules-and-cost.md``):
what no TikTok API gives Juli, each optional --

- ``sku_cost`` (scope: TikTok SKU id) -- VND per unit, ≥ 0. Wins over
  ``product_cost`` for that SKU.
- ``default_gross_margin_pct`` (shop-wide) -- %, 0 < v < 100: the margin to
  assume for a product with no cost set.
- ``default_max_discount_pct`` (shop-wide) -- %, 0 ≤ v ≤ 100: the discount cap
  for every SKU without its own ``max_discount_pct``.
- ``program_fee_pct`` (shop-wide) -- %, 0 ≤ v < 100: the fee of the programmes
  the shop is in (Voucher Xtra, Flash Sale service fee …), known only after an
  order settles.
- ``joins_platform_campaigns`` (shop-wide) -- bool.
- ``platform_campaign_note`` (shop-wide) -- text ≤ 500: the campaigns the
  seller has registered for (there is no campaign-registration API).
- ``target_roas`` (shop-wide) -- 0 < v ≤ 100 (GMV ÷ ad cost).
- ``gmv_max_daily_budget`` (shop-wide) -- VND per day, ≥ 0 (no Business API yet).
- ``live_schedule`` (shop-wide) -- up to 14 regular LIVE slots
  ``{"days": ["mon", …], "start": "HH:MM", "end": "HH:MM"}``.

They are read by nothing yet but the ranking layer's typed accessor
(``economics.shop_economics``).

Wired today: ``max_open_cards`` caps Optimize Product's surfaced cards
(``action_cards.persist``), ``auto_levers`` decides which cards are executable
(the decisions list and approve), ``stability_band`` drives the day-7
guardrail, ``protected_terms`` gate the seller's edit at the consent step
(``listing_edits``, P10-A). The cost, margin and discount rules are stored for
the ranking / price consumers that do not exist yet.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.run_changes import SET_BY_VALUES, ShopRule

STABILITY_BAND = "stability_band"
PRODUCT_COST = "product_cost"
MIN_MARGIN_PCT = "min_margin_pct"
MAX_DISCOUNT_PCT = "max_discount_pct"
MAX_OPEN_CARDS = "max_open_cards"
AUTO_LEVERS = "auto_levers"
PROTECTED_TERMS = "protected_terms"
# P14-F: what the APIs cannot tell Juli.
SKU_COST = "sku_cost"
DEFAULT_GROSS_MARGIN_PCT = "default_gross_margin_pct"
DEFAULT_MAX_DISCOUNT_PCT = "default_max_discount_pct"
PROGRAM_FEE_PCT = "program_fee_pct"
JOINS_PLATFORM_CAMPAIGNS = "joins_platform_campaigns"
PLATFORM_CAMPAIGN_NOTE = "platform_campaign_note"
TARGET_ROAS = "target_roas"
GMV_MAX_DAILY_BUDGET = "gmv_max_daily_budget"
LIVE_SCHEDULE = "live_schedule"

#: The P14-F keys, in the editor's order.
OFF_API_RULE_KEYS: tuple[str, ...] = (
    SKU_COST,
    DEFAULT_GROSS_MARGIN_PCT,
    DEFAULT_MAX_DISCOUNT_PCT,
    PROGRAM_FEE_PCT,
    JOINS_PLATFORM_CAMPAIGNS,
    PLATFORM_CAMPAIGN_NOTE,
    TARGET_ROAS,
    GMV_MAX_DAILY_BUDGET,
    LIVE_SCHEDULE,
)

RULE_KEYS: tuple[str, ...] = (
    STABILITY_BAND,
    PRODUCT_COST,
    MIN_MARGIN_PCT,
    MAX_DISCOUNT_PCT,
    MAX_OPEN_CARDS,
    AUTO_LEVERS,
    PROTECTED_TERMS,
    *OFF_API_RULE_KEYS,
)

#: P14-F shop-wide keys; each is a ``ShopRules`` attribute of the same name.
_SHOP_WIDE_OFF_API: frozenset[str] = frozenset(set(OFF_API_RULE_KEYS) - {SKU_COST})

#: Rules keyed by a subject (metric / product / SKU); the rest are shop-wide.
SCOPED_RULES: frozenset[str] = frozenset({STABILITY_BAND, PRODUCT_COST, MAX_DISCOUNT_PCT, SKU_COST})

WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_LIVE_SLOTS = 14
MAX_NOTE_LENGTH = 500
MAX_TARGET_ROAS = 100
MAX_DAILY_BUDGET_VND = 10_000_000_000

#: The metric keys a stability band can be set for -- the impact reader's
#: metrics (``services/impact/metric_map.ALL_METRICS``): Lượt hiển thị sản phẩm,
#: CTR, tỷ lệ chuyển đổi, số sản phẩm bán, GMV, đơn hàng SKU, AOV.
BAND_METRICS: tuple[str, ...] = (
    "impressions",
    "ctr",
    "conversion_rate",
    "items_sold",
    "gmv",
    "sku_orders",
    "gmv_per_order",
)

LISTING_LEVERS: tuple[str, ...] = ("title", "description", "attributes", "image")
DEFAULT_AUTO_LEVERS: frozenset[str] = frozenset(LISTING_LEVERS)
DEFAULT_MAX_OPEN_CARDS = 5
MAX_OPEN_CARDS_CEILING = 5
MAX_PROTECTED_TERMS = 200
MAX_TERM_LENGTH = 100


class RuleValidationError(ValueError):
    """A rule write the store refuses; the message is safe to show the caller."""


@dataclass(frozen=True)
class RuleValue:
    value: Any
    set_by: str | None
    set_by_user_id: uuid.UUID | None
    set_at: datetime | None


@dataclass
class ShopRules:
    """All of a shop's rules, defaults applied where nothing is set."""

    stability_band: dict[str, RuleValue] = field(default_factory=dict)
    product_cost: dict[str, RuleValue] = field(default_factory=dict)
    max_discount_pct: dict[str, RuleValue] = field(default_factory=dict)
    min_margin_pct: RuleValue | None = None
    max_open_cards: RuleValue = field(
        default_factory=lambda: RuleValue(DEFAULT_MAX_OPEN_CARDS, None, None, None)
    )
    auto_levers: RuleValue = field(
        default_factory=lambda: RuleValue(sorted(DEFAULT_AUTO_LEVERS), None, None, None)
    )
    protected_terms: RuleValue = field(default_factory=lambda: RuleValue([], None, None, None))
    # P14-F: unset (``None`` / empty) until the seller sets them.
    sku_cost: dict[str, RuleValue] = field(default_factory=dict)
    default_gross_margin_pct: RuleValue | None = None
    default_max_discount_pct: RuleValue | None = None
    program_fee_pct: RuleValue | None = None
    joins_platform_campaigns: RuleValue | None = None
    platform_campaign_note: RuleValue | None = None
    target_roas: RuleValue | None = None
    gmv_max_daily_budget: RuleValue | None = None
    live_schedule: RuleValue | None = None


def _number(value: Any, *, rule: str) -> Decimal:
    if isinstance(value, bool):
        raise RuleValidationError(f"{rule}: value must be a number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise RuleValidationError(f"{rule}: value must be a number") from None
    if not number.is_finite():
        raise RuleValidationError(f"{rule}: value must be a finite number")
    return number


def _json_number(number: Decimal) -> int | float:
    return int(number) if number == number.to_integral_value() else float(number)


def validate_rule(rule_key: str, scope_ref: str, value: Any) -> tuple[str, Any]:
    """Normalise ``(scope_ref, value)`` for ``rule_key`` or raise ``RuleValidationError``."""
    if rule_key not in RULE_KEYS:
        raise RuleValidationError(f"unknown rule {rule_key!r}; known rules: {list(RULE_KEYS)}")
    scope_ref = (scope_ref or "").strip()
    if rule_key in SCOPED_RULES:
        if not scope_ref:
            raise RuleValidationError(f"{rule_key}: scope_ref is required")
        if len(scope_ref) > 100:
            raise RuleValidationError(f"{rule_key}: scope_ref is too long")
    elif scope_ref:
        raise RuleValidationError(f"{rule_key}: a shop-wide rule takes no scope_ref")

    if rule_key == STABILITY_BAND:
        if scope_ref not in BAND_METRICS:
            raise RuleValidationError(
                f"stability_band: unknown metric {scope_ref!r}; known: {list(BAND_METRICS)}"
            )
        band = _number(value, rule=rule_key)
        if not Decimal(0) < band <= Decimal(100):
            raise RuleValidationError("stability_band: value must be > 0 and ≤ 100 (%)")
        return scope_ref, _json_number(band)
    if rule_key in (PRODUCT_COST, SKU_COST):
        cost = _number(value, rule=rule_key)
        if cost < 0:
            raise RuleValidationError(f"{rule_key}: value must be ≥ 0")
        return scope_ref, _json_number(cost)
    if rule_key in _OFF_API_VALIDATORS:
        return scope_ref, _OFF_API_VALIDATORS[rule_key](value)
    if rule_key in (MIN_MARGIN_PCT, MAX_DISCOUNT_PCT):
        pct = _number(value, rule=rule_key)
        upper_ok = pct < 100 if rule_key == MIN_MARGIN_PCT else pct <= 100
        if pct < 0 or not upper_ok:
            raise RuleValidationError(f"{rule_key}: value is a percentage out of range")
        return scope_ref, _json_number(pct)
    if rule_key == MAX_OPEN_CARDS:
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuleValidationError("max_open_cards: value must be an integer")
        if not 1 <= value <= MAX_OPEN_CARDS_CEILING:
            raise RuleValidationError(
                f"max_open_cards: value must be between 1 and {MAX_OPEN_CARDS_CEILING}"
            )
        return scope_ref, value
    if rule_key == AUTO_LEVERS:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise RuleValidationError("auto_levers: value must be a list of lever names")
        if "price" in value:
            raise RuleValidationError("auto_levers: price is never auto-executable (D13)")
        unknown = sorted(set(value) - set(LISTING_LEVERS))
        if unknown:
            raise RuleValidationError(
                f"auto_levers: unknown levers {unknown}; known: {list(LISTING_LEVERS)}"
            )
        return scope_ref, sorted(set(value))
    # PROTECTED_TERMS
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise RuleValidationError("protected_terms: value must be a list of strings")
    terms = [term.strip() for term in value if term.strip()]
    if len(terms) > MAX_PROTECTED_TERMS or any(len(t) > MAX_TERM_LENGTH for t in terms):
        raise RuleValidationError("protected_terms: too many terms, or a term is too long")
    return scope_ref, list(dict.fromkeys(terms))


def _pct(value: Any, *, rule: str, low_open: bool, high: int, high_open: bool) -> int | float:
    pct = _number(value, rule=rule)
    low_ok = pct > 0 if low_open else pct >= 0
    high_ok = pct < high if high_open else pct <= high
    if not (low_ok and high_ok):
        raise RuleValidationError(f"{rule}: value is a percentage out of range")
    return _json_number(pct)


def _bool(value: Any, *, rule: str) -> bool:
    if not isinstance(value, bool):
        raise RuleValidationError(f"{rule}: value must be true or false")
    return value


def _note(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuleValidationError(f"{PLATFORM_CAMPAIGN_NOTE}: value must be non-empty text")
    text = value.strip()
    if len(text) > MAX_NOTE_LENGTH:
        raise RuleValidationError(f"{PLATFORM_CAMPAIGN_NOTE}: at most {MAX_NOTE_LENGTH} characters")
    return text


def _target_roas(value: Any) -> int | float:
    roas = _number(value, rule=TARGET_ROAS)
    if not Decimal(0) < roas <= Decimal(MAX_TARGET_ROAS):
        raise RuleValidationError(f"{TARGET_ROAS}: value must be > 0 and ≤ {MAX_TARGET_ROAS}")
    return _json_number(roas)


def _daily_budget(value: Any) -> int | float:
    budget = _number(value, rule=GMV_MAX_DAILY_BUDGET)
    if not Decimal(0) <= budget <= Decimal(MAX_DAILY_BUDGET_VND):
        raise RuleValidationError(f"{GMV_MAX_DAILY_BUDGET}: value must be ≥ 0 VND per day")
    return _json_number(budget)


def _clock(value: Any, *, rule: str) -> str:
    text = value.strip() if isinstance(value, str) else ""
    parts = text.split(":")
    if len(parts) != 2 or not all(p.isdigit() and len(p) == 2 for p in parts):
        raise RuleValidationError(f"{rule}: times are HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if hour > 23 or minute > 59:
        raise RuleValidationError(f"{rule}: times are HH:MM")
    return f"{hour:02d}:{minute:02d}"


def _live_schedule(value: Any) -> list[dict[str, Any]]:
    rule = LIVE_SCHEDULE
    if not isinstance(value, list):
        raise RuleValidationError(f"{rule}: value must be a list of slots")
    if len(value) > MAX_LIVE_SLOTS:
        raise RuleValidationError(f"{rule}: at most {MAX_LIVE_SLOTS} slots")
    slots: list[dict[str, Any]] = []
    for slot in value:
        if not isinstance(slot, Mapping) or set(slot) != {"days", "start", "end"}:
            raise RuleValidationError(f"{rule}: each slot is {{days, start, end}}")
        days = slot["days"]
        if (
            not isinstance(days, list)
            or not days
            or not all(isinstance(d, str) and d in WEEKDAYS for d in days)
        ):
            raise RuleValidationError(f"{rule}: days are a non-empty subset of {list(WEEKDAYS)}")
        start, end = _clock(slot["start"], rule=rule), _clock(slot["end"], rule=rule)
        if start == end:
            raise RuleValidationError(f"{rule}: a slot cannot start and end at the same time")
        ordered = [d for d in WEEKDAYS if d in set(days)]
        normalised = {"days": ordered, "start": start, "end": end}
        if normalised not in slots:
            slots.append(normalised)
    return slots


#: P14-F validators (``sku_cost`` shares ``product_cost``'s rule above).
_OFF_API_VALIDATORS: Mapping[str, Any] = {
    DEFAULT_GROSS_MARGIN_PCT: lambda v: _pct(
        v, rule=DEFAULT_GROSS_MARGIN_PCT, low_open=True, high=100, high_open=True
    ),
    DEFAULT_MAX_DISCOUNT_PCT: lambda v: _pct(
        v, rule=DEFAULT_MAX_DISCOUNT_PCT, low_open=False, high=100, high_open=False
    ),
    PROGRAM_FEE_PCT: lambda v: _pct(
        v, rule=PROGRAM_FEE_PCT, low_open=False, high=100, high_open=True
    ),
    JOINS_PLATFORM_CAMPAIGNS: lambda v: _bool(v, rule=JOINS_PLATFORM_CAMPAIGNS),
    PLATFORM_CAMPAIGN_NOTE: _note,
    TARGET_ROAS: _target_roas,
    GMV_MAX_DAILY_BUDGET: _daily_budget,
    LIVE_SCHEDULE: _live_schedule,
}


def _validate_set_by(set_by: str) -> str:
    if set_by not in SET_BY_VALUES:
        raise RuleValidationError(f"set_by must be one of {list(SET_BY_VALUES)}")
    return set_by


def _naive_utc(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None)


async def set_rule(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    rule_key: str,
    scope_ref: str | None,
    value: Any,
    set_by: str,
    set_by_user_id: uuid.UUID | None,
    now: datetime | None = None,
) -> ShopRule:
    """Insert or replace one rule value; flush, no commit."""
    scope, normalised = validate_rule(rule_key, scope_ref or "", value)
    _validate_set_by(set_by)
    row = (
        await session.execute(
            select(ShopRule).where(
                ShopRule.shop_id == shop_id,
                ShopRule.rule_key == rule_key,
                ShopRule.scope_ref == scope,
            )
        )
    ).scalar_one_or_none()
    set_at = _naive_utc(now)
    if row is None:
        row = ShopRule(
            shop_id=shop_id,
            rule_key=rule_key,
            scope_ref=scope,
            value=normalised,
            set_by=set_by,
            set_by_user_id=set_by_user_id,
            set_at=set_at,
        )
        session.add(row)
    else:
        row.value = normalised
        row.set_by = set_by
        row.set_by_user_id = set_by_user_id
        row.set_at = set_at
    await session.flush()
    return row


async def delete_rule(
    session: AsyncSession, shop_id: uuid.UUID, *, rule_key: str, scope_ref: str | None
) -> bool:
    """Unset one rule value (its default applies again). Returns whether a row existed."""
    if rule_key not in RULE_KEYS:
        raise RuleValidationError(f"unknown rule {rule_key!r}")
    row = (
        await session.execute(
            select(ShopRule).where(
                ShopRule.shop_id == shop_id,
                ShopRule.rule_key == rule_key,
                ShopRule.scope_ref == (scope_ref or "").strip(),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def _rows(session: AsyncSession, shop_id: uuid.UUID, *keys: str) -> list[ShopRule]:
    stmt = select(ShopRule).where(ShopRule.shop_id == shop_id)
    if keys:
        stmt = stmt.where(ShopRule.rule_key.in_(keys))
    return list((await session.execute(stmt.order_by(ShopRule.scope_ref))).scalars().all())


def _value(row: ShopRule) -> RuleValue:
    return RuleValue(row.value, row.set_by, row.set_by_user_id, row.set_at)


async def get_rules(session: AsyncSession, shop_id: uuid.UUID) -> ShopRules:
    """The shop's rules with defaults applied."""
    rules = ShopRules()
    for row in await _rows(session, shop_id):
        if row.rule_key == STABILITY_BAND:
            rules.stability_band[row.scope_ref] = _value(row)
        elif row.rule_key == PRODUCT_COST:
            rules.product_cost[row.scope_ref] = _value(row)
        elif row.rule_key == MAX_DISCOUNT_PCT:
            rules.max_discount_pct[row.scope_ref] = _value(row)
        elif row.rule_key == MIN_MARGIN_PCT:
            rules.min_margin_pct = _value(row)
        elif row.rule_key == MAX_OPEN_CARDS:
            rules.max_open_cards = _value(row)
        elif row.rule_key == AUTO_LEVERS:
            rules.auto_levers = _value(row)
        elif row.rule_key == PROTECTED_TERMS:
            rules.protected_terms = _value(row)
        elif row.rule_key == SKU_COST:
            rules.sku_cost[row.scope_ref] = _value(row)
        elif row.rule_key in _SHOP_WIDE_OFF_API:
            setattr(rules, row.rule_key, _value(row))
    return rules


async def max_open_cards(session: AsyncSession, shop_id: uuid.UUID) -> int:
    """The seller's open-card cap for Optimize Product, 5 until set."""
    rows = await _rows(session, shop_id, MAX_OPEN_CARDS)
    if not rows or not isinstance(rows[0].value, int):
        return DEFAULT_MAX_OPEN_CARDS
    return max(1, min(MAX_OPEN_CARDS_CEILING, rows[0].value))


async def auto_levers(session: AsyncSession, shop_id: uuid.UUID) -> frozenset[str]:
    """The levers Juli may execute for this shop; all listing levers until set."""
    rows = await _rows(session, shop_id, AUTO_LEVERS)
    if not rows or not isinstance(rows[0].value, list):
        return DEFAULT_AUTO_LEVERS
    return frozenset(str(v) for v in rows[0].value) & DEFAULT_AUTO_LEVERS


async def configured_max_open_cards(session: AsyncSession, shop_id: uuid.UUID) -> int | None:
    """The seller's open-card cap when one is set, else ``None`` (keep the config)."""
    rows = await _rows(session, shop_id, MAX_OPEN_CARDS)
    if not rows or not isinstance(rows[0].value, int):
        return None
    return max(1, min(MAX_OPEN_CARDS_CEILING, rows[0].value))


async def stability_bands(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Decimal]:
    """metric key -> the seller's ± % band. Empty when none is set."""
    return {
        row.scope_ref: Decimal(str(row.value))
        for row in await _rows(session, shop_id, STABILITY_BAND)
    }


async def protected_terms(session: AsyncSession, shop_id: uuid.UUID) -> list[str]:
    """The shop's protected terms (listing edits must keep them); empty until set."""
    rows = await _rows(session, shop_id, PROTECTED_TERMS)
    if not rows or not isinstance(rows[0].value, list):
        return []
    return [str(term) for term in rows[0].value if isinstance(term, str) and term.strip()]


#: ADR-106 card lever code -> the rule's lever name. Codes absent here
#: (discounts, flash sale, shipping, buy-more) are price/promotion levers:
#: recommendation only, never executable (D13, ADR-109 d.10).
CARD_LEVER_TO_RULE_LEVER: Mapping[str, str] = {
    "title": "title",
    "description": "description",
    "cover_image": "image",
    "attributes": "attributes",
}


def card_lever_code(recommendation_payload: str | Mapping[str, Any] | None) -> str | None:
    """The ADR-106 lever code of a card's ``recommendation_payload``, or ``None``."""
    payload: Any = recommendation_payload
    if isinstance(payload, str):
        try:
            payload = json.loads(payload or "{}")
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, Mapping):
        return None
    diagnosis = payload.get("diagnosis")
    lever = diagnosis.get("lever") if isinstance(diagnosis, Mapping) else None
    code = lever.get("code") if isinstance(lever, Mapping) else None
    return str(code) if code else None


def card_lever_allowed(lever_code: str | None, allowed: frozenset[str]) -> bool:
    """Whether a card with this ADR-106 lever code may execute under ``allowed``.

    ``None`` (a card with no ADR-106 lever, e.g. the rule pipeline's legacy
    card) is not judged here and stays executable as before.
    """
    if lever_code is None:
        return True
    rule_lever = CARD_LEVER_TO_RULE_LEVER.get(lever_code)
    return rule_lever is not None and rule_lever in allowed


@dataclass(frozen=True)
class CostImportResult:
    imported: int
    errors: list[str]


async def import_product_costs_csv(
    session: AsyncSession,
    shop_id: uuid.UUID,
    csv_text: str,
    *,
    set_by: str,
    set_by_user_id: uuid.UUID | None,
    now: datetime | None = None,
) -> CostImportResult:
    """Import ``product_id,cost`` rows (D18 catalog upload). Flush, no commit.

    Header row required (``product_id`` and ``cost``; extra columns ignored).
    Bad rows are skipped and reported by line number; good rows are written.
    """
    _validate_set_by(set_by)
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("﻿")))
    fields = {name.strip().lower() for name in reader.fieldnames or []}
    if not {"product_id", "cost"} <= fields:
        raise RuleValidationError("CSV needs a header with product_id and cost columns")
    imported = 0
    errors: list[str] = []
    for line, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        product_id = row.get("product_id", "")
        cost = row.get("cost", "").replace(",", "")
        try:
            await set_rule(
                session,
                shop_id,
                rule_key=PRODUCT_COST,
                scope_ref=product_id,
                value=cost,
                set_by=set_by,
                set_by_user_id=set_by_user_id,
                now=now,
            )
        except RuleValidationError as exc:
            errors.append(f"line {line}: {exc}")
            continue
        imported += 1
    return CostImportResult(imported=imported, errors=errors)
