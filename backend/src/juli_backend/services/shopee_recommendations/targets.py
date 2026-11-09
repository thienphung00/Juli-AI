"""P97 D85.13: one card, many targets.

A strategy Shopee applies as one setting to many things (giảm giá %, hoa hồng affiliate, ngân sách /
ROAS of several campaigns) is ONE card with a target list. Each target is built as an ordinary
single-target card by the existing evaluators; this module only lays the targets side by side and
adds them up:

- money (certain layer, P10..P90 totals, per day, over the period) -- P50s add, the range is the
  root sum of squares of the targets' half-widths (the rule of ``plan_aggregate.combine_predicted``,
  the targets' prediction errors being treated as independent);
- floors per target (``floor.breaches`` carry the ``target`` they belong to), the shop spend check
  once on the summed spend;
- ``targets`` -- the rows the card page shows (a figure per target, a refusal per target that cannot
  be evaluated) and the list the Connector's fill queue reads: ``{id, kind, variant}`` with the
  per-target variant (``change_kind``, ``items`` / ``campaign_key``, ``inputs``);
- ``fill`` -- ``bulk`` when Shopee has a bulk edit for the kind (affiliate commission, the product
  picker of a voucher), else ``per_target`` (one job per target).

Pure over cards already built; ``build_multi`` takes the single-target builder as a callback so this
module imports nothing from ``manual``.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from juli_backend.services.shopee_recommendations.env import RecoEnv

KEY = "targets"
QUANTILES = ("p10", "p25", "p50", "p75", "p90")
METRICS = ("dgmv", "dorders", "dprofit")
#: kinds for which Shopee has a bulk edit (one pass for all targets)
BULK_KINDS = frozenset({"affiliate_commission", "min_spend_voucher"})
Builder = Callable[..., "tuple[dict[str, Any] | None, dict[str, str] | None]"]


def is_multi(variant_or_card: Mapping[str, Any]) -> bool:
    return bool(variant_or_card.get(KEY))


def _f(value: float | None) -> float:
    return 0.0 if value is None else float(value)


def combine(
    parts: Sequence[Mapping[str, Mapping[str, float | None]]], *, strict: bool = False
) -> dict[str, Any]:
    """``{quantile: {metric: v}}`` of several independent parts: P50s add, widths add in quadrature.
    A metric nobody knows stays ``None``. A part that does not know it is left out -- unless
    ``strict``: then the total is unknown too (a card total never passes a partial sum off as the
    whole: one target without a giá vốn makes the profit of the card "chưa tính")."""
    out: dict[str, dict[str, float | None]] = {q: {} for q in QUANTILES}
    for m in METRICS:
        known = [p for p in parts if p["p50"].get(m) is not None]
        if not known or (strict and len(known) != len(parts)):
            for q in QUANTILES:
                out[q][m] = None
            continue
        mid = sum(_f(p["p50"][m]) for p in known)
        for q in QUANTILES:
            if q == "p50":
                out[q][m] = mid
                continue
            squares = sum(
                (_f(p["p50"][m]) - _f(p[q][m])) ** 2 for p in known if p[q].get(m) is not None
            )
            width = math.sqrt(squares)
            out[q][m] = mid - width if q in ("p10", "p25") else mid + width
    return out


def _sum_certain(blocks: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    keys = ("dgmv", "dprofit", "dchi")
    return {k: sum(float(b.get(k) or 0.0) for b in blocks) for k in keys}


def merge_money(blocks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The ``prediction.convert`` blocks of several cards as one."""
    out: dict[str, Any] = {
        "days": min(int(b["days"]) for b in blocks),
        "certain": _sum_certain([b["certain"] for b in blocks]),
        "predicted": combine([b["predicted"] for b in blocks], strict=True),
        "total": combine([b["total"] for b in blocks], strict=True),
    }
    for key in ("period", "per_day"):
        if all(b.get(key) for b in blocks):
            merged: dict[str, Any] = {
                "certain": _sum_certain([b[key]["certain"] for b in blocks]),
                "total": combine([b[key]["total"] for b in blocks], strict=True),
            }
            if key == "period":
                merged["days"] = int(blocks[0][key]["days"])
            out[key] = merged
    return out


