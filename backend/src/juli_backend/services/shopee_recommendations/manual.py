"""p91 D-3: manual offers and comparison ("Tự tạo phương án", "So sánh phương án").

``compare(env, variants)`` builds 2-4 variants on the SAME environment and history window with
the card builder (``cards.build_card``; ``combo_multi`` through the combo calculator behind the
evaluator registry) and returns them side by side with the deltas between them and against
today. It saves nothing. A variant that cannot be built carries a refusal reason; the others
still compute.

``create_manual(...)`` saves one chosen variant as a card with ``origin = "manual"`` through the
existing ``store.save_card`` (a card is the usual three rows: action card, proposal, frozen
`proposed` event), keeping the variants sent as ``versions`` (chosen first). Approve / "Đã làm" /
verification / learning run unchanged on it.

A variant is a plain dict::

    {"label": str | None, "change_kind": str, "items": [item_id, ...],
     "extra": {"addon_item": ..., "gift_item": ..., "combo_items": [{item_id, sku?, qty}],
               "discount_type": "pct|amount|fixed_price", "discount_value": n, "voucher": {...}},
     "inputs": {<the kind's what-if knobs>}}
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services.shop_proposals import cycle as proposals
from juli_backend.services.shop_proposals.cycle import ProposalError
from juli_backend.services.shopee_recommendations import combo, config, store
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.evaluate import evaluate
from juli_backend.services.shopee_recommendations.kinds import KINDS
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.model import Candidate

ORIGIN_MANUAL = "manual"
MIN_VARIANTS, MAX_VARIANTS = 2, 4
#: queue position given to a non-primary manual card until the queue integration lands
DEFAULT_MANUAL_POSITION = 50

ERROR_BAD_VARIANT = "reco_manual_invalid"
ERROR_BREACH = "reco_breach_not_acknowledged"
ERROR_NO_DATA = "reco_no_data"

#: change kinds a person may build by hand (the mega sale is a campaign of other cards)
MANUAL_KINDS: tuple[str, ...] = tuple(k for k, s in KINDS.items() if s.family != "mega_sale")

_REFUSAL_TEXT = {
    **combo.REFUSALS,
    "unknown_kind": "Loại thay đổi không hợp lệ.",
    "no_item": "Chưa chọn sản phẩm.",
    "item_unknown": "Sản phẩm chưa có đơn trong kỳ phân tích.",
    "no_order_lines": "Chưa có đơn trong kỳ phân tích để tính.",
    "no_addon": "Chưa chọn sản phẩm mua kèm.",
    "no_tier": "Chưa có bậc giảm nào.",
    "title_too_long": "Tên sản phẩm vượt quá số ký tự cho phép.",
    "invalid_inputs": "Các giá trị nhập vào không tính được.",
    "gift_cost_unknown": "Chưa biết giá vốn của quà tặng nên chưa tính được.",
    "no_listing": "Chưa có thông tin niêm yết của sản phẩm này.",
    "description_empty": "Dòng đầu mô tả đang trống.",
    "description_too_long": "Dòng đầu mô tả quá dài hoặc có nhiều dòng.",
    "banned_term": "Nội dung có từ không được dùng.",
    "variations_invalid": "Bảng phân loại chưa hợp lệ.",
    "stock_invalid": "Số lượng tồn không hợp lệ.",
}


def refusal(code: str) -> dict[str, str]:
    head = code.split(":", 1)[0]
    return {"code": code, "message": _REFUSAL_TEXT.get(head, code)}


class BreachNotAcknowledged(ProposalError):
    """The chosen variant breaks a floor or the spend cap and the request did not
    acknowledge it (owner decision 2026-11-04: breaches never block, they need a yes)."""

    def __init__(self, breaches: list[dict[str, Any]]) -> None:
        super().__init__(
            ERROR_BREACH, 422, "the offer breaks a floor price or the spend cap; acknowledge it"
        )
        self.breaches = breaches


def breaches_of(card: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = [{"type": "floor", **b} for b in card["floor"]["breaches"]]
    spend = card.get("spend") or {}
    if spend.get("over_cap"):
        out.append(
            {
                "type": "spend_cap",
                "spend_per_day_after": spend.get("shop_chi_per_day_after"),
                "cap": spend.get("cap"),
            }
        )
    return out


@dataclass(frozen=True)
class Actor:
    """Who creates the manual card: ``kind`` is ``staff`` (Ops) or ``seller`` (Demo)."""

    kind: str
    id: uuid.UUID
    staff_id: uuid.UUID | None = None

    def json(self) -> dict[str, str]:
        return {"type": self.kind, "id": str(self.id)}


# ----------------------------------------------------------------------------- variants


def candidate_of(variant: Mapping[str, Any]) -> Candidate:
    """The :class:`Candidate` a variant describes (combo variants fold ``extra`` into inputs)."""
    kind = str(variant.get("change_kind", ""))
    extra = dict(variant.get("extra") or {})
    inputs = dict(variant.get("inputs") or {})
    items = tuple(str(i) for i in (variant.get("items") or ()))
    if kind == combo.KIND:
        lines = [dict(x) for x in (extra.get("combo_items") or inputs.get("lines") or [])]
        inputs["lines"] = lines
        for key in ("discount_type", "discount_value", "voucher", "gift_item"):
            if key in extra and key not in inputs:
                inputs[key] = extra[key]
        inputs.setdefault("discount_type", "pct")
        items = tuple(str(x.get("item_id", "")) for x in lines)
        extra = {}
    return Candidate(
        kind=kind,
        items=items,
        inputs=inputs,
        extra={k: v for k, v in extra.items() if v is not None},
        reason=str(variant.get("reason") or ""),
        wiring_key=variant.get("wiring_key"),
    )


def _combo_title(env: RecoEnv, cand: Candidate) -> str:
    names = " + ".join(env.name(i) for i in cand.items)
    gift = " + quà" if cand.inputs.get("gift_item") else ""
    return f"{KINDS[combo.KIND].label} — {names}{gift}"


def build_variant(
    env: RecoEnv, variant: Mapping[str, Any], *, now: datetime
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """``(card, None)`` or ``(None, refusal)``; never raises on a bad variant."""
    kind = str(variant.get("change_kind", ""))
    if kind not in MANUAL_KINDS:
        return None, refusal("unknown_kind")
    try:
        cand = candidate_of(variant)
        if kind != combo.KIND:
            if not cand.items and KINDS[kind].subject_type == "item":
                return None, refusal("no_item")
            known = set(env.item_ids())
            for item in (
                *cand.items,
                *(cand.extra.get(k) for k in ("addon_item", "gift_item") if cand.extra.get(k)),
            ):
                if str(item) not in known:
                    return None, refusal(f"item_unknown:{item}")
        title = cand.inputs.get("title")
        if kind == "title" and isinstance(title, str) and len(title) > config.MAX_TITLE_CHARS:
            return None, refusal("title_too_long")
        ev = evaluate(env, cand)
        if ev.refusal:
            return None, refusal(ev.refusal)
        card = build_card(env, cand, now=now)
    except combo.ComboRefusal as exc:
        return None, refusal(exc.code)
    except (KeyError, IndexError, ValueError, TypeError, ArithmeticError):
        return None, refusal("invalid_inputs")
    if card is None:
        return None, refusal("no_order_lines")
    if kind == combo.KIND:
        card["title"] = _combo_title(env, cand)
    return card, None


# ---------------------------------------------------------------------------- metrics

_METRIC_KEYS = (
    "dprofit_p10",
    "dprofit_p50",
    "dprofit_p90",
    "dprofit_certain",
    "dgmv_p50",
    "dorders_p50",
    "aov_p25",
    "margin_points_p25",
    "cost_month",
    "floor_breaches",
)


def metrics_of(card: Mapping[str, Any]) -> dict[str, Any]:
    """The numbers the side-by-side shows (all per month, vs doing nothing)."""
    pm = card["predicted"]["money_per_month"]
    total, certain = pm["total"], pm["certain"]
    kpi = card["rank_inputs"]["kpi_p25"]
    spend = card.get("spend") or {}
    return {
        "dprofit_p10": total["p10"]["dprofit"],
        "dprofit_p50": total["p50"]["dprofit"],
        "dprofit_p90": total["p90"]["dprofit"],
        "dprofit_certain": certain["dprofit"],
        "dgmv_p50": total["p50"]["dgmv"],
        "dorders_p50": total["p50"]["dorders"],
        "aov_p25": kpi.get("aov"),
        "margin_points_p25": kpi.get("bien"),
        "cost_month": certain["dchi"],
        "floor_breaches": len(card["floor"]["breaches"]),
        "floor_ok": card["floor"]["ok"],
        "spend_after_per_day": spend.get("shop_chi_per_day_after"),
        "spend_cap": spend.get("cap"),
        "spend_over_cap": spend.get("over_cap"),
    }


def _diff(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    """``b - a`` per numeric metric (None when either side is unknown)."""
    out: dict[str, Any] = {}
    for key in _METRIC_KEYS:
        x, y = a.get(key), b.get(key)
        out[key] = None if x is None or y is None else round(y - x, 4)
    return out


def today_of(env: RecoEnv) -> dict[str, Any]:
    gmv, orders = float(env.shop_gmv_30d), env.shop_orders_30d
    sp = env.view.profit
    cap = env.daily_cap
    return {
        "as_of": env.as_of.isoformat(),
        "window": env.view.window.json(),
        "gmv_30d": gmv,
        "orders_30d": orders,
        "aov": gmv / orders if orders else None,
        "margin_pct": None if sp.margin_rate is None else float(sp.margin_rate) * 100,
        "spend_per_day": float(env.shop_chi_per_day()),
        "spend_cap": None if cap is None else float(cap),
    }


def compare(
    env: RecoEnv, variants: Sequence[Mapping[str, Any]], *, now: datetime
) -> dict[str, Any]:
    """Build 2-4 variants on one environment; side by side + deltas. Saves nothing."""
    if not MIN_VARIANTS <= len(variants) <= MAX_VARIANTS:
        raise ProposalError(ERROR_BAD_VARIANT, 422, "compare needs 2 to 4 variants")
    rows: list[dict[str, Any]] = []
    for n, v in enumerate(variants):
        card, why = build_variant(env, v, now=now)
        rows.append(
            {
                "index": n,
                "label": v.get("label") or f"Phương án {n + 1}",
                "change_kind": v.get("change_kind"),
                "ok": card is not None,
                "refusal": why,
                "title": None if card is None else card["title"],
                "metrics": None if card is None else metrics_of(card),
                "card": card,
            }
        )
    ok = [r for r in rows if r["ok"]]
    between = [
        {"from": a["index"], "to": b["index"], "delta": _diff(a["metrics"], b["metrics"])}
        for i, a in enumerate(ok)
        for b in ok[i + 1 :]
    ]
    safe = [r for r in ok if r["metrics"]["floor_ok"] and r["metrics"]["dprofit_p50"] is not None]
    best = max(safe, key=lambda r: r["metrics"]["dprofit_p50"], default=None)
    return {
        "today": today_of(env),
        "variants": rows,
        "vs_today": [
            {"index": r["index"], "delta": {k: r["metrics"][k] for k in _METRIC_KEYS}} for r in ok
        ],
        "between": between,
        "best_profit_p50": None if best is None else best["index"],
        "saved": False,
    }


# ------------------------------------------------------------------------------- save


def _enqueue(card: dict[str, Any], *, primary: bool) -> int:
    """INTEGRATION POINT (p91-core): put the new card into its product's queue and return the
    position to store. TODO(p91-core): replace with the per-product queue -- assign the card
    code ``JC-yymm-seq4``, take ``product_queue = 1`` when ``primary`` (previous #1 moves to
    2), else append by score. Until then: position 1 for a primary card, a fixed late position
    otherwise, and the intent is recorded on the card (``primary``) for the queue to read."""
    card["primary"] = primary
    return 1 if primary else DEFAULT_MANUAL_POSITION


def _version_row(
    index: int,
    variant: Mapping[str, Any],
    card: dict[str, Any] | None,
    why: dict | None,
    *,
    chosen: bool,
    version: int = 1,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "version": version,
        "index": index,
        "chosen": chosen,
        "label": variant.get("label") or f"Phương án {index + 1}",
        "change_kind": variant.get("change_kind"),
        "items": list(variant.get("items") or []),
        "extra": dict(variant.get("extra") or {}),
        "inputs": dict(variant.get("inputs") or {}),
        "refusal": why,
        "title": None if card is None else card["title"],
        "metrics": None if card is None else metrics_of(card),
    }
    if card is not None and not chosen:
        row["card"] = card
    return row


async def create_manual(
    session: Any,
    shop_id: uuid.UUID,
    variants: Sequence[Mapping[str, Any]],
    chosen: int,
    primary: bool,
    actor: Actor,
    *,
    now: datetime,
    as_of: date | None = None,
    env: RecoEnv | None = None,
    cards: Sequence[dict[str, Any] | None] | None = None,
    acknowledge_breaches: bool = False,
    origin: str = ORIGIN_MANUAL,
    card_extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Save ``variants[chosen]`` as a manual card. Never commits (the route does).

    ``origin`` ("import") and ``card_extra`` (``external_ref`` ...) are for the planned-changes
    import (p91 D-13).

    ``cards`` (tests / a caller that already built them) skips building. The chosen variant
    must build; one that breaks a floor / the spend cap needs ``acknowledge_breaches`` (422
    with the breach list otherwise) and the acknowledgement is stored on the card.
    Returns ``{id, status, versions, position}``.
    A seller's card is sent at once (the seller approves it in the app); Ops' stays a draft.
    """
    now = now.replace(tzinfo=None)
    if not 1 <= len(variants) <= MAX_VARIANTS or not 0 <= chosen < len(variants):
        raise ProposalError(ERROR_BAD_VARIANT, 422, "1 to 4 variants and a valid chosen index")
    built: list[tuple[dict[str, Any] | None, dict[str, str] | None]]
    if cards is not None:
        built = [(c, None if c is not None else refusal("invalid_inputs")) for c in cards]
        window_env = env
    else:
        window_env = env or await load_env(session, shop_id, as_of=as_of, now=now)
        if window_env is None:
            raise ProposalError(ERROR_NO_DATA, 409, "shop has no Shopee numbers")
        built = [build_variant(window_env, v, now=now) for v in variants]
    card, why = built[chosen]
    if card is None:
        assert why is not None
        raise ProposalError(ERROR_BAD_VARIANT, 422, why["message"])
    breaches = breaches_of(card)
    if breaches and not acknowledge_breaches:
        raise BreachNotAcknowledged(breaches)
    if breaches:
        card["acknowledged_breaches"] = {
            "by": actor.json(),
            "at": now.isoformat(),
            "breaches": breaches,
        }
    order = [chosen, *[i for i in range(len(variants)) if i != chosen]]
    card["origin"] = origin
    card["created_by"] = actor.json()
    card.update(card_extra or {})
    card["versions"] = [
        _version_row(i, variants[i], *built[i], chosen=i == chosen, version=n)
        for n, i in enumerate(order, 1)
    ]
    position = _enqueue(card, primary=primary)
    card["rank"] = {
        "position": position,
        "score": None,
        "detail": {},
        "mode": origin,
        "explore": False,
    }
    cycle = f"{window_env.as_of:%Y-%m}" if window_env is not None else f"{now:%Y-%m}"
    card_id = await store.save_card(
        session,
        shop_id,
        card,
        cycle=cycle,
        position=position,
        now=now,
        staff_id=actor.staff_id,
    )
    await store.set_meta(
        session,
        shop_id,
        card_id,
        {"origin": origin, "created_by": actor.json(), "primary": primary},
    )
    status = "draft"
    if actor.kind == "seller":
        proposal = await session.get(ShopProposal, card_id)
        await proposals.send(session, proposal, now=now)
        status = proposal.status
    return {
        "id": str(card_id),
        "status": status,
        "origin": origin,
        "position": position,
        "primary": primary,
        "versions": [{k: v for k, v in row.items() if k != "card"} for row in card["versions"]],
        "card": card,
    }


__all__ = [
    "Actor",
    "BreachNotAcknowledged",
    "MANUAL_KINDS",
    "ORIGIN_MANUAL",
    "build_variant",
    "candidate_of",
    "compare",
    "create_manual",
    "metrics_of",
    "refusal",
]
