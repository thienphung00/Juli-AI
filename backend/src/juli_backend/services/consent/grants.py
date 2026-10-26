"""Write side: record a grant or a withdrawal (ADR-116 §2).

Validation lives here, not in the repository: a grant names a known scope and
method, says which terms it refers to and where the evidence is, and there is
at most one open grant per (shop, scope). A withdrawal closes the open grant;
the next grant is a new row, so the table is the history.

Runs on the caller's session and transaction (nothing commits here), which must
be scoped to the shop (``with_shop_scope``).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.exceptions import NotFound
from juli_backend.models.consent import METHODS, SCOPES, DataUseConsent
from juli_backend.repositories._base import utc_now_naive
from juli_backend.repositories.consent import DataUseConsentsRepo

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class InvalidConsent(ValueError):
    """The grant or withdrawal request is malformed or conflicts with the current state."""


def _naive_utc(value: datetime | None) -> datetime:
    if value is None:
        return utc_now_naive()
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _required(name: str, value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise InvalidConsent(f"{name} is required")
    return stripped


async def grant_consent(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    scope: str,
    method: str,
    terms_version: str,
    evidence_ref: str,
    granted_by: str,
    evidence_sha256: str | None = None,
    granted_at: datetime | None = None,
) -> DataUseConsent:
    """Record that the shop granted ``scope``; refuses when a grant is already open."""
    if scope not in SCOPES:
        raise InvalidConsent(f"unknown scope {scope!r}")
    if method not in METHODS:
        raise InvalidConsent(f"unknown method {method!r}")
    if evidence_sha256 is not None and not _SHA256.match(evidence_sha256):
        raise InvalidConsent("evidence_sha256 must be 64 lower-case hex characters")
    repo = DataUseConsentsRepo(session)
    if await repo.find_open(shop_id, scope) is not None:
        raise InvalidConsent(f"an open {scope} grant already exists; revoke it first")
    return await repo.record_grant(
        shop_id,
        scope=scope,
        method=method,
        terms_version=_required("terms_version", terms_version),
        evidence_ref=_required("evidence_ref", evidence_ref),
        evidence_sha256=evidence_sha256,
        granted_by=_required("granted_by", granted_by),
        granted_at=_naive_utc(granted_at),
    )


async def revoke_consent(
    session: AsyncSession,
    shop_id: uuid.UUID,
    scope: str,
    *,
    revoked_at: datetime | None = None,
) -> DataUseConsent:
    """Close the shop's open grant of ``scope``; refuses when there is none."""
    try:
        return await DataUseConsentsRepo(session).mark_revoked(
            shop_id, scope, _naive_utc(revoked_at)
        )
    except NotFound as exc:
        raise InvalidConsent(f"no open {scope} grant to revoke") from exc
