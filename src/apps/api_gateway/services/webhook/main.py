"""Compatibility shim — runtime moved to `backend.api.services.webhook` (issue #252)."""
from backend.api.services.webhook.main import *  # noqa: F403
from backend.api.api.main import app
