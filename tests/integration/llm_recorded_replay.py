"""Deterministic OpenAI Responses replay for the agent LLM adapter (issue #989).

Mirrors `tests/integration/tiktok_recorded_replay.py`, adapted to `httpx`:
the marketplace client rides `requests`, so that harness patches
``requests.Session.request``; the LLM adapter rides `httpx`, and
`OpenAIResponsesAdapter` already exposes an injectable
``httpx.AsyncBaseTransport`` seam, so no patching is needed here — the
recorded exchange is served through `httpx.MockTransport`.

CI never needs a provider key: the replay-backed test drives the adapter
entirely through this transport. The one live round-trip that proves the
fixture reflects reality carries the ``live`` marker
(`test_agent_llm_live_roundtrip.py`) and is skipped without a key.

## Fixture format

One JSON object per recorded exchange::

    {
      "provenance": "<how this was obtained>",
      "recorded_at": "<ISO-8601 UTC, or null when hand-authored>",
      "model": "<model string the response came from>",
      "request": { ...the request body actually sent, secrets never included... },
      "response": { ...the provider response body verbatim... }
    }

Only the request *body* is recorded. Headers are deliberately excluded so an
``Authorization: Bearer ...`` value can never reach the repository.

## Regenerating from a real response

    cd <worktree>
    export OPENAI_API_KEY=...            # never committed; see ADR-030
    PYTHONPATH=$PWD/backend/src JULI_RECORD_LLM_FIXTURE=1 \
      python3 -m pytest tests/integration/test_agent_llm_live_roundtrip.py -m live -q

That rewrites `tests/fixtures/agent_llm/responses_tool_call_roundtrip.json`
in place from the real provider response. Re-run the replay test afterwards —
it must still pass unchanged, which is the whole point of the pairing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "agent_llm"
TOOL_CALL_FIXTURE = FIXTURES_DIR / "responses_tool_call_roundtrip.json"

#: Set as `provenance` while the fixture is still hand-authored. The issue #989
#: closing condition is that this string is replaced by a real recording.
PROVISIONAL_PROVENANCE = "hand-authored placeholder pending the live GPT-5.4 nano run"


def load_recorded_exchange(path: Path = TOOL_CALL_FIXTURE) -> dict[str, Any]:
    """Load a recorded request/response pair."""
    return json.loads(path.read_text(encoding="utf-8"))


def is_provisional(exchange: dict[str, Any]) -> bool:
    """True while the fixture has not yet been regenerated from a real response."""
    return exchange.get("provenance") == PROVISIONAL_PROVENANCE


def write_recorded_exchange(
    *,
    request_body: dict[str, Any],
    response_body: dict[str, Any],
    model: str,
    recorded_at: str,
    path: Path = TOOL_CALL_FIXTURE,
) -> None:
    """Persist a real exchange as the golden fixture.

    Sorted keys and a trailing newline keep regeneration byte-stable, so a
    re-record with no provider change produces an empty `git diff`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provenance": "recorded from a live OpenAI Responses API call (issue #989)",
        "recorded_at": recorded_at,
        "model": model,
        "request": request_body,
        "response": response_body,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def recorded_llm_transport(
    exchange: dict[str, Any],
    *,
    captured: dict[str, Any] | None = None,
) -> httpx.MockTransport:
    """A transport that replays `exchange["response"]` for any request.

    When ``captured`` is supplied, the outgoing request's URL, method and
    parsed body are recorded into it so a test can assert on what the adapter
    actually sent — the request half of the contract, which a
    response-only fixture would leave unguarded.
    """
    response_body = exchange["response"]

    def _handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            captured["body"] = json.loads(request.content)
            # Header presence only — never the value.
            captured["has_authorization"] = "authorization" in {
                key.lower() for key in request.headers
            }
        return httpx.Response(200, json=response_body)

    return httpx.MockTransport(_handler)
