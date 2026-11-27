"""The gate's doors to Anthropic Messages and TypeSafe System One (ADR-116 §5 amendment,
jev-router grill J1 / J9 / J10).

The analytics agent (the Juli tab) parses questions and writes answers with Claude
(``POST https://api.anthropic.com/v1/messages``, plain and streamed) and routes them with
TypeSafe's Jev (``POST https://api.typesafe.ai/v1/systemone``). Both carry shop-derived
text, so both go through the same :class:`~.gate.OpenAIGate` object as the OpenAI paths
and get the same guarantees, BEFORE ANY HTTP:

1. **Purpose and endpoint allowlist.** ``agent_chat_parse`` / ``agent_chat_write`` may
   reach only Anthropic ``/v1/messages``; ``agent_chat_route`` only TypeSafe
   ``/v1/systemone`` (:data:`VENDOR_ENDPOINTS`). Anything else: ``unknown_purpose`` /
   ``endpoint_not_allowed``.
2. **Shape allowlist (fail closed, ``payload_shape``).**

   - Messages: top-level keys :data:`MESSAGES_KEYS` only (no ``temperature``: current
     Claude models reject non-default sampling; no ``metadata``, ``container``,
     ``mcp_servers``...). Roles ``user`` / ``assistant``. Content blocks ``text``,
     ``tool_use``, ``tool_result`` only -- no image or document block, so no image ever
     leaves on this path. ``system`` is a string or a list of ``text`` blocks.
     ``output_config`` and ``thinking`` must be objects and pass as they are (config, not
     data), like ``tools`` (schemas) and ``tool_choice``. ``tool_use.id`` / ``name`` and
     ``tool_result.tool_use_id`` must be strings, ``is_error`` a bool, ``stop_sequences``
     a list of strings (minimised).
   - System One: exactly ``{model, state, questions}`` (no ``assets``); every question
     is ``choice`` (non-empty ``criteria``) or ``noul`` (``criteria`` absent or
     ``{true, false}``) with keys ``type``, ``instructions``, ``criteria`` only.

3. **Consent.** Every call on these paths is text, so it needs ``llm_processing``
   (``consent_llm_processing`` otherwise). Neither vendor keeps provider-side state on
   these endpoints, so there is no ZDR flag to check (legal scope: J9, owner).
4. **Minimisation**, the same cleaner as the OpenAI paths (:mod:`.payload`):
   ``deidentify_text``, forbidden keys dropped at any depth (JSON text and structured
   values such as ``tool_use.input`` and the System One ``state``), the shop's ids replaced
   by ``[shop]``, and every image URL in text replaced by ``[ảnh đã ẩn]`` -- images never
   go to these vendors, whatever the shop granted. Choice *labels* (criteria keys) are
   kept: the answer names them.
5. **Key.** ``ANTHROPIC_API_KEY`` / ``TYPESAFE_API_KEY`` through ``require_env``; absent
   or blank -> ``GateRefused("unconfigured")``, never a crash.
6. **One ``llm_call_log`` row per attempt** with ``project`` = ``anthropic`` /
   ``typesafe`` (so the OpenAI ``juli-client-data`` monthly reconciliation stays
   intact), the model, the endpoint, the usage and the provider's request id
   (``request-id`` / ``x-typesafe-request-id``). Refused / sent / error as for OpenAI.

FAILURES. A non-2xx status, a transport error, a stream ``error`` event or a stream that
ends without ``message_stop``, and a System One body without ``answers`` are logged as
``error`` and raised as :class:`GateCallFailed` (``status_code`` and ``retry-after`` kept
for the caller's 429 / 529 fallback, J11). No response body is copied into the exception.

Plain ``httpx``: the backend never imports a vendor SDK (J1 REST fallback).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx

from juli_backend.core.config import require_env
from juli_backend.models.llm_call_log import STATUS_ERROR, STATUS_REFUSED, STATUS_SENT
from juli_backend.services.llm_gate.call_log import CallLogEntry
from juli_backend.services.llm_gate.gate import (
    REASON_ENDPOINT,
    REASON_PURPOSE,
    GateRefused,
    OpenAIGate,
)
from juli_backend.services.llm_gate.payload import (
    LLM_PROCESSING,
    REASON_SHAPE,
    PayloadRefused,
    _TextCleaner,
    drop_forbidden_keys,
)

logger = logging.getLogger(__name__)

ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_MESSAGES_ENDPOINT = "/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_KEY_ENV = "ANTHROPIC_API_KEY"
ANTHROPIC_REQUEST_ID_HEADER = "request-id"

TYPESAFE_BASE_URL = "https://api.typesafe.ai"
TYPESAFE_SYSTEM_ONE_ENDPOINT = "/v1/systemone"
TYPESAFE_KEY_ENV = "TYPESAFE_API_KEY"
TYPESAFE_REQUEST_ID_HEADER = "x-typesafe-request-id"

#: ``(base URL, path)`` pairs the vendor doors may reach.
VENDOR_ENDPOINTS = frozenset(
    {
        (ANTHROPIC_BASE_URL, ANTHROPIC_MESSAGES_ENDPOINT),
        (TYPESAFE_BASE_URL, TYPESAFE_SYSTEM_ONE_ENDPOINT),
    }
)

#: ``llm_call_log.project`` for these rows (OpenAI rows keep ``juli-client-data``).
PROJECT_ANTHROPIC = "anthropic"
PROJECT_TYPESAFE = "typesafe"

PURPOSE_AGENT_CHAT_PARSE = "agent_chat_parse"
PURPOSE_AGENT_CHAT_WRITE = "agent_chat_write"
PURPOSE_AGENT_CHAT_ROUTE = "agent_chat_route"
ANTHROPIC_PURPOSES = frozenset({PURPOSE_AGENT_CHAT_PARSE, PURPOSE_AGENT_CHAT_WRITE})
TYPESAFE_PURPOSES = frozenset({PURPOSE_AGENT_CHAT_ROUTE})
VENDOR_PURPOSES: tuple[str, ...] = (
    PURPOSE_AGENT_CHAT_PARSE,
    PURPOSE_AGENT_CHAT_WRITE,
    PURPOSE_AGENT_CHAT_ROUTE,
)

REASON_UNCONFIGURED = "unconfigured"
FAIL_HTTP_STATUS = "http_status"
FAIL_TRANSPORT = "transport"
FAIL_STREAM = "stream_error"
FAIL_BAD_RESPONSE = "bad_response"

MESSAGES_KEYS = frozenset(
    {
        "model",
        "system",
        "messages",
        "max_tokens",
        "stream",
        "tools",
        "tool_choice",
        "stop_sequences",
        "output_config",
        "thinking",
    }
)
SYSTEM_ONE_KEYS = frozenset({"model", "state", "questions"})
_ROLES = frozenset({"user", "assistant"})
_QUESTION_KEYS = frozenset({"type", "instructions", "criteria"})
_NOUL_CRITERIA_KEYS = frozenset({"true", "false"})


class GateCallFailed(Exception):
    """The request was sent (or attempted) and failed; the row says ``error``.

    ``reason``: ``http_status`` / ``transport`` / ``stream_error`` / ``bad_response``.
    """

    def __init__(
        self,
        reason: str,
        *,
        provider: str,
        purpose: str,
        status_code: int | None = None,
        retry_after: str | None = None,
        error_text: str | None = None,
    ) -> None:
        detail = f" {status_code}" if status_code is not None else ""
        said = f": {error_text}" if error_text else ""
        super().__init__(f"{provider} call failed ({purpose}): {reason}{detail}{said}")
        self.reason = reason
        #: the provider's own error, short and redacted (:func:`redacted_error_text`)
        self.error_text = error_text
        self.provider = provider
        self.purpose = purpose
        self.status_code = status_code
        self.retry_after = retry_after


#: the longest provider error kept (log line / exception text)
ERROR_TEXT_MAX = 300
_QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
_SECRET = re.compile(r"(sk-[\w-]+|bearer\s+\S+|x-api-key\S*)", re.I)
_DIGITS = re.compile(r"\d{3,}")


def redacted_error_text(
    response: httpx.Response | None, identifiers: tuple[str, ...] = ()
) -> str | None:
    """The provider's error body, safe to log (#112): the ``error.type`` / ``message`` of a JSON
    body (else the raw text), with every quoted value, key-like token, shop identifier and run of
    3+ digits masked, whitespace collapsed, at most :data:`ERROR_TEXT_MAX` characters. A quoted
    value may echo the request (shop data), so none is kept; the field paths and the reason stay.
    """
    if response is None:
        return None
    try:
        raw = response.text
    except httpx.ResponseNotRead:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        err = payload.get("error", payload)
        if isinstance(err, dict):
            bits = [str(err.get(k)) for k in ("type", "message", "detail") if err.get(k)]
            raw = " ".join(bits) or raw
        elif isinstance(err, str):
            raw = err
    text = raw
    for ident in identifiers:
        if ident:
            text = text.replace(ident, "[shop]")
    text = _SECRET.sub("[key]", text)
    text = _QUOTED.sub("…", text)
    text = _DIGITS.sub("#", text)
    text = " ".join(text.split())
    return text[:ERROR_TEXT_MAX] or None


@dataclass
class Usage:
    """Tokens of one call, for cost logging (``input_tokens``, ``output_tokens``)."""

    input_tokens: int = 0
    output_tokens: int = 0


# -- pure checks ------------------------------------------------------------------------


def _cleaner(shop_identifiers: tuple[str, ...]) -> _TextCleaner:
    return _TextCleaner(images_allowed=False, shop_identifiers=shop_identifiers)


def _clean_value(value: Any, cleaner: _TextCleaner) -> Any:
    """A structured value (JSON-like) minimised: forbidden keys dropped, every string
    cleaned."""
    value = drop_forbidden_keys(value)
    if isinstance(value, dict):
        return {k: _clean_value(v, cleaner) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_value(v, cleaner) for v in value]
    if isinstance(value, str):
        return cleaner.clean(value)
    return value


def _text_block(block: Any, cleaner: _TextCleaner) -> dict[str, Any]:
    if (
        not isinstance(block, Mapping)
        or block.get("type") != "text"
        or set(block) - {"type", "text"}
        or not isinstance(block.get("text"), str)
    ):
        raise PayloadRefused(REASON_SHAPE)
    return {"type": "text", "text": cleaner.clean(block["text"])}


def _content_block(block: Any, cleaner: _TextCleaner) -> dict[str, Any]:
    if not isinstance(block, Mapping):
        raise PayloadRefused(REASON_SHAPE)
    kind = block.get("type")
    if kind == "text":
        return _text_block(block, cleaner)
    if kind == "tool_use":
        if (
            set(block) - {"type", "id", "name", "input"}
            or not isinstance(block.get("input"), Mapping)
            or not isinstance(block.get("id"), str)
            or not isinstance(block.get("name"), str)
        ):
            raise PayloadRefused(REASON_SHAPE)
        return {**block, "input": _clean_value(dict(block["input"]), cleaner)}
    if kind == "tool_result":
        if (
            set(block) - {"type", "tool_use_id", "content", "is_error"}
            or not isinstance(block.get("tool_use_id"), str)
            or not isinstance(block.get("is_error", False), bool)
        ):
            raise PayloadRefused(REASON_SHAPE)
        content = block.get("content", "")
        if isinstance(content, str):
            cleaned: Any = cleaner.clean(content)
        elif isinstance(content, list):
            cleaned = [_text_block(part, cleaner) for part in content]
        else:
            raise PayloadRefused(REASON_SHAPE)
        return {**block, "content": cleaned}
    raise PayloadRefused(REASON_SHAPE)


def inspect_messages_body(
    body: Mapping[str, Any], *, shop_identifiers: tuple[str, ...]
) -> dict[str, Any]:
    """Check and minimise an Anthropic Messages body (module docstring)."""
    if set(body) - MESSAGES_KEYS:
        raise PayloadRefused(REASON_SHAPE)
    if not isinstance(body.get("model"), str) or not body["model"]:
        raise PayloadRefused(REASON_SHAPE)
    max_tokens = body.get("max_tokens")
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool):
        raise PayloadRefused(REASON_SHAPE)
    for key in ("output_config", "thinking", "tool_choice"):
        if key in body and not isinstance(body[key], Mapping):
            raise PayloadRefused(REASON_SHAPE)
    if "tools" in body and not isinstance(body["tools"], list):
        raise PayloadRefused(REASON_SHAPE)
    stops = body.get("stop_sequences")
    if stops is not None and (
        not isinstance(stops, list) or not all(isinstance(stop, str) for stop in stops)
    ):
        raise PayloadRefused(REASON_SHAPE)
    cleaner = _cleaner(shop_identifiers)
    out = dict(body)
    if stops is not None:
        out["stop_sequences"] = [cleaner.clean(stop) for stop in stops]
    system = body.get("system")
    if system is not None:
        if isinstance(system, str):
            out["system"] = cleaner.clean(system)
        elif isinstance(system, list):
            out["system"] = [_text_block(block, cleaner) for block in system]
        else:
            raise PayloadRefused(REASON_SHAPE)
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise PayloadRefused(REASON_SHAPE)
    cleaned_messages = []
    for message in messages:
        if (
            not isinstance(message, Mapping)
            or set(message) - {"role", "content"}
            or message.get("role") not in _ROLES
        ):
            raise PayloadRefused(REASON_SHAPE)
        content = message.get("content")
        if isinstance(content, str):
            cleaned_content: Any = cleaner.clean(content)
        elif isinstance(content, list):
            cleaned_content = [_content_block(block, cleaner) for block in content]
        else:
            raise PayloadRefused(REASON_SHAPE)
        cleaned_messages.append({"role": message["role"], "content": cleaned_content})
    out["messages"] = cleaned_messages
    return out


def _question(question: Any, cleaner: _TextCleaner) -> dict[str, Any]:
    if not isinstance(question, Mapping) or set(question) - _QUESTION_KEYS:
        raise PayloadRefused(REASON_SHAPE)
    kind = question.get("type")
    out: dict[str, Any] = {"type": kind}
    if question.get("instructions") is not None:
        out["instructions"] = _clean_value(question["instructions"], cleaner)
    criteria = question.get("criteria")
    if kind == "choice":
        if not isinstance(criteria, Mapping) or not criteria:
            raise PayloadRefused(REASON_SHAPE)
    elif kind == "noul":
        if criteria is not None and (
            not isinstance(criteria, Mapping) or set(criteria) - _NOUL_CRITERIA_KEYS
        ):
            raise PayloadRefused(REASON_SHAPE)
    else:
        raise PayloadRefused(REASON_SHAPE)
    if criteria is not None:
        out["criteria"] = {
            str(label): (None if text is None else _clean_value(text, cleaner))
            for label, text in criteria.items()
        }
    return out


def inspect_system_one_body(
    body: Mapping[str, Any], *, shop_identifiers: tuple[str, ...]
) -> dict[str, Any]:
    """Check and minimise a System One body (module docstring)."""
    if set(body) != SYSTEM_ONE_KEYS:
        raise PayloadRefused(REASON_SHAPE)
    model, state, questions = body["model"], body["state"], body["questions"]
    if not isinstance(model, str) or not model:
        raise PayloadRefused(REASON_SHAPE)
    if not isinstance(state, str | dict | list):
        raise PayloadRefused(REASON_SHAPE)
    if not isinstance(questions, Mapping) or not questions:
        raise PayloadRefused(REASON_SHAPE)
    cleaner = _cleaner(shop_identifiers)
    return {
        "model": model,
        "state": _clean_value(state, cleaner),
        "questions": {str(name): _question(q, cleaner) for name, q in questions.items()},
    }


# -- the doors --------------------------------------------------------------------------


@dataclass
class _Call:
    """One call attempt; it writes exactly one ``llm_call_log`` row (the first wins)."""

    gate: OpenAIGate
    provider: str
    purpose: str
    endpoint: str
    model: str
    written: bool = False

    def entry(
        self,
        status: str,
        *,
        refusal_reason: str | None = None,
        usage: Usage | None = None,
        request_id: str | None = None,
    ) -> CallLogEntry:
        return CallLogEntry(
            shop_id=self.gate.shop_id,
            purpose=self.purpose,
            model=self.model,
            endpoint=self.endpoint,
            status=status,
            project=self.provider,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            request_id=request_id,
            refusal_reason=refusal_reason,
        )

    async def write(self, entry: CallLogEntry) -> None:
        if self.written:
            return
        self.written = True
        await self.gate._write(entry)

    async def refuse(self, reason: str) -> GateRefused:
        await self.write(self.entry(STATUS_REFUSED, refusal_reason=reason))
        return GateRefused(reason, purpose=self.purpose)

    async def failed(
        self,
        reason: str,
        *,
        usage: Usage | None = None,
        response: httpx.Response | None = None,
        request_id_header: str,
    ) -> GateCallFailed:
        await self.write(
            self.entry(
                STATUS_ERROR,
                usage=usage,
                request_id=response.headers.get(request_id_header) if response else None,
            )
        )
        error_text = (
            redacted_error_text(response, (str(self.gate.shop_id), *self.gate.shop_identifiers))
            if reason == FAIL_HTTP_STATUS
            else None
        )
        status = response.status_code if response is not None else None
        logger.warning(
            "llm_gate_call_failed",
            extra={
                "provider": self.provider,
                "purpose": self.purpose,
                "reason": reason,
                "status_code": status,
                "error_text": error_text,
            },
        )
        return GateCallFailed(
            reason,
            provider=self.provider,
            purpose=self.purpose,
            status_code=status,
            retry_after=response.headers.get("retry-after") if response is not None else None,
            error_text=error_text,
        )


async def _prepare(
    call: _Call,
    *,
    purposes: frozenset[str],
    base_url: str,
    key_env: str,
    inspect: Any,
    body: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    """Purpose, endpoint, shape, consent, key -- in that order; the body to send and the
    key, or a refusal (row written)."""
    if call.purpose not in purposes:
        raise await call.refuse(REASON_PURPOSE)
    if (base_url, call.endpoint) not in VENDOR_ENDPOINTS:
        raise await call.refuse(REASON_ENDPOINT)
    identifiers = (str(call.gate.shop_id), *call.gate.shop_identifiers)
    try:
        cleaned: dict[str, Any] = inspect(body, shop_identifiers=identifiers)
    except PayloadRefused as exc:
        raise await call.refuse(exc.reason) from exc
    if not call.gate.allows(LLM_PROCESSING):
        raise await call.refuse(f"consent_{LLM_PROCESSING}")
    try:
        key = require_env(key_env)
    except RuntimeError:
        raise await call.refuse(REASON_UNCONFIGURED) from None
    return cleaned, key


def _anthropic_headers(key: str) -> dict[str, str]:
    return {
        "x-api-key": key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }


def _usage(payload: Any) -> Usage:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return Usage()

    def _int(key: str) -> int:
        value = usage.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    return Usage(input_tokens=_int("input_tokens"), output_tokens=_int("output_tokens"))


async def _post(
    call: _Call,
    *,
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
    transport: httpx.AsyncBaseTransport | None,
    request_id_header: str,
) -> tuple[dict[str, Any], Usage]:
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            response = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise await call.failed(FAIL_TRANSPORT, request_id_header=request_id_header) from exc
    if not response.is_success:
        raise await call.failed(
            FAIL_HTTP_STATUS, response=response, request_id_header=request_id_header
        )
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        raise await call.failed(
            FAIL_BAD_RESPONSE, response=response, request_id_header=request_id_header
        )
    usage = _usage(payload)
    await call.write(
        call.entry(STATUS_SENT, usage=usage, request_id=response.headers.get(request_id_header))
    )
    return payload, usage


async def anthropic_messages(
    gate: OpenAIGate,
    *,
    purpose: str,
    body: Mapping[str, Any],
    timeout: float,
    endpoint: str = ANTHROPIC_MESSAGES_ENDPOINT,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[dict[str, Any], Usage]:
    """One non-streamed Messages call: the response JSON and its usage."""
    call = _Call(gate, PROJECT_ANTHROPIC, purpose, endpoint, str(body.get("model") or ""))
    cleaned, key = await _prepare(
        call,
        purposes=ANTHROPIC_PURPOSES,
        base_url=ANTHROPIC_BASE_URL,
        key_env=ANTHROPIC_KEY_ENV,
        inspect=inspect_messages_body,
        body=body,
    )
    return await _post(
        call,
        url=ANTHROPIC_BASE_URL + endpoint,
        body={**cleaned, "stream": False},
        headers=_anthropic_headers(key),
        timeout=timeout,
        transport=transport,
        request_id_header=ANTHROPIC_REQUEST_ID_HEADER,
    )


class AnthropicStream:
    """The text deltas of one streamed Messages call (``async for text in stream``);
    ``usage`` holds the tokens seen so far (complete after the iteration ends)."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.usage = Usage()
        self.completed = False
        self.failed = False

    def __aiter__(self) -> AsyncIterator[str]:
        return self._texts()

    async def _texts(self) -> AsyncIterator[str]:
        async for line in self._response.aiter_lines():
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "message_start":
                message = event.get("message")
                started = _usage(message)
                self.usage.input_tokens = started.input_tokens
                self.usage.output_tokens = started.output_tokens
            elif kind == "content_block_delta":
                delta = event.get("delta")
                if isinstance(delta, dict) and delta.get("type") == "text_delta":
                    text = delta.get("text")
                    if isinstance(text, str) and text:
                        yield text
            elif kind == "message_delta":
                final = event.get("usage")
                if isinstance(final, dict):
                    if isinstance(final.get("output_tokens"), int):
                        self.usage.output_tokens = final["output_tokens"]
                    if isinstance(final.get("input_tokens"), int) and final["input_tokens"]:
                        self.usage.input_tokens = final["input_tokens"]
            elif kind == "message_stop":
                self.completed = True
                return
            elif kind == "error":
                self.failed = True
                raise _StreamBroken
        self.failed = True
        raise _StreamBroken


