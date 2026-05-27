"""Multi-channel seller alerts: rule engine + pluggable delivery."""

from src.alerts.channels.fcm import FcmAdapter
from src.alerts.delivery import deliver_alert
from src.alerts.engine import configure_rules, evaluate_rules
from src.alerts.types import (
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
    "RuleConfigInput",
    "configure_rules",
    "deliver_alert",
    "evaluate_rules",
]
