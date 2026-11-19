"""The gate's Anthropic Messages and TypeSafe System One doors (ADR-116 §5 amendment, J9/J10).

No network: every call rides an ``httpx.MockTransport`` that records requests. The
gate is built directly (no database): consent is the ``granted`` set, the log is a
``MemoryCallLog``.

- allowlisted endpoints and purposes only; a purpose is bound to its provider;
- shape allowlists (Anthropic: no ``temperature``, no image / document blocks;
  TypeSafe: ``{model, state, questions}``, choice / noul only, no assets);
- consent: text -> ``llm_processing``; nothing is sent without it;
- minimisation: forbidden keys dropped, shop ids -> ``[shop]``, image URLs stripped;
- a missing key is refused as ``unconfigured`` (never a crash);
- one ``llm_call_log`` row per attempt, project ``anthropic`` / ``typesafe``, with usage
  and the provider's request id; HTTP failures are logged and raised as
  ``GateCallFailed``;
- streaming: text deltas in order, usage from ``message_start`` + ``message_delta``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest

from juli_backend.services.llm_gate import (
    ANTHROPIC_MESSAGES_ENDPOINT,
    IMAGE_REMOVED,
    LLM_PROCESSING,
    PROJECT_ANTHROPIC,
    PROJECT_TYPESAFE,
    PURPOSE_AGENT_CHAT_PARSE,
    PURPOSE_AGENT_CHAT_ROUTE,
    PURPOSE_AGENT_CHAT_WRITE,
    TYPESAFE_SYSTEM_ONE_ENDPOINT,
    VENDOR_ENDPOINTS,
    GateCallFailed,
    GateRefused,
    MemoryCallLog,
    OpenAIGate,
    Usage,
    anthropic_messages,
    anthropic_stream,
    typesafe_system_one,
)
from juli_backend.services.llm_gate.payload import PayloadRefused
from juli_backend.services.llm_gate.vendors import inspect_system_one_body

SHOP = uuid.UUID("11111111-2222-3333-4444-555555555555")
PLATFORM_ID = "7495123456789012345"
IMAGE_URL = "https://p16-oec-va.ibyteimg.com/tos-maliva-i-o3syd03w52-us/abc.jpeg"


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test-not-real")


def _gate(
    *, granted: frozenset[str] = frozenset({LLM_PROCESSING})
) -> tuple[OpenAIGate, MemoryCallLog]:
    log = MemoryCallLog()
    gate = OpenAIGate(shop_id=SHOP, granted=granted, sink=log, shop_identifiers=(PLATFORM_ID,))
    return gate, log


class Recorder:
    """A MockTransport that records requests and answers with a fixed response."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def body(self, index: int = 0) -> dict[str, Any]:
        return json.loads(self.requests[index].content)


def _message_response(**extra: Any) -> httpx.Response:
    payload = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": "Xin chào"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 42, "output_tokens": 7},
        **extra,
    }
    return httpx.Response(200, json=payload, headers={"request-id": "req_ant_1"})


def _messages_body(**extra: Any) -> dict[str, Any]:
    return {
        "model": "claude-haiku-5-5",
        "max_tokens": 200,
        "system": "You parse questions.",
        "messages": [{"role": "user", "content": "Vì sao GMV giảm?"}],
        **extra,
    }


def _system_one_response() -> httpx.Response:
    payload = {
        "model": "jev-latest",
        "answers": {
            "chain": {"type": "choice", "choice": "gmv", "probabilities": {"gmv": 0.9, "aov": 0.1}},
            "fits": {"type": "noul", "noul": 0.97},
        },
        "usage": {"input_tokens": 120, "output_tokens": 12},
    }
    return httpx.Response(200, json=payload, headers={"x-typesafe-request-id": "req_ts_1"})


QUESTIONS: dict[str, dict[str, Any]] = {
    "fits": {"type": "noul", "instructions": "Does `intent` ask about the shop's sales?"},
    "chain": {
        "type": "choice",
        "instructions": "Which analysis fits `intent`?",
        "criteria": {"gmv": "Revenue changed", "aov": "Average order value changed"},
    },
}


