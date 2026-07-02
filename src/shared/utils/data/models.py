"""Compatibility shim — runtime moved to `backend.database` (issue #252)."""
from backend.database.models import *  # noqa: F403
from backend.database.models import models
