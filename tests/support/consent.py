"""Consent grants for tests whose subject is not consent itself (ADR-116 §2, §5)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.consent import DataUseConsent
from juli_backend.services.consent import grant_consent
from juli_backend.services.llm_gate import LLM_SCOPES, MemoryCallLog, OpenAIGate, open_gate

GRANTED_AT = datetime(2026, 10, 26, 3, 0)


async def grant_service_consent(session: AsyncSession, shop_id: uuid.UUID) -> DataUseConsent:
    """An open ``service`` grant for ``shop_id``, as a signed contract would record it."""
    return await grant_consent(
        session,
        shop_id,
        scope="service",
        method="contract_paper",
        terms_version="test-terms-v1",
        evidence_ref="tests/contract.pdf",
        granted_by="test client",
        granted_at=GRANTED_AT,
    )


async def grant_llm_consent(
    session: AsyncSession, shop_id: uuid.UUID, scopes: Iterable[str] = LLM_SCOPES
) -> None:
    """Open OpenAI grants for ``shop_id`` (ADR-116 §5): text, images and media by default."""
    for scope in scopes:
        await grant_consent(
            session,
            shop_id,
            scope=scope,
            method="in_app_click",
            terms_version="test-terms-v1",
            evidence_ref="tests/terms-accepted",
            granted_by="test seller",
            granted_at=GRANTED_AT,
        )


async def consenting_gate(
    session: AsyncSession, shop_id: uuid.UUID, scopes: Iterable[str] = LLM_SCOPES
) -> tuple[OpenAIGate, MemoryCallLog]:
    """Grant ``scopes`` through ``grant_consent`` and open the shop's OpenAI gate on them,
    logging into memory."""
    await grant_llm_consent(session, shop_id, scopes)
    log = MemoryCallLog()
    return await open_gate(session, shop_id, sink=log, sync_sink=log), log


def granted_gate(
    scopes: Iterable[str] = LLM_SCOPES, *, shop_id: uuid.UUID | None = None
) -> OpenAIGate:
    """A gate holding ``scopes`` without a database, for tests of the OpenAI wire
    translation whose subject is not consent (the consent read itself is covered by
    ``tests/unit/test_llm_gate.py`` through ``grant_consent``)."""
    log = MemoryCallLog()
    return OpenAIGate(
        shop_id=shop_id or uuid.uuid4(), granted=frozenset(scopes), sink=log, sync_sink=log
    )
