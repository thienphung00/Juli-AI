"""Multi-channel seller alerts: rule engine + pluggable delivery."""

from src.modules.catalog.domain.alerts.channels.fcm import FcmAdapter
from src.modules.catalog.domain.alerts.channels.zalo import ZaloOaAdapter
from src.modules.catalog.domain.alerts.delivery import deliver_alert
from src.modules.catalog.domain.alerts.engine import configure_rules, evaluate_rules
from src.modules.catalog.domain.alerts.types import (
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
