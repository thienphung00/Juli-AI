"""Per-shop data-use consent (ADR-116 §2, D76).

``require_consent`` is the one question every gate on client data asks; it fails
closed. ``grant_consent`` / ``revoke_consent`` record the answers. See
``MODULE.md`` for the scopes and who calls what.
"""

from __future__ import annotations

from juli_backend.services.consent.check import ConsentRequired, has_consent, require_consent
from juli_backend.services.consent.grants import InvalidConsent, grant_consent, revoke_consent

__all__ = [
    "ConsentRequired",
    "InvalidConsent",
    "grant_consent",
    "has_consent",
    "require_consent",
    "revoke_consent",
]
