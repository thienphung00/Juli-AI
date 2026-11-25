"""F11: the Shopee adapter of the shared trigger detector (``services/forecast/triggers.py``).

Generation goes through the detector in two places:

* :func:`augment_critical` adds a problem item for every product the detector finds a GMV drop on
  (beyond its F3 band, TikTok's method) that Phân tích has no item for, so the levers allowed for
  the target metric (``kinds.WIRING``) are generated for it.
* :func:`route_cards` types every built card (problem / opportunity / rule) and drops the
  opportunity cards whose forecast P50 does not clear the F3 band with a positive value.

Card kinds by type: a candidate that came from a critical item is a PROBLEM card; a kind in
:data:`RULE_KINDS` (stock_alert, listing_hide, ads_pause, voucher_cap: the F5 non-uplift kinds) is a
RULE card whatever its source; the rest of the opportunity pass (flash_sale, program_registration,
ads_add_product, affiliate_target_campaign, title / keyword listing audit, KOL cards) is an
OPPORTUNITY card. Combo and set price are builder-only kinds, not generated here.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from juli_backend.services.forecast import triggers as trg
from juli_backend.services.forecast.noise import NON_UPLIFT_KINDS
from juli_backend.services.shopee_analytics import funnel
from juli_backend.services.shopee_recommendations.kinds import allowed_for_metric
from juli_backend.services.shopee_recommendations.model import Candidate

RULE_KINDS = frozenset(NON_UPLIFT_KINDS)


def series_of(env: Any) -> list[trg.ProductSeries]:
    """The products' daily rows (views, clicks, orders, GMV) of the stored funnel history."""
    rows = env.funnel_history
    if not isinstance(rows, funnel.FunnelRows):
        rows = env.view.data.funnel
    if not isinstance(rows, funnel.FunnelRows):
        return []
    by_item: dict[str, list[trg.DayRow]] = {}
    for d in rows.product_days:
        if d.item_id is None:
            continue
        by_item.setdefault(str(d.item_id), []).append(
            trg.DayRow(
                d.day, float(d.views or 0), float(d.clicks or 0), float(d.orders), float(d.gmv)
            )
        )
    return [trg.ProductSeries(i, tuple(r)) for i, r in by_item.items()]


def _period_p50(card: dict[str, Any]) -> tuple[float | None, float | None, int]:
    money = (card.get("predicted") or {}).get("money_per_month") or {}
    period = money.get("period") or {}
    total = period.get("total") or money.get("total") or {}
    p50 = total.get("p50") or {}
    days = int(period.get("days") or money.get("days") or 0)
    return p50.get("dgmv"), p50.get("dprofit"), days


class ShopeeAdapter:
    def __init__(
        self,
        env: Any,
        series: Sequence[trg.ProductSeries] = (),
        built: Sequence[tuple[Candidate, dict[str, Any]]] = (),
    ) -> None:
        self.env = env
        per_day = {s.product_id: sum(r.gmv for r in s.days) / len(s.days) for s in series if s.days}
        self._median = trg.shop_median(list(per_day.values()))
        self._built = built

    def reference(self, product_id: str) -> trg.Reference:
        return trg.Reference(shop_median=self._median)

    def levers_for(self, metric: str) -> tuple[str, ...]:
        return allowed_for_metric(metric)

    def profit_per_gmv(self, product_id: str) -> float | None:
        margin = self.env.view.profit.margin_pct
        return None if margin is None else float(margin) / 100.0

    def forecasts(self, product_id: str) -> list[trg.LeverForecast]:
        from juli_backend.services.shopee_recommendations.cards import _history

        out: list[trg.LeverForecast] = []
        for cand, card in self._built:
            if _key(cand) != product_id or card["trigger_type"] != trg.OPPORTUNITY:
                continue
            dgmv, dprofit, days = _period_p50(card)
            if dgmv is None or days <= 0:
                continue  # no forecast to judge: the card is kept as it is
            hist = (_history(self.env, cand) or {}).get("gmv") or ()
            out.append(
                trg.LeverForecast(
                    product_id, cand.kind, card["metric"]["key"], dgmv, dprofit, days, hist
                )
            )
        return out

    def rule_triggers(self) -> list[trg.RuleTrigger]:
        return [
            trg.RuleTrigger(c.kind, c.item, value=float(card["rank_inputs"]["dprofit_p50"] or 0))
            for c, card in self._built
            if card["trigger_type"] == trg.RULE
        ]