# -- allowlists ------------------------------------------------------------------------


def test_the_vendor_endpoints_are_pinned():
    assert VENDOR_ENDPOINTS == {
        ("https://api.anthropic.com", "/v1/messages"),
        ("https://api.typesafe.ai", "/v1/systemone"),
    }
    assert ANTHROPIC_MESSAGES_ENDPOINT == "/v1/messages"
    assert TYPESAFE_SYSTEM_ONE_ENDPOINT == "/v1/systemone"


async def test_anthropic_messages_sends_and_logs_one_row_with_usage_and_request_id():
    gate, log = _gate()
    rec = Recorder(_message_response())
    data, usage = await anthropic_messages(
        gate,
        purpose=PURPOSE_AGENT_CHAT_PARSE,
        body=_messages_body(output_config={"effort": "low"}, thinking={"type": "disabled"}),
        timeout=5,
        transport=rec.transport,
    )
    assert data["content"][0]["text"] == "Xin chào"
    assert usage == Usage(input_tokens=42, output_tokens=7)
    request = rec.requests[0]
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "sk-ant-test-not-real"
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in request.headers
    sent = rec.body()
    assert sent["stream"] is False
    assert sent["output_config"] == {"effort": "low"}
    assert sent["thinking"] == {"type": "disabled"}
    [entry] = log.entries
    assert (entry.status, entry.purpose, entry.endpoint, entry.project) == (
        "sent",
        PURPOSE_AGENT_CHAT_PARSE,
        "/v1/messages",
        PROJECT_ANTHROPIC,
    )
    assert (entry.model, entry.input_tokens, entry.output_tokens, entry.request_id) == (
        "claude-haiku-5-5",
        42,
        7,
        "req_ant_1",
    )
    assert entry.refusal_reason is None


async def test_typesafe_system_one_sends_and_logs_one_row():
    gate, log = _gate()
    rec = Recorder(_system_one_response())
    answers, usage = await typesafe_system_one(
        gate,
        purpose=PURPOSE_AGENT_CHAT_ROUTE,
        model="jev-latest",
        state={"intent": {"metric": "gmv", "window": "last_7d_vs_prev_7d"}},
        questions=QUESTIONS,
        timeout=5,
        transport=rec.transport,
    )
    assert answers["chain"]["choice"] == "gmv"
    assert answers["fits"]["noul"] == 0.97
    assert usage == Usage(input_tokens=120, output_tokens=12)
    request = rec.requests[0]
    assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
    assert request.headers["authorization"] == "Bearer ts-test-not-real"
    assert set(rec.body()) == {"model", "state", "questions"}
    [entry] = log.entries
    assert (entry.status, entry.endpoint, entry.project, entry.request_id) == (
        "sent",
        "/v1/systemone",
        PROJECT_TYPESAFE,
        "req_ts_1",
    )
    assert (entry.input_tokens, entry.output_tokens) == (120, 12)


@pytest.mark.parametrize(
    "purpose",
    ["agent_run", "agent_chat_route", "unknown_thing"],
)
async def test_anthropic_refuses_a_purpose_not_bound_to_it(purpose):
    gate, log = _gate()
    rec = Recorder(_message_response())
    with pytest.raises(GateRefused) as excinfo:
        await anthropic_messages(
            gate, purpose=purpose, body=_messages_body(), timeout=5, transport=rec.transport
        )
    assert excinfo.value.reason == "unknown_purpose"
    assert rec.requests == []
    assert [(e.status, e.refusal_reason) for e in log.entries] == [("refused", "unknown_purpose")]


@pytest.mark.parametrize(
    "purpose", [PURPOSE_AGENT_CHAT_PARSE, PURPOSE_AGENT_CHAT_WRITE, "agent_run"]
)
async def test_typesafe_refuses_a_purpose_not_bound_to_it(purpose):
    gate, log = _gate()
    rec = Recorder(_system_one_response())
    with pytest.raises(GateRefused) as excinfo:
        await typesafe_system_one(
            gate,
            purpose=purpose,
            model="jev-latest",
            state="x",
            questions=QUESTIONS,
            timeout=5,
            transport=rec.transport,
        )
    assert excinfo.value.reason == "unknown_purpose"
    assert rec.requests == []
    assert log.entries[0].project == PROJECT_TYPESAFE


