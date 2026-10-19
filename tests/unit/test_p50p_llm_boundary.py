"""P50-P (D68.2): every request to the LLM provider is de-identified first.

1. The Responses adapter (the agent, content cards, content-analysis vision and
   scoring all ride it): user text, content parts, tool results (JSON) and the
   system text reach the (mocked) transport scrubbed; numbers, tool schemas and the
   structured-output schema are unchanged.
2. The two direct HTTP call sites -- transcription (glossary prompt) and the agent's
   product-image inspector (title / description) -- scrub their text too.
3. Guard: every module in backend/src that names an OpenAI endpoint is on a reviewed
   list, and every module on it imports the de-identifier.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from juli_backend.core.privacy import REDACTED
from juli_backend.services.agent.llm import LLMConfig
from juli_backend.services.agent.llm.openai_adapter import (
    JsonSchemaFormat,
    OpenAIResponsesAdapter,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "backend/src/juli_backend"

_OK = {
    "output": [
        {
            "type": "message",
            "content": [{"type": "output_text", "text": "Đã xem."}],
        }
    ],
    "usage": {"input_tokens": 1, "output_tokens": 1},
}

_CONFIG = LLMConfig(
    model="gpt-5.4-nano", max_output_tokens=100, temperature=0.0, request_timeout_seconds=5.0
)


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-patched-not-real")


def _capturing_transport(seen: dict[str, Any]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_OK)

    return httpx.MockTransport(handler)


async def test_adapter_scrubs_every_message_before_the_provider() -> None:
    seen: dict[str, Any] = {}
    adapter = OpenAIResponsesAdapter(transport=_capturing_transport(seen))
    tool_result = json.dumps(
        {
            "order_id": "576543210987654321",
            "buyer_name": "Nguyễn Thị Lan",
            "buyer_user_id": "7000111222333",
            "recipient_phone": "0912345678",
            "price": 189000,
            "quantity": 3,
            "note": "gọi 0987 654 321",
        },
        ensure_ascii=False,
    )
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    tool = {
        "name": "get_orders",
        "description": "Đơn hàng",
        "input_schema": {"type": "object", "properties": {}},
    }
    await adapter.complete(
        messages=[
            {"role": "user", "content": "Khách lan.nguyen@gmail.com phàn nàn, SĐT 0912 345 678"},
            {
                "role": "assistant",
                "tool_call": {"call_id": "c1", "tool_name": "get_orders", "arguments": {}},
            },
            {"role": "tool", "tool_call_id": "c1", "content": tool_result},
            {"role": "assistant", "content": "Liên hệ +84912345678 nhé"},
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Mail khách: a.b@yahoo.com"},
                    {"type": "input_image", "image_url": "https://cdn.example/p.jpg"},
                ],
            },
        ],
        system="Bạn là trợ lý của shop. Hotline khách để lại: 0912345678.",
        tools=[tool],
        config=_CONFIG,
        response_format=JsonSchemaFormat(name="check", schema=schema),
    )
    body = seen["body"]
    wire = json.dumps(body, ensure_ascii=False)
    for secret in (
        "lan.nguyen@gmail.com",
        "0912 345 678",
        "0912345678",
        "+84912345678",
        "0987 654 321",
        "a.b@yahoo.com",
        "Nguyễn Thị Lan",
        "7000111222333",
    ):
        assert secret not in wire, secret

    user, call, tool_out, assistant, parts = body["input"]
    assert user["content"][0]["text"] == f"Khách {REDACTED} phàn nàn, SĐT {REDACTED}"
    assert call["type"] == "function_call" and call["call_id"] == "c1"
    out = json.loads(tool_out["output"])
    assert out["order_id"] == "576543210987654321"
    assert out["price"] == 189000 and out["quantity"] == 3
    assert out["buyer_name"] == REDACTED and out["recipient_phone"] == REDACTED
    assert out["buyer_user_id"].startswith("demo-buyer-")
    assert assistant["content"][0]["text"] == f"Liên hệ {REDACTED} nhé"
    assert parts["content"][0]["text"] == f"Mail khách: {REDACTED}"
    assert parts["content"][1] == {"type": "input_image", "image_url": "https://cdn.example/p.jpg"}
    assert body["instructions"] == f"Bạn là trợ lý của shop. Hotline khách để lại: {REDACTED}."
    # Structured output and tool schemas reach the provider untouched.
    assert body["text"]["format"]["schema"] == schema
    assert body["tools"][0]["parameters"] == tool["input_schema"]


async def test_adapter_leaves_clean_shop_text_byte_identical() -> None:
    seen: dict[str, Any] = {}
    adapter = OpenAIResponsesAdapter(transport=_capturing_transport(seen))
    text = "Giá 189.000đ, bán 1.234 đơn, GMV 45.600.000, CTR 3,2%"
    tool_result = '{"price": 189000, "units": 7}'
    await adapter.complete(
        messages=[
            {"role": "user", "content": text},
            {"role": "tool", "tool_call_id": "c1", "content": tool_result},
        ],
        system="Phân tích shop.",
        tools=[],
        config=_CONFIG,
    )
    assert seen["body"]["input"][0]["content"][0]["text"] == text
    assert seen["body"]["input"][1]["output"] == tool_result
    assert seen["body"]["instructions"] == "Phân tích shop."


async def test_transcription_glossary_prompt_is_scrubbed(tmp_path: Path) -> None:
    from juli_backend.services.content_analysis.openai_media import OpenAITranscriber

    seen: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, json={"text": "", "segments": [], "words": []})

    audio = tmp_path / "slice.m4a"
    audio.write_bytes(b"\x00\x00\x00\x18ftypM4A ")
    client = OpenAITranscriber("whisper-1", transport=httpx.MockTransport(handler))
    await client.transcribe(
        audio, prompt="Bùn Xanh, hotline 0912345678, shop@gmail.com", offset_s=0, duration_s=1
    )
    body = seen["body"].decode("utf-8", "replace")
    assert "Bùn Xanh" in body
    assert "0912345678" not in body and "shop@gmail.com" not in body


def test_image_inspector_title_and_description_are_scrubbed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from juli_backend.services.agent import vision

    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_OK)

    real_client = httpx.Client

    def fake_client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", fake_client)
    inspect = vision.build_image_inspector(
        api_key="sk-test", config=vision.InspectionConfig(model="gpt-5.4-nano")
    )
    inspect(
        image_url="https://cdn.example/p.jpg",
        title="Kem SPF50 - Zalo 0912345678",
        description="Liên hệ shop@gmail.com để sỉ",
    )
    text = seen["body"]["input"][0]["content"][0]["text"]
    assert "Kem SPF50" in text
    assert "0912345678" not in text and "shop@gmail.com" not in text
    assert seen["body"]["input"][0]["content"][1]["image_url"] == "https://cdn.example/p.jpg"


# -- guard -----------------------------------------------------------------------

#: Fragments that only a module talking to the provider names.
_PROVIDER_MARKERS = (
    "openai.com",
    "/v1/responses",
    "/v1/audio/",
    "/v1/chat/completions",
    "/v1/embeddings",
    "/v1/images/",
)

#: Every module that sends requests to OpenAI, with what it sends. Adding one means
#: routing its text through ``juli_backend.core.privacy`` and naming it here.
REVIEWED_PROVIDER_MODULES = {
    # The Responses adapter: agent runner, content cards, content-analysis vision/scoring.
    "services/agent/llm/openai_adapter.py",
    # Transcription (glossary prompt + audio slices) and the vision batch (via the adapter).
    "services/content_analysis/openai_media.py",
    # Product-image inspector: title / description text + the CDN image URL.
    "services/agent/vision.py",
}


def _string_constants(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        if id(node) not in docstrings
    ]


def _imports_deidentifier(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(
        isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("juli_backend.core.privacy")
        for node in ast.walk(tree)
    )


def test_every_provider_call_site_is_reviewed_and_deidentified() -> None:
    files = [p for p in SRC_ROOT.rglob("*.py") if "migrations" not in p.parts]
    assert len(files) > 100, "the scan did not find the backend source"
    callers = {
        str(path.relative_to(SRC_ROOT))
        for path in files
        if any(m in s for s in _string_constants(path) for m in _PROVIDER_MARKERS)
    }
    assert callers == REVIEWED_PROVIDER_MODULES, (
        "A module that talks to OpenAI must de-identify what it sends (D68.2): route its "
        "text through juli_backend.core.privacy, then add it to REVIEWED_PROVIDER_MODULES."
    )
    for module in sorted(REVIEWED_PROVIDER_MODULES):
        assert _imports_deidentifier(SRC_ROOT / module), module
