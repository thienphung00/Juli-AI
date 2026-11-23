"""Entity answers (Q17, Q22, Q23): a question that names a voucher, an affiliate (TTLK) channel,
an ad campaign or one product is answered from that entity's own rows, or not at all.

The rule: never a shop number under an entity's label. When a reader returns nothing, the answer
is `NO_DATA_VI` ("Juli chưa có số liệu này"), decided by code.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from juli_backend.services.analytics_agent import fmt
from juli_backend.services.analytics_agent.types import DataPort
from juli_backend.services.analytics_agent.windows import (
    anchor_for,
    build_windows,
    campaign_days,
)

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
        **extra,
    }


def _sale_note(w: Any) -> str:
    days = campaign_days(*w.cur)
    return f" (có ngày sale {', '.join(f'{d:%d/%m}' for d in days)})" if days else ""


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
        preset, anchor_for(preset, as_of, latest), explicit=explicit, named_month=named_month
    )
    return w, latest


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
        now = await data.entity_totals(kind, w.cur[0], w.cur[1], item_id)
        before = await data.entity_totals(kind, w.prev[0], w.prev[1], item_id) if w.prev else None
        label = "voucher" if kind == "voucher" else "Tiếp thị liên kết"
        use_cost = bool(_COST.search(blob))
        if use_cost:
            key, mkey = "cost", "gmv"
            title = (
                "Chi phí voucher (Ưu đãi)" if kind == "voucher" else "Hoa hồng Tiếp thị liên kết"
            )
            if now["cost"] is None:
                return []
        else:
            key, mkey = "orders", "orders"
            title = f"Đơn dùng {label}" if kind == "voucher" else "Đơn từ Tiếp thị liên kết"
        n, b0 = _f(now[key]), _f(before[key]) if before else None
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
            rows = (await data.voucher_rows(*w.cur))[:TOP_ROWS]
            if rows:
                out.append(
                    _answer(
                        "top_products",
                        "Kết quả từng mã voucher",
                        w,
                        latest,
                        rows=[
                            {
                                "label_vi": str(r["code"]),
                                "value_vi": fmt.value("gmv", _f(r["gmv"])),
                                "detail_vi": (
                                    f"{fmt.value('orders', _f(r['orders']))} đơn · chi phí "
                                    f"{fmt.value('gmv', _f(r['cost']))}"
                                ),
                            }
                            for r in rows
                        ],
                        stop="data_answer",
                    )
                )
        return out
    if kind == "campaign":
        camps = await data.campaign_rows(*w.cur)
        if not camps:
            return []
        loss_only = bool(_LOSS.search(blob))
        pick = [
            c
            for c in camps
            if not loss_only
            or (
                c["roas"] is not None
                and c["break_even"] is not None
                and c["roas"] < c["break_even"]
            )
        ]
        pick.sort(key=lambda c: float(c["profit_after_ads"]))
        title = "Chiến dịch dưới ROAS hoà vốn" if loss_only else "Hiệu quả từng chiến dịch"
        return [
            _answer(
                "top_products",
                title,
                w,
                latest,
                rows=[
                    {
                        "label_vi": str(c["name"]),
                        "value_vi": f"ROAS {fmt.value('roas', _f(c['roas']))} · hoà vốn "
                        f"{fmt.value('roas', _f(c['break_even']))}",
                        "detail_vi": f"chi {fmt.value('ads_spend', _f(c['spend']))} · GMV "
                        f"{fmt.value('gmv', _f(c['gmv']))}",
                    }
                    for c in pick[:TOP_ROWS]
                ],
                stop="data_answer",
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
