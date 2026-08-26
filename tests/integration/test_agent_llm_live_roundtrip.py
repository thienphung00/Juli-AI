"""One live GPT-5.4 nano tool-calling round-trip — issue #989 (W1-B), HITL.

Marked ``live`` (ADR-040): runs on merge_group ``test-live-sandbox``, never on
PR-safe Tests, so CI never needs a provider key. Skips when `OPENAI_API_KEY` is
absent so a keyless local run is green rather than red.

This is the test that proves the recorded fixture reflects reality. Its
companion, `test_agent_llm_recorded_replay.py`, must stay green unchanged
before and after a re-record — that pairing is the P11 gate ("one real
tool-calling round-trip green live, same test green in CI via recorded
replay").

## Re-recording the fixture from this run

    export OPENAI_API_KEY=...        # never committed; see ADR-030
    PYTHONPATH=$PWD/backend/src JULI_RECORD_LLM_FIXTURE=1 \
      python3 -m pytest tests/integration/test_agent_llm_live_roundtrip.py -m live -q

Then re-run the replay test and commit the regenerated fixture.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx
import pytest

from juli_backend.services.agent.llm import ToolCallBlock
from juli_backend.services.agent.llm.config import resolve_llm_config
from juli_backend.services.agent.llm.openai_adapter import OpenAIResponsesAdapter
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.registry import ToolRegistry
from juli_backend.services.agent.tools.terminal import register_terminal_tools
from tests.integration.llm_recorded_replay import write_recorded_exchange

pytestmark = pytest.mark.live

requires_provider_key = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY", "").strip(),
    reason="OPENAI_API_KEY absent — live provider round-trip skipped",
)

LIVE_PROMPT = (
    "Start optimizing this listing. Look up the product information first. "
    "Call a tool; do not answer in prose."
)
LIVE_SYSTEM = (
    "You are Juli, optimizing a TikTok Shop listing. The product is already bound "
    "to this run - tools take no identifier arguments. Use the tools."
)


def _registry_tool_definitions():
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.render_input_schema(),
        }
        for spec in sorted(registry.list_all(), key=lambda spec: spec.name)
    ]


class _RecordingTransport(httpx.AsyncBaseTransport):
    """Real network, plus a copy of the exchange for fixture regeneration.

    Only the request *body* is retained — headers carry the bearer token and
    must never reach the repository.
    """

    def __init__(self) -> None:
        self._inner = httpx.AsyncHTTPTransport()
        self.request_body: dict | None = None
        self.response_body: dict | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        import json

        self.request_body = json.loads(request.content)
        response = await self._inner.handle_async_request(request)
        await response.aread()
        try:
            self.response_body = json.loads(response.content)
        except ValueError:
            self.response_body = None
        return response


@requires_provider_key
@pytest.mark.asyncio
async def test_live_gpt_nano_returns_a_real_tool_call():
    """One real round-trip against the provider, using the real ADR-069 registry."""
    config = resolve_llm_config()
    transport = _RecordingTransport()
    adapter = OpenAIResponsesAdapter(transport=transport)

    turn = await adapter.complete(
        messages=[{"role": "user", "content": LIVE_PROMPT}],
        system=LIVE_SYSTEM,
        tools=_registry_tool_definitions(),
        config=config,
    )

    tool_calls = [block for block in turn.blocks if isinstance(block, ToolCallBlock)]
    assert tool_calls, (
        "the live model returned no tool call — round-trip reached the provider but "
        f"the model answered in prose: {turn.blocks!r}"
    )
    assert tool_calls[0].tool_name in {
        "check_product_status",
        "get_product_information",
        "get_seo_keywords",
        "update_product_listing",
        "update_product_price",
        "upload_product_image",
    }
    assert turn.usage.input_tokens > 0
    assert turn.usage.output_tokens > 0

    if os.environ.get("JULI_RECORD_LLM_FIXTURE", "").strip() == "1":
        assert transport.request_body is not None
        assert transport.response_body is not None
        write_recorded_exchange(
            request_body=transport.request_body,
            response_body=transport.response_body,
            model=config.model,
            recorded_at=datetime.now(UTC).isoformat(),
        )
