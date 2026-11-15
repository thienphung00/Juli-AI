"""Platform capabilities (T9): what Juli can read or write on each platform, and by which route.

Design: ``docs/architecture/metric-registry.md`` §8. Step 1: declared only; ``_shopee()`` in the
routes and the frontend platform checks are not replaced yet.
"""

from __future__ import annotations

from juli_backend.services.capabilities.registry import CAPABILITIES, Capability, Route, can

__all__ = ["CAPABILITIES", "Capability", "Route", "can"]