def _key(cand: Candidate) -> str:
    return cand.item or ""


def augment_critical(env: Any, critical: dict[str, Any]) -> dict[str, Any]:
    """Add a problem item per detector problem with no Phân tích item on the same product."""
    series = series_of(env)
    if not series:
        return critical
    adapter = ShopeeAdapter(env, series)
    have = {it.get("product_id") for it in critical.get("items", []) if it.get("product_id")}
    added: list[dict[str, Any]] = []
    for t in trg.detect(series, adapter, as_of=env.as_of):
        if t.trigger_type != trg.PROBLEM or t.product_id in have or t.target_metric is None:
            continue
        ref = float(t.detail["reference_per_day"])
        now = float(t.detail["gmv_per_day"])
        added.append(
            {
                "id": f"trigger:{t.product_id}:{t.target_metric}",
                "kind": "below_reference",
                "kpi": t.target_metric,
                "level": "product",
                "flow": None,
                "product_id": t.product_id,
                "deviation_pct": round((now - ref) / ref * 100, 1),
                "at_stake_per_day": ref - now,
                "at_stake_per_month": (ref - now) * trg.VALUE_DAYS,
                "money_basis": "confirmed",
                "cause": {"stage": t.target_metric, "text": ""},
                "trigger_type": trg.PROBLEM,
            }
        )
    if not added:
        return critical
    return {**critical, "items": [*critical.get("items", []), *added]}


def type_of(cand: Candidate) -> str:
    if cand.kind in RULE_KINDS:
        return trg.RULE
    return trg.PROBLEM if cand.critical is not None else trg.OPPORTUNITY


def route_cards(
    env: Any, built: list[tuple[Candidate, dict[str, Any]]]
) -> tuple[list[tuple[Candidate, dict[str, Any]]], Counter[str]]:
    kept, dropped, _cands = route_cards_detailed(env, built)
    return kept, dropped


def route_cards_detailed(
    env: Any, built: list[tuple[Candidate, dict[str, Any]]]
) -> tuple[
    list[tuple[Candidate, dict[str, Any]]], Counter[str], list[tuple[Candidate, dict[str, Any]]]
]:
    """Tag each card with ``trigger_type`` / ``trigger_metric`` and drop the opportunity cards
    that do not clear the F3 band. Cards with no forecast to judge are kept."""
    for cand, card in built:
        card["trigger_type"] = type_of(cand)
    adapter = ShopeeAdapter(env, series_of(env), built)
    passed: set[tuple[str, str]] = set()
    judged: set[tuple[str, str]] = set()
    for pid in {_key(c) for c, k in built if k["trigger_type"] == trg.OPPORTUNITY}:
        fs = adapter.forecasts(pid)
        judged.update((pid, f.lever) for f in fs)
        known = adapter.profit_per_gmv(pid) is not None
        passed.update(
            (pid, lv) for t in trg.detect_opportunities(pid, adapter, known) for lv in t.levers
        )
    kept: list[tuple[Candidate, dict[str, Any]]] = []
    dropped: Counter[str] = Counter()
    below: list[tuple[Candidate, dict[str, Any]]] = []
    for cand, card in built:
        if card["trigger_type"] == trg.OPPORTUNITY and (_key(cand), cand.kind) in judged:
            if (_key(cand), cand.kind) not in passed:
                dropped[cand.kind] += 1
                below.append((cand, card))
                continue
        card["trigger_metric"] = (
            (cand.critical or {}).get("kpi") if card["trigger_type"] == trg.PROBLEM else None
        ) or card["metric"]["key"]
        kept.append((cand, card))
    return kept, dropped, below
