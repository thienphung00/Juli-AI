"""Does the question's pairing apply? (owner #115) Chat reads the capability table
(`metrics.capabilities`) before it answers: a metric that cannot be measured on the named scope,
or a card kind asked to move a metric it does not move, gets ONE line naming what applies and the
buttons for it, never a figure of another scope or metric under the asked label and never "Juli
chưa có số liệu này" (that stays for pairings that apply but have no data).

The scope is read from the parser's typed slots only (`entity_phrase`, `source_phrase`,
`product_phrase`): the seller's own words also carry the metric's name ("chi phí voucher").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from juli_backend.services.analytics_agent import routing, windows
from juli_backend.services.analytics_agent.types import LabelTable
from juli_backend.services.metrics import capabilities as cap
from juli_backend.services.metrics.registry import METRICS

#: the stop reason (and label kind) of a pairing that does not apply
STOP = "not_applicable"
MAX_BUTTONS = 4

_PROGRAMME = tuple(
    (routing.folded(rx), sid)
    for rx, sid in (
        (r"combo khuyến mãi", "combo"),
        (r"mua kèm deal sốc", "add_on"),
        (r"flash sale của shop", "flash_sale"),
        (r"chương trình của shop", "programme"),
        (r"mua để nhận quà", "gift"),
    )
)
_AD_LINE_SCOPE = {
    "ads_product": "dvht_product",
    "ads_shop": "dvht_shop",
    "ads_livestream": "ads_live",
    "ads_other": "ads_other",
}
_ORGANIC = routing.folded(r"organic|tự nhiên")
_KOL = routing.folded(r"\bkol\b|\bkoc\b")


@dataclass(frozen=True)
class Refusal:
    line: str
    buttons: list[dict[str, str]] = field(default_factory=list)


def scope_of(intent: dict[str, Any]) -> str:
    """The capability scope the intent names (its typed slots), else the shop or the product."""
    entity = routing.fold(str(intent.get("entity_phrase") or ""))
    source = routing.fold(str(intent.get("source_phrase") or ""))
    for text in (entity, source):
        if not text:
            continue
        for rx, sid in _PROGRAMME:
            if rx.search(text):
                return sid
        line = next((k for rx, k in routing.AD_LINE_WORDS if rx.search(text)), None)
        if line and routing._AD_WORDS.search(text):
            return _AD_LINE_SCOPE[line]
        for rx, kind in routing.ENTITY_WORDS:
            if rx.search(text) and kind == "voucher":
                return "voucher"
            if rx.search(text) and kind == "affiliate":
                return "kol" if _KOL.search(text) else "affiliate"
        if routing._CAMPAIGN.search(text):
            return "campaign"
        if _ORGANIC.search(text):
            return "organic"
        if routing._AD_WORDS.search(text):
            return "ads"
    return "product" if _product_named(intent) else "shop"


def _product_named(intent: dict[str, Any]) -> bool:
    return bool(intent.get("product_phrase") or intent.get("item_id"))


def kind_of(intent: dict[str, Any]) -> str | None:
    """The card kind the seller asks about: the parser's `card_kind`, else the kind a create
    request builds."""
    k = intent.get("card_kind")
    if k and k != "none" and k in cap.MOVES:
        return str(k)
    if intent.get("question_type") == "create_card":
        from juli_backend.services.analytics_agent.create_card import ENGINE_KIND

        # the parse flattens the schema's `card` object (routing.flatten_card)
        ct = str(intent.get("card_type") or (intent.get("card") or {}).get("card_type") or "none")
        if ct != "none":
            k = ENGINE_KIND.get(ct, "min_spend_voucher" if ct == "voucher" else ct)
            return k if k in cap.MOVES else None
    return None


def _metric(intent: dict[str, Any]) -> str | None:
    mk = intent.get("metric_key")
    return str(mk) if mk and mk != "none" and mk in METRICS else None


def _period_vi(intent: dict[str, Any]) -> str:
    p = windows.PERIOD_VI.get(windows.window_from_phrase(intent.get("time_phrase")) or "")
    return f" {p.lower()}" if p else ""


def _kind_label(labels: LabelTable, kind: str) -> str:
    got = labels.kind(kind)
    if got != kind:
        return got
    from juli_backend.services.shopee_recommendations.kinds import KINDS

    return KINDS[kind].label if kind in KINDS else kind


def _scope_button(metric: str, scope: str, when: str) -> dict[str, str]:
    m, s = cap.metric_label(metric), cap.SCOPES[scope].label_vi
    text = m if scope == "shop" else f"{m} {s}"
    return {"label_vi": s, "text": f"{text}{when}"}


def refusal(intent: dict[str, Any], labels: LabelTable) -> Refusal | None:
    """The one line + buttons when the intent's pairing does not apply, else None."""
    metric = _metric(intent)
    if metric is None or intent.get("question_type") == "other":
        return None  # nothing named, or not about the shop's data (J11 offers instead)
    when = _period_vi(intent)
    kind = kind_of(intent)
    if kind is not None:
        if cap.moves(kind, metric):
            return None
        from juli_backend.services.analytics_agent import levers

        m = cap.metric_label(metric)
        names = [
            _kind_label(labels, k)
            for k in cap.kinds_moving(metric, levers.card_kinds(None))[:MAX_BUTTONS]
        ]
        return Refusal(
            cap.kind_line(kind, _kind_label(labels, kind), metric),
            [{"label_vi": n, "text": f"{n} để tăng {m}"} for n in names],
        )
    scope = scope_of(intent)
    if scope not in ("shop", "product") and _product_named(intent):
        if not cap.SCOPES[scope].per_product:
            alt = [s for s in (scope, "product") if cap.measurable(s, metric)]
            return Refusal(
                cap.scope_line(scope, metric, per_product=True),
                [_scope_button(metric, s, when) for s in alt],
            )
    checked = scope
    if scope == "shop" and routing.ranking_of(intent) in ("top", "decline"):
        checked = "product"  # a ranking lists products: the metric is read per product
    if cap.measurable(checked, metric):
        return None
    return Refusal(
        cap.scope_line(checked, metric),
        [_scope_button(metric, s, when) for s in cap.short_scopes(metric)[:MAX_BUTTONS]],
    )


def events(r: Refusal) -> list[dict[str, Any]]:
    """The seller's events: the one line, then the buttons (asked as a new question)."""
    out: list[dict[str, Any]] = [
        {"type": "label", "stop_reason": STOP, "text_vi": r.line, "detail_vi": None}
    ]
    if r.buttons:
        out.append({"type": "more", "items": r.buttons})
    return out


__all__ = ["STOP", "Refusal", "events", "kind_of", "refusal", "scope_of"]
