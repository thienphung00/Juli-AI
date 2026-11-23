"""Card stage (E5): G1-G5 gates, Jev chooses, Juli's recommendation engine supplies the values.

Order: chain -> G1 -> Jev (actionable Noul, kind, product) -> G2 WIRING -> G5 evidence -> G3 engine
values (read-only, never persisted) -> G4 overlap (exact in code, then a Jev overlap Noul) -> Jev
picks
the recommended version. A Juli card is a DRAFT the seller may send into Đề xuất; it never exists
until T3's send creates it. Stock-outs are mentioned only, never a card. Numbers are copied from the
engine result, never recomputed.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from juli_backend.services.analytics_agent import fmt
from juli_backend.services.analytics_agent.chains import ChainResult
from juli_backend.services.analytics_agent.routing import FITS_GO, choice_ok
from juli_backend.services.analytics_agent.types import (
    CardEnginePort,
    DataPort,
    JevPort,
    LabelTable,
    Template,
    Usage,
)

KIND_EN: dict[str, str] = {
    "product_discount": "discount on the product's price",
    "price": "change the listed price",
    "min_spend_voucher": "voucher with a minimum spend",
    "review_voucher": "voucher for buyers who review",
    "voucher_cap": "cap or cut the voucher value",
    "flash_sale": "join a flash sale",
    "program_registration": "join a Shopee programme",
    "bundle_deal": "bundle deal (buy more, pay less)",
    "add_on": "add-on deal",
    "gift": "gift with purchase",
    "variation_set": "sell a set / multi-pack variation",
    "ads_budget": "change the ads budget",
    "ads_roas_target": "change the ads ROAS target",
    "ads_pause": "pause ads",
    "ads_purpose": "change the ads campaign goal",
    "title": "rewrite the product title",
    "keyword": "change listing keywords",
    "cover_image": "change the cover image",
    "price_display": "change how the price is displayed",
    "affiliate_commission": "change the affiliate commission",
    "affiliate_target_campaign": "affiliate target campaign",
}
#: driver metric -> WIRING keys (funnel factors expanded)
FACTORS: dict[str, tuple[str, ...]] = {
    "orders": ("views", "ctr", "ctor"),
    "units": ("views", "ctr", "ctor"),
    "clicks": ("views", "ctr"),
    "gmv": ("views", "ctr", "ctor", "aov"),
    "views": ("views",),
    "ctr": ("ctr",),
    "ctor": ("ctor",),
    "aov": ("aov",),
    "profit": ("bien",),
    "margin": ("bien",),
    "roas": ("roas",),
    "ads_spend": ("roas",),
}
#: cost_ratio: the kinds by the cost line that drives it (ads / affiliate / offers only; COGS, fees,
#: shipping, packaging are mentioned, never a card)
COST_KINDS: dict[str, tuple[str, ...]] = {
    "cost_ads": ("ads_budget", "ads_roas_target", "ads_pause"),
    "cost_affiliate": ("affiliate_commission",),
    "cost_offers": ("voucher_cap", "product_discount", "price"),
}
COARSE = {
    "product_discount": "price",
    "price": "price",
    "min_spend_voucher": "voucher",
    "review_voucher": "voucher",
    "voucher_cap": "voucher",
    "flash_sale": "flash_sale",
    "program_registration": "program",
    "bundle_deal": "bundle",
    "add_on": "bundle",
    "gift": "bundle",
    "variation_set": "bundle",
    "title": "title",
    "keyword": "title",
    "cover_image": "images",
    "price_display": "images",
}
NO_CARD_VI = {
    "within_noise": "Biến động nằm trong mức bình thường nên chưa cần đề xuất.",
    "data_missing": "Thiếu dữ liệu nên chưa đề xuất.",
    "data_stale": "Dữ liệu chưa cập nhật nên chưa đề xuất.",
    "unexplained": "Chưa rõ nguyên nhân nên chưa đề xuất.",
}


def card_figures(accepted: list[dict[str, Any]]) -> list[float]:
    """Every number of an accepted card (P50s, costs): never allowed in the text."""
    out: list[float] = []
    for a in accepted:
        for v in (a.get("engine_card") or {}).get("versions") or []:
            r = v.get("result") or {}
            d = _own(v).get("delta") or {}
            for x in (
                (d.get("gmv") or {}).get("p50"),
                (d.get("profit") or {}).get("p50"),
                r.get("cost_total"),
            ):
                if isinstance(x, (int, float)):
                    out.append(float(x))
    return out


def coarse(kind: str) -> str:
    """The lever family of a change kind; an already-coarse proposal kind maps to itself."""
    return COARSE.get(kind, "ads" if kind.startswith("ads") else kind)


@dataclass
class CardOutcome:
    accepted: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)  # `card` / `no_card`
    routing: list[dict[str, Any]] = field(default_factory=list)
    cost_usd: float = 0.0
    gates: dict[str, Any] = field(default_factory=dict)


def g1(chain: ChainResult, template: Template | None) -> bool:
    """Explained, or unexplained with an actionable event (not a stock-out); templates: any stop
    reason."""
    if template is not None and template.allows_card_any_stop:
        return True
    if chain.stop_reason == "explained":
        return True
    return chain.stop_reason == "unexplained" and any(
        e["kind"] == "ads_spend_drop" for e in chain.events
    )


def evidence(chain: ChainResult) -> tuple[set[str], set[str]]:
    """Products and metrics that appear in the explaining findings (G5)."""
    items: set[str] = set()
    metrics: set[str] = {chain.metric}
    if chain.item_id:
        items.add(chain.item_id)
    for f in chain.findings:
        m = re.search(r"product:([^:\s]+)", f.evidence_ref or "")
        if m:
            items.add(m.group(1))
        m2 = re.match(r"metric_view:[a-z_]+:product:([^:\s]+)", f.evidence_ref or "")
        if m2:
            items.add(m2.group(1))
        if f.level == "formula":
            metrics.add(f.node)
        m3 = re.match(r"(?:rate_mix|lmdi|metric_view):([a-z_]+)", f.evidence_ref or "")
        if m3:
            metrics.add(m3.group(1))
    for name in list(metrics):
        metrics |= set(FACTORS.get(name, ()))
    if "margin" in metrics or "profit" in metrics:
        metrics.add("bien")
    return items, metrics


def candidate_kinds(chain: ChainResult, engine: CardEnginePort) -> list[str]:
    if chain.metric == "cost_ratio":
        top = next(
            (
                f.node
                for f in sorted(
                    (f for f in chain.findings if f.level == "line" and f.contribution_pct),
                    key=lambda f: -abs(f.contribution_pct or 0),
                )
            ),
            None,
        )
        lines = [top] if top else list(COST_KINDS)
        out: list[str] = []
        for ln in lines:
            out += [k for k in COST_KINDS.get(ln, ()) if k not in out]
        return [k for k in out if k in KIND_EN]
    out = []
    for key in FACTORS.get(chain.metric, (chain.metric,)):
        for k in engine.allowed_kinds(key):
            if k not in out and k in KIND_EN:
                out.append(k)
    return out


def _compact(chain: ChainResult) -> dict[str, Any]:
    """English, no free text: what Jev may see when choosing a card."""
    return {
        "metric": chain.metric,
        "stop_reason": chain.stop_reason,
        "drivers": [
            {
                "level": f.level,
                "node": f.node.partition(".")[0]
                if f.level in ("source", "formula")
                else f.node[:80],
                "share_pct": f.contribution_pct,
            }
            for f in chain.findings
            if f.contribution_pct is not None
        ][:8],
        "events": [e["kind"] for e in chain.events][:6],
    }


def _own(v: dict[str, Any]) -> dict[str, Any]:
    return (v.get("result") or {}).get("own") or {}


def render_versions(engine_card: dict[str, Any], recommended: str | None) -> list[dict[str, Any]]:
    out = []
    for v in engine_card.get("versions") or []:
        r = v.get("result") or {}
        d = _own(v).get("delta") or {}
        m = r.get("margin") or {}
        est = bool(r.get("estimable"))
        out.append(
            {
                "label_vi": v.get("label"),
                "inputs": v.get("inputs"),
                "recommended": v.get("label") == recommended,
                "estimable": est,
                "gmv_p50": (d.get("gmv") or {}).get("p50") if est else None,
                "profit_p50": (d.get("profit") or {}).get("p50") if est else None,
                "days": _own(v).get("days") if est else None,
                "cost_total": r.get("cost_total"),
                "cost_text_vi": ((r.get("option") or {}).get("cost") or {}).get("text")
                if est
                else "Chưa đủ dữ liệu",
                "margin_before_pct": m.get("before_pct") if est else None,
                "margin_after_pct": m.get("after_pct") if est else None,
                "gmv_p50_vi": fmt.value("gmv", (d.get("gmv") or {}).get("p50"))
                if est
                else "Chưa đủ dữ liệu",
                "profit_p50_vi": fmt.value("profit", (d.get("profit") or {}).get("p50"))
                if est
                else "Chưa đủ dữ liệu",
                "gmv_dir": _dir((d.get("gmv") or {}).get("p50")) if est else "flat",
                "profit_dir": _dir((d.get("profit") or {}).get("p50")) if est else "flat",
            }
        )
    return out


def _dir(v: float | None) -> str:
    return "flat" if not v else ("up" if v > 0 else "down")


async def _version_pick(
    jev: JevPort, engine_card: dict[str, Any]
) -> tuple[str | None, dict[str, Any], Usage]:
    vers = engine_card.get("versions") or []
    est = [v for v in vers if (v.get("result") or {}).get("estimable")]
    if not est:
        return None, {"note": "no estimable version"}, Usage()
    state = {
        "versions": [
            {
                "label": v.get("label"),
                "gmv_p50": _own(v).get("delta", {}).get("gmv", {}).get("p50"),
                "profit_p50": _own(v).get("delta", {}).get("profit", {}).get("p50"),
                "cost": (v.get("result") or {}).get("cost_total"),
            }
            for v in est
        ]
    }
    ans, u = await jev.ask(
        state,
        {
            "version": {
                "type": "choice",
                "instructions": "Which version in `versions` should the seller try: the best "
                "profit for "
                "its cost?",
                "criteria": {v.get("label"): "" for v in est},
            }
        },
    )
    ok, info = choice_ok(ans["version"])
    labels = {v.get("label") for v in est}
    if info["pick"] in labels:  # an unestimable version is never preselected (U6d)
        return info["pick"], info, u
    best = max(est, key=lambda v: _own(v).get("delta", {}).get("profit", {}).get("p50") or 0)
    return best.get("label"), {**info, "fallback": "best estimable"}, u


async def _engine_and_overlap(
    out: CardOutcome,
    data: DataPort,
    engine: CardEnginePort,
    jev: JevPort,
    kind: str,
    item: str | None,
    as_of: date,
    prior_drafts: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any], tuple[str, str | None] | None]:
    """G3 (engine values), then G4 (exact overlap in code, then a Jev overlap Noul).
    Returns (engine card, None) when the kind passes, else ({}, (reason_vi, existing_card_code))."""
    eng = await engine.engine_card(kind, item, as_of)
    out.gates["G3"] = bool(eng.get("ok"))
    if not eng.get("ok"):
        reason = {
            "generator_returned_none": "Juli chưa tìm được mức phù hợp (giá sàn / dữ liệu không "
            "cho phép).",
            "kind_needs_a_product": "Loại thẻ này cần một sản phẩm cụ thể.",
        }.get(eng.get("reason", ""), "Juli chưa tạo được phương án cho đòn bẩy này.")
        return {}, (reason, None)
    card: dict[str, Any] = eng["card"]
    open_cards = await data.open_cards()
    exact = [
        c
        for c in open_cards
        if coarse(c["kind"]) == coarse(kind)
        and (c.get("item_id") or None) == (item or None)
        and c.get("code")  # never "Đã có thẻ" without the card to show
    ]
    if exact:
        out.gates["G4"] = False
        return {}, ("Đã có thẻ đang làm việc này.", exact[0].get("code"))
    others = [*open_cards, *(prior_drafts or [])]
    if others:
        nm = await data.item_names(
            [c["item_id"] for c in others if c.get("item_id")] + ([item] if item else [])
        )
        ov, u2 = await jev.ask(
            {
                "draft": {
                    "kind": kind,
                    "item_name": nm.get(item or "", item),
                    "change_after": card.get("title"),
                },
                "open_cards": [
                    {
                        "kind": c.get("kind"),
                        "item_name": nm.get(c.get("item_id") or "", c.get("item_id")),
                        "change_after": c.get("change_after"),
                        "status": c.get("status"),
                    }
                    for c in others
                ][:30],
            },
            {
                "overlap": {
                    "type": "noul",
                    "instructions": "Does `draft` make the same change as one of `open_cards`, "
                    "or change the same lever (price, voucher, stock, ads, listing...) on the "
                    "same product?",
                }
            },
        )
        out.cost_usd += u2.cost_usd
        n = ov["overlap"]["noul"]
        out.routing.append({"step": "overlap", "noul": round(n, 4), "rule": f">={FITS_GO} blocked"})
        out.gates["G4"] = n < FITS_GO
        if n >= FITS_GO:
            return {}, ("Đã có thẻ đang làm việc này.", None)
    out.gates["G4"] = True
    return card, None


async def card_stage(
    *,
    chains: list[ChainResult],
    data: DataPort,
    engine: CardEnginePort,
    jev: JevPort,
    labels: LabelTable,
    as_of: date,
    template: Template | None = None,
    prior_drafts: list[dict[str, Any]] | None = None,
) -> CardOutcome:
    out = CardOutcome()
    chain = chains[0]
    window = (chain.windows.cur[0], chain.windows.cur[1])
    critical_item: dict[str, Any] | None = None

    def none(reason: str, code: str | None = None) -> CardOutcome:
        ev: dict[str, Any] = {"type": "no_card", "reason_vi": reason}
        if code:
            ev["existing_card_code"] = code
        out.events.append(ev)
        return out

    out.gates["G1"] = g1(chain, template)
    if not out.gates["G1"]:
        return none(
            NO_CARD_VI.get(chain.stop_reason, "Không có đòn bẩy phù hợp với nguyên nhân này.")
        )
    kinds = candidate_kinds(chain, engine)
    items, metrics = evidence(chain)
    names = await data.item_names(sorted(items))
    state: dict[str, Any] = {"findings": _compact(chain)}
    if template and chain.stop_reason != "explained":
        # nothing changed much: target the biggest ₫-at-stake gap of Juli's own critical list (U2d)
        crit = await data.critical(*window)
        top = next(iter(crit.get("items") or []), None)
        if top:
            critical_item = top
            kinds = [k for k in (top.get("change_kinds") or []) if k in KIND_EN] or kinds
            if top.get("product_id"):
                items = {top["product_id"]}
                names = await data.item_names([top["product_id"]])
            metrics = metrics | {top.get("cause", {}).get("stage") or ""}
            state["findings"]["critical"] = {
                "stage": (top.get("cause") or {}).get("stage"),
                "rank": 1,
            }
    if not names:  # D: no product available -> only kinds whose generator needs no item
        kinds = [k for k in kinds if not engine.needs_item(k)]
    if not kinds:
        return none("Không có đòn bẩy phù hợp với nguyên nhân này.")
    state["findings"]["products"] = [{"item_id": k, "name": v[:80]} for k, v in names.items()]
    qs: dict[str, dict[str, Any]] = {
        "kind": {
            "type": "choice",
            "instructions": "Which change fits the main driver in `findings` best?",
            "criteria": {k: KIND_EN[k] for k in kinds},
        },
    }
    if len(names) > 1:
        qs["product"] = {
            "type": "choice",
            "instructions": "Which product should the change target, given `findings`?",
            "criteria": {k: v[:150] for k, v in names.items()},
        }
    ans, u = await jev.ask(state, qs)
    out.cost_usd += u.cost_usd
    kok, kinfo = choice_ok(ans["kind"])
    item: str | None = next(iter(names)) if len(names) == 1 else None
    if "product" in ans:
        pok, pinfo = choice_ok(ans["product"])
        out.routing.append({"step": "card_product", **pinfo})
        item = pinfo["pick"] if pok else None
    # A+C+D: G1 is the only eligibility gate; a clear kind is taken, an unsure one sends the top 2
    # (by probability) through the gates and the engine in order; the first that passes is drafted
    ranked = [
        k
        for k, _ in sorted((ans["kind"].get("probabilities") or {}).items(), key=lambda kv: -kv[1])
    ]
    ranked = ranked or [kinfo["pick"]]
    if item is None:
        ranked = [k for k in ranked if not engine.needs_item(k)]
    candidates = [kinfo["pick"]] if kok and kinfo["pick"] in ranked else ranked[:2]
    out.routing.append(
        {
            "step": "card_choice",
            "variant": "A+C+D",
            "kind": kinfo,
            "mode": "choice" if kok else "top2",
            "candidates": candidates,
            "item": item,
            "offered_kinds": kinds,
        }
    )
    if not candidates:
        return none("Juli không thấy đòn bẩy phù hợp với nguyên nhân này.")
    first_failure: tuple[str, str | None] | None = None
    card: dict[str, Any] = {}
    kind = ""
    fail: tuple[str, str | None] | None
    for kind in candidates:
        out.gates["G2"] = kind in kinds
        if not out.gates["G2"]:
            fail = ("Loại thẻ này không tác động tới chỉ số gây thay đổi.", None)
        else:
            out.gates["G5"] = (item is None or item in items) and chain.metric in metrics
            if not out.gates["G5"]:
                fail = ("Sản phẩm hoặc chỉ số của thẻ không nằm trong phần giải thích.", None)
            else:
                card, fail = await _engine_and_overlap(
                    out, data, engine, jev, kind, item, as_of, prior_drafts
                )
        out.routing.append({"step": "card_try", "kind": kind, "passed": fail is None})
        if fail is None:
            break
        first_failure = first_failure or fail
    else:
        reason, code = first_failure or ("Juli chưa tạo được phương án cho đòn bẩy này.", None)
        return none(reason, code)
    await draft_event(out, data, jev, labels, kind, item, card, critical_item)
    return out


async def draft_event(
    out: CardOutcome,
    data: DataPort,
    jev: JevPort,
    labels: LabelTable,
    kind: str,
    item: str | None,
    card: dict[str, Any],
    critical_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Accept one engine card as a Juli DRAFT (never sent, never executed): the recommended
    version, the `card` event and the accepted row, appended to `out`."""
    rec, vinfo, u3 = await _version_pick(jev, card)
    out.cost_usd += u3.cost_usd
    out.routing.append({"step": "version", **vinfo})
    ref = f"d_{uuid.uuid4().hex[:12]}"
    item_name = (await data.item_names([item])).get(item) if item else None
    acc = {
        "ref": ref,
        "kind": kind,
        "kind_vi": labels.kind(kind),
        "item_id": item,
        "item_name": item_name,
        "engine_card": card,
        "recommended": rec,
        "critical": critical_item,
    }
    out.accepted.append(acc)
    out.events.append(
        {
            "type": "card",
            "draft_ref": ref,
            "kind": kind,
            "kind_vi": labels.kind(kind),
            "item_id": item,
            "item_name": item_name,
            "title_vi": card.get("title") or labels.kind(kind),
            "versions": render_versions(card, rec),
            "recommendation_vi": f"Juli gợi ý: {rec}."
            if rec
            else "Chưa đủ dữ liệu để gợi ý một phương án.",
        }
    )
    return out.events[-1]