@pytest.mark.parametrize("endpoint", ["/v1/messages/batches", "/v1/files", "/v1/complete"])
async def test_anthropic_refuses_an_endpoint_outside_the_allowlist(endpoint):
    gate, log = _gate()
    rec = Recorder(_message_response())
    with pytest.raises(GateRefused) as excinfo:
        await anthropic_messages(
            gate,
            purpose=PURPOSE_AGENT_CHAT_PARSE,
            body=_messages_body(),
            timeout=5,
            endpoint=endpoint,
            transport=rec.transport,
        )
    assert excinfo.value.reason == "endpoint_not_allowed"
    assert rec.requests == []
    assert log.entries[0].endpoint == endpoint


async def test_typesafe_refuses_an_endpoint_outside_the_allowlist():
    gate, log = _gate()
    rec = Recorder(_system_one_response())
    with pytest.raises(GateRefused) as excinfo:
        await typesafe_system_one(
            gate,
            purpose=PURPOSE_AGENT_CHAT_ROUTE,
            model="jev-latest",
            state="x",
            questions=QUESTIONS,
            timeout=5,
            endpoint="/v1/models",
            transport=rec.transport,
        )
    assert excinfo.value.reason == "endpoint_not_allowed"
    assert rec.requests == []


@pytest.mark.parametrize(
    "change",
    [
        {"temperature": 0.0},
        {"metadata": {"user_id": "u"}},
        {"container": "c"},
        {"mcp_servers": []},
        {"messages": [{"role": "system", "content": "x"}]},
        {"messages": [{"role": "user", "content": [{"type": "image", "source": {}}]}]},
        {"messages": [{"role": "user", "content": [{"type": "document", "source": {}}]}]},
        {"messages": [{"role": "user", "content": [{"type": "text", "text": "x", "extra": 1}]}]},
        {"messages": [{"role": "user", "content": "x", "name": "n"}]},
        {"messages": "x"},
        {"system": [{"type": "image", "source": {}}]},
        {"system": 5},
        {"output_config": "low"},
        {"thinking": True},
        {"max_tokens": "200"},
    ],
)
async def test_an_anthropic_body_outside_the_shape_is_refused(change):
    gate, log = _gate()
    rec = Recorder(_message_response())
    with pytest.raises(GateRefused) as excinfo:
        await anthropic_messages(
            gate,
            purpose=PURPOSE_AGENT_CHAT_PARSE,
            body=_messages_body(**change),
            timeout=5,
            transport=rec.transport,
        )
    assert excinfo.value.reason == "payload_shape"
    assert rec.requests == []
    assert [(e.status, e.refusal_reason) for e in log.entries] == [("refused", "payload_shape")]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"questions": {}},
        {"questions": {"q": {"type": "score", "instructions": "x", "criteria": {"a": "b"}}}},
        {"questions": {"q": {"type": "box", "instructions": "x"}}},
        {"questions": {"q": {"type": "choice", "instructions": "x"}}},
        {"questions": {"q": {"type": "choice", "criteria": {}}}},
        {"questions": {"q": {"type": "noul", "instructions": "x", "asset": "a"}}},
        {"questions": {"q": {"type": "noul", "criteria": {"true": "y", "maybe": "z"}}}},
        {"questions": "x"},
        {"state": 5},
        {"model": ""},
    ],
)
async def test_a_system_one_request_outside_the_shape_is_refused(kwargs):
    gate, log = _gate()
    rec = Recorder(_system_one_response())
    args: dict[str, Any] = {"model": "jev-latest", "state": "x", "questions": QUESTIONS, **kwargs}
    with pytest.raises(GateRefused) as excinfo:
        await typesafe_system_one(
            gate, purpose=PURPOSE_AGENT_CHAT_ROUTE, timeout=5, transport=rec.transport, **args
        )
    assert excinfo.value.reason == "payload_shape"
    assert rec.requests == []
    assert log.entries[0].refusal_reason == "payload_shape"


