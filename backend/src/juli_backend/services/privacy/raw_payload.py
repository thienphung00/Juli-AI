"""One call before every raw platform write: allowlist, then pseudonymise (ADR-116 §4).

``sanitize_raw_payload`` is what the bronze writers and the ingest gateway call
instead of storing a platform body as received. It raises
:class:`~juli_backend.services.privacy.payload_allowlist.UnknownPayloadEndpoint`
for an endpoint without an allowlist, and the caller stores nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.privacy.payload_allowlist import allowlist_payload
from juli_backend.services.privacy.pseudonym import pseudonymize_buyer_ids


async def sanitize_raw_payload(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    platform: str,
    endpoint: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """``payload`` limited to its allowlist, every ``buyer_id`` as the shop's pseudonym."""
    kept = allowlist_payload(platform, endpoint, payload)
    return await pseudonymize_buyer_ids(session, shop_id, kept)