#: figures of ``card["certain"]`` that add up over independent targets (a total, not a rate)
ADDITIVE = (
    "profit_delta_same_volume",
    "break_even_extra_orders",
    "commission_cost_before",
    "commission_cost_after",
    "spend_per_day_now",
    "spend_per_day_after",
)


def _add_known(values: Sequence[Any]) -> float | None:
    return None if any(v is None for v in values) else sum(float(v) for v in values)


def _spend(env: RecoEnv, cards: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    spends: list[Mapping[str, Any]] = [c["spend"] for c in cards if c.get("spend")]
    if not spends:
        return None
    first = dict(spends[0])
    delta = sum(float(s.get("card_dchi_per_day") or 0.0) for s in spends)
    now = first.get("shop_chi_per_day_now")
    cap = first.get("cap")
    after = None if now is None else float(now) + delta
    first["card_dchi_per_day"] = delta
    first["shop_chi_per_day_after"] = after
    first["over_cap"] = None if cap is None or after is None else after > float(cap)
    return first


def brief(card: Mapping[str, Any]) -> dict[str, Any]:
    money = card["predicted"]["money_per_month"]
    total = money["total"]
    return {
        "dgmv_p50": total["p50"]["dgmv"],
        "dorders_p50": total["p50"]["dorders"],
        "dprofit_p50": total["p50"]["dprofit"],
        "dprofit_p10": total["p10"]["dprofit"],
        "dprofit_p90": total["p90"]["dprofit"],
        "cost_month": money["certain"]["dchi"],
        "floor_ok": bool(card["floor"]["ok"]),
    }


def fill_mode(change_kind: str) -> str:
    return "bulk" if change_kind in BULK_KINDS else "per_target"


def merge_cards(
    env: RecoEnv,
    cards: Sequence[dict[str, Any]],
    entries: Sequence[Mapping[str, Any]],
    refused: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """One card out of several single-target cards of the same strategy. ``entries[i]`` is the
    ``{id, kind, name?, variant}`` row of ``cards[i]``; ``refused`` rows (``{id, kind, name?,
    refusal}``) are kept in the list with their reason and add nothing."""
    from juli_backend.services.shopee_recommendations.cards import shop_deltas

    if not cards or len(cards) != len(entries):
        raise ValueError("one entry per card")
    out = copy.deepcopy(cards[0])
    ids = list(dict.fromkeys(i for c in cards for i in c["scope"]["product_ids"]))
    out["scope"]["product_ids"] = ids
    out["scope"]["sku_ids"] = sorted({s for c in cards for s in c["scope"]["sku_ids"]})
    n = len(cards)
    head = str(out["title"]).split(" — ")[0]
    out["title"] = f"{head} — {n} {'sản phẩm' if entries[0]['kind'] == 'item' else 'chiến dịch'}"
    pairs = list(zip(cards, entries, strict=True))
    breaches = [{**b, "target": e["id"]} for c, e in pairs for b in c["floor"]["breaches"]]
    out["floor"] = {
        "breaches": breaches,
        "unknown_skus": sorted({s for c in cards for s in c["floor"]["unknown_skus"]}),
        "ok": not breaches,
    }
    out["spend"] = _spend(env, cards)
    money = merge_money([c["predicted"]["money_per_month"] for c in cards])
    out["predicted"]["money_per_month"] = money
    out["five_numbers"] = None  # a shop-wide before -> after of one product no longer applies
    notes = list(dict.fromkeys(note for c in cards for note in c.get("notes", [])))
    out["notes"] = notes
    additive = {k: _add_known([c["certain"].get(k) for c in cards]) for k in ADDITIVE}
    out["certain"] = {
        **out["certain"],
        **{k: v for k, v in additive.items() if k in out["certain"]},
        "targets": n,
        "targets_certain": _sum_certain(
            [c["predicted"]["money_per_month"]["certain"] for c in cards]
        ),
    }
    deltas = shop_deltas(env, money, "p25")
    dprofit = money["total"]["p50"]["dprofit"]
    if dprofit is None:
        dprofit = money["certain"]["dprofit"]
    out["rank_inputs"] = {
        **out["rank_inputs"],
        "kpi_p25": deltas,
        "kpi_p50": shop_deltas(env, money, "p50"),
        "dgmv_p25": money["total"]["p25"]["dgmv"],
        "dprofit_p50": dprofit,
        "floor_breach": bool(breaches),
        "spend_after": (out["spend"] or {}).get("shop_chi_per_day_after"),
        "in_stock": all(c["rank_inputs"].get("in_stock") is not False for c in cards),
        "items": ids,
    }
    sheets = [{"target": e["id"], "sheet": c["execution_sheet"]} for c, e in pairs]
    out["execution_sheet"] = {**out["execution_sheet"], "per_target": sheets}
    out["change"] = {**out["change"], "targets": [e["id"] for e in entries]}
    rows = [
        {
            "id": e["id"],
            "kind": e["kind"],
            "name": e.get("name"),
            "variant": e["variant"],
            "ok": True,
            "refusal": None,
            **brief(c),
        }
        for c, e in pairs
    ] + [
        {
            "id": r["id"],
            "kind": r["kind"],
            "name": r.get("name"),
            "variant": r.get("variant"),
            "ok": False,
            "refusal": r["refusal"],
        }
        for r in refused
    ]
    out[KEY] = rows
    out["fill"] = {"mode": fill_mode(out["change_kind"]), "targets": n}
    return out


def build_multi(
    env: RecoEnv, variant: Mapping[str, Any], *, now: datetime, build_one: Builder
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Build the merged card of a variant that carries ``targets`` (``manual.build_variant``)."""
    cards: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = [dict(r) for r in variant.get("refused_targets") or []]
    first_why: dict[str, str] | None = None
    for t in variant[KEY]:
        card, why = build_one(env, t["variant"], now=now)
        if card is None:
            first_why = first_why or why
            refused.append({**t, "refusal": why})
            continue
        cards.append(card)
        entries.append(dict(t))
    if not cards:
        return None, first_why
    return merge_cards(env, cards, entries, refused), None


def part_cards(
    env: RecoEnv,
    targets: Sequence[Mapping[str, Any]],
    overrides: Mapping[str, Any],
    *,
    now: datetime,
    merge_inputs: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """The single-target cards of a stored target list on THIS environment, with the what-if
    ``overrides`` applied to each target's inputs. ``(cards, entries, refused)``."""
    from juli_backend.services.shopee_recommendations import manual
    from juli_backend.services.shopee_recommendations.cards import build_card

    cards: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    for t in targets:
        variant = copy.deepcopy(dict(t["variant"]))
        cand = manual.candidate_of(variant)
        cand.inputs = merge_inputs(dict(cand.inputs), dict(overrides))
        card = build_card(env, cand, now=now)
        if card is None:
            refused.append({**t, "refusal": manual.refusal("no_order_lines")})
            continue
        variant["inputs"] = dict(cand.inputs)
        cards.append(card)
        entries.append({**t, "variant": variant})
    return cards, entries, refused


def recompute(
    env: RecoEnv,
    targets: Sequence[Mapping[str, Any]],
    overrides: Mapping[str, Any],
    *,
    now: datetime,
    merge_inputs: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
) -> dict[str, Any] | None:
    """The merged card again (``service.recompute_card`` of a multi-target card). The single-target
    cards ride along as ``_parts`` for the plan's joint evaluation; they are never stored."""
    cards, entries, refused = part_cards(
        env, targets, overrides, now=now, merge_inputs=merge_inputs
    )
    if not cards:
        return None
    merged = merge_cards(env, cards, entries, refused)
    merged["_parts"] = cards
    return merged


__all__ = [
    "BULK_KINDS",
    "KEY",
    "brief",
    "build_multi",
    "combine",
    "fill_mode",
    "is_multi",
    "merge_cards",
    "merge_money",
    "part_cards",
    "recompute",
]
