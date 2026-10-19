"""Seller privacy: preferences, terms consent, export, deletion (fast track P50-B, D68).

Contract ``fasttrack/contracts/p50-privacy.md``. Routes: ``api/routes/me.py``.
Purge: ``workers/tasks/privacy_account_purge.py``.
"""

from juli_backend.services.privacy.export import FORMAT_VERSION, build_export, export_json_default
from juli_backend.services.privacy.prefs import (
    PREFERENCE_KEYS,
    LiabilityClauseRequired,
    PrivacyState,
    TermsDateMismatch,
    cancel_deletion,
    deletion_pending,
    get_privacy,
    now_utc,
    record_consent,
    request_deletion,
    update_preferences,
)
from juli_backend.services.privacy.purge import PurgeCounts, due_account_ids, purge_account
from juli_backend.services.privacy.terms import (
    DELETION_GRACE,
    EXPORT_ROW_LIMIT,
    LEGAL_TERMS_DATE,
)

__all__ = [
    "DELETION_GRACE",
    "EXPORT_ROW_LIMIT",
    "FORMAT_VERSION",
    "LEGAL_TERMS_DATE",
    "PREFERENCE_KEYS",
    "LiabilityClauseRequired",
    "PrivacyState",
    "PurgeCounts",
    "TermsDateMismatch",
    "build_export",
    "cancel_deletion",
    "deletion_pending",
    "due_account_ids",
    "export_json_default",
    "get_privacy",
    "now_utc",
    "purge_account",
    "record_consent",
    "request_deletion",
    "update_preferences",
]
