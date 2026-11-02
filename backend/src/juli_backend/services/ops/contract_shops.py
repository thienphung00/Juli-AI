"""Contract-client shops managed from Juli Ops (owner decisions 2026-11-02, ADR-118).

A client under a signed contract whose platform API Juli cannot reach yet (Shopee
before the ISV approval) has no seller login: Juli Ops creates the shop and staff
work on it there.

- :func:`create_contract_shop` makes the owner row the ``shops.user_id`` foreign key
  needs -- a ``users`` row with no e-mail and no phone, which no sign-in resolves to,
  stamped ``staff_access_consent_at`` (the contract is the reason staff see the shop)
  -- and the ``platform='shopee'`` shop through the seller path's own
  ``connect_shopee_shop``.
- :func:`enable_consent` is the Ops "Bật" button: no fields. It grants the Terms
  scopes (``service``, ``llm_*``; never ``pooled_training``) with method
  ``contract_paper``, ``granted_by`` the staff member's id, and an evidence reference
  that names the button. It refuses a shop with a seller login: that seller's own
  Terms acceptance decides their consent, never Ops.

Nothing commits here; the route audits and commits.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope, with_user_scope
from juli_backend.models.models import Shop, User
from juli_backend.repositories.consent import DataUseConsentsRepo
from juli_backend.services.consent import TERMS_SCOPES, grant_consent
from juli_backend.services.ingest import connect_shopee_shop

CONTRACT_METHOD = "contract_paper"
CONTRACT_TERMS_VERSION = "contract"
EVIDENCE_PREFIX = "ops_contract_consent_enable"


class NotAContractShop(ValueError):
    """The shop has a seller login: its consent is the seller's to give."""


@dataclass(frozen=True)
class ConsentState:
    #: scope -> whether an open grant exists, for every Terms scope.
    scopes: dict[str, bool]
    contract_client: bool

    @property
    def enabled(self) -> bool:
        return all(self.scopes.values())


def evidence_ref(staff_id: uuid.UUID | None) -> str:
    return f"{EVIDENCE_PREFIX}:{staff_id or 'unknown'}"


async def create_contract_shop(
    session: AsyncSession, *, shop_name: str, shopee_shop_id: str | None, now: datetime
) -> Shop:
    """The login-less owner and its Shopee shop. ``ValueError`` on a bad name or id."""
    owner_id = uuid.uuid4()
    async with with_user_scope(session, owner_id):
        # One INSERT (no phone, no e-mail: nothing a sign-in can resolve to).
        session.add(User(id=owner_id, phone=None, staff_access_consent_at=now))
        await session.flush()
    return await connect_shopee_shop(
        session, user_id=owner_id, shop_name=shop_name, shopee_shop_id=shopee_shop_id
    )


async def is_contract_client(
    session: AsyncSession, shop_id: uuid.UUID, owner_id: uuid.UUID
) -> bool:
    """A Shopee shop whose owner has no e-mail and accepted no Terms: no sign-in behind it.

    ``owner_id`` comes from the Ops listing (``ops_list_shops``); ``shops`` and ``users``
    are read under that owner's scope, which their RLS policies key on.
    """
    async with with_user_scope(session, owner_id):
        row = (
            await session.execute(
                select(Shop.platform, User.email, User.terms_accepted_at)
                .join(User, User.id == Shop.user_id)
                .where(Shop.id == shop_id, Shop.user_id == owner_id)
            )
        ).one_or_none()
    if row is None:
        return False
    platform, email, accepted = row
    return platform == "shopee" and email is None and accepted is None


async def consent_state(
    session: AsyncSession, shop_id: uuid.UUID, owner_id: uuid.UUID
) -> ConsentState:
    contract = await is_contract_client(session, shop_id, owner_id)
    async with with_shop_scope(session, shop_id):
        repo = DataUseConsentsRepo(session)
        scopes = {scope: await repo.find_open(shop_id, scope) is not None for scope in TERMS_SCOPES}
    return ConsentState(scopes=scopes, contract_client=contract)


async def enable_consent(
    session: AsyncSession,
    shop_id: uuid.UUID,
    owner_id: uuid.UUID,
    *,
    staff_id: uuid.UUID | None,
    now: datetime,
) -> list[str]:
    """Grant every Terms scope not yet open; returns the scopes granted now."""
    if not await is_contract_client(session, shop_id, owner_id):
        raise NotAContractShop(str(shop_id))
    granted: list[str] = []
    async with with_shop_scope(session, shop_id):
        repo = DataUseConsentsRepo(session)
        for scope in TERMS_SCOPES:
            if await repo.find_open(shop_id, scope) is not None:
                continue
            await grant_consent(
                session,
                shop_id,
                scope=scope,
                method=CONTRACT_METHOD,
                terms_version=CONTRACT_TERMS_VERSION,
                evidence_ref=evidence_ref(staff_id),
                granted_by=str(staff_id or "ops"),
                granted_at=now,
            )
            granted.append(scope)
    return granted
