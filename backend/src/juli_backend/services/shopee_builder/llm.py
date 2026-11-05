"""The builder's one door to a language model: fail-closed, through the shop's OpenAI gate.

``LLMClient`` is the seam: ``complete_json`` takes a system prompt, a user prompt and a JSON schema
and returns the parsed object. The production client (``GatedLLMClient``) sends through
``services.llm_gate.OpenAIGate`` (consent ``llm_processing``, payload allowlist, ZDR flags, one
``llm_call_log`` row per call) with the existing Responses adapter and structured output, exactly as
the content drafts do. It is never built without a key, a consent or an enabled switch: every
failure becomes :class:`LLMUnavailable` and the route answers "LLM tắt" (HTTP 503), never an
invented text.

Kill switch: ``SHOPEE_BUILDER_LLM`` set to ``0`` / ``false`` / ``no`` / ``off`` turns the drafts off
(read at call time, like ``LLM_STREAMING``); unset = on. Tests pass a fake client; nothing in the
test suite reaches a model.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.agent.llm.blocks import FinalResponse, TextBlock
from juli_backend.services.agent.llm.config import LLMConfig, resolve_llm_config
from juli_backend.services.llm_gate import (
    LLM_PROCESSING,
    PURPOSE_CONTENT_DRAFT,
    GateRefused,
    SessionCallLog,
    open_gate,
)

logger = logging.getLogger(__name__)

SWITCH_ENV_VAR = "SHOPEE_BUILDER_LLM"
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
MAX_OUTPUT_TOKENS = 1_500
REQUEST_TIMEOUT_S = 45.0
OFF_MESSAGE = "LLM tắt"

REASON_SWITCH = "switch_off"
REASON_NOT_CONFIGURED = "not_configured"
REASON_CONSENT = "consent"
REASON_PROVIDER = "provider"
REASON_BAD_OUTPUT = "bad_output"


class LLMUnavailable(RuntimeError):
    """The model cannot be used right now. ``reason`` is one of the ``REASON_*`` constants."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{OFF_MESSAGE}: {reason}" + (f" ({detail})" if detail else ""))
        self.reason = reason
        self.detail = detail


class LLMClient(Protocol):
    @property
    def model(self) -> str: ...

    async def complete_json(
        self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any]
    ) -> dict[str, Any]: ...


def switch_on() -> bool:
    raw = os.environ.get(SWITCH_ENV_VAR, "").strip().lower()
    return raw not in _FALSE_VALUES


@dataclass
class GatedLLMClient:
    """The production client; build it with :func:`gated_client`."""

    adapter: Any
    config: LLMConfig

    @property
    def model(self) -> str:
        return self.config.model

    async def complete_json(
        self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any]
    ) -> dict[str, Any]:
        from juli_backend.services.agent.llm.openai_adapter import (
            JsonSchemaFormat,
            LLMGateRefusedError,
            LLMProviderError,
        )

        try:
            turn = await self.adapter.complete(
                messages=[{"role": "user", "content": user}],
                system=system,
                tools=[],
                config=self.config,
                response_format=JsonSchemaFormat(name=schema_name, schema=schema),
            )
        except LLMGateRefusedError as exc:
            raise LLMUnavailable(REASON_CONSENT, exc.refusal.reason) from exc
        except LLMProviderError as exc:
            logger.warning("builder_llm_provider_error", extra={"detail": str(exc)[:200]})
            raise LLMUnavailable(REASON_PROVIDER, str(exc)[:200]) from exc
        text = "".join(
            block.content if isinstance(block, FinalResponse) else block.text
            for block in turn.blocks
            if isinstance(block, FinalResponse | TextBlock)
        )
        try:
            data = json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise LLMUnavailable(REASON_BAD_OUTPUT, "not JSON") from exc
        if not isinstance(data, dict):
            raise LLMUnavailable(REASON_BAD_OUTPUT, "not an object")
        return data


async def gated_client(session: AsyncSession, shop_id: Any) -> GatedLLMClient:
    """The shop's gated client, or :class:`LLMUnavailable` (switch off, no key, no consent)."""
    if not switch_on():
        raise LLMUnavailable(REASON_SWITCH)
    try:
        config = resolve_llm_config()  # raises RuntimeError when OPENAI_API_KEY is absent
    except RuntimeError as exc:
        raise LLMUnavailable(REASON_NOT_CONFIGURED, "OPENAI_API_KEY") from exc
    from dataclasses import replace

    from juli_backend.services.agent.llm.openai_adapter import OpenAIResponsesAdapter

    try:
        gate = await open_gate(session, shop_id, sink=SessionCallLog(session))
    except GateRefused as exc:  # pragma: no cover - open_gate only reads consents
        raise LLMUnavailable(REASON_CONSENT, exc.reason) from exc
    if not gate.allows(LLM_PROCESSING):
        raise LLMUnavailable(REASON_CONSENT, LLM_PROCESSING)
    adapter = OpenAIResponsesAdapter(gate=gate, purpose=PURPOSE_CONTENT_DRAFT)
    config = replace(
        config,
        max_output_tokens=max(config.max_output_tokens, MAX_OUTPUT_TOKENS),
        request_timeout_seconds=max(config.request_timeout_seconds, REQUEST_TIMEOUT_S),
    )
    return GatedLLMClient(adapter, config)


__all__ = [
    "OFF_MESSAGE",
    "SWITCH_ENV_VAR",
    "GatedLLMClient",
    "LLMClient",
    "LLMUnavailable",
    "gated_client",
    "switch_on",
]
