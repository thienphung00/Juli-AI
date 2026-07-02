"""Compatibility shim — runtime moved to `backend.api.services.webhook` (issue #252)."""
from backend.api.services.webhook.app import *  # noqa: F403
from backend.api.services.webhook.app import app
