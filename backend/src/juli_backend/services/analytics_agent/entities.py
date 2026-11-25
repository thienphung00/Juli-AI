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
from juli_backend.services.analytics_agent.labels import METRICS_VI
from juli_backend.services.analytics_agent.types import DataPort
from juli_backend.services.analytics_agent.windows import (
    anchor_for,
    build_windows,
    campaign_days,
    clip_to_freshness,
    sale_days_vi,
)
from juli_backend.services.metrics.compute import raw_value

NO_DATA_VI = "Juli chưa có số liệu này"
_COST = re.compile(r"cost|spend|chi phí|commission|hoa hồng|discount|ưu đãi", re.I)
_LOSS = re.compile(r"los(e|es|ing|s|t)\b|lỗ|unprofitable|below|thua|not worth|negative", re.I)
TOP_ROWS = 8


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
    return {
        "label_vi": str(c["name"]),
        "value_vi": f"{campaign_verdict(c)} · ROAS {fmt.value('roas', _f(c['roas']))}"
        f" · hoà vốn {be}",
        "detail_vi": prefix
        + f"chi {fmt.value('ads_spend', _f(c['spend']))} · GMV {fmt.value('gmv', _f(c['gmv']))}",
    }


def product_loss_row(r: dict[str, Any]) -> dict[str, Any]:
    """One product losing after ads: profit after ads, contribution before ads, ads spend and
    ROAS hoà vốn (the shared `ProductProfit` figures)."""
    be = r.get("break_even_roas")
    contrib = r.get("contribution")
    return {
        "label_vi": str(r.get("name") or r["item_id"]),
        "value_vi": "Lỗ " + fmt.value("profit", abs(float(r["profit"]))),
        "detail_vi": METRICS_VI["contribution"].lower()
        + " "
        + (fmt.value("profit", _f(contrib)) if contrib is not None else "chưa có")
        + f" · chi quảng cáo {fmt.value('ads_spend', _f(r.get('ad_spend')))}"
        + f" · hoà vốn {fmt.value('roas', _f(be)) if be is not None else 'chưa có'}",
        "link": {"kind": "product", "item_id": r["item_id"]},
    }


def campaign_order(c: dict[str, Any]) -> float:
    """Worst profit after ads first; unknown last."""
    p = c.get("profit_after_ads")
    return float("inf") if p is None else float(p)


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
    if kind in ("voucher", "affiliate"):
        if kind == "voucher":
            # the stored per-order income (`order_settlements.seller_voucher_borne`): only days
            # that HAVE income rows count, never as 0; no source splits it by product
            if item_id:
                return []
            now = await data.voucher_income(w.cur[0], w.cur[1])
            before = await data.voucher_income(w.prev[0], w.prev[1]) if w.prev else None
            if not now.get("rows"):
                return []
            if before is not None and not before.get("rows"):
                before = None
        else:
            now = await data.entity_totals(kind, w.cur[0], w.cur[1], item_id)
            before = (
                await data.entity_totals(kind, w.prev[0], w.prev[1], item_id) if w.prev else None
            )
        want = "cost" if _COST.search(blob) else (metric or "orders")
        if want not in ("orders", "gmv", "aov", "cost"):
            return []  # this entity has no such metric: never another metric under its label
        who = "dùng voucher" if kind == "voucher" else "từ Tiếp thị liên kết"
        title = {
            "orders": f"Đơn {who}",
            "gmv": f"GMV đơn {who}",
            "aov": f"AOV đơn {who}",
            "cost": "Chi phí voucher (Ưu đãi)"
            if kind == "voucher"
            else "Hoa hồng Tiếp thị liên kết",
        }[want]
        if want == "cost" and now["cost"] is None:
            return []

        def value_of(t: dict[str, Any] | None) -> float | None:
            if t is None:
                return None
            if want == "aov":
                raw = raw_value(
                    "aov", {"gmv": Decimal(str(t["gmv"])), "orders": Decimal(str(t["orders"]))}
                )
                return float(raw) if isinstance(raw, Decimal) else None
            return _f(t[want])

        mkey = {"orders": "orders", "gmv": "gmv", "aov": "aov", "cost": "gmv"}[want]
        n, b0 = value_of(now), value_of(before)
        out = [
            _answer(
                "metric_total",
                title + _sale_note(w),
                w,
                latest,
                value=fmt.value(mkey, n),
                value_raw=n,
                before=b0,
                before_vi=fmt.value(mkey, b0) if before else None,
                delta=fmt.delta(mkey, n, b0) if before else None,
                stop="data_answer",
            )
        ]
        if kind == "voucher":
            # Ưu đãi is a COST (owner 2026-11-20): the voucher part is the cost answer above; the
            # income data may end before the window does, and the answers say how far it goes
            income_to = now.get("income_to")
            if income_to is not None and income_to < w.cur[1]:
                for ev in out:
                    ev["fresh_vi"] = f"Số liệu thu nhập đến hết {income_to:%d/%m}"
            # no source names the voucher code of an order (the income rows carry only amounts)
            out.append(
                _answer(
                    "metric_total",
                    "Kết quả từng mã voucher",
                    w,
                    latest,
                    value=NO_DATA_VI,
                    value_raw=None,
                    stop="data_answer",
                )
            )
        return out
    if kind == "campaign":
        camps = await data.campaign_rows(*w.cur)
        if not camps:
            return []
        loss_only = bool(_LOSS.search(blob))
        losing = [c for c in camps if campaign_verdict(c) == "Lỗ"]
        pick = losing if loss_only and losing else camps
        pick = sorted(pick, key=campaign_order)
        title = (
            "Chiến dịch đang lỗ (dưới ROAS hoà vốn)"
            if loss_only and losing
            else ("Chưa có chiến dịch nào lỗ" if loss_only else "Hiệu quả từng chiến dịch")
        )
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
        if not rows:
            return []
        return [
            _answer(
                "top_products",
                "Sản phẩm đang lỗ sau quảng cáo"
                if losing
                else "Chưa có sản phẩm nào lỗ sau quảng cáo",
                w,
                latest,
                rows=[product_loss_row(r) for r in losing[:TOP_ROWS]],
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
        if p.get("contribution") is not None:
            extra["contribution_vi"] = (
                METRICS_VI["contribution"] + " " + fmt.value("profit", _f(p["contribution"]))
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
