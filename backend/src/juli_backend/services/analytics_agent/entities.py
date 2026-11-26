"""Entity answers (Q17, Q22, Q23): a question that names a voucher, an affiliate (TTLK) channel,
an ad campaign or one product is answered from that entity's own rows, or not at all.

The rule: never a shop number under an entity's label. When a reader returns nothing, the answer
is `NO_DATA_VI` ("Juli chưa có số liệu này"), decided by code.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any

from juli_backend.services.analytics_agent import fmt
from juli_backend.services.analytics_agent.types import DataPort
from juli_backend.services.analytics_agent.windows import (
    anchor_for,
    build_windows,
    campaign_days,
    clip_to_freshness,
    sale_days_vi,
)
from juli_backend.services.metrics.compute import raw_value
from juli_backend.services.shop_diagnosis.confidence import Confidence
from juli_backend.services.shop_diagnosis.config import ShopDiagnosisConfig

NO_DATA_VI = "Juli chưa có số liệu này"
_COST = re.compile(r"cost|spend|chi phí|commission|hoa hồng|discount|ưu đãi", re.I)
_LOSS = re.compile(r"los(e|es|ing|s|t)\b|lỗ|unprofitable|below|thua|not worth|negative", re.I)
TOP_ROWS = 8
#: an analysis request: every voucher figure together, not one metric
_ANALYSE = re.compile(r"phân tích|analy[sz]|đánh giá|tổng hợp|hiệu quả|review", re.I)
#: the rankings' order floor (`shopee_analytics.rankings.CONFIG`): under it on a side, a change
#: is "Chưa đủ dữ liệu"
RANKING_FLOOR = ShopDiagnosisConfig()


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _intent_blob(intent: dict[str, Any]) -> str:
    return " ".join(
        str(intent.get(k) or "") for k in ("metric_phrase", "entity_phrase", "question_type")
    )


def _answer(kind: str, title: str, w: Any, latest: date, **extra: Any) -> dict[str, Any]:
    return {
        "type": "data_answer",
        "kind": kind,
        "title_vi": title,
        "window_vi": w.label(),
        "fresh_vi": f"Số liệu đến hết {latest:%d/%m}",
        **({"sale_vi": sv} if (sv := sale_days_vi(w)) else {}),
        **extra,
    }


def _sale_note(w: Any) -> str:
    days = campaign_days(*w.cur)
    return f" (có ngày sale {', '.join(f'{d:%d/%m}' for d in days)})" if days else ""


def campaign_verdict(c: dict[str, Any]) -> str:
    """ "Lỗ" / "Lãi" / "Chưa rõ": ROAS against the registry's ROAS hoà vốn; the profit after ads
    when the break-even is not defined (no giá vốn). Never a guess."""
    if c.get("roas") is not None and c.get("break_even") is not None:
        return "Lỗ" if c["roas"] < c["break_even"] else "Lãi"
    p = c.get("profit_after_ads")
    return "Chưa rõ" if p is None else ("Lỗ" if float(p) < 0 else "Lãi")


def campaign_row(c: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """One campaign: name, spend, GMV, ROAS, ROAS hoà vốn (registry) and lỗ / lãi."""
    be = fmt.value("roas", _f(c["break_even"])) if c.get("break_even") is not None else "chưa có"
    if c.get("break_even") is not None and c.get("break_even_scope"):
        be += f" ({c['break_even_scope']})"
    # unknown money is left out, never 0 and never a figure that is not there
    money = [
        f"{label} {fmt.value(metric, _f(c.get(key)))}"
        for label, metric, key in (("chi", "ads_spend", "spend"), ("GMV", "gmv", "gmv"))
        if c.get(key) is not None
    ]
    roas = fmt.value("roas", _f(c["roas"])) if c.get("roas") is not None else "chưa tính"
    return {
        "label_vi": str(c["name"]),
        "value_vi": f"{campaign_verdict(c)} · ROAS {roas} · hoà vốn {be}",
        "detail_vi": prefix + " · ".join(money),
    }


def product_loss_row(r: dict[str, Any]) -> dict[str, Any]:
    """One product losing after ads: profit after ads, contribution before ads, ads spend and
    ROAS hoà vốn (the shared `ProductProfit` figures)."""
    be = r.get("break_even_roas")
    contrib = r.get("contribution_before_ads")
    ads = r.get("ad_spend")
    profit = r.get("profit")
    return {
        "label_vi": str(r.get("name") or r["item_id"]),
        "value_vi": "Lỗ " + fmt.value("profit", abs(float(profit)))
        if profit is not None
        else "Chưa tính",
        "detail_vi": "đóng góp trước quảng cáo "
        + (fmt.value("profit", _f(contrib)) if contrib is not None else "chưa tính")
        + (f" · chi quảng cáo {fmt.value('ads_spend', _f(ads))}" if ads is not None else "")
        + f" · hoà vốn {fmt.value('roas', _f(be)) if be is not None else 'chưa tính'}",
        "link": {"kind": "product", "item_id": r["item_id"]},
    }


def campaign_order(c: dict[str, Any]) -> float:
    """Worst profit after ads first; unknown last."""
    p = c.get("profit_after_ads")
    return float("inf") if p is None else float(p)


def _value_of(want: str, t: dict[str, Any] | None) -> float | None:
    if t is None:
        return None
    if want == "aov":
        raw = raw_value("aov", {"gmv": Decimal(str(t["gmv"])), "orders": Decimal(str(t["orders"]))})
        return float(raw) if isinstance(raw, Decimal) else None
    return _f(t[want])


def _total_answer(
    want: str,
    title: str,
    w: Any,
    latest: date,
    now: dict[str, Any],
    before: dict[str, Any] | None,
    *,
    thin: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    """One entity total against the window before. `thin` = a side has too few orders for a
    change to mean anything (the rankings' order floor): the change reads "Chưa đủ dữ liệu",
    never a % of a near-empty base."""
    mkey = {"orders": "orders", "gmv": "gmv", "aov": "aov", "cost": "gmv"}[want]
    n, b0 = _value_of(want, now), _value_of(want, before)
    delta = None
    if before is not None:
        delta = (
            {"dir": "flat", "text_vi": Confidence.INSUFFICIENT.value}
            if thin
            else fmt.delta(mkey, n, b0)
        )
    return _answer(
        "metric_total",
        title + _sale_note(w),
        w,
        latest,
        value=fmt.value(mkey, n),
        value_raw=n,
        before=b0,
        before_vi=fmt.value(mkey, b0) if before else None,
        delta=delta,
        stop="data_answer",
        **extra,
    )


def _pct_vi(v: float) -> str:
    return fmt.decimal(v, 1)


def coverage_vi(t: dict[str, Any]) -> str:
    """The cost's coverage in Tổng quan's words (`KnownCostProfit.label`): the voucher orders
    with every cost known and their share of the voucher GMV."""
    if t.get("known_gmv_share_pct") is None:
        return f"trên {int(t['known_orders'])} đơn có chi phí"
    share = _pct_vi(t["known_gmv_share_pct"])
    return f"trên {int(t['known_orders'])} đơn có chi phí, {share} % GMV"


def _span_vi(a: date, b: date | None) -> str:
    if b is None:
        return f"từ {a:%d/%m}"
    return f"{a:%d/%m}–{b:%d/%m}" if a != b else f"{a:%d/%m}"


def setting_row(v: dict[str, Any]) -> dict[str, Any]:
    """One voucher that ran in the window, from its settings (no result columns: the settings
    carry none). Only the fields Shopee stated; the live usage only with the day it was read."""
    span = _span_vi(v["starts"], v["ends"])
    parts = [span]
    if v.get("discount_amount") is not None:
        off = "Giảm " + fmt.value("gmv", _f(v["discount_amount"]))
    elif v.get("discount_percent") is not None:
        off = f"Giảm {fmt.decimal(float(v['discount_percent']), 0)}%"
        if v.get("max_value") is not None:
            off += f" (tối đa {fmt.value('gmv', _f(v['max_value']))})"
    else:  # no discount stated: the run dates are the value
        off, parts = span, []
    if v.get("min_spend") is not None:
        parts.append("đơn tối thiểu " + fmt.value("gmv", _f(v["min_spend"])))
    if v.get("usage") is not None and v.get("usage_on") is not None:
        # Shopee's running count at the read, never the window's uses (it may hold earlier ones)
        parts.append(f"Lượt dùng {fmt.value('orders', _f(v['usage']))} (đọc {v['usage_on']:%d/%m})")
    return {"label_vi": str(v["name"]), "value_vi": off, "detail_vi": " · ".join(parts)}


def _names_a_metric(intent: dict[str, Any]) -> bool:
    from juli_backend.services.analytics_agent.routing import metric_from_phrase

    said = f"{intent.get('metric_phrase') or ''} {intent.get('raw_text') or ''}"
    return bool(_COST.search(said)) or metric_from_phrase(said) is not None


async def _voucher_answers(
    data: DataPort,
    intent: dict[str, Any],
    metric: str | None,
    w: Any,
    latest: date,
    item_id: str | None,
) -> list[dict[str, Any]]:
    """Voucher answers from the tabs' own view (`voucher_figures`): đơn and GMV of the orders
    that used a shop voucher, the voucher part of Ưu đãi (a COST, owner 2026-11-20) with its
    coverage, and the per-voucher card. A question naming one figure gets that figure; an
    analysis ("phân tích các voucher") or no named figure gets all three together. No source
    splits vouchers by product."""
    if item_id:
        return []
    now = await data.voucher_figures(*w.cur)
    if not now or not now.get("lines"):
        return []  # no order line in the window: nothing to say, never 0
    before = await data.voucher_figures(*w.prev) if w.prev else None
    if before is not None and not before.get("lines"):
        before = None
    said = f"{intent.get('metric_phrase') or ''} {intent.get('raw_text') or ''}"
    if _ANALYSE.search(said) or not _names_a_metric(intent):
        wants = ["orders", "gmv", "cost"]
    else:
        one = "cost" if _COST.search(_intent_blob(intent) + " " + said) else (metric or "orders")
        if one not in ("orders", "gmv", "aov", "cost"):
            return []  # this entity has no such metric: never another metric under its label
        wants = [one]
    floor = RANKING_FLOOR.reference_min_orders
    thin = before is not None and min(float(now["orders"]), float(before["orders"])) < floor
    titles = {
        "orders": "Đơn dùng voucher",
        "gmv": "GMV đơn dùng voucher",
        "aov": "AOV đơn dùng voucher",
        "cost": "Chi phí voucher (Ưu đãi)",
    }
    out = []
    for want in wants:
        if want == "cost":
            if now["cost"] is None:
                continue  # voucher orders without one known cost: missing, never 0
            cov = coverage_vi(now)
            b = before if before is not None and before.get("cost") is not None else None
            out.append(
                _total_answer(
                    "cost", f"{titles['cost']} · {cov}", w, latest, now, b,
                    thin=thin, coverage_vi=cov,
                )
            )  # fmt: skip
        else:
            out.append(_total_answer(want, titles[want], w, latest, now, before, thin=thin))
    if not out:
        return []
    settings = now.get("settings") or []
    if settings:  # owner #107: the Connector's voucher list only, no result per voucher
        out.append(
            _answer(
                "top_products",
                "Voucher của shop trong kỳ",
                w,
                latest,
                rows=[setting_row(v) for v in settings[:TOP_ROWS]],
                stop="data_answer",
            )
        )
    return out


async def _window(
    data: DataPort,
    preset: str,
    as_of: date,
    explicit: tuple[date, date] | None,
    named_month: str | None,
    item_id: str | None,
) -> tuple[Any, date] | None:
    rows = await data.shop_daily(as_of, item_id)
    latest = max((r["day"] for r in rows if r["complete"]), default=None)
    if latest is None:
        return None
    w = build_windows(
        preset,
        anchor_for(preset, as_of, latest),
        explicit=explicit,
        named_month=named_month,
        sale_aware=True,
    )
    return clip_to_freshness(w, latest), latest


async def run_entity(
    kind: str | None,
    data: DataPort,
    intent: dict[str, Any],
    metric: str | None,
    preset: str,
    as_of: date,
    *,
    item_id: str | None = None,
    item_name: str | None = None,
    explicit: tuple[date, date] | None = None,
    named_month: str | None = None,
) -> list[dict[str, Any]]:
    """The data answers for the named entity; [] = no reader has it (the caller says
    `NO_DATA_VI`). `kind` None + `item_id` = one product's profit / margin / ads."""
    got = await _window(data, preset, as_of, explicit, named_month, None)
    if got is None:
        return []
    w, latest = got
    blob = _intent_blob(intent)
    if kind == "voucher":
        return await _voucher_answers(data, intent, metric, w, latest, item_id)
    if kind == "affiliate":
        now = await data.entity_totals(kind, w.cur[0], w.cur[1], item_id)
        before = await data.entity_totals(kind, w.prev[0], w.prev[1], item_id) if w.prev else None
        want = "cost" if _COST.search(blob) else (metric or "orders")
        if want not in ("orders", "gmv", "aov", "cost"):
            return []  # this entity has no such metric: never another metric under its label
        title = {
            "orders": "Đơn từ Tiếp thị liên kết",
            "gmv": "GMV đơn từ Tiếp thị liên kết",
            "aov": "AOV đơn từ Tiếp thị liên kết",
            "cost": "Hoa hồng Tiếp thị liên kết",
        }[want]
        if want == "cost" and now["cost"] is None:
            return []
        return [_total_answer(want, title, w, latest, now, before)]
    if kind == "campaign":
        camps = await data.campaign_rows(*w.cur)
        if not camps:
            return []
        loss_only = bool(_LOSS.search(blob))
        losing = [c for c in camps if campaign_verdict(c) == "Lỗ"]
        unclear = [c for c in camps if campaign_verdict(c) == "Chưa rõ"]
        # a verdict sentence about the set only when every member has a verdict; else the known
        # ones are stated and the rest are named "chưa rõ"
        pick = (losing + unclear) if loss_only and (losing or unclear) else camps
        pick = sorted(pick, key=campaign_order)
        rest = f"{len(unclear)} chiến dịch chưa rõ"
        if not loss_only:
            title = "Hiệu quả từng chiến dịch"
        elif losing:
            title = "Chiến dịch đang lỗ (dưới ROAS hoà vốn)" + (f" · còn {rest}" if unclear else "")
        elif unclear:
            title = f"Chưa thấy chiến dịch nào lỗ trong số đã rõ · {rest}"
        else:
            title = "Chưa có chiến dịch nào lỗ"
        return [
            _answer(
                "top_products",
                title,
                w,
                latest,
                rows=[campaign_row(c) for c in pick[:TOP_ROWS]],
                stop="data_answer",
            )
        ]
    if kind == "product_loss" and not item_id:
        rows = await data.product_profit_rows(*w.cur)
        losing = sorted(
            (r for r in rows if r.get("profit") is not None and float(r["profit"]) < 0),
            key=lambda r: float(r["profit"]),
        )
        unclear = [r for r in rows if r.get("profit") is None]
        if not rows:
            return []
        rest = f"{len(unclear)} sản phẩm chưa tính được lợi nhuận"
        if losing:
            title = "Sản phẩm đang lỗ sau quảng cáo" + (f" · còn {rest}" if unclear else "")
        elif unclear:
            title = f"Chưa thấy sản phẩm nào lỗ trong số đã tính · {rest}"
        else:
            title = "Chưa có sản phẩm nào lỗ sau quảng cáo"
        return [
            _answer(
                "top_products",
                title,
                w,
                latest,
                rows=[product_loss_row(r) for r in (losing + unclear)[:TOP_ROWS]],
                stop="data_answer",
            )
        ]
    if item_id and metric == "roas_break_even":
        # the product's own value from the shared profit service (as the cards / Phân tích)
        p = await data.product_profit(item_id, *w.cur)
        if p is None:
            return []
        before = await data.product_profit(item_id, *w.prev) if w.prev else None
        now_v = _f(p.get("break_even_roas"))
        old_v = None if before is None else _f(before.get("break_even_roas"))
        extra: dict[str, Any] = {}
        if p.get("contribution_before_ads") is not None:
            extra["contribution_vi"] = "Đóng góp trước quảng cáo " + fmt.value(
                "profit", _f(p["contribution_before_ads"])
            )
        return [
            _answer(
                "metric_total",
                f"ROAS hoà vốn · {item_name or item_id}",
                w,
                latest,
                value=fmt.value("roas_break_even", now_v),
                value_raw=now_v,
                before=old_v,
                before_vi=fmt.value("roas_break_even", old_v) if before else None,
                delta=fmt.delta("roas_break_even", now_v, old_v) if before else None,
                stop="data_answer",
                **extra,
            )
        ]
    if item_id and metric in ("profit", "margin"):
        p = await data.product_profit(item_id, *w.cur)
        if p is None:
            return []
        before = await data.product_profit(item_id, *w.prev) if w.prev else None
        m = metric
        now_v = _f(p["profit"]) if m == "profit" else _f(p["margin_pct"])
        old_v = (
            None
            if before is None
            else (_f(before["profit"]) if m == "profit" else _f(before["margin_pct"]))
        )
        if m == "margin":  # service gives points (42.8); the app formats a fraction
            now_v = None if now_v is None else now_v / 100
            old_v = None if old_v is None else old_v / 100
        name = item_name or item_id
        return [
            _answer(
                "metric_total",
                f"{'Lợi nhuận' if m == 'profit' else 'Biên lợi nhuận'} · {name}",
                w,
                latest,
                value=fmt.value(m, now_v),
                value_raw=now_v,
                before=old_v,
                before_vi=fmt.value(m, old_v) if before else None,
                delta=fmt.delta(m, now_v, old_v) if before else None,
                stop="data_answer",
            )
        ]
    return []
