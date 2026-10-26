"""Read side: may Juli use this shop's data for this purpose? (ADR-116 §2).

Every gate that touches client data asks here and nowhere else: the OpenAI
adapter (``llm_processing``), the shared-model dataset builder and fleet
calibration (``pooled_training``), the ingest gateway and the client layer
(``service``). The answer fails closed: no grant, a revoked grant, an unknown
scope or a failed lookup all mean "no".

The caller's session must already be scoped to the shop (``with_shop_scope``):
under RLS another shop's grants are invisible, so a mis-scoped session reads
"no grant" rather than someone else's yes.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.consent import SCOPES, DataUseConsent
from juli_backend.repositories.consent import DataUseConsentsRepo

logger = logging.getLogger(__name__)


class ConsentRequired(Exception):
    """The shop has not granted ``scope`` (or the answer could not be read)."""

    def __init__(self, shop_id: uuid.UUID, scope: str) -> None:
        super().__init__(f"shop {shop_id} has no open {scope} consent")
        self.shop_id = shop_id
        self.scope = scope


async def require_consent(session: AsyncSession, shop_id: uuid.UUID, scope: str) -> DataUseConsent:
    """The shop's open grant of ``scope``; raises :class:`ConsentRequired` otherwise."""
    if scope not in SCOPES:
        raise ConsentRequired(shop_id, scope)
    try:
        grant = await DataUseConsentsRepo(session).find_open(shop_id, scope)
    except Exception as exc:  # fail closed: a lookup that errors is a "no"
        logger.warning(
            "consent_lookup_failed",
            extra={"shop_id": str(shop_id), "scope": scope, "error": type(exc).__name__},
        )
        raise ConsentRequired(shop_id, scope) from exc
    if grant is None:
        raise ConsentRequired(shop_id, scope)
    return grant


async def has_consent(session: AsyncSession, shop_id: uuid.UUID, scope: str) -> bool:
    """``True`` only when :func:`require_consent` would return a grant."""
    try:
        await require_consent(session, shop_id, scope)
    except ConsentRequired:
        return False
    return True