# -- consent ---------------------------------------------------------------------------


async def test_without_llm_processing_nothing_is_sent_to_either_vendor():
    gate, log = _gate(granted=frozenset())
    ant, ts = Recorder(_message_response()), Recorder(_system_one_response())
    with pytest.raises(GateRefused) as first:
        await anthropic_messages(
            gate,
            purpose=PURPOSE_AGENT_CHAT_PARSE,
            body=_messages_body(),
            timeout=5,
            transport=ant.transport,
        )
    with pytest.raises(GateRefused) as second:
        await typesafe_system_one(
            gate,
            purpose=PURPOSE_AGENT_CHAT_ROUTE,
            model="jev-latest",
            state="x",
            questions=QUESTIONS,
            timeout=5,
            transport=ts.transport,
        )
    with pytest.raises(GateRefused) as third:
        async with anthropic_stream(
            gate,
            purpose=PURPOSE_AGENT_CHAT_WRITE,
            body=_messages_body(),
            timeout=5,
            transport=ant.transport,
        ):
            pass
    assert first.value.is_consent and second.value.is_consent and third.value.is_consent
    assert first.value.reason == "consent_llm_processing"
    assert ant.requests == [] and ts.requests == []
    assert [(e.status, e.refusal_reason, e.project) for e in log.entries] == [
        ("refused", "consent_llm_processing", PROJECT_ANTHROPIC),
        ("refused", "consent_llm_processing", PROJECT_TYPESAFE),
        ("refused", "consent_llm_processing", PROJECT_ANTHROPIC),
    ]


# -- minimisation ----------------------------------------------------------------------


async def test_anthropic_bodies_are_minimised():
    gate, _ = _gate()
    rec = Recorder(_message_response())
    tool_result = json.dumps(
        {
            "shop_name": "Secret Brand Store",
            "shop_id": PLATFORM_ID,
            "rows": [{"title": "Áo thun", "gmv": 1200, "buyer_name": "Nguyen Van A"}],
        }
    )
    body = _messages_body(
        system=[{"type": "text", "text": f"Shop {SHOP} sells shirts."}],
        tools=[{"name": "parse", "description": "d", "input_schema": {"type": "object"}}],
        tool_choice={"type": "tool", "name": "parse"},
        messages=[
            {"role": "user", "content": f"Shop {PLATFORM_ID} xem ảnh {IMAGE_URL}"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "parse",
                        "input": {
                            "access_token": "tok-secret-1",
                            "metric": "gmv",
                            "note": PLATFORM_ID,
                        },
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu_1", "content": tool_result},
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_1",
                        "content": [{"type": "text", "text": f"id {PLATFORM_ID}"}],
                        "is_error": False,
                    },
                ],
            },
        ],
    )
    await anthropic_messages(
        gate, purpose=PURPOSE_AGENT_CHAT_PARSE, body=body, timeout=5, transport=rec.transport
    )
    raw = rec.requests[0].content.decode()
    for leaked in (
        PLATFORM_ID,
        str(SHOP),
        "Secret Brand Store",
        "Nguyen Van A",
        "tok-secret-1",
        IMAGE_URL,
    ):
        assert leaked not in raw, leaked
    sent = rec.body()
    assert sent["system"][0]["text"] == "Shop [shop] sells shirts."
    assert sent["messages"][0]["content"] == f"Shop [shop] xem ảnh {IMAGE_REMOVED}"
    assert sent["messages"][1]["content"][0]["input"] == {"metric": "gmv", "note": "[shop]"}
    first_result = json.loads(sent["messages"][2]["content"][0]["content"])
    assert first_result == {"rows": [{"title": "Áo thun", "gmv": 1200}]}
    assert sent["messages"][2]["content"][1]["content"][0]["text"] == "id [shop]"
    assert sent["tools"] == body["tools"]
    assert sent["tool_choice"] == body["tool_choice"]


