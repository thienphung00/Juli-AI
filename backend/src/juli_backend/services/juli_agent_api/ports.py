"""The engine's ``LLMPort`` (Anthropic Messages) and ``JevPort`` (TypeSafe System One) on T2.

T2 (``services.llm_gate``) owns the doors: allowlists, consent, minimisation, one
``llm_call_log`` row per attempt. These adapters own what the contract leaves to T3:

- the request shapes (a forced tool call for ``parse``; plain / streamed text for the writer);
- retries (jev-router grill J11): an attempt that failed with 408 / 409 / 429 / 5xx / 529, a
  transport error or a broken stream is tried again, at most twice (three attempts); a router
  (Jev) 400 is tried once more (#112), with a
  short backoff that honours ``retry-after`` up to :data:`MAX_BACKOFF_S`. A stream is retried
  only before its first text; after that the failure is the run's.
- the final failure: :class:`LLMUnavailable` (writer / parse; the run answers ``error``, "Juli
  đang gặp sự cố", ``busy`` when the vendor was overloaded) and :class:`JevUnavailable` (the
  runner answers with the template buttons as a ``needs_choice``).

Models come from the environment (``JULI_AGENT_PARSE_MODEL`` / ``_WRITE_MODEL`` /
``_JEV_MODEL``) with the experiment's defaults.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.analytics_agent.types import Usage
from juli_backend.services.juli_agent_api import config

logger = logging.getLogger(__name__)

PARSE_MODEL_ENV = "JULI_AGENT_PARSE_MODEL"
WRITE_MODEL_ENV = "JULI_AGENT_WRITE_MODEL"
JEV_MODEL_ENV = "JULI_AGENT_JEV_MODEL"
DEFAULT_PARSE_MODEL = "claude-haiku-5-5"
DEFAULT_WRITE_MODEL = "claude-haiku-5-5"
DEFAULT_JEV_MODEL = "jev-latest"

PARSE_MAX_TOKENS = 2000
WRITE_MAX_TOKENS = 3000
AGENT_MAX_TOKENS = 1500
TIMEOUT_S = 60.0
RETRIES = 2
BASE_BACKOFF_S = 0.5
MAX_BACKOFF_S = 8.0
RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504, 529})
BUSY_STATUS = frozenset({429, 529})


class LLMUnavailable(RuntimeError):
    """The writer / parser call failed after its retries (or the gate refused it)."""

    def __init__(self, message: str, *, busy: bool = False) -> None:
        super().__init__(message)
        self.busy = busy


class JevUnavailable(RuntimeError):
    """The router call failed after its retries (or the gate refused it)."""


def _model(env: str, default: str) -> str:
    return os.environ.get(env, "").strip() or default


def _tokens(raw: Any) -> tuple[int, int]:
    """(input, output) tokens of the gate's `Usage` (tokens only, no cost); 0 when it is missing."""
    return int(getattr(raw, "input_tokens", 0) or 0), int(getattr(raw, "output_tokens", 0) or 0)


def llm_usage(model: str, raw: Any) -> Usage:
    """The engine's `Usage` (with `cost_usd`) from the gate's token counts and the price table."""
    i, o = _tokens(raw)
    return Usage(input_tokens=i, output_tokens=o, cost_usd=config.llm_cost_usd(model, i, o))


def jev_usage(raw: Any) -> Usage:
    i, o = _tokens(raw)
    return Usage(input_tokens=i, output_tokens=o, cost_usd=config.jev_cost_usd(i))


@dataclass
class Vendors:
    """T2's door functions (``llm_gate``); a test passes fakes."""

    messages: Callable[..., Awaitable[tuple[dict[str, Any], Any]]]
    stream: Callable[..., Any]
    system_one: Callable[..., Awaitable[tuple[dict[str, dict[str, Any]], Any]]]
    call_failed: type[BaseException]
    refused: type[BaseException]
    purpose_parse: str = "agent_chat_parse"
    purpose_write: str = "agent_chat_write"
    purpose_route: str = "agent_chat_route"
    sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep)


def gate_vendors() -> Vendors:
    # by name: T2's doors land in the batch beside this track (mypy passes before and after)
    llm_gate: Any = importlib.import_module("juli_backend.services.llm_gate")

    return Vendors(
        messages=llm_gate.anthropic_messages,
        stream=llm_gate.anthropic_stream,
        system_one=llm_gate.typesafe_system_one,
        call_failed=llm_gate.GateCallFailed,
        refused=llm_gate.GateRefused,
        purpose_parse=llm_gate.PURPOSE_AGENT_CHAT_PARSE,
        purpose_write=llm_gate.PURPOSE_AGENT_CHAT_WRITE,
        purpose_route=llm_gate.PURPOSE_AGENT_CHAT_ROUTE,
    )


