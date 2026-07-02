"""Multi-channel seller alerts: rule engine + pluggable delivery."""

from backend.integrations.catalog.domain.alerts.channels.fcm import FcmAdapter
from backend.integrations.catalog.domain.alerts.channels.zalo import ZaloOaAdapter
from backend.integrations.catalog.domain.alerts.delivery import deliver_alert
from backend.integrations.catalog.domain.alerts.engine import configure_rules, evaluate_rules
from backend.integrations.catalog.domain.alerts.types import (
    Alert,
    AlertEvent,
    ChannelAdapter,
    DeliveryResult,
    RuleConfigInput,
)

__all__ = [
    "Alert",
    "AlertEvent",
    "ChannelAdapter",
    "DeliveryResult",
    "FcmAdapter",
    "ZaloOaAdapter",
    "RuleConfigInput",
    "configure_rules",
    "deliver_alert",
    "evaluate_rules",
]
