"""Assemble one recommendation card: the frozen ADR-107/121 proposal payload.

``build_card(env, candidate, now=)`` evaluates the certain layer, predicts the range, plans
the measurement and writes the execution sheet. The returned dict is what the `proposed`
event freezes (inputs, certain numbers, the lift model's range and version, the simulation
run and its prediction, the measurement plan) and what the API serves. Money in the card is
JSON numbers (VND); the seller-facing texts are Vietnamese.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_profit.money import ZERO, safe_div
from juli_backend.services.shopee_profit.whatif import PredictedRange
from juli_backend.services.shopee_recommendations import config, freshness
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.evaluate import evaluate
from juli_backend.services.shopee_recommendations.kinds import (
    FAMILY_LABELS,
    allowed_for_metric,
    spec,
)
from juli_backend.services.shopee_recommendations.model import Candidate, Evaluation
from juli_backend.services.shopee_recommendations.plan import measurement_plan, stats_for
from juli_backend.services.shopee_recommendations.prediction import (
    Lift,
    convert,
    extra_orders_range,
    magnitude_of,
    predict_lift,
)
from juli_backend.services.shopee_recommendations.sheet import build_sheet


def variant_hints(cand: Candidate) -> list[str]:
    """Names of the simulation variants closest to this change (exact match only)."""
    i = cand.inputs
    k = cand.kind
    if k in ("product_discount",) and i.get("discount_pct") is not None:
        d = int(i["discount_pct"])
        return [f"price_-{d}_banner", f"price_-{d}"]
    if k == "flash_sale" and i.get("discount_pct") is not None:
        return [f"flash_-{int(i['discount_pct'])}"]
    if k == "bundle_deal":
        return [f"tier_3_-{int(i.get('tier3_pct', 0))}", f"tier_2_-{int(i.get('tier2_pct', 0))}"]
    return []


def _label(env: RecoEnv, cand: Candidate) -> str:
    s = spec(cand.kind)
    if cand.item:
        return f"{s.label} — {env.name(cand.item)}"
    if cand.campaign_key:
        alloc = next((c for c in env.view.ads.campaigns if c.key == cand.campaign_key), None)
        return f"{s.label} — {alloc.name if alloc else 'chiến dịch'}"
    return s.label


def shop_deltas(env: RecoEnv, money: dict[str, Any], quantile: str = "p25") -> dict[str, float]:
    """Shop-level dKPI at a quantile (default P25; month): GMV, orders, AOV (VND), margin (points).
    ``money`` is a ``prediction.convert`` dict (a card's, or a plan's combined one)."""
    p25 = money["total"][quantile]
    gmv, orders = float(env.shop_gmv_30d), float(env.shop_orders_30d)
    d_gmv = p25["dgmv"]
    d_orders = p25["dorders"] or 0.0
    d_aov = 0.0
    if orders > 0:
        d_aov = (gmv + d_gmv) / (orders + d_orders) - gmv / orders if orders + d_orders > 0 else 0.0
    d_bien = 0.0
    sp = env.view.profit
    m0 = sp.margin_rate
    base_paid = float(sp.buyer_paid_covered)
    d_profit = p25["dprofit"] if p25["dprofit"] is not None else money["certain"]["dprofit"]
    if m0 is not None and base_paid > 0 and gmv > 0:
        profit0 = float(m0) * base_paid
        scale = base_paid / gmv
        after = (
            (profit0 + d_profit) / (base_paid + d_gmv * scale)
            if base_paid + d_gmv * scale > 0
            else float(m0)
        )
        d_bien = (after - float(m0)) * 100
    return {"gmv": d_gmv, "orders": d_orders, "aov": d_aov, "bien": d_bien}


def _slider_rows(env: RecoEnv, cand: Candidate) -> list[dict[str, Any]]:
    s = spec(cand.kind)
    rows = []
    for sl in s.sliders:
        if sl.key not in cand.inputs or cand.inputs[sl.key] is None:
            continue
        rows.append(
            {
                "key": sl.key,
                "label": sl.label,
                "unit": sl.unit,
                "min": sl.minimum,
                "max": sl.maximum,
                "step": sl.step,
                "default": cand.inputs[sl.key],
                "default_source": cand.extra.get("default_source", {}).get(sl.key, "generator"),
            }
        )
    return rows


def _text_fields(cand: Candidate) -> list[dict[str, Any]]:
    """Free-text inputs a person may edit before approving (only the proposed title)."""
    if cand.kind != "title":
        return []
    return [
        {
            "key": "title",
            "label": "Tên sản phẩm mới",
            "max_chars": config.MAX_TITLE_CHARS,
            "default": cand.inputs.get("title"),
        }
    ]


def _in_stock(env: RecoEnv, cand: Candidate) -> bool | None:
    if not cand.items:
        return True
    stocks = [env.stock(i) for i in cand.items]
    if any(s == 0 for s in stocks):
        return False
    if all(s is None for s in stocks):
        return None
    return True


def build_card(env: RecoEnv, cand: Candidate, *, now: datetime) -> dict[str, Any] | None:
    if cand.kind in ("affiliate_sample", "affiliate_invite"):  # P91 D-9: own model
        from juli_backend.services.shopee_recommendations.kol_cards import build_kol_card

        kol = build_kol_card(env, cand, now=now)
        if kol is not None:
            kol["freshness"] = freshness.stamp(env, cand.items, now)
        return kol
    s = spec(cand.kind)
    ev0 = evaluate(env, cand)
    if ev0.refusal:
        return None
    mag = magnitude_of(cand, ev0.before, ev0.after)
    if mag is None:
        mag = cand.extra.get("magnitude_pct")
    lift = predict_lift(s, cand, env, mag, sim_variant=variant_hints(cand))
    rng = extra_orders_range(lift, ev0.profit)
    ev: Evaluation = ev0
    if rng is not None and s.family in ("voucher", "promotion", "sale"):
        ev = evaluate(env, cand, predicted=PredictedRange(rng[0], rng[1], config.MODEL_VERSION))
    money = convert(lift, ev.profit)
    plan = measurement_plan(s.target_metric, stats_for(env, cand.items or None, s.target_metric))
    if lift.sim.get("row_found") and cand.item:
        sim_kg = env.sim.kg_value(cand.item, s.sim_kind) if env.sim and s.sim_kind else None
    else:
        sim_kg = (
            env.sim.kg_value(cand.item, s.sim_kind)
            if env.sim and s.sim_kind and cand.item
            else None
        )
    sheet = build_sheet(cand.kind, ev.target, ev.before, ev.after, dict(cand.inputs))
    deltas = shop_deltas(env, money)
    dprofit_p50 = money["total"]["p50"]["dprofit"]
    if dprofit_p50 is None:
        dprofit_p50 = money["certain"]["dprofit"]
    spend = ev.spend_check or {}
    scope_items = list(cand.items)
    card: dict[str, Any] = {
        "schema": config.SCHEMA,
        "family": s.family,
        "family_label": FAMILY_LABELS[s.family],
        "change_kind": cand.kind,
        "title": _label(env, cand),
        "reason": cand.reason,
        "platform": "shopee",
        "model_version": config.MODEL_VERSION,
        "generated_at": now.isoformat(),
        "as_of": env.as_of.isoformat(),
        "window": env.view.window.json(),
        "order_basis": {"key": "confirmed", "label": "Đơn đã xác nhận"},
        "metric": {
            "key": s.target_metric,
            "critical_id": (cand.critical or {}).get("id"),
            "critical_kpi": (cand.critical or {}).get("kpi"),
            "flow": (cand.critical or {}).get("flow"),
            "at_stake_per_day": (cand.critical or {}).get("at_stake_per_day"),
            "at_stake_per_month": (cand.critical or {}).get("at_stake_per_month"),
        },
        "wiring": {
            "critical_metric": cand.wiring_key,
            "allowed_kinds": list(allowed_for_metric(cand.wiring_key or "")),
        },
        "scope": {
            "level": s.subject_type,
            "product_ids": scope_items,
            "sku_ids": sorted({sk for i in scope_items for sk in env.skus_of(i)}),
            "campaign_key": cand.campaign_key,
        },
        "change": {
            "change_kind": cand.kind,
            "target": ev.target,
            "before": ev.before,
            "after": ev.after,
        },
        "inputs": dict(cand.inputs),
        "candidate_extra": dict(cand.extra),
        "wiring_key": cand.wiring_key,
        "gap_pct": cand.gap_pct,
        "whatif": {"sliders": _slider_rows(env, cand), "text_fields": _text_fields(cand)},
        "certain": {**ev.certain, "label": "Chắc chắn"},
        "five_numbers": ev.five,
        "floor": {
            "breaches": ev.breaches,
            "unknown_skus": ev.floor_unknown_skus,
            "ok": not ev.breaches,
        },
        "spend": ev.spend_check,
        "predicted": {
            "label": "Dự kiến",
            "model_version": config.MODEL_VERSION,
            "lift": lift.json(),
            # P96d: the change's own size (``ProfitModel.lift_scale``) that the money already
            # carries; the driver metrics read it so each version's "after" follows its size
            "lift_scale": float(ev.profit.lift_scale),
            "money_per_month": money,
            "base": ev.profit.base_label,
            "sim": lift.sim,
        },
        "measurement_plan": plan,
        "execution_sheet": sheet,
        "notes": ev.notes,
        "rank_inputs": {
            "kpi_p25": deltas,
            "dgmv_p25": money["total"]["p25"]["dgmv"],
            "dprofit_p50": dprofit_p50,
            "floor_breach": bool(ev.breaches),
            "spend_after": spend.get("shop_chi_per_day_after"),
            "spend_cap": spend.get("cap"),
            "in_stock": _in_stock(env, cand),
            "kg_value": sim_kg,
            "items": scope_items,
        },
        "bundle": False,
        "freshness": freshness.stamp(env, scope_items, now),
    }
    return card


def proposal_fields(card: dict[str, Any], env_name: str) -> dict[str, Any]:
    """Seller-readable pieces for ``shop_proposals`` (change_before / change_after / label)."""
    ch = card["change"]
    return {
        "kind": spec(card["change_kind"]).proposal_kind,
        "subject_type": "item"
        if card["scope"]["product_ids"]
        else ("campaign" if card["scope"]["level"] == "campaign" else "shop"),
        "item_id": card["scope"]["product_ids"][0] if card["scope"]["product_ids"] else None,
        "subject_label": card["title"][:255] or env_name,
        "change_before": {"change_kind": ch["change_kind"], **ch["before"]},
        "change_after": {"change_kind": ch["change_kind"], **ch["after"], "inputs": card["inputs"]},
        "reason": card["reason"] or card["title"],
    }


__all__ = ["Decimal", "Lift", "ZERO", "build_card", "proposal_fields", "safe_div", "variant_hints"]
