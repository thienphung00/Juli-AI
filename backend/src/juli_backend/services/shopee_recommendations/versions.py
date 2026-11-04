"""Versions inside a card (P91 D-2): the same change tried with other inputs, side by side.

A card carries 2-4 ``versions``. Version 1 is the engine's default (the inputs the generator
chose, after the acceptance defaults) and is the only one that is ranked. The others are the
SAME change at other points of the kind's own sliders -- ``ALTERNATIVES`` below is the one place
that says which points, per ``change_kind`` -- or, for a title / keyword card, another proposal
from the same listing core. Each version is a full ``build_card`` evaluation (the same payload
fields: five numbers before -> after, certain and predicted layers, floor, spend check, plan,
execution sheet). A version that cannot be evaluated is kept as ``refused`` with its inputs, one
that breaks a floor is kept as ``floor_breach`` with its numbers: both are shown, marked, and
never ranked, never approvable.

Kinds with no slider (cover_image, price_display, ads_pause, ...) and mega_sale keep one version.
``versions[n].code`` (``<card code>-V<n>``) is filled when the card is persisted.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from juli_backend.services.shopee_recommendations import config
from juli_backend.services.shopee_recommendations import listing as lst
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.evaluate import evaluate
from juli_backend.services.shopee_recommendations.kinds import KINDS, Slider, spec
from juli_backend.services.shopee_recommendations.model import Candidate

#: The fields of a card that belong to ONE evaluation of the change; a version carries these.
EVAL_FIELDS: tuple[str, ...] = (
    "reason",
    "change",
    "inputs",
    "whatif",
    "certain",
    "five_numbers",
    "floor",
    "spend",
    "predicted",
    "measurement_plan",
    "execution_sheet",
    "notes",
    "rank_inputs",
)
#: Evaluation fields only some kinds have (P91 D-9: the KOL block of a "Gửi mẫu" / "Mời KOL" card,
#: its product, samples and expected orders per version); copied when the card has them.
OPTIONAL_EVAL_FIELDS: tuple[str, ...] = ("kol",)
STATUS_OK = "ok"
STATUS_FLOOR = "floor_breach"
STATUS_SPEND = "spend_breach"
STATUS_REFUSED = "refused"
DEFAULT_LABEL = "Mặc định của Juli"

Inputs = Mapping[str, Any]
Rule = Callable[[Inputs, Inputs], list[dict[str, Any]]]


# ------------------------------------------------------------------ alternative inputs (pure)


def _scale(keys: tuple[str, ...], *factors: float) -> Rule:
    """Alternatives that multiply these inputs together by each factor."""

    def rule(inputs: Inputs, before: Inputs) -> list[dict[str, Any]]:
        del before
        out = []
        for f in factors:
            alt = {k: inputs[k] * f for k in keys if isinstance(inputs.get(k), int | float)}
            if alt:
                out.append(alt)
        return out

    return rule


def _shift(key: str, *deltas: float) -> Rule:
    """Alternatives that move one input by each delta (in the slider's unit)."""

    def rule(inputs: Inputs, before: Inputs) -> list[dict[str, Any]]:
        del before
        value = inputs.get(key)
        if not isinstance(value, int | float) or isinstance(value, bool):
            return []
        return [{key: value + d} for d in deltas]

    return rule


def _from_current(key: str, *factors: float) -> Rule:
    """Alternatives relative to what the shop has today (the card's ``before``), falling back to
    the default input: ads budget -20 % / +20 % / +50 %."""

    def rule(inputs: Inputs, before: Inputs) -> list[dict[str, Any]]:
        base = before.get(key)
        if not isinstance(base, int | float) or isinstance(base, bool) or base <= 0:
            base = inputs.get(key)
        if not isinstance(base, int | float) or isinstance(base, bool):
            return []
        return [{key: base * f} for f in factors]

    return rule


def _tiers(inputs: Inputs, before: Inputs) -> list[dict[str, Any]]:
    del before
    t2, t3 = inputs.get("tier2_pct"), inputs.get("tier3_pct")
    if not isinstance(t2, int | float) or not isinstance(t3, int | float):
        return []
    return [{"tier2_pct": t2 + a, "tier3_pct": t3 + b} for a, b in ((-2, -3), (2, 3), (4, 6))]


def _flash(inputs: Inputs, before: Inputs) -> list[dict[str, Any]]:
    out = _shift("discount_pct", -5, 5)(inputs, before)
    units = inputs.get("units")
    if isinstance(units, int | float) and units > 1:
        out.append({"units": units * 0.5})
    return out


#: change_kind -> where else on its sliders to try it. At most three are kept (four versions).
ALTERNATIVES: dict[str, Rule] = {
    "ads_budget": _from_current("daily_budget", 0.8, 1.2, 1.5),
    "ads_roas_target": _scale(("roas_target",), 0.85, 1.15, 1.3),
    "product_discount": _shift("discount_pct", -3, 3, 5),
    "price": _shift("new_price_pct", 2, 4, -2),
    "min_spend_voucher": _scale(("value", "max_value", "min_spend"), 0.7, 1.3, 1.6),
    "review_voucher": _scale(("value", "min_spend"), 0.7, 1.4),
    "voucher_cap": _scale(("value",), 0.8, 0.6, 1.2),
    "flash_sale": _flash,
    "program_registration": _flash,
    "bundle_deal": _tiers,
    "add_on": _shift("addon_discount_pct", -5, 5, 10),
    "gift": _scale(("min_spend",), 0.7, 1.3, 1.6),
    "variation_set": _shift("set_size", -1, 1, 2),
    "affiliate_commission": _shift("commission_pct", -2, 2, 5),
    "affiliate_target_campaign": _shift("commission_pct", -2, 2, 5),
    # P91 D-9: other products are added by ``kol_cards.product_alternatives``; these move the rest
    "affiliate_sample": _shift("qty", 2, -1),
    "affiliate_invite": _shift("commission_pct", 2, -2),
}


def fit_inputs(kind: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """The inputs inside the kind's slider ranges, snapped to the step (integers stay integers)."""
    sliders: dict[str, Slider] = {s.key: s for s in spec(kind).sliders}
    out: dict[str, Any] = {}
    for k, v in inputs.items():
        sl = sliders.get(k)
        if sl is None or not isinstance(v, int | float) or isinstance(v, bool):
            out[k] = v
            continue
        v = min(max(float(v), sl.minimum), sl.maximum)
        if sl.step:
            v = math.floor(v / sl.step + 0.5) * sl.step  # half up, not banker's
            v = min(max(v, sl.minimum), sl.maximum)
        out[k] = int(v) if float(v).is_integer() else round(v, 6)
    return out


def alternative_inputs(
    kind: str, inputs: Mapping[str, Any], before: Mapping[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Up to ``MAX_VERSIONS - 1`` alternative input sets for a kind: inside the slider ranges,
    different from the default and from each other. Pure; kinds with no rule give ``[]``."""
    rule = ALTERNATIVES.get(kind)
    if rule is None or kind not in KINDS:
        return []
    seen = [dict(inputs)]  # an alternative equal to the default as written is no alternative
    out: list[dict[str, Any]] = []
    for delta in rule(inputs, before or {}):
        alt = fit_inputs(kind, {**inputs, **delta})
        if alt in seen:
            continue
        seen.append(alt)
        out.append(alt)
        if len(out) == config.MAX_VERSIONS - 1:
            break
    return out


# ----------------------------------------------------------------------------- labels


def _fmt(value: Any, unit: str) -> str:
    if isinstance(value, float) and not value.is_integer():
        text = f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    else:
        text = f"{int(value):,}".replace(",", ".")
    return {"vnd": f"{text} ₫", "pct": f"{text}%", "days": f"{text} ngày"}.get(unit, text)


def input_label(kind: str, default: Mapping[str, Any], alt: Mapping[str, Any]) -> str:
    """What differs from the default, in the seller's words: ``Mức giảm 8%``."""
    sliders = {s.key: s for s in spec(kind).sliders}
    bits = [
        f"{sliders[k].label} {_fmt(v, sliders[k].unit)}"
        for k, v in alt.items()
        if k in sliders and v != default.get(k) and isinstance(v, int | float)
    ]
    return ", ".join(bits) or "Phương án khác"


# --------------------------------------------------------------------------- the payload


def breaches_of(card: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Floor and spend-cap breaches of one evaluation (they never block, they must be
    acknowledged to approve; a breaching version is never ranked)."""
    out = [{"type": "floor", **b} for b in (card.get("floor") or {}).get("breaches") or []]
    ri = card.get("rank_inputs") or {}
    after, cap = ri.get("spend_after"), ri.get("spend_cap")
    if after is not None and cap is not None and after > cap:
        out.append({"type": "spend_cap", "spend_after": after, "cap": cap})
    return out


def version_of(
    card: Mapping[str, Any],
    number: int,
    label: str,
    *,
    status: str | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    """One version from a full card payload: its evaluation fields plus the version header."""
    floor_ok = bool((card.get("floor") or {}).get("ok", True))
    spend_ok = not any(b["type"] == "spend_cap" for b in breaches_of(card))
    st = status or (
        STATUS_OK if floor_ok and spend_ok else STATUS_FLOOR if not floor_ok else STATUS_SPEND
    )
    out: dict[str, Any] = {
        "version": number,
        "code": code,
        "label": label,
        "status": st,
        "default": number == 1,
        "ranked": number == 1 and st == STATUS_OK,
        "refusal": None,
    }
    out.update(
        {k: copy.deepcopy(card[k]) for k in (*EVAL_FIELDS, *OPTIONAL_EVAL_FIELDS) if k in card}
    )
    return out


def refused_version(
    number: int, label: str, inputs: Mapping[str, Any], reason: str | None
) -> dict[str, Any]:
    return {
        "version": number,
        "code": None,
        "label": label,
        "status": STATUS_REFUSED,
        "default": False,
        "ranked": False,
        "refusal": reason or "refused",
        "inputs": dict(inputs),
    }


def versions_of(card: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The card's versions; a card made before P91 has just its own evaluation as version 1."""
    found = card.get("versions")
    if found:
        return [dict(v) for v in found]
    return [version_of(card, 1, DEFAULT_LABEL, code=card.get("code") and f"{card['code']}-V1")]


def overlay(card: Mapping[str, Any], version: Mapping[str, Any]) -> dict[str, Any]:
    """The card as it reads when ``version`` is the one chosen (its evaluation over the card)."""
    out = dict(card)
    out.update(
        {
            k: copy.deepcopy(version[k])
            for k in (*EVAL_FIELDS, *OPTIONAL_EVAL_FIELDS)
            if k in version
        }
    )
    out["version"] = version["version"]
    return out


# ------------------------------------------------------------------------ the alternatives


def _title_alternatives(env: RecoEnv, cand: Candidate) -> list[tuple[str, Candidate]]:
    """Title B / C: the same listing, rewritten for fewer core keywords (the weakest go first)."""
    current = cand.extra.get("current_title")
    core = list(cand.extra.get("core") or [])
    if not current or len(core) < 2:
        return []
    seen = {cand.inputs.get("title")}
    out: list[tuple[str, Candidate]] = []
    for keep in (len(core) - 1, 1):
        if keep < 1 or keep >= len(core):
            continue
        prop = lst.propose_title(current, core[:keep], env.banned_terms)
        if prop is None or prop.title in seen or len(prop.title) > config.MAX_TITLE_CHARS:
            continue
        seen.add(prop.title)
        extra = {**cand.extra, "proposal": prop.json()}
        out.append(
            (
                f"Tên chứa {keep} từ khoá Chính đầu tiên",
                replace(cand, inputs={**cand.inputs, "title": prop.title}, extra=extra),
            )
        )
    return out


def _keyword_alternatives(env: RecoEnv, cand: Candidate) -> list[tuple[str, Candidate]]:
    """Other 'Phụ' keywords to promote instead of the best one (next in priority order)."""
    item = cand.item
    li = env.listings.get(item) if item else None
    if li is None:
        return []
    out: list[tuple[str, Candidate]] = []
    for nth in (1, 2):
        prop = lst.propose_keywords(li, env.banned_terms, nth=nth)
        if prop is None or prop.promote.keyword == cand.inputs.get("promote"):
            continue
        inputs = {
            **cand.inputs,
            "promote": prop.promote.keyword,
            "demote": None if prop.demote is None else prop.demote.keyword,
        }
        extra = {**cand.extra, "core_before": list(prop.core_before), "proposal": prop.json()}
        out.append(
            (f"Đưa “{prop.promote.keyword}” lên Chính", replace(cand, inputs=inputs, extra=extra))
        )
    return out


def _alternative_candidates(
    env: RecoEnv, cand: Candidate, card: Mapping[str, Any]
) -> list[tuple[str, Candidate]]:
    if cand.kind == "title":
        return _title_alternatives(env, cand)
    if cand.kind == "keyword":
        return _keyword_alternatives(env, cand)
    before = (card.get("change") or {}).get("before") or {}
    out = []
    if cand.kind in ("affiliate_sample", "affiliate_invite"):
        from juli_backend.services.shopee_recommendations.kol_cards import product_alternatives

        out = product_alternatives(env, cand)  # P91 D-9: the product pitched is a version axis
    for alt in alternative_inputs(cand.kind, cand.inputs, before):
        out.append((input_label(cand.kind, cand.inputs, alt), replace(cand, inputs=alt)))
    return out


def build_versions(
    env: RecoEnv, cand: Candidate, card: Mapping[str, Any], *, now: datetime
) -> list[dict[str, Any]]:
    """Version 1 (the card itself) and its alternatives, each a full evaluation."""
    versions = [version_of(card, 1, DEFAULT_LABEL)]
    for label, alt in _alternative_candidates(env, cand, card)[: config.MAX_VERSIONS - 1]:
        n = len(versions) + 1
        built = build_card(env, alt, now=now)
        if built is None:
            versions.append(refused_version(n, label, alt.inputs, evaluate(env, alt).refusal))
        else:
            versions.append(version_of(built, n, label))
    return versions