async def test_system_one_requests_are_minimised():
    gate, _ = _gate()
    rec = Recorder(_system_one_response())
    await typesafe_system_one(
        gate,
        purpose=PURPOSE_AGENT_CHAT_ROUTE,
        model="jev-latest",
        state={"intent": {"shop_id": PLATFORM_ID, "text": f"shop {PLATFORM_ID}", "metric": "gmv"}},
        questions={
            "product": {
                "type": "choice",
                "instructions": {"seller_id": "s1", "ask": "Which product?"},
                "criteria": {"p1": f"Áo {PLATFORM_ID}", "p2": None},
            },
            "named": {
                "type": "noul",
                "instructions": "Named?",
                "criteria": {"true": "yes", "false": "no"},
            },
        },
        timeout=5,
        transport=rec.transport,
    )
    raw = rec.requests[0].content.decode()
    assert PLATFORM_ID not in raw and "s1" not in raw
    sent = rec.body()
    assert sent["state"] == {"intent": {"text": "shop [shop]", "metric": "gmv"}}
    assert sent["questions"]["product"]["instructions"] == {"ask": "Which product?"}
    assert sent["questions"]["product"]["criteria"] == {"p1": "Áo [shop]", "p2": None}
    assert sent["questions"]["named"]["criteria"] == {"true": "yes", "false": "no"}


async def test_a_string_state_is_minimised():
    gate, _ = _gate()
    rec = Recorder(_system_one_response())
    await typesafe_system_one(
        gate,
        purpose=PURPOSE_AGENT_CHAT_ROUTE,
        model="jev-latest",
        state=json.dumps({"buyer_phone": "0901234567", "metric": "gmv"}),
        questions=QUESTIONS,
        timeout=5,
        transport=rec.transport,
    )
    assert json.loads(rec.body()["state"]) == {"metric": "gmv"}


