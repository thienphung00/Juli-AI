"""Channel adapters for alert delivery."""

from backend.integrations.catalog.domain.alerts.channels.fcm import FcmAdapter
from backend.integrations.catalog.domain.alerts.channels.zalo import ZaloOaAdapter

__all__ = ["FcmAdapter", "ZaloOaAdapter"]
