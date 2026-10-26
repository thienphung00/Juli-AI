"""The one door to OpenAI for every backend call that carries shop data (ADR-116 §5, D76).

Four call paths reach OpenAI, and all four go through :class:`OpenAIGate`: agent runs
(``services/agent/llm/openai_adapter.py``), product-image inspection
(``services/agent/vision.py``), content-analysis transcription and keyframes
(``services/content_analysis/openai_media.py``), and content scoring / content-card
drafts (through the adapter). Nothing else in ``backend/src`` may name
``api.openai.com`` -- ``tests/unit/test_llm_gate_ci_rule.py`` fails CI otherwise.

PER CALL, BEFORE ANY HTTP, the gate:

1. allows only ``/v1/responses`` and ``/v1/audio/transcriptions`` (no files, vector
   stores, assistants, threads, conversations, batches, fine-tuning or evals);
2. checks the body against the allowlisted shape and the ZDR flags, minimises it and
   works out which input kinds it carries (:mod:`.payload`);
3. requires the shop's consent for every kind present -- ``llm_processing`` (text),
   ``llm_images`` (product images), ``llm_media`` (frames / audio) -- read once per unit
   of work through ``services.consent.has_consent`` (:func:`open_gate`);
4. refuses with :class:`GateRefused` when any of that fails, and writes one
   ``llm_call_log`` row per attempt: ``refused`` (with the reason), ``sent`` (tokens,
   ``x-request-id``) or ``error``.

WHY CONSENT IS READ ONCE PER UNIT OF WORK. Image inspection is a synchronous call made
from inside a tool handler, where no async session is available; reading the three
grants when the run leg / analysis / draft is wired keeps every path on the same
answer. A withdrawal therefore takes effect at the next run leg, analysis or draft.

A CALL WITH NO GATE IS REFUSED. Every client is built with the shop's gate; a client
built without one (a missed wiring) refuses before any HTTP rather than sending
unaccounted shop data (``no_shop_gate``, logged as a warning: there is no shop to
write a row for).

ONE KEY. The key is ``OPENAI_API_KEY`` (project ``juli-client-data``); there is no key
routing. The boot checks that require it stay where they are.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config import require_env
from juli_backend.models.llm_call_log import STATUS_ERROR, STATUS_REFUSED, STATUS_SENT
from juli_backend.services.consent import has_consent
from juli_backend.services.llm_gate.call_log import (
    CallLogEntry,
    CallLogSink,
    SyncCallLogSink,
)
from juli_backend.services.llm_gate.payload import (
    LLM_IMAGES,
    LLM_SCOPES,
    OPENAI_BASE_URL,
    RESPONSES_ENDPOINT,
    TRANSCRIPTIONS_ENDPOINT,
    InspectedRequest,
    PayloadRefused,
    inspect_responses_body,
    inspect_transcription_form,
)

logger = logging.getLogger(__name__)

API_KEY_ENV_VAR = "OPENAI_API_KEY"
REQUEST_ID_HEADER = "x-request-id"
ALLOWED_ENDPOINTS = frozenset({RESPONSES_ENDPOINT, TRANSCRIPTIONS_ENDPOINT})

PURPOSE_AGENT_RUN = "agent_run"
PURPOSE_IMAGE_INSPECTION = "image_inspection"
PURPOSE_CONTENT_DRAFT = "content_draft"
PURPOSE_CONTENT_SCORING = "content_scoring"
PURPOSE_CONTENT_FRAMES = "content_frames"
PURPOSE_CONTENT_TRANSCRIPTION = "content_transcription"
PURPOSES: tuple[str, ...] = (
    PURPOSE_AGENT_RUN,
    PURPOSE_IMAGE_INSPECTION,
    PURPOSE_CONTENT_DRAFT,
    PURPOSE_CONTENT_SCORING,
    PURPOSE_CONTENT_FRAMES,
    PURPOSE_CONTENT_TRANSCRIPTION,
)
#: Purposes whose ``data:`` images are video / LIVE keyframes (``llm_media``).
FRAME_PURPOSES = frozenset({PURPOSE_CONTENT_FRAMES})

REASON_NO_GATE = "no_shop_gate"
REASON_ENDPOINT = "endpoint_not_allowed"
REASON_PURPOSE = "unknown_purpose"


class GateRefused(Exception):
    """The gate sent nothing. ``reason`` is the ``llm_call_log.refusal_reason``
    (``consent_llm_images``, ``zdr_store``, ``payload_shape``, ``no_shop_gate``...)."""

    def __init__(self, reason: str, *, purpose: str) -> None:
        super().__init__(f"OpenAI call refused ({purpose}): {reason}")
        self.reason = reason
        self.purpose = purpose

    @property
    def is_consent(self) -> bool:
        return self.reason.startswith("consent_")


def refuse_without_gate(purpose: str) -> GateRefused:
    """The refusal for a client built without a shop gate (module docstring)."""
    logger.warning("llm_gate_refused_no_shop", extra={"purpose": purpose})
    return GateRefused(REASON_NO_GATE, purpose=purpose)


@dataclass
class StreamingCall:
    """What :meth:`OpenAIGate.stream_json` yields: the open response, and the usage the
    caller sets once the stream is read (the gate logs it on exit)."""

    response: httpx.Response
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class OpenAIGate:
    """One shop's door to OpenAI for one unit of work (a run leg, an analysis, a draft).

    ``granted`` holds the shop's open OpenAI consent scopes; build it with
    :func:`open_gate`. ``sink`` / ``sync_sink`` write ``llm_call_log``; a gate without
    the sink a path needs still gates, and logs ``llm_call_log_unwritten``.
    """

    shop_id: uuid.UUID
    granted: frozenset[str]
    sink: CallLogSink | None = None
    sync_sink: SyncCallLogSink | None = None
    #: Values replaced by ``[shop]`` in every text (the shop's platform ids).
    shop_identifiers: tuple[str, ...] = field(default_factory=tuple)

    def allows(self, scope: str) -> bool:
        return scope in self.granted

    # -- checks --------------------------------------------------------------------

    def _inspect(
        self,
        *,
        purpose: str,
        endpoint: str,
        body: Mapping[str, Any],
        files: Mapping[str, Any] | None = None,
    ) -> InspectedRequest:
        if purpose not in PURPOSES:
            raise PayloadRefused(REASON_PURPOSE)
        if endpoint not in ALLOWED_ENDPOINTS:
            raise PayloadRefused(REASON_ENDPOINT)
        identifiers = (str(self.shop_id), *self.shop_identifiers)
        if endpoint == TRANSCRIPTIONS_ENDPOINT:
            inspected = inspect_transcription_form(body, files or {}, shop_identifiers=identifiers)
        else:
            inspected = inspect_responses_body(
                body,
                frames_purpose=purpose in FRAME_PURPOSES,
                images_allowed=self.allows(LLM_IMAGES),
                shop_identifiers=identifiers,
            )
        for scope in LLM_SCOPES:
            if scope in inspected.required and not self.allows(scope):
                raise PayloadRefused(f"consent_{scope}")
        if inspected.stripped_image_urls:
            logger.info(
                "llm_gate_image_urls_stripped",
                extra={
                    "shop_id": str(self.shop_id),
                    "purpose": purpose,
                    "count": inspected.stripped_image_urls,
                },
            )
        return inspected

    def _entry(
        self,
        *,
        purpose: str,
        endpoint: str,
        model: str,
        status: str,
        refusal_reason: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        request_id: str | None = None,
    ) -> CallLogEntry:
        return CallLogEntry(
            shop_id=self.shop_id,
            purpose=purpose,
            model=model,
            endpoint=endpoint,
            status=status,
            refusal_reason=refusal_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_id=request_id,
        )

    async def _write(self, entry: CallLogEntry) -> None:
        if entry.status == STATUS_REFUSED:
            logger.warning(
                "llm_gate_refused",
                extra={
                    "shop_id": str(self.shop_id),
                    "purpose": entry.purpose,
                    "reason": entry.refusal_reason,
                },
            )
        if self.sink is None:
            logger.warning("llm_call_log_unwritten", extra={"purpose": entry.purpose})
            return
        await self.sink.write(entry)

    def _write_sync(self, entry: CallLogEntry) -> None:
        if entry.status == STATUS_REFUSED:
            logger.warning(
                "llm_gate_refused",
                extra={
                    "shop_id": str(self.shop_id),
                    "purpose": entry.purpose,
                    "reason": entry.refusal_reason,
                },
            )
        if self.sync_sink is None:
            logger.warning("llm_call_log_unwritten", extra={"purpose": entry.purpose})
            return
        self.sync_sink.write_sync(entry)

    async def _prepare(
        self,
        *,
        purpose: str,
        endpoint: str,
        body: Mapping[str, Any],
        files: Mapping[str, Any] | None = None,
    ) -> InspectedRequest:
        try:
            return self._inspect(purpose=purpose, endpoint=endpoint, body=body, files=files)
        except PayloadRefused as exc:
            await self._write(
                self._entry(
                    purpose=purpose,
                    endpoint=endpoint,
                    model=str(body.get("model") or ""),
                    status=STATUS_REFUSED,
                    refusal_reason=exc.reason,
                )
            )
            raise GateRefused(exc.reason, purpose=purpose) from exc

    def _prepare_sync(
        self, *, purpose: str, endpoint: str, body: Mapping[str, Any]
    ) -> InspectedRequest:
        try:
            return self._inspect(purpose=purpose, endpoint=endpoint, body=body)
        except PayloadRefused as exc:
            self._write_sync(
                self._entry(
                    purpose=purpose,
                    endpoint=endpoint,
                    model=str(body.get("model") or ""),
                    status=STATUS_REFUSED,
                    refusal_reason=exc.reason,
                )
            )
            raise GateRefused(exc.reason, purpose=purpose) from exc

    def _outcome(
        self, *, purpose: str, endpoint: str, model: str, response: httpx.Response
    ) -> CallLogEntry:
        input_tokens, output_tokens = usage_of(response)
        return self._entry(
            purpose=purpose,
            endpoint=endpoint,
            model=model,
            status=STATUS_SENT if response.is_success else STATUS_ERROR,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_id=response.headers.get(REQUEST_ID_HEADER),
        )

    # -- HTTP ------------------------------------------------------------------------

    async def post_json(
        self,
        *,
        purpose: str,
        body: Mapping[str, Any],
        timeout: float,
        endpoint: str = RESPONSES_ENDPOINT,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = OPENAI_BASE_URL,
        extra_headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """One non-streamed JSON call; the caller maps the status / body as before."""
        inspected = await self._prepare(purpose=purpose, endpoint=endpoint, body=body)
        model = str(body.get("model") or "")
        headers = _json_headers(extra_headers)
        try:
            async with httpx.AsyncClient(
                transport=transport, base_url=base_url, timeout=timeout
            ) as client:
                response = await client.post(endpoint, json=inspected.body, headers=headers)
        except httpx.HTTPError:
            await self._write(
                self._entry(purpose=purpose, endpoint=endpoint, model=model, status=STATUS_ERROR)
            )
            raise
        await self._write(
            self._outcome(purpose=purpose, endpoint=endpoint, model=model, response=response)
        )
        return response

    @asynccontextmanager
    async def stream_json(
        self,
        *,
        purpose: str,
        body: Mapping[str, Any],
        timeout: float,
        endpoint: str = RESPONSES_ENDPOINT,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = OPENAI_BASE_URL,
    ) -> AsyncIterator[StreamingCall]:
        """A streamed JSON call. The row is written when the block exits: ``sent`` with
        the usage the caller set on the :class:`StreamingCall`, or ``error`` when the
        status was not 2xx or the block raised."""
        inspected = await self._prepare(purpose=purpose, endpoint=endpoint, body=body)
        model = str(body.get("model") or "")
        headers = _json_headers(None)
        call: StreamingCall | None = None
        completed = False
        try:
            async with httpx.AsyncClient(
                transport=transport, base_url=base_url, timeout=timeout
            ) as client:
                async with client.stream(
                    "POST", endpoint, json=inspected.body, headers=headers
                ) as response:
                    call = StreamingCall(response=response)
                    yield call
                    completed = response.is_success
        finally:
            await self._write(
                self._entry(
                    purpose=purpose,
                    endpoint=endpoint,
                    model=model,
                    status=STATUS_SENT if completed else STATUS_ERROR,
                    input_tokens=call.input_tokens if call else 0,
                    output_tokens=call.output_tokens if call else 0,
                    request_id=call.response.headers.get(REQUEST_ID_HEADER) if call else None,
                )
            )

    def post_json_sync(
        self,
        *,
        purpose: str,
        body: Mapping[str, Any],
        timeout: float,
        endpoint: str = RESPONSES_ENDPOINT,
        transport: httpx.BaseTransport | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """The synchronous form of :meth:`post_json` (image inspection runs inside a
        synchronous tool handler)."""
        inspected = self._prepare_sync(purpose=purpose, endpoint=endpoint, body=body)
        model = str(body.get("model") or "")
        headers = _json_headers(extra_headers)
        try:
            with httpx.Client(transport=transport, timeout=timeout) as client:
                response = client.post(
                    OPENAI_BASE_URL + endpoint, json=inspected.body, headers=headers
                )
        except httpx.HTTPError:
            self._write_sync(
                self._entry(purpose=purpose, endpoint=endpoint, model=model, status=STATUS_ERROR)
            )
            raise
        self._write_sync(
            self._outcome(purpose=purpose, endpoint=endpoint, model=model, response=response)
        )
        return response

    async def post_transcription(
        self,
        *,
        data: Mapping[str, Any],
        files: Mapping[str, Any],
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = OPENAI_BASE_URL,
    ) -> httpx.Response:
        """One ``/v1/audio/transcriptions`` call (multipart). This endpoint has no
        ``store`` field, so there is no ZDR flag to set or check."""
        purpose, endpoint = PURPOSE_CONTENT_TRANSCRIPTION, TRANSCRIPTIONS_ENDPOINT
        inspected = await self._prepare(purpose=purpose, endpoint=endpoint, body=data, files=files)
        model = str(data.get("model") or "")
        headers = {"Authorization": f"Bearer {require_env(API_KEY_ENV_VAR)}"}
        try:
            async with httpx.AsyncClient(
                transport=transport, base_url=base_url, timeout=timeout
            ) as client:
                response = await client.post(
                    endpoint, data=inspected.body, files=dict(files), headers=headers
                )
        except httpx.HTTPError:
            await self._write(
                self._entry(purpose=purpose, endpoint=endpoint, model=model, status=STATUS_ERROR)
            )
            raise
        await self._write(
            self._outcome(purpose=purpose, endpoint=endpoint, model=model, response=response)
        )
        return response


def _json_headers(extra: Mapping[str, str] | None) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {require_env(API_KEY_ENV_VAR)}",
        "Content-Type": "application/json",
        **dict(extra or {}),
    }


def usage_of(response: httpx.Response) -> tuple[int, int]:
    """``(input_tokens, output_tokens)`` from a JSON body's ``usage``; ``(0, 0)`` when the
    body has none (a transcription, an error, a non-JSON body)."""
    try:
        payload = response.json()
    except ValueError:
        return 0, 0
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return 0, 0

    def _int(key: str) -> int:
        value = usage.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    return _int("input_tokens"), _int("output_tokens")


async def _shop_identifiers(session: AsyncSession, shop_id: uuid.UUID) -> tuple[str, ...]:
    """The shop's platform ids, for the text scrub (own row, own scope).

    Not the shop name: a shop is often named after its brand, which is listing content
    (titles, descriptions); scrubbing it from text would feed ``[shop]`` into drafted
    copy. The name is dropped where it travels as a field (``shop_name``)."""
    from sqlalchemy import select

    from juli_backend.models.models import Shop

    row = (
        await session.execute(
            select(
                Shop.tiktok_shop_id,
                Shop.tiktok_numeric_shop_id,
                Shop.shopee_shop_id,
            ).where(Shop.id == shop_id)
        )
    ).one_or_none()
    if row is None:
        return ()
    return tuple(str(value) for value in row if value)


async def open_gate(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    sink: CallLogSink | None = None,
    sync_sink: SyncCallLogSink | None = None,
    scopes: Iterable[str] = LLM_SCOPES,
) -> OpenAIGate:
    """The shop's gate: its open OpenAI grants (``has_consent``, fail closed) and the
    platform ids scrubbed from text. The session must hold the shop's scope."""
    granted = frozenset([scope for scope in scopes if await has_consent(session, shop_id, scope)])
    return OpenAIGate(
        shop_id=shop_id,
        granted=granted,
        sink=sink,
        sync_sink=sync_sink,
        shop_identifiers=await _shop_identifiers(session, shop_id),
    )


__all__ = [
    "ALLOWED_ENDPOINTS",
    "API_KEY_ENV_VAR",
    "FRAME_PURPOSES",
    "OPENAI_BASE_URL",
    "PURPOSES",
    "PURPOSE_AGENT_RUN",
    "PURPOSE_CONTENT_DRAFT",
    "PURPOSE_CONTENT_FRAMES",
    "PURPOSE_CONTENT_SCORING",
    "PURPOSE_CONTENT_TRANSCRIPTION",
    "PURPOSE_IMAGE_INSPECTION",
    "REASON_NO_GATE",
    "GateRefused",
    "OpenAIGate",
    "StreamingCall",
    "open_gate",
    "refuse_without_gate",
    "usage_of",
]
