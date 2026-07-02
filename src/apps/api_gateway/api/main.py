"""Compatibility shim — runtime moved to `backend.api.api` (issue #252)."""
from backend.api.api.main import *  # noqa: F403
from backend.api.api.main import app
