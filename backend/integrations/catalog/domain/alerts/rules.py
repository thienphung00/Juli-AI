"""Rule matching helpers for alert evaluation."""

from __future__ import annotations

import json
from typing import Any

from backend.integrations.catalog.domain.alerts.types import AlertEvent
from backend.database.models import AlertConfig


def parse_threshold(config: AlertConfig) -> dict[str, Any]:
    if not config.threshold_json:
        return {}
    try:
        data = json.loads(config.threshold_json)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def cooldown_seconds(config: AlertConfig) -> int:
    threshold = parse_threshold(config)
    raw = threshold.get("cooldown_seconds", 3600)
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return 3600


def rule_matches(config: AlertConfig, event: AlertEvent) -> bool:
    threshold = parse_threshold(config)
    alert_type = config.alert_type

    if alert_type == "revenue_milestone":
        if event.metric != "revenue":
            return False
        minimum = threshold.get("min_revenue")
        if minimum is None:
            return False
        return event.value >= float(minimum)

    if alert_type == "low_stock":
        if event.metric != "stock_quantity":
            return False
        maximum = threshold.get("max_quantity")
        if maximum is None:
            return False
        return event.value <= float(maximum)

    if alert_type == "anomaly":
        if event.event_type != "anomaly":
            return False
        min_severity = threshold.get("min_severity", "medium")
        severity = str(event.context.get("severity", "low"))
        order = {"low": 0, "medium": 1, "high": 2}
        return order.get(severity, 0) >= order.get(str(min_severity), 1)

    if alert_type == "violation_risk":
        if event.event_type != "policy":
            return False
        return bool(event.context.get("violation", False))

    return False


def build_alert_copy(config: AlertConfig, event: AlertEvent) -> tuple[str, str]:
    if config.alert_type == "revenue_milestone":
        return (
            "Mốc doanh thu đạt",
            f"Cửa hàng vừa đạt {event.value:,.0f} VND doanh thu.",
        )
    if config.alert_type == "low_stock":
        sku = event.context.get("sku_id", "SKU")
        return (
            "Sắp hết hàng",
            f"{sku} còn {int(event.value)} sản phẩm — nên nhập thêm.",
        )
    if config.alert_type == "anomaly":
        return (
            "Bất thường phát hiện",
            str(event.context.get("message", "Có chỉ số bất thường cần xem lại.")),
        )
    if config.alert_type == "violation_risk":
        return (
            "Rủi ro vi phạm",
            str(event.context.get("message", "Có dấu hiệu vi phạm chính sách.")),
        )
    return ("Cảnh báo", "Có sự kiện cần xử lý.")
