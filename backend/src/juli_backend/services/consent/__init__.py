"""Per-shop data-use consent (ADR-116 §2, D76).

``require_consent`` is the one question every gate on client data asks; it fails
closed. ``grant_consent`` / ``revoke_consent`` record the answers. ``pooling`` holds
the pooled-cell rules (D14 / D15 / D17). See ``MODULE.md`` for the scopes and who
calls what.
"""

from __future__ import annotations

from juli_backend.services.consent.check import ConsentRequired, has_consent, require_consent
from juli_backend.services.consent.grants import InvalidConsent, grant_consent, revoke_consent
from juli_backend.services.consent.pooling import (
    FIGURE_FLEET_CALIBRATION,
    FIGURE_OPS_GROUP_PRIOR,
    MAX_SHOP_SHARE,
    MIN_CONTRIBUTING_SHOPS,
    CellCheck,
    ContributingSet,
    check_cell,
    contributing_set,
    log_contributing_set,
    record_contributing_set,
)

__all__ = [
    "FIGURE_FLEET_CALIBRATION",
    "FIGURE_OPS_GROUP_PRIOR",
    "MAX_SHOP_SHARE",
    "MIN_CONTRIBUTING_SHOPS",
    "CellCheck",
    "ConsentRequired",
    "ContributingSet",
    "InvalidConsent",
    "check_cell",
    "contributing_set",
    "grant_consent",
    "has_consent",
    "log_contributing_set",
    "record_contributing_set",
    "require_consent",
    "revoke_consent",
]
