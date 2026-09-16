"""ProcessedEventsRepo — ETL ingest idempotency claims."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories._base import utc_now_naive
from juli_backend.services.etl.channels import RAW_CHANNELS
from juli_backend.services.etl.persistence.ingest.model import (
    INITIAL_EPOCH,
    IngestDedupEpoch,
    ProcessedEvent,
)

logger = logging.getLogger(__name__)


class ProcessedEventsRepo:
    """Tracks consumed ingest event IDs for idempotent ETL (#32)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(
        self,
        *,
        event_id: str,
        shop_id: uuid.UUID,
        epoch: int = INITIAL_EPOCH,
    ) -> bool:
        """Insert *event_id* for *epoch* if unseen. False when already processed.

        The claim is scoped to an epoch (#1968): the same *event_id* is
        claimable again once the channel's epoch advances, which is how a
        deliberate re-ingest of lost history is expressed without deleting the
        record of the original ingest.
        """
        stmt = select(ProcessedEvent).where(
            ProcessedEvent.event_id == event_id,
            ProcessedEvent.epoch == epoch,
        )
        result = await self._session.execute(stmt)
        if result.scalar_one_or_none() is not None:
            return False
        self._session.add(ProcessedEvent(event_id=event_id, shop_id=shop_id, epoch=epoch))
        try:
            async with self._session.begin_nested():
                await self._session.flush()
        except IntegrityError:
            return False
        return True


class IngestDedupEpochsRepo:
    """Reads and advances the per-``(shop, channel)`` dedup epoch (#1968).

    Only :meth:`advance` writes, and only an operator calls it. Nothing on the
    import, startup or migration path may move an epoch — advancing one asks
    the pipeline to re-ingest that channel's whole history, which on every
    release would be a re-ingest storm rather than a recovery.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def current(self, *, shop_id: uuid.UUID, channel: str) -> int:
        """Return the channel's epoch. Absent row ⇒ :data:`INITIAL_EPOCH`.

        Read-only by construction: a consumer that has never seen an advance
        must not create one just by looking.
        """
        stmt = select(IngestDedupEpoch.epoch).where(
            IngestDedupEpoch.shop_id == shop_id,
            IngestDedupEpoch.channel == channel,
        )
        result = await self._session.execute(stmt)
        found = result.scalar_one_or_none()
        return INITIAL_EPOCH if found is None else int(found)

    async def advance(
        self,
        *,
        shop_id: uuid.UUID,
        channel: str,
        operator: str,
        reason: str,
    ) -> int:
        """Advance *channel*'s epoch by one and record who did it and why.

        The explicit, recorded operator action of issue #1968's recovery
        procedure. Raises ``ValueError`` when unattributed: an epoch advance
        with no operator and no reason is indistinguishable from an accident,
        and this is the row that explains a re-ingest months later.

        Also raises when *channel* is not one the consumer reads
        (:data:`RAW_CHANNELS`). Returning an epoch for a channel nobody ingests
        would be a successful-looking recovery that recovers nothing.
        """
        if not operator.strip():
            raise ValueError("advancing a dedup epoch requires a named operator")
        if not reason.strip():
            raise ValueError("advancing a dedup epoch requires a recorded reason")
        if channel not in RAW_CHANNELS:
            # An unknown channel is the silent success this issue exists to
            # remove. `tiktok.order.raw` is singular and plausible; the consumer
            # reads `tiktok.orders.raw`, so a typo would return an epoch, write
            # an audit row, and recover nothing -- and the operator would have
            # every reason to believe the recovery had run.
            raise ValueError(
                f"unknown ingest channel {channel!r}: no consumer reads it, so advancing "
                "its epoch would recover nothing. Known channels: "
                + ", ".join(sorted(RAW_CHANNELS))
            )

        stmt = select(IngestDedupEpoch).where(
            IngestDedupEpoch.shop_id == shop_id,
            IngestDedupEpoch.channel == channel,
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()

        if row is None:
            previous_epoch = INITIAL_EPOCH
            row = IngestDedupEpoch(
                shop_id=shop_id,
                channel=channel,
                epoch=INITIAL_EPOCH + 1,
                advanced_by=operator,
                reason=reason,
            )
            self._session.add(row)
        else:
            previous_epoch = int(row.epoch)
            row.epoch += 1
            row.advanced_by = operator
            row.reason = reason
            row.advanced_at = utc_now_naive()

        await self._session.flush()

        # WARNING, not INFO: this is the widest-blast-radius action in the
        # module -- it asks the pipeline to re-ingest a channel's whole history
        # -- and it is rare, so it should survive a journal filtered above INFO.
        # The audit row records it; this is what someone greps at 3am.
        logger.warning(
            "etl_dedup_epoch_advanced",
            extra={
                "shop_id": str(shop_id),
                "channel": channel,
                "operator": operator,
                "reason": reason,
                "previous_epoch": previous_epoch,
                "epoch": int(row.epoch),
            },
        )
        return int(row.epoch)
