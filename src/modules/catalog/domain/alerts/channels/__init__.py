"""Channel adapters for alert delivery."""

from src.modules.catalog.domain.alerts.channels.fcm import FcmAdapter
from src.modules.catalog.domain.alerts.channels.zalo import ZaloOaAdapter

__all__ = ["FcmAdapter", "ZaloOaAdapter"]