def _retryable(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if status is None:  # transport error, broken stream
        return getattr(exc, "reason", None) != "bad_response"
    return int(status) in RETRYABLE_STATUS


def _status(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    return int(status) if status is not None else None


def _busy(exc: BaseException) -> bool:
    return getattr(exc, "status_code", None) in BUSY_STATUS


def _backoff(exc: BaseException, attempt: int) -> float:
    raw = getattr(exc, "retry_after", None)
    try:
        wanted = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        wanted = None
    delay = wanted if wanted is not None else BASE_BACKOFF_S * (2**attempt)
    return max(0.0, min(delay, MAX_BACKOFF_S))


def _texts(response: Mapping[str, Any]) -> str:
    return "".join(
        str(b.get("text", ""))
        for b in response.get("content") or []
        if isinstance(b, Mapping) and b.get("type") == "text"
    )


def _tool_input(response: Mapping[str, Any], name: str) -> dict[str, Any] | None:
    for block in response.get("content") or []:
        if isinstance(block, Mapping) and block.get("type") == "tool_use":
            if block.get("name") == name and isinstance(block.get("input"), Mapping):
                return dict(block["input"])
    return None


class GateLLM:
    """``LLMPort``: ``parse`` (forced tool call), ``text`` and ``stream_text`` (the writer)."""

    def __init__(self, gate: Any, vendors: Vendors) -> None:
        self._gate = gate
        self._v = vendors

    def _body(self, model: str, system: str, user: str, max_tokens: int) -> dict[str, Any]:
        return {
            "model": model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": max_tokens,
        }

    async def _call(self, purpose: str, body: dict[str, Any]) -> tuple[dict[str, Any], Any]:
        for attempt in range(RETRIES + 1):
            try:
                return await self._v.messages(
                    self._gate, purpose=purpose, body=body, timeout=TIMEOUT_S
                )
            except self._v.refused as exc:
                raise LLMUnavailable(f"gate refused: {exc}") from exc
            except self._v.call_failed as exc:
                if attempt == RETRIES or not _retryable(exc):
                    raise LLMUnavailable(str(exc), busy=_busy(exc)) from exc
                await self._v.sleep(_backoff(exc, attempt))
        raise AssertionError("unreachable")  # pragma: no cover

    async def parse(
        self, system: str, tool: dict[str, Any], user: str
    ) -> tuple[dict[str, Any] | None, Usage]:
        model = _model(PARSE_MODEL_ENV, DEFAULT_PARSE_MODEL)
        body = self._body(model, system, user, PARSE_MAX_TOKENS)
        body["tools"] = [tool]
        body["tool_choice"] = {"type": "tool", "name": tool["name"]}
        response, usage = await self._call(self._v.purpose_parse, body)
        return _tool_input(response, str(tool["name"])), llm_usage(model, usage)

    async def agent(
        self,
        system: str,
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        *,
        force_tool: str | None = None,
    ) -> tuple[list[dict[str, Any]], Usage]:
        """One turn of the advisor's tool loop (same model, retry and gate as ``text``)."""
        model = _model(WRITE_MODEL_ENV, DEFAULT_WRITE_MODEL)
        body = self._body(model, system, "", AGENT_MAX_TOKENS)
        body["messages"] = messages
        body["tools"] = tools
        # Haiku 5.5 may return `thinking` blocks, which the gate's block allowlist refuses on the
        # replay turn (payload_shape); a forced tool_choice also needs thinking off.
        body["thinking"] = {"type": "disabled"}
        if force_tool:
            body["tool_choice"] = {"type": "tool", "name": force_tool}
        response, usage = await self._call(self._v.purpose_write, body)
        content = response.get("content") if isinstance(response, Mapping) else None
        blocks = [
            dict(b)
            for b in content or []
            if isinstance(b, Mapping) and b.get("type") not in ("thinking", "redacted_thinking")
        ]
        return blocks, llm_usage(model, usage)

    async def text(self, system: str, user: str) -> tuple[str, Usage]:
        model = _model(WRITE_MODEL_ENV, DEFAULT_WRITE_MODEL)
        body = self._body(model, system, user, WRITE_MAX_TOKENS)
        response, usage = await self._call(self._v.purpose_write, body)
        return _texts(response), llm_usage(model, usage)

    async def stream_text(self, system: str, user: str) -> AsyncIterator[str]:
        body = self._body(
            _model(WRITE_MODEL_ENV, DEFAULT_WRITE_MODEL), system, user, WRITE_MAX_TOKENS
        )
        for attempt in range(RETRIES + 1):
            started = False
            try:
                async with self._v.stream(
                    self._gate, purpose=self._v.purpose_write, body=body, timeout=TIMEOUT_S
                ) as stream:
                    async for delta in stream:
                        started = True
                        yield delta
                return
            except self._v.refused as exc:
                raise LLMUnavailable(f"gate refused: {exc}") from exc
            except self._v.call_failed as exc:
                if started or attempt == RETRIES or not _retryable(exc):
                    raise LLMUnavailable(str(exc), busy=_busy(exc)) from exc
                await self._v.sleep(_backoff(exc, attempt))


class GateJev:
    """``JevPort``: one System One request per ``ask``."""

    def __init__(self, gate: Any, vendors: Vendors) -> None:
        self._gate = gate
        self._v = vendors

    async def ask(
        self, state: dict[str, Any], questions: dict[str, dict[str, Any]]
    ) -> tuple[dict[str, dict[str, Any]], Usage]:
        for attempt in range(RETRIES + 1):
            try:
                answers, usage = await self._v.system_one(
                    self._gate,
                    purpose=self._v.purpose_route,
                    model=_model(JEV_MODEL_ENV, DEFAULT_JEV_MODEL),
                    state=state,
                    questions=questions,
                    timeout=TIMEOUT_S,
                )
                return answers, jev_usage(usage)
            except self._v.refused as exc:
                raise JevUnavailable(f"gate refused: {exc}") from exc
            except self._v.call_failed as exc:
                # #112: a router 400 is tried once more (TypeSafe answered 400 to a valid request)
                again = _retryable(exc) or (_status(exc) == 400 and attempt == 0)
                if attempt == RETRIES or not again:
                    raise JevUnavailable(str(exc)) from exc
                logger.warning(
                    "juli_agent_jev_retry",
                    extra={
                        "attempt": attempt + 1,
                        "status_code": _status(exc),
                        "error_text": getattr(exc, "error_text", None),
                    },
                )
                await self._v.sleep(_backoff(exc, attempt))
        raise AssertionError("unreachable")  # pragma: no cover


class CommittingCallLog:
    """``CallLogSink`` that writes each ``llm_call_log`` row in its own short transaction.

    A run lasts seconds and its analysis sessions are read-only, so the log cannot share either;
    a fresh WRITABLE session per row, in the shop's scope, committed at once. Never raises into
    the call path (the gate's own rule).
    """

    def __init__(self, factory: async_sessionmaker[AsyncSession], shop_id: uuid.UUID) -> None:
        self._factory = factory
        self._shop_id = shop_id

    async def write(self, entry: Any) -> None:
        try:
            async with self._factory() as session, with_shop_scope(session, self._shop_id):
                session.add(entry.to_row())
                await session.commit()
        except Exception:  # the log never breaks the call path
            logger.warning(
                "juli_agent_call_log_write_failed", extra={"shop_id": str(self._shop_id)}
            )


async def open_ports(
    factory: async_sessionmaker[AsyncSession], shop_id: uuid.UUID, *, vendors: Vendors | None = None
) -> tuple[GateLLM, GateJev]:
    """The shop's gate (its consent grants read once, on a short writable session) and the ports."""
    from juli_backend.services import llm_gate

    async with factory() as session, with_shop_scope(session, shop_id):
        gate = await llm_gate.open_gate(session, shop_id, sink=CommittingCallLog(factory, shop_id))
        await session.commit()
    v = vendors or gate_vendors()
    return GateLLM(gate, v), GateJev(gate, v)


__all__ = [
    "DEFAULT_JEV_MODEL",
    "DEFAULT_PARSE_MODEL",
    "DEFAULT_WRITE_MODEL",
    "RETRIES",
    "CommittingCallLog",
    "GateJev",
    "GateLLM",
    "JevUnavailable",
    "LLMUnavailable",
    "Vendors",
    "gate_vendors",
    "open_ports",
]
