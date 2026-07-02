"""Compatibility shim — runtime moved to `backend.database` (issue #252)."""
from backend.database.exceptions import *  # noqa: F403
from backend.database.exceptions import exceptions