# -- keys ------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "   "])
async def test_a_missing_anthropic_key_is_refused_as_unconfigured(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", value)
    gate, log = _gate()
    rec = Recorder(_message_response())
    with pytest.raises(GateRefused) as excinfo:
        await anthropic_messages(
            gate,
            purpose=PURPOSE_AGENT_CHAT_PARSE,
            body=_messages_body(),
            timeout=5,
            transport=rec.transport,
        )
    assert excinfo.value.reason == "unconfigured"
    with pytest.raises(GateRefused) as streamed:
        async with anthropic_stream(
            gate,
            purpose=PURPOSE_AGENT_CHAT_WRITE,
            body=_messages_body(),
            timeout=5,
            transport=rec.transport,
        ):
            pass
    assert streamed.value.reason == "unconfigured"
    assert rec.requests == []
    assert [(e.status, e.refusal_reason) for e in log.entries] == [
        ("refused", "unconfigured"),
        ("refused", "unconfigured"),
    ]


async def test_a_missing_typesafe_key_is_refused_as_unconfigured(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    gate, log = _gate()
    rec = Recorder(_system_one_response())
    with pytest.raises(GateRefused) as excinfo:
        await typesafe_system_one(
            gate,
            purpose=PURPOSE_AGENT_CHAT_ROUTE,
            model="jev-latest",
            state="x",
            questions=QUESTIONS,
            timeout=5,
            transport=rec.transport,
        )
    assert excinfo.value.reason == "unconfigured"
    assert rec.requests == []
    assert log.entries[0].project == PROJECT_TYPESAFE


# -- failures --------------------------------------------------------------------------


@pytest.mark.parametrize("status", [429, 500, 529])
async def test_an_anthropic_error_status_is_logged_and_raised(status):
    gate, log = _gate()
    rec = Recorder(
        httpx.Response(
            status,
            json={"type": "error", "error": {"type": "overloaded_error"}},
            headers={"request-id": "req_err", "retry-after": "3"},
        )
    )
    with pytest.raises(GateCallFailed) as excinfo:
        await anthropic_messages(
            gate,
            purpose=PURPOSE_AGENT_CHAT_PARSE,
            body=_messages_body(),
            timeout=5,
            transport=rec.transport,
        )
    assert (excinfo.value.status_code, excinfo.value.retry_after) == (status, "3")
    assert excinfo.value.reason == "http_status"
    assert excinfo.value.provider == PROJECT_ANTHROPIC
    assert [(e.status, e.request_id) for e in log.entries] == [("error", "req_err")]


async def test_a_transport_error_is_logged_and_raised_as_a_call_failure():
    gate, log = _gate()

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(GateCallFailed) as excinfo:
        await typesafe_system_one(
            gate,
            purpose=PURPOSE_AGENT_CHAT_ROUTE,
            model="jev-latest",
            state="x",
            questions=QUESTIONS,
            timeout=5,
            transport=httpx.MockTransport(boom),
        )
    assert excinfo.value.reason == "transport"
    assert excinfo.value.status_code is None
    assert isinstance(excinfo.value.__cause__, httpx.ConnectTimeout)
    assert [e.status for e in log.entries] == ["error"]


async def test_a_system_one_response_without_answers_is_a_call_failure():
    gate, log = _gate()
    rec = Recorder(httpx.Response(200, json={"model": "jev-latest", "usage": {}}))
    with pytest.raises(GateCallFailed) as excinfo:
        await typesafe_system_one(
            gate,
            purpose=PURPOSE_AGENT_CHAT_ROUTE,
            model="jev-latest",
            state="x",
            questions=QUESTIONS,
            timeout=5,
            transport=rec.transport,
        )
    assert excinfo.value.reason == "bad_response"
    assert [e.status for e in log.entries] == ["error"]


def test_a_system_one_body_with_any_other_key_is_refused():
    body = {"model": "jev-latest", "state": "x", "questions": QUESTIONS}
    inspect_system_one_body(body, shop_identifiers=())
    for extra in ({"assets": {"a": {"type": "image", "part": "p0"}}}, {"metadata": {}}):
        with pytest.raises(PayloadRefused) as excinfo:
            inspect_system_one_body({**body, **extra}, shop_identifiers=())
        assert excinfo.value.reason == "payload_shape"


async def test_a_gate_without_a_sink_still_gates_and_sends():
    gate = OpenAIGate(shop_id=SHOP, granted=frozenset({LLM_PROCESSING}))
    rec = Recorder(_message_response())
    _, usage = await anthropic_messages(
        gate,
        purpose=PURPOSE_AGENT_CHAT_PARSE,
        body=_messages_body(),
        timeout=5,
        transport=rec.transport,
    )
    assert usage.output_tokens == 7
    refused = OpenAIGate(shop_id=SHOP, granted=frozenset())
    with pytest.raises(GateRefused):
        await anthropic_messages(
            refused,
            purpose=PURPOSE_AGENT_CHAT_PARSE,
            body=_messages_body(),
            timeout=5,
            transport=rec.transport,
        )
    assert len(rec.requests) == 1


# -- streaming -------------------------------------------------------------------------


def _sse(*events: dict[str, Any]) -> bytes:
    return "".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
    ).encode()


STREAM_OK = _sse(
    {
        "type": "message_start",
        "message": {
            "id": "msg_1",
            "model": "claude-haiku-5-5",
            "usage": {"input_tokens": 30, "output_tokens": 1},
        },
    },
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "ping"},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "GMV "}},
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "giảm 12%"},
    },
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 9}},
    {"type": "message_stop"},
)


async def test_a_stream_yields_text_deltas_and_logs_usage_on_exit():
    gate, log = _gate()
    rec = Recorder(
        httpx.Response(
            200,
            content=STREAM_OK,
            headers={"content-type": "text/event-stream", "request-id": "req_stream"},
        )
    )
    async with anthropic_stream(
        gate,
        purpose=PURPOSE_AGENT_CHAT_WRITE,
        body=_messages_body(),
        timeout=5,
        transport=rec.transport,
    ) as stream:
        assert log.entries == []
        texts = [text async for text in stream]
    assert texts == ["GMV ", "giảm 12%"]
    assert stream.usage == Usage(input_tokens=30, output_tokens=9)
    assert rec.body()["stream"] is True
    [entry] = log.entries
    assert (entry.status, entry.purpose, entry.project, entry.request_id) == (
        "sent",
        PURPOSE_AGENT_CHAT_WRITE,
        PROJECT_ANTHROPIC,
        "req_stream",
    )
    assert (entry.input_tokens, entry.output_tokens) == (30, 9)


