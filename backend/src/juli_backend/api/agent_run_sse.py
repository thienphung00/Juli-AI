"""HTTP adapter for the agent-run event stream.

The route stays a thin handler. This module builds the response that releases
the per-shop stream slot on a clean end, a mid-stream end, and an unread body.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from juli_backend.services.agent import abuse_limits as agent_abuse_limits


class StreamSlot:
    """The per-shop SSE slot, released exactly once whichever exit comes first."""

    def __init__(self, gate: agent_abuse_limits.AbuseLimitGate, shop_id: str) -> None:
        self._gate, self._shop_id, self._released = gate, shop_id, False

    async def release(self) -> None:
        if not self._released:
            self._released = True
            await self._gate.release_stream(self._shop_id)


async def sse_stream_with_concurrency_slot(
    generator: AsyncIterator[str],
    slot: StreamSlot,
) -> AsyncIterator[str]:
    """Release the SSE concurrency slot on every exit path (ADR-075 decision 4).

    A clean end and a run terminating mid-stream both exit through ``finally``
    synchronously. A client disconnect does not: Starlette abandons the
    generator at its last ``yield`` and release waits for the async-generator
    GC finalizer, which is real but not prompt. The gate's one-hour safety TTL
    on the slot bounds that case. ``test_agent_abuse_limits_routes.py`` proves
    the cancellation path by cancelling the consuming task, the mechanism the
    legacy ASGI path actually uses.
    """
    try:
        async for chunk in generator:
            yield chunk
    finally:
        await slot.release()


def sse_response(
    generator: AsyncIterator[str],
    gate: agent_abuse_limits.AbuseLimitGate,
    shop_id: str,
) -> StreamingResponse:
    """Stream events and release the slot on every exit, including an unread body."""
    slot = StreamSlot(gate, shop_id)
    return StreamingResponse(
        sse_stream_with_concurrency_slot(generator, slot),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
        background=BackgroundTask(slot.release),
    )
