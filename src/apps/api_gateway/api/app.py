"""Compatibility shim — runtime moved to `backend.api.api` (issue #252)."""
from backend.api.api.app import *  # noqa: F403
from backend.api.api.app import app
