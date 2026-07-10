"""Multi-channel seller alerts: rule engine + pluggable delivery."""

from juli_backend.services.alerts.channels.fcm import FcmAdapter
from juli_backend.services.alerts.channels.zalo import ZaloOaAdapter
from juli_backend.services.alerts.delivery import deliver_alert
from juli_backend.services.alerts.engine import configure_rules, evaluate_rules
from juli_backend.services.alerts.types import (
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
