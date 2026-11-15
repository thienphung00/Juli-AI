"""P100 S2-F2: "Đã làm" on the reviewer's sample shop, without a Juli Connector.

On a real shop the Connector reads Seller Centre back after the seller saves, and the verification
job writes ``verified`` / ``mismatch`` / ``not_seen``. The sample shop has no Connector and no
Seller Centre, so a card would stop at "Đã điền · chờ bạn lưu" and never reach Khớp or Đo lường.
Here, for the sample pin only:

- :func:`sample_voucher_id` gives a sample voucher a code of its own (there is no Seller Centre
  voucher to copy one from);
- :func:`simulate_readback` writes the ``verified`` event the read-back would write, observing what
  the card expected, through the real :func:`verification.record_verdict` (same event, same
  dedup key, so measurement starts exactly as on a real shop).

Nothing leaves Juli. The reviewer's sample shop rows only (the caller checks the pin).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_events import EVENT_VERIFIED
from juli_backend.services.card_events import verification

#: The sample shop's vouchers take codes in this range (the generator's voucher is 9300000000001).
SAMPLE_VOUCHER_PREFIX = "93"


def sample_voucher_id(card_id: uuid.UUID) -> str:
    """A stable 13-digit sample voucher code for a card (same card, same code)."""
    return SAMPLE_VOUCHER_PREFIX + f"{card_id.int % 10**11:011d}"


async def simulate_readback(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID, now: datetime
) -> int:
    """Write ``verified`` for the card's pending executed changes (no commit). Returns how many."""
    written = 0
    for change in await verification.pending_changes(session, shop_id, now):
        if change.card_id != card_id:
            continue
        verdict = verification.Verdict(EVENT_VERIFIED, dict(change.expected), change.executed_at)
        if await verification.record_verdict(session, change, verdict, now=now):
            written += 1
    return written
