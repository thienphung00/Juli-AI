"""Forbidden: api must not deep-import integrations.tiktok.client."""

from juli_backend.integrations.tiktok.client import TikTokClient

__all__ = ["TikTokClient"]