class _StreamBroken(Exception):
    """Internal: the stream sent ``error`` or ended without ``message_stop``."""


@asynccontextmanager
async def anthropic_stream(
    gate: OpenAIGate,
    *,
    purpose: str,
    body: Mapping[str, Any],
    timeout: float,
    endpoint: str = ANTHROPIC_MESSAGES_ENDPOINT,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[AnthropicStream]:
    """A streamed Messages call::

        async with anthropic_stream(gate, purpose=..., body=..., timeout=...) as stream:
            async for text in stream:
                ...
        stream.usage

    The row is written once, when the block exits: ``sent`` when the stream reached
    ``message_stop``, ``error`` otherwise (error status, error event, cut-off stream, or
    a block left early). An error status raises :class:`GateCallFailed` before the
    block runs; a broken stream raises it from the iteration."""
    call = _Call(gate, PROJECT_ANTHROPIC, purpose, endpoint, str(body.get("model") or ""))
    cleaned, key = await _prepare(
        call,
        purposes=ANTHROPIC_PURPOSES,
        base_url=ANTHROPIC_BASE_URL,
        key_env=ANTHROPIC_KEY_ENV,
        inspect=inspect_messages_body,
        body=body,
    )
    header = ANTHROPIC_REQUEST_ID_HEADER
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            async with client.stream(
                "POST",
                ANTHROPIC_BASE_URL + endpoint,
                json={**cleaned, "stream": True},
                headers=_anthropic_headers(key),
            ) as response:
                if not response.is_success:
                    await response.aread()
                    raise await call.failed(
                        FAIL_HTTP_STATUS, response=response, request_id_header=header
                    )
                stream = AnthropicStream(response)
                try:
                    yield stream
                except _StreamBroken:
                    raise await call.failed(
                        FAIL_STREAM, usage=stream.usage, response=None, request_id_header=header
                    ) from None
                except httpx.HTTPError as exc:
                    raise await call.failed(
                        FAIL_TRANSPORT,
                        usage=stream.usage,
                        response=None,
                        request_id_header=header,
                    ) from exc
                except BaseException:
                    await call.write(
                        call.entry(
                            STATUS_ERROR,
                            usage=stream.usage,
                            request_id=response.headers.get(header),
                        )
                    )
                    raise
                await call.write(
                    call.entry(
                        STATUS_SENT if stream.completed else STATUS_ERROR,
                        usage=stream.usage,
                        request_id=response.headers.get(header),
                    )
                )
    except httpx.HTTPError as exc:
        raise await call.failed(FAIL_TRANSPORT, request_id_header=header) from exc


async def typesafe_system_one(
    gate: OpenAIGate,
    *,
    purpose: str,
    model: str,
    state: Any,
    questions: Mapping[str, Any],
    timeout: float,
    endpoint: str = TYPESAFE_SYSTEM_ONE_ENDPOINT,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[dict[str, dict[str, Any]], Usage]:
    """One System One call: the answers keyed by question name, and the usage."""
    call = _Call(gate, PROJECT_TYPESAFE, purpose, endpoint, str(model or ""))
    body = {"model": model, "state": state, "questions": questions}
    cleaned, key = await _prepare(
        call,
        purposes=TYPESAFE_PURPOSES,
        base_url=TYPESAFE_BASE_URL,
        key_env=TYPESAFE_KEY_ENV,
        inspect=inspect_system_one_body,
        body=body,
    )
    header = TYPESAFE_REQUEST_ID_HEADER
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            response = await client.post(
                TYPESAFE_BASE_URL + endpoint,
                json=cleaned,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise await call.failed(FAIL_TRANSPORT, request_id_header=header) from exc
    if not response.is_success:
        raise await call.failed(FAIL_HTTP_STATUS, response=response, request_id_header=header)
    try:
        payload = response.json()
    except ValueError:
        payload = None
    answers = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(answers, dict) or not all(isinstance(a, dict) for a in answers.values()):
        raise await call.failed(FAIL_BAD_RESPONSE, response=response, request_id_header=header)
    usage = _usage(payload)
    await call.write(call.entry(STATUS_SENT, usage=usage, request_id=response.headers.get(header)))
    return answers, usage


__all__ = [
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_KEY_ENV",
    "ANTHROPIC_MESSAGES_ENDPOINT",
    "ANTHROPIC_PURPOSES",
    "MESSAGES_KEYS",
    "PROJECT_ANTHROPIC",
    "PROJECT_TYPESAFE",
    "PURPOSE_AGENT_CHAT_PARSE",
    "PURPOSE_AGENT_CHAT_ROUTE",
    "PURPOSE_AGENT_CHAT_WRITE",
    "REASON_UNCONFIGURED",
    "SYSTEM_ONE_KEYS",
    "TYPESAFE_BASE_URL",
    "TYPESAFE_KEY_ENV",
    "TYPESAFE_PURPOSES",
    "TYPESAFE_SYSTEM_ONE_ENDPOINT",
    "VENDOR_ENDPOINTS",
    "VENDOR_PURPOSES",
    "AnthropicStream",
    "GateCallFailed",
    "Usage",
    "anthropic_messages",
    "anthropic_stream",
    "inspect_messages_body",
    "inspect_system_one_body",
    "typesafe_system_one",
]
