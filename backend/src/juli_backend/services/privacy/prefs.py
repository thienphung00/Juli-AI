"""Privacy preferences, terms consent and the deletion request (P50-B, D60).

Every write goes through ``UsersRepo.update_privacy`` (the caller's own row under
``with_user_scope``); nothing here commits -- the route does.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import User
from juli_backend.repositories.identity import UsersRepo
from juli_backend.services.privacy.terms import DELETION_GRACE, LEGAL_TERMS_DATE

#: The keys ``PATCH /v1/me/privacy`` accepts.
PREFERENCE_KEYS: tuple[str, ...] = (
    "marketing_opt_out",
    "ad_measurement_opt_out",
    "case_study_opt_in",
)


class TermsDateMismatch(Exception):
    """The client accepted a legal text that is not the current one (409)."""


class LiabilityClauseRequired(Exception):
    """Điều 11 must be accepted separately (D60.4) (422)."""


def as_utc(value: datetime | None) -> datetime | None:
    """A stored instant as aware UTC (SQLite hands timezone columns back naive)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso_utc(value: datetime | None) -> str | None:
    moment = as_utc(value)
    return None if moment is None else moment.isoformat().replace("+00:00", "Z")


def now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class PrivacyState:
    marketing_opt_out: bool
    ad_measurement_opt_out: bool
    case_study_opt_in: bool
    terms_date_accepted: date | None
    terms_accepted_at: datetime | None
    liability_clause_accepted_at: datetime | None
    deletion_scheduled_for: datetime | None

    @classmethod
    def of(cls, user: User) -> PrivacyState:
        return cls(
            marketing_opt_out=bool(user.marketing_opt_out),
            ad_measurement_opt_out=bool(user.ad_measurement_opt_out),
            case_study_opt_in=bool(user.case_study_opt_in),
            terms_date_accepted=user.terms_date_accepted,
            terms_accepted_at=as_utc(user.terms_accepted_at),
            liability_clause_accepted_at=as_utc(user.liability_clause_accepted_at),
            deletion_scheduled_for=as_utc(user.deletion_scheduled_for),
        )

    @property
    def needs_terms_acceptance(self) -> bool:
        return (
            self.terms_date_accepted != LEGAL_TERMS_DATE
            or self.liability_clause_accepted_at is None
        )

    def to_json(self) -> dict[str, Any]:
        """Contract §GET /v1/me/privacy."""
        return {
            "marketing_opt_out": self.marketing_opt_out,
            "ad_measurement_opt_out": self.ad_measurement_opt_out,
            "case_study_opt_in": self.case_study_opt_in,
            "terms_date_accepted": (
                self.terms_date_accepted.isoformat() if self.terms_date_accepted else None
            ),
            "terms_accepted_at": iso_utc(self.terms_accepted_at),
            "liability_clause_accepted_at": iso_utc(self.liability_clause_accepted_at),
            "current_terms_date": LEGAL_TERMS_DATE.isoformat(),
            "needs_terms_acceptance": self.needs_terms_acceptance,
            "deletion_scheduled_for": iso_utc(self.deletion_scheduled_for),
        }


async def get_privacy(session: AsyncSession, user_id: uuid.UUID) -> PrivacyState:
    return PrivacyState.of(await UsersRepo(session).get_own(user_id))


async def update_preferences(
    session: AsyncSession, user_id: uuid.UUID, changes: dict[str, bool]
) -> PrivacyState:
    unknown = set(changes) - set(PREFERENCE_KEYS)
    if unknown:
        raise ValueError(f"not a preference: {sorted(unknown)}")
    repo = UsersRepo(session)
    if not changes:
        return PrivacyState.of(await repo.get_own(user_id))
    return PrivacyState.of(await repo.update_privacy(user_id, **changes))


async def record_consent(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    terms_date: date,
    liability_clause: bool,
    now: datetime | None = None,
) -> PrivacyState:
    """D60.4 / D60.8: the current text, and Điều 11 accepted separately."""
    if terms_date != LEGAL_TERMS_DATE:
        raise TermsDateMismatch(terms_date.isoformat())
    if liability_clause is not True:
        raise LiabilityClauseRequired()
    at = now or now_utc()
    user = await UsersRepo(session).update_privacy(
        user_id,
        terms_date_accepted=terms_date,
        terms_accepted_at=at,
        liability_clause_accepted_at=at,
    )
    return PrivacyState.of(user)


async def request_deletion(
    session: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None
) -> PrivacyState:
    """D60.10: delete in 30 days. Idempotent -- a pending date is never moved."""
    repo = UsersRepo(session)
    user = await repo.get_own(user_id)
    if user.deletion_scheduled_for is not None:
        return PrivacyState.of(user)
    when = (now or now_utc()) + DELETION_GRACE
    return PrivacyState.of(await repo.update_privacy(user_id, deletion_scheduled_for=when))


async def cancel_deletion(session: AsyncSession, user_id: uuid.UUID) -> PrivacyState:
    repo = UsersRepo(session)
    user = await repo.get_own(user_id)
    if user.deletion_scheduled_for is None:
        return PrivacyState.of(user)
    return PrivacyState.of(await repo.update_privacy(user_id, deletion_scheduled_for=None))


def deletion_pending(user: User | None) -> bool:
    return getattr(user, "deletion_scheduled_for", None) is not None


__all__ = [
    "PREFERENCE_KEYS",
    "LiabilityClauseRequired",
    "PrivacyState",
    "TermsDateMismatch",
    "as_utc",
    "cancel_deletion",
    "deletion_pending",
    "get_privacy",
    "iso_utc",
    "record_consent",
    "request_deletion",
    "update_preferences",
]