async def test_a_stream_skips_thinking_deltas():
    gate, _ = _gate()
    body = _sse(
        {"type": "message_start", "message": {"usage": {"input_tokens": 5, "output_tokens": 0}}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "hmm"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "signature_delta", "signature": "s"},
        },
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "ok"}},
        {"type": "message_delta", "delta": {}, "usage": {"output_tokens": 3}},
        {"type": "message_stop"},
    )
    rec = Recorder(httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
    async with anthropic_stream(
        gate,
        purpose=PURPOSE_AGENT_CHAT_WRITE,
        body=_messages_body(),
        timeout=5,
        transport=rec.transport,
    ) as stream:
        assert [t async for t in stream] == ["ok"]


async def test_an_error_event_mid_stream_is_a_call_failure_logged_as_error():
    gate, log = _gate()
    body = _sse(
        {"type": "message_start", "message": {"usage": {"input_tokens": 5, "output_tokens": 0}}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "a"}},
        {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
    )
    rec = Recorder(httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
    seen: list[str] = []
    with pytest.raises(GateCallFailed) as excinfo:
        async with anthropic_stream(
            gate,
            purpose=PURPOSE_AGENT_CHAT_WRITE,
            body=_messages_body(),
            timeout=5,
            transport=rec.transport,
        ) as stream:
            async for text in stream:
                seen.append(text)
    assert seen == ["a"]
    assert excinfo.value.reason == "stream_error"
    [entry] = log.entries
    assert (entry.status, entry.input_tokens) == ("error", 5)


async def test_a_stream_that_ends_without_message_stop_is_logged_as_error():
    gate, log = _gate()
    body = _sse(
        {"type": "message_start", "message": {"usage": {"input_tokens": 5, "output_tokens": 0}}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "a"}},
    )
    rec = Recorder(httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
    with pytest.raises(GateCallFailed) as excinfo:
        async with anthropic_stream(
            gate,
            purpose=PURPOSE_AGENT_CHAT_WRITE,
            body=_messages_body(),
            timeout=5,
            transport=rec.transport,
        ) as stream:
            async for _ in stream:
                pass
    assert excinfo.value.reason == "stream_error"
    assert [e.status for e in log.entries] == ["error"]


async def test_a_stream_error_status_raises_before_any_text():
    gate, log = _gate()
    rec = Recorder(httpx.Response(529, json={"type": "error"}, headers={"retry-after": "1"}))
    with pytest.raises(GateCallFailed) as excinfo:
        async with anthropic_stream(
            gate,
            purpose=PURPOSE_AGENT_CHAT_WRITE,
            body=_messages_body(),
            timeout=5,
            transport=rec.transport,
        ):
            pytest.fail("the block must not run on an error status")
    assert (excinfo.value.status_code, excinfo.value.retry_after) == (529, "1")
    assert [e.status for e in log.entries] == ["error"]


async def test_a_stream_abandoned_early_is_logged_once_as_error():
    gate, log = _gate()
    rec = Recorder(
        httpx.Response(200, content=STREAM_OK, headers={"content-type": "text/event-stream"})
    )
    async with anthropic_stream(
        gate,
        purpose=PURPOSE_AGENT_CHAT_WRITE,
        body=_messages_body(),
        timeout=5,
        transport=rec.transport,
    ) as stream:
        async for _ in stream:
            break
    [entry] = log.entries
    assert entry.status == "error"
    assert entry.input_tokens == 30


async def test_a_stream_purpose_must_be_bound_to_anthropic():
    gate, log = _gate()
    rec = Recorder(httpx.Response(200, content=STREAM_OK))
    with pytest.raises(GateRefused) as excinfo:
        async with anthropic_stream(
            gate,
            purpose=PURPOSE_AGENT_CHAT_ROUTE,
            body=_messages_body(),
            timeout=5,
            transport=rec.transport,
        ):
            pass
    assert excinfo.value.reason == "unknown_purpose"
    assert rec.requests == []
    assert log.entries[0].status == "refused"
