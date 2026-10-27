"""Terms acceptance grants consent for the seller's shops (ADR-116 §2, owner decision D10).

A self-serve seller who accepts the Terms of Service in the app (``POST /v1/me/consents``)
grants, for every shop they own, the four scopes the Terms and the privacy policy cover:
``service``, ``llm_processing``, ``llm_images`` and ``llm_media`` -- method
``in_app_click``, evidence ``users.terms_accepted_at:<user id>``. ``pooled_training``
is never granted here: it needs a separate written opt-in.

Two callers: ``services/privacy/prefs.record_consent`` (the acceptance itself) and
``services/tiktok/oauth.complete_tiktok_oauth_callback`` (a shop connected after the
owner already accepted). The operator backfill (``cli.py backfill-terms``) uses the
same function for sellers who accepted before this existed.

Idempotent: a scope that already has an open grant is skipped, whatever its method.
Each shop's writes run in a SAVEPOINT under that shop's scope (``with_shop_scope``;
RLS on ``data_use_consents`` keys on ``app_current_shop_id()``); the rollback to the
savepoint also puts the caller's tenant GUCs back. A failure is logged
(``consent_terms_grant_failed``, shop id and error type only) and never raised, the
``card_events`` writer's shape: consent is a side write, and terms acceptance or a
shop connect must not fail because of it. A shop left without a grant fails closed
at every gate and is picked up by the next backfill run.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.repositories.consent import DataUseConsentsRepo
from juli_backend.repositories.identity import ShopsRepo, UsersRepo
from juli_backend.services.consent.grants import grant_consent

logger = logging.getLogger(__name__)

#: What accepting the Terms grants (D10). Never ``pooled_training``.
TERMS_SCOPES: tuple[str, ...] = ("service", "llm_processing", "llm_images", "llm_media")
TERMS_METHOD = "in_app_click"


@dataclass(frozen=True)
class TermsGrantResult:
    """Counts of one run: scopes granted (or, on a dry run, that would be), already
    open, and shops whose writes failed and were rolled back."""

    granted: int = 0
    already_open: int = 0
    failed_shops: int = 0

    def __add__(self, other: TermsGrantResult) -> TermsGrantResult:
        return TermsGrantResult(
            self.granted + other.granted,
            self.already_open + other.already_open,
            self.failed_shops + other.failed_shops,
        )


def terms_evidence_ref(user_id: uuid.UUID) -> str:
    """Where the evidence is: the owner's ``users.terms_accepted_at`` stamp."""
    return f"users.terms_accepted_at:{user_id}"


async def _grant_one_shop(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    accepted_at: datetime,
    terms_version: str,
    write: bool,
) -> TermsGrantResult:
    granted = already = 0
    async with session.begin_nested(), with_shop_scope(session, shop_id):
        repo = DataUseConsentsRepo(session)
        for scope in TERMS_SCOPES:
            if await repo.find_open(shop_id, scope) is not None:
                already += 1
                continue
            if write:
                await grant_consent(
                    session,
                    shop_id,
                    scope=scope,
                    method=TERMS_METHOD,
                    terms_version=terms_version,
                    evidence_ref=terms_evidence_ref(user_id),
                    granted_by=str(user_id),
                    granted_at=accepted_at,
                )
            granted += 1
    return TermsGrantResult(granted, already)


async def grant_terms_consents(
    session: AsyncSession,
    user_id: uuid.UUID,
    shop_ids: Iterable[uuid.UUID],
    *,
    accepted_at: datetime,
    terms_version: str,
    write: bool = True,
) -> TermsGrantResult:
    """Grant :data:`TERMS_SCOPES` to each of ``user_id``'s ``shop_ids``; never raises.

    ``granted_by`` is the user id, never a contact detail. ``write=False`` counts what
    would be granted without writing (the operator dry run). Nothing commits here.
    """
    total = TermsGrantResult()
    for shop_id in shop_ids:
        try:
            total += await _grant_one_shop(
                session,
                shop_id,
                user_id=user_id,
                accepted_at=accepted_at,
                terms_version=terms_version,
                write=write,
            )
        except Exception as exc:
            logger.warning(
                "consent_terms_grant_failed",
                extra={"shop_id": str(shop_id), "error_type": type(exc).__name__},
            )
            total += TermsGrantResult(failed_shops=1)
    return total


def terms_version_of(terms_date: date) -> str:
    """The ``terms_version`` a Terms acceptance records: the legal text's date."""
    return terms_date.isoformat()


async def grant_terms_consents_for_owned_shops(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    accepted_at: datetime,
    terms_date: date,
) -> TermsGrantResult:
    """The acceptance path: every shop ``user_id`` owns (read under their user scope)."""
    try:
        async with session.begin_nested():
            shops = await ShopsRepo(session).list_for_authorization(user_id)
    except Exception as exc:
        logger.warning("consent_terms_grant_failed", extra={"error_type": type(exc).__name__})
        return TermsGrantResult(failed_shops=1)
    return await grant_terms_consents(
        session,
        user_id,
        [shop.id for shop in shops],
        accepted_at=accepted_at,
        terms_version=terms_version_of(terms_date),
    )


async def grant_terms_consents_if_accepted(
    session: AsyncSession,
    user_id: uuid.UUID,
    shop_ids: Iterable[uuid.UUID],
    *,
    write: bool = True,
) -> TermsGrantResult:
    """Grant to ``shop_ids`` only when ``user_id`` has accepted the Terms; never raises.

    For a shop connected after its owner accepted, and for the backfill. No recorded
    acceptance (``terms_accepted_at`` or ``terms_date_accepted`` empty) grants nothing.
    """
    shop_ids = list(shop_ids)
    try:
        async with session.begin_nested():
            user = await UsersRepo(session).get_own(user_id)
    except Exception as exc:
        logger.warning(
            "consent_terms_grant_failed",
            extra={"shops": len(shop_ids), "error_type": type(exc).__name__},
        )
        return TermsGrantResult(failed_shops=len(shop_ids))
    if user.terms_accepted_at is None or user.terms_date_accepted is None:
        return TermsGrantResult()
    return await grant_terms_consents(
        session,
        user_id,
        shop_ids,
        accepted_at=user.terms_accepted_at,
        terms_version=terms_version_of(user.terms_date_accepted),
        write=write,
    )


__all__ = [
    "TERMS_METHOD",
    "TERMS_SCOPES",
    "TermsGrantResult",
    "grant_terms_consents",
    "grant_terms_consents_for_owned_shops",
    "grant_terms_consents_if_accepted",
    "terms_evidence_ref",
    "terms_version_of",
]
