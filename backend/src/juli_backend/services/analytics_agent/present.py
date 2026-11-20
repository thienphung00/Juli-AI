"""Code-rendered pieces of an answer: the path row (U4b, links per U7), the stop label (U4c), status
lines."""

from __future__ import annotations

import re
from typing import Any

from juli_backend.services.analytics_agent import fmt
from juli_backend.services.analytics_agent.chains import ChainResult
from juli_backend.services.analytics_agent.types import LabelTable

STATUS = {
    "thinking": "Đang tìm hiểu",
    "checking_data": "Đang kiểm tra dữ liệu",
    "finding_cause": "Đang tìm nguyên nhân",
    "preparing_card": "Đang chuẩn bị đề xuất",
}
EVENT_VI = {
    "ads_spend_drop": "Chi phí quảng cáo giảm mạnh",
    "stock_out": "Có sản phẩm hết kho",
    "unlisted": "Có sản phẩm bị ẩn",
    "daily_outlier": "Có ngày bất thường",
    "campaign_day": "Có ngày siêu sale",
}


def status(key: str, text_vi: str | None = None) -> dict[str, Any]:
    return {"type": "status", "key": key, "text_vi": text_vi or STATUS[key]}


def comparing(chain: ChainResult) -> dict[str, Any]:
    return status("comparing", f"Đang so sánh {chain.windows.label().replace(' so với ', ' với ')}")


def _window(chain: ChainResult) -> dict[str, str]:
    w = chain.windows
    return {"from": str(w.cur[0]), "to": str(w.cur[1])}


def path_steps(chain: ChainResult, labels: LabelTable, limit: int = 4) -> list[dict[str, Any]]:
    """shop -> channel -> product, each a link. Values pre-formatted; direction is data."""
    metric = chain.metric
    w = _window(chain)
    steps: list[dict[str, Any]] = []
    head = chain.findings[0] if chain.findings else None
    if head is not None:
        steps.append(
            {
                "label_vi": labels.metric(metric),
                "value_vi": fmt.value(metric, head.now),
                "delta": fmt.delta(metric, head.now, head.before),
                "link": {"kind": "metric", "metric": metric, **w},
            }
        )
    for f in chain.findings[1:]:
        if f.contribution_pct is None or len(steps) >= limit + 1:
            continue
        base, _, sub = f.node.partition(".")
        m = sub or (base if base in labels.metrics else metric)
        label = chain.node_vi(f.node, labels)
        if f.level in ("source", "endpoint.channel"):
            link: dict[str, Any] = {"kind": "channel", "metric": metric, "channel": base, **w}
        elif f.level in ("product", "endpoint.product"):
            pid = re.search(r"product:([^:\s]+)", f.evidence_ref or "")
            link = {"kind": "product", "item_id": pid.group(1) if pid else None, **w}
        elif f.level == "line" and f.node in ("cost_ads", "cost_affiliate"):
            link = {"kind": "ads", **w}
        else:
            link = {"kind": "metric", "metric": m if m in labels.metrics else metric, **w}
        steps.append(
            {
                "label_vi": label,
                "value_vi": fmt.value(m if m in labels.metrics else metric, f.now),
                "delta": fmt.delta(m if m in labels.metrics else metric, f.now, f.before),
                "link": link,
            }
        )
    return steps


def event_lines(chain: ChainResult) -> str:
    kinds = list(dict.fromkeys(e["kind"] for e in chain.events if e["kind"] != "campaign_day"))
    return "; ".join(EVENT_VI.get(k, "") for k in kinds if EVENT_VI.get(k))


def label_event(chain: ChainResult, latest_text: str | None = None) -> dict[str, Any] | None:
    """Stop label. `explained` shows none."""
    sr = chain.stop_reason
    if sr == "explained":
        return None
    if sr == "within_noise":
        band = (chain.noise or {}).get("band")
        detail = (
            f"Mức dao động thường gặp từ {fmt.decimal(100 * band[0], 1)}% "
            f"đến {fmt.decimal(100 * band[1], 1)}%"
            if band
            else None
        )
        return {
            "type": "label",
            "stop_reason": sr,
            "text_vi": "Không phát hiện gì bất thường",
            "detail_vi": detail,
        }
    if sr == "unexplained":
        return {
            "type": "label",
            "stop_reason": sr,
            "text_vi": "Chưa rõ nguyên nhân",
            "detail_vi": event_lines(chain) or None,
        }
    if sr == "data_stale":
        flag = next(
            (f for x in chain.findings for f in x.flags if f.startswith("latest_complete:")), ""
        )
        d = flag.split(":", 1)[-1]
        txt = f"Dữ liệu đến {d[8:10]}/{d[5:7]}" if len(d) == 10 else "Dữ liệu chưa cập nhật"
        return {"type": "label", "stop_reason": sr, "text_vi": txt, "detail_vi": latest_text}
    return {
        "type": "label",
        "stop_reason": "data_missing",
        "text_vi": "Thiếu dữ liệu",
        "detail_vi": None,
    }
