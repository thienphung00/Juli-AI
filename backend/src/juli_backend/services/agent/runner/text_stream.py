"""Relay a streamed model turn's text deltas as `assistant.text.delta` events
(ADR-071 amendment, D71.3 / P61-C).

The adapter hands the runner raw output-text deltas (a few characters each).
Persisting one row per provider delta would mean hundreds of INSERT + COMMIT
+ PUBLISH round trips per turn, so this relay **coalesces**: it emits one
event when at least `STREAM_DELTA_FLUSH_MIN_CHARS` characters are ready, or
when `STREAM_DELTA_FLUSH_INTERVAL_SECONDS` has passed since the last emit and
anything at all is ready. A typical nano turn (a few hundred to ~2k chars)
becomes roughly 5-40 rows.

**Outbound guard before anything leaves (ADR-070 decision 6(b)).** The final
`assistant.text` / `FinalResponse` is scanned by `guard_outbound_agent_output`
before it is recorded; a streamed preview must not get around that. Before
every emit the relay scans the WHOLE text received so far and only releases
text that ends `STREAM_GUARD_HOLDBACK_CHARS` characters short of it. So a
banned match of up to that many characters is complete -- and caught --
before its first character could have been released. On a hit (or a scan
failure, which the guard treats as a hit) the relay stops emitting for the
rest of the turn; whatever already went out was scanned clean. The run then
goes through the existing guard on the final block exactly as before.

**Previews, not the record.** The text still held back when the turn ends is
never emitted as a delta: the runner's following `assistant.text` (the
authoritative, complete text) supersedes the block's deltas on the client,
and a block with no following `assistant.text` (the turn failed or was
refused) is discarded there.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from juli_backend.services.agent.events import AssistantTextDeltaPayload
from juli_backend.services.agent.sanitize import (
    BannedPatternGuardFailure,
    guard_outbound_agent_output,
)

logger = logging.getLogger(__name__)

#: Emit once this many released characters are waiting.
STREAM_DELTA_FLUSH_MIN_CHARS = 48
#: ... or once this long has passed since the last emit (seconds).
STREAM_DELTA_FLUSH_INTERVAL_SECONDS = 0.1
#: Characters kept back from the end of the received text until the turn's
#: authoritative `assistant.text`. Longer than any literal banned phrase, so a
#: banned match is whole (and caught) before any of it is released.
STREAM_GUARD_HOLDBACK_CHARS = 64

ChunkEmitter = Callable[[AssistantTextDeltaPayload], Awaitable[None]]


class TextDeltaRelay:
    """One streamed turn's coalescing, guard-checked delta relay.

    Pass `on_delta` as the adapter's `on_text_delta`. `emitted` tells the
    runner whether any preview went out (so a `FinalResponse` turn commits
    its text with an `assistant.text`).
    """

    def __init__(
        self,
        *,
        emit_chunk: ChunkEmitter,
        clock: Callable[[], float] | None = None,
        block_id: str | None = None,
    ) -> None:
        self.block_id = block_id or uuid.uuid4().hex
        self._emit_chunk = emit_chunk
        # Looked up per call (not bound at import) so a frozen test clock applies.
        self._clock: Callable[[], float] = clock or (lambda: time.monotonic())
        self._received = ""
        self._released = 0
        self._chunks = 0
        self._last_emit_at = self._clock()
        self._stopped = False

    @property
    def emitted(self) -> bool:
        return self._chunks > 0

    @property
    def stopped(self) -> bool:
        """True once the outbound guard refused the text received so far."""
        return self._stopped

    async def on_delta(self, text: str) -> None:
        if self._stopped or not text:
            return
        self._received += text
        release_to = len(self._received) - STREAM_GUARD_HOLDBACK_CHARS
        ready = release_to - self._released
        if ready <= 0:
            return
        now = self._clock()
        if (
            ready < STREAM_DELTA_FLUSH_MIN_CHARS
            and now - self._last_emit_at < STREAM_DELTA_FLUSH_INTERVAL_SECONDS
        ):
            return
        try:
            guard_outbound_agent_output({"content": self._received})
        except BannedPatternGuardFailure:
            self._stopped = True
            logger.warning(
                "assistant_text_stream_stopped_by_guard",
                extra={"block_id": self.block_id, "chunks_emitted": self._chunks},
            )
            return
        payload = AssistantTextDeltaPayload(
            block_id=self.block_id,
            chunk_index=self._chunks,
            text=self._received[self._released : release_to],
        )
        await self._emit_chunk(payload)
        self._released = release_to
        self._chunks += 1
        self._last_emit_at = now


__all__ = [
    "STREAM_DELTA_FLUSH_INTERVAL_SECONDS",
    "STREAM_DELTA_FLUSH_MIN_CHARS",
    "STREAM_GUARD_HOLDBACK_CHARS",
    "TextDeltaRelay",
]
