"""The one OpenAI gate on the SQLite schema (ADR-116 §5, D76; migration 105).

Consent is seeded through ``grant_consent`` and read by ``open_gate``; OpenAI is
never called -- every path rides an ``httpx.MockTransport`` that counts requests.

- no consent: each of the four paths (agent adapter, image inspection, content
  analysis transcription / keyframes, scoring and content drafts) makes ZERO HTTP
  calls and writes a ``refused`` row;
- text-only consent (Ory): text sent; image inspection, keyframes and transcription
  refused; an image URL inside text is stripped;
- full consent: every path sent;
- minimisation: shop name / ids / cipher, buyer fields and tokens never reach a
  request body (snapshot); listing content and the shop's rules do;
- ZDR: every body says ``store: false``, never ``previous_response_id`` /
  ``background``; a body that breaks this is refused;
- ``llm_call_log``: one row per attempt with tokens and ``x-request-id``, no content;
  a failing log write never breaks the call;
- migration 105: revision id, parent, the deferred tail, vocabulary and grants.

Postgres claims (RLS, append-only grants, round trip) are in
``tests/integration/test_llm_call_log_db.py``.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP
from juli_backend.models.llm_call_log import STATUSES, LLMCallLog
from juli_backend.services.agent.llm.config import LLMConfig
from juli_backend.services.agent.llm.openai_adapter import (
    LLMGateRefusedError,
    OpenAIResponsesAdapter,
)
from juli_backend.services.agent.vision import InspectionConfig, build_image_inspector
from juli_backend.services.content_analysis.openai_media import (
    OpenAITranscriber,
    OpenAIVision,
)
from juli_backend.services.content_analysis.scoring import OpenAIScorer, Signals
from juli_backend.services.content_cards.drafter import OpenAIContentDrafter
from juli_backend.services.llm_gate import (
    IMAGE_REMOVED,
    LLM_IMAGES,
    LLM_MEDIA,
    LLM_PROCESSING,
    LLM_SCOPES,
    PURPOSE_AGENT_RUN,
    GateRefused,
    MemoryCallLog,
    OpenAIGate,
    SessionCallLog,
    is_forbidden_key,
    open_gate,
)
from juli_backend.services.llm_gate.call_log import CallLogEntry
from tests.support.builders import make_tenant
from tests.support.consent import grant_llm_consent

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
MIGRATION = MIGRATIONS / "versions/105_llm_call_log.py"
BACKFILL = MIGRATIONS / "deferred/101_write_mode_backfill.py"

CONFIG = LLMConfig(
    model="gpt-5.4-nano", max_output_tokens=200, temperature=0.0, request_timeout_seconds=5
)
IMAGE_URL = "https://p16-oec-va.ibyteimg.com/tos-maliva-i-o3syd03w52-us/abc.jpeg"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-patched-not-real")


class Recorder:
    """An OpenAI stand-in: counts requests, keeps JSON bodies, answers with usage."""

    def __init__(self, text: str = '{"ok": true}') -> None:
        self.requests: list[httpx.Request] = []
        self.text = text

    def bodies(self) -> list[dict[str, Any]]:
        return [
            json.loads(r.content)
            for r in self.requests
            if r.headers.get("content-type", "").startswith("application/json")
        ]

    def _response(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/audio/transcriptions"):
            return httpx.Response(
                200,
                json={"text": "xin chào", "segments": [{"start": 0, "end": 1, "text": "xin chào"}]},
                headers={"x-request-id": "req_asr"},
            )
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": self.text}],
                    }
                ],
                "usage": {"input_tokens": 120, "output_tokens": 7},
            },
            headers={"x-request-id": "req_123"},
        )

    def async_transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._response)

    def sync_transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._response)


async def _gate(session, scopes=LLM_SCOPES, *, shop_overrides=None) -> tuple[OpenAIGate, Any]:
    _, shop = await make_tenant(session, **(shop_overrides or {}))
    await grant_llm_consent(session, shop.id, scopes)
    log = MemoryCallLog()
    return await open_gate(session, shop.id, sink=log, sync_sink=log), log


def _adapter(gate, recorder, purpose=PURPOSE_AGENT_RUN) -> OpenAIResponsesAdapter:
    return OpenAIResponsesAdapter(gate=gate, purpose=purpose, transport=recorder.async_transport())


async def _agent_call(adapter, messages=None) -> Any:
    return await adapter.complete(
        messages=messages or [{"role": "user", "content": "Tối ưu tiêu đề sản phẩm."}],
        system="Bạn là Juli.",
        tools=[],
        config=CONFIG,
    )


def _inspector(gate, recorder):
    return build_image_inspector(
        gate=gate,
        config=InspectionConfig(model="gpt-5.4-nano"),
        transport=recorder.sync_transport(),
    )


def _frames(tmp_path: Path) -> list[tuple[float, Path]]:
    from PIL import Image

    out = []
    for i, shade in enumerate((10, 200)):
        path = tmp_path / f"f{i}.jpg"
        Image.new("RGB", (64, 36), (shade, shade, shade)).save(path)
        out.append((float(i * 2), path))
    return out


def _audio(tmp_path: Path) -> Path:
    path = tmp_path / "a.m4a"
    path.write_bytes(b"\x00" * 64)
    return path


SIGNALS = Signals(
    kind="video",
    analysed_s=10.0,
    segments=[{"start": 0.0, "end": 2.0, "text": "xin chào"}],
    screen=[],
    cuts=[],
    product_spans=[],
    product_first_s=None,
    product_checked=False,
    windows=[],
    product_name="Mặt nạ đất sét",
    brand="Bùn Xanh",
)


async def _run_every_path(gate, recorder, tmp_path) -> dict[str, Any]:
    """Drive the four paths through ``gate``; return what each one did."""
    from juli_backend.services.content_analysis.scoring import ContentRules
    from juli_backend.services.content_cards.drafter import DraftInputs
    from juli_backend.services.content_cards.guardrails import ContentRules as CardRules
    from juli_backend.services.content_cards.guardrails import DraftFacts

    out: dict[str, Any] = {}
    try:
        await _agent_call(_adapter(gate, recorder))
        out["agent"] = "sent"
    except LLMGateRefusedError as exc:
        out["agent"] = exc.refusal.reason
    inspection = _inspector(gate, recorder)(image_url=IMAGE_URL, title="Mặt nạ", description="")
    out["inspection"] = "sent" if inspection.get("inspected", True) else "refused"
    try:
        await OpenAITranscriber(
            "whisper-1", gate=gate, transport=recorder.async_transport()
        ).transcribe(_audio(tmp_path), prompt="Mặt nạ đất sét", offset_s=0.0, duration_s=1.0)
        out["transcription"] = "sent"
    except GateRefused as exc:
        out["transcription"] = exc.reason
    vision = OpenAIVision(
        "gpt-5.4-nano", adapter=_adapter(gate, recorder, "content_frames"), gate=gate
    )
    try:
        await vision.read(_frames(tmp_path), product_name="Mặt nạ", product_images=[IMAGE_URL])
        out["frames"] = "sent"
    except GateRefused as exc:
        out["frames"] = exc.reason
    try:
        await OpenAIScorer(
            "gpt-5.4-nano", adapter=_adapter(gate, recorder, "content_scoring")
        ).score(SIGNALS, ContentRules())
        out["scoring"] = "sent"
    except GateRefused as exc:
        out["scoring"] = exc.reason
    drafter = OpenAIContentDrafter(_adapter(gate, recorder, "content_draft"))
    outcome = await drafter.draft(
        kind="video",
        inputs=DraftInputs(
            facts=DraftFacts(product_label="MN-015", product_title="Mặt nạ", basket_skus=()),
            rules=CardRules(),
        ),
        version=1,
        previous=None,
        config=CONFIG,
    )
    out["draft"] = "refused" if outcome.error == "provider" else "sent"
    return out


# -- the four paths under each consent ------------------------------------------------


async def test_no_consent_means_zero_http_calls_and_a_refused_row_on_every_path(session, tmp_path):
    gate, log = await _gate(session, scopes=())
    recorder = Recorder()

    out = await _run_every_path(gate, recorder, tmp_path)

    assert recorder.requests == []
    assert out == {
        "agent": "consent_llm_processing",
        "inspection": "refused",
        "transcription": "consent_llm_processing",
        "frames": "consent_llm_processing",
        "scoring": "consent_llm_processing",
        "draft": "refused",
    }
    assert [(e.purpose, e.status) for e in log.entries] == [
        ("agent_run", "refused"),
        ("image_inspection", "refused"),
        ("content_transcription", "refused"),
        ("content_frames", "refused"),
        ("content_scoring", "refused"),
        ("content_draft", "refused"),
    ]
    assert all(e.refusal_reason and e.request_id is None for e in log.entries)


async def test_text_only_consent_sends_text_and_refuses_images_frames_and_audio(session, tmp_path):
    gate, log = await _gate(session, scopes=(LLM_PROCESSING,))
    recorder = Recorder()

    out = await _run_every_path(gate, recorder, tmp_path)

    assert out == {
        "agent": "sent",
        "inspection": "refused",
        "transcription": "consent_llm_media",
        "frames": "consent_llm_media",
        "scoring": "sent",
        "draft": "sent",
    }
    assert {r.url.path for r in recorder.requests} == {"/v1/responses"}
    assert len(recorder.requests) == 3
    reasons = {e.purpose: e.refusal_reason for e in log.entries if e.status == "refused"}
    assert reasons == {
        "image_inspection": "consent_llm_images",
        "content_transcription": "consent_llm_media",
        "content_frames": "consent_llm_media",
    }


async def test_full_consent_sends_every_path(session, tmp_path):
    gate, log = await _gate(session)
    recorder = Recorder(text='{"frames": [], "verdict": "aligned"}')

    out = await _run_every_path(gate, recorder, tmp_path)

    assert out["agent"] == out["transcription"] == out["frames"] == out["scoring"] == "sent"
    assert out["inspection"] == "sent"
    assert {e.status for e in log.entries} == {"sent"}
    assert len(log.entries) == len(recorder.requests) == 6
    frames = next(
        b
        for b in recorder.bodies()
        if any(
            p.get("type") == "input_image" and p["image_url"].startswith("data:")
            for m in b["input"]
            for p in (m.get("content") if isinstance(m.get("content"), list) else [])
        )
    )
    image_urls = [
        p["image_url"] for p in frames["input"][0]["content"] if p.get("type") == "input_image"
    ]
    assert image_urls[0] == IMAGE_URL  # the listing's reference image goes with llm_images


async def test_frames_without_image_consent_leave_the_listing_images_out(session, tmp_path):
    gate, _ = await _gate(session, scopes=(LLM_PROCESSING, LLM_MEDIA))
    recorder = Recorder(text='{"frames": []}')
    vision = OpenAIVision(
        "gpt-5.4-nano", adapter=_adapter(gate, recorder, "content_frames"), gate=gate
    )

    await vision.read(_frames(tmp_path), product_name="Mặt nạ", product_images=[IMAGE_URL])

    (body,) = recorder.bodies()
    urls = [p["image_url"] for p in body["input"][0]["content"] if p["type"] == "input_image"]
    assert urls and all(url.startswith("data:image/jpeg;base64,") for url in urls)


async def test_an_image_url_in_text_is_stripped_without_image_consent(session):
    gate, log = await _gate(session, scopes=(LLM_PROCESSING,))
    recorder = Recorder()
    tool_result = json.dumps({"title": "Mặt nạ", "main_image": IMAGE_URL, "sold_30d": 42})

    await _agent_call(
        _adapter(gate, recorder),
        messages=[
            {"role": "user", "content": f"Ảnh: {IMAGE_URL} và data:image/png;base64,AAAA"},
            {"role": "tool", "tool_call_id": "c1", "content": tool_result},
        ],
    )

    raw = recorder.requests[0].content.decode()
    assert "ibyteimg" not in raw and "base64,AAAA" not in raw
    (body,) = recorder.bodies()
    assert body["input"][0]["content"][0]["text"] == f"Ảnh: {IMAGE_REMOVED} và {IMAGE_REMOVED}"
    output = json.loads(body["input"][1]["output"])
    assert output == {"title": "Mặt nạ", "main_image": IMAGE_REMOVED, "sold_30d": 42}
    assert [e.status for e in log.entries] == ["sent"]


async def test_an_image_url_in_text_is_kept_with_image_consent(session):
    gate, _ = await _gate(session, scopes=(LLM_PROCESSING, LLM_IMAGES))
    recorder = Recorder()
    await _agent_call(_adapter(gate, recorder), messages=[{"role": "user", "content": IMAGE_URL}])
    assert recorder.bodies()[0]["input"][0]["content"][0]["text"] == IMAGE_URL


async def test_a_revoked_grant_is_refused(session):
    from juli_backend.services.consent import revoke_consent

    _, shop = await make_tenant(session)
    await grant_llm_consent(session, shop.id, (LLM_PROCESSING,))
    await revoke_consent(session, shop.id, LLM_PROCESSING)
    gate = await open_gate(session, shop.id)
    assert gate.granted == frozenset()


async def test_an_adapter_without_a_gate_refuses_before_any_http():
    recorder = Recorder()
    with pytest.raises(LLMGateRefusedError) as info:
        await _agent_call(OpenAIResponsesAdapter(transport=recorder.async_transport()))
    assert info.value.refusal.reason == "no_shop_gate" and recorder.requests == []
    with pytest.raises(GateRefused):
        await OpenAITranscriber("whisper-1").transcribe(
            Path("/nonexistent"), prompt="", offset_s=0, duration_s=1
        )


# -- minimisation ------------------------------------------------------------------


async def test_forbidden_keys_and_shop_ids_never_reach_the_request_body(session):
    gate, _ = await _gate(
        session,
        shop_overrides={
            "shop_name": "Bùn Xanh Official",
            "tiktok_shop_id": "7494000111222333",
        },
    )
    recorder = Recorder()
    tool_result = {
        "title": "Mặt nạ đất sét Bùn Xanh 100g",
        "price": 129000,
        "attributes": {"weight": "100g", "origin": "Việt Nam"},
        "shop_name": "Bùn Xanh Official",
        "shop_id": str(gate.shop_id),
        "shop_cipher": "ROW_abcdef",
        "orders": [{"buyer_id": "b-1", "buyer": {"name": "Lan"}, "quantity": 2, "user_id": "u-9"}],
        "access_token": "TTP_secret_token",
        "credentials": {"refresh_token": "r"},
        "sold_30d": 42,
    }
    opening = {
        "source": "juli",
        "shop_rules": {"banned_terms": ["rẻ nhất"]},
        "note": f"shop 7494000111222333 / {gate.shop_id}",
    }

    await _agent_call(
        _adapter(gate, recorder),
        messages=[
            {"role": "user", "content": json.dumps(opening, ensure_ascii=False)},
            {
                "role": "assistant",
                "tool_call": {
                    "call_id": "c1",
                    "tool_name": "get_product_information",
                    "arguments": {"product_id": "p-1", "shop_id": str(gate.shop_id)},
                },
            },
            {"role": "tool", "tool_call_id": "c1", "content": json.dumps(tool_result)},
        ],
    )

    raw = recorder.requests[0].content.decode()
    for secret in (
        str(gate.shop_id),
        "7494000111222333",
        "Bùn Xanh Official",
        "ROW_abcdef",
        "b-1",
        "u-9",
        "Lan",
        "TTP_secret_token",
        "shop_cipher",
        "buyer",
        "access_token",
        "refresh_token",
    ):
        assert secret not in raw, secret
    (body,) = recorder.bodies()
    assert body["input"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": json.dumps(
                        {
                            "source": "juli",
                            "shop_rules": {"banned_terms": ["rẻ nhất"]},
                            "note": "shop [shop] / [shop]",
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
        },
        {
            "type": "function_call",
            "call_id": "c1",
            "name": "get_product_information",
            "arguments": json.dumps({"product_id": "p-1"}, ensure_ascii=False),
        },
        {
            "type": "function_call_output",
            "call_id": "c1",
            "output": json.dumps(
                {
                    "title": "Mặt nạ đất sét Bùn Xanh 100g",
                    "price": 129000,
                    "attributes": {"weight": "100g", "origin": "Việt Nam"},
                    "orders": [{"quantity": 2}],
                    "sold_30d": 42,
                },
                ensure_ascii=False,
            ),
        },
    ]


def test_the_forbidden_key_predicate():
    for key in (
        "shop_name",
        "Shop_Id",
        "shop_cipher",
        "buyer_id",
        "buyer_email",
        "recipient_address",
        "user_id",
        "access_token",
        "app_secret",
        "api_key",
        "token",
        "credentials",
    ):
        assert is_forbidden_key(key), key
    for key in (
        "title",
        "product_name",
        "shop_rules",
        "price",
        "sold_30d",
        "input_tokens",
        "sku_id",
        "product_id",
        "brand",
    ):
        assert not is_forbidden_key(key), key


# -- ZDR flags ---------------------------------------------------------------------


async def test_every_body_is_stateless(session, tmp_path):
    gate, _ = await _gate(session)
    recorder = Recorder(text='{"frames": []}')
    await _run_every_path(gate, recorder, tmp_path)
    bodies = recorder.bodies()
    assert len(bodies) == 5  # every responses call (the sixth is the transcription form)
    for body in bodies:
        assert body["store"] is False
        assert "previous_response_id" not in body and "background" not in body
        assert "conversation" not in body


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"store": True}, "zdr_store"),
        ({"store": None}, "zdr_store"),
        ({"previous_response_id": "resp_1"}, "zdr_previous_response_id"),
        ({"background": True}, "zdr_background"),
        ({"conversation": "conv_1"}, "zdr_conversation"),
        ({"metadata": {"shop": "x"}}, "payload_shape"),
    ],
)
async def test_a_non_zdr_body_is_refused(session, change, reason):
    gate, log = await _gate(session)
    recorder = Recorder()
    body = {"model": "gpt-5.4-nano", "input": [], "store": False, **change}
    with pytest.raises(GateRefused) as info:
        await gate.post_json(
            purpose=PURPOSE_AGENT_RUN, body=body, timeout=5, transport=recorder.async_transport()
        )
    assert info.value.reason == reason and recorder.requests == []
    assert [(e.status, e.refusal_reason) for e in log.entries] == [("refused", reason)]


async def test_only_the_two_allowlisted_endpoints_are_reachable(session):
    gate, log = await _gate(session)
    recorder = Recorder()
    for endpoint in ("/v1/files", "/v1/vector_stores", "/v1/threads", "/v1/batches"):
        with pytest.raises(GateRefused, match="endpoint_not_allowed"):
            await gate.post_json(
                purpose=PURPOSE_AGENT_RUN,
                endpoint=endpoint,
                body={"model": "m", "store": False, "input": []},
                timeout=5,
                transport=recorder.async_transport(),
            )
    assert recorder.requests == [] and len(log.entries) == 4


# -- llm_call_log ------------------------------------------------------------------


async def test_one_row_per_call_with_tokens_and_request_id_and_no_content(session):
    _, shop = await make_tenant(session)
    await grant_llm_consent(session, shop.id)
    gate = await open_gate(session, shop.id, sink=SessionCallLog(session))
    recorder = Recorder(text="Tiêu đề mới: Mặt nạ đất sét")

    await _agent_call(_adapter(gate, recorder))
    rows = (await session.execute(select(LLMCallLog))).scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert (row.shop_id, row.purpose, row.model, row.endpoint, row.project) == (
        shop.id,
        "agent_run",
        "gpt-5.4-nano",
        "/v1/responses",
        "juli-client-data",
    )
    assert (row.input_tokens, row.output_tokens, row.request_id, row.status) == (
        120,
        7,
        "req_123",
        "sent",
    )
    assert row.refusal_reason is None
    assert {c.name for c in LLMCallLog.__table__.columns} == {
        "id",
        "shop_id",
        "purpose",
        "model",
        "endpoint",
        "project",
        "input_tokens",
        "output_tokens",
        "request_id",
        "status",
        "refusal_reason",
        "created_at",
    }
    stored = " ".join(str(getattr(row, c.name)) for c in LLMCallLog.__table__.columns)
    assert "Tối ưu" not in stored and "Mặt nạ" not in stored and "Juli" not in stored


async def test_a_refusal_writes_a_refused_row(session):
    _, shop = await make_tenant(session)
    gate = await open_gate(session, shop.id, sink=SessionCallLog(session))
    with pytest.raises(LLMGateRefusedError):
        await _agent_call(_adapter(gate, Recorder()))
    (row,) = (await session.execute(select(LLMCallLog))).scalars().all()
    assert (row.status, row.refusal_reason, row.request_id) == (
        "refused",
        "consent_llm_processing",
        None,
    )
    assert (row.input_tokens, row.output_tokens) == (0, 0)


async def test_the_project_label_can_be_overridden(session, monkeypatch):
    monkeypatch.setenv("OPENAI_PROJECT_LABEL", "juli-client-ory")
    gate, log = await _gate(session)
    await _agent_call(_adapter(gate, Recorder()))
    assert log.entries[0].project == "juli-client-ory"


async def test_a_streamed_call_logs_its_usage(session, monkeypatch):
    monkeypatch.setenv("LLM_STREAMING", "on")
    gate, log = await _gate(session)
    events = [
        {"type": "response.output_text.delta", "output_index": 0, "delta": "Xin"},
        {
            "type": "response.completed",
            "response": {
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "Xin"}]}
                ],
                "usage": {"input_tokens": 50, "output_tokens": 3},
            },
        },
    ]
    sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events)
    transport = httpx.MockTransport(
        lambda r: httpx.Response(
            200,
            content=sse.encode(),
            headers={"content-type": "text/event-stream", "x-request-id": "req_s"},
        )
    )
    deltas: list[str] = []

    async def on_delta(text: str) -> None:
        deltas.append(text)

    adapter = OpenAIResponsesAdapter(gate=gate, purpose=PURPOSE_AGENT_RUN, transport=transport)
    await adapter.complete(
        messages=[{"role": "user", "content": "hi"}],
        system="s",
        tools=[],
        config=CONFIG,
        on_text_delta=on_delta,
    )
    assert deltas == ["Xin"]
    (entry,) = log.entries
    assert (entry.status, entry.input_tokens, entry.output_tokens, entry.request_id) == (
        "sent",
        50,
        3,
        "req_s",
    )


async def test_an_http_error_is_logged_as_error_and_still_raised(session):
    gate, log = await _gate(session)
    adapter = OpenAIResponsesAdapter(
        gate=gate,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(500, json={}, headers={"x-request-id": "req_500"})
        ),
    )
    from juli_backend.services.agent.llm.openai_adapter import LLMProviderError

    with pytest.raises(LLMProviderError):
        await _agent_call(adapter)
    assert [(e.status, e.request_id) for e in log.entries] == [("error", "req_500")]


async def test_a_failing_log_write_never_breaks_the_call(session, monkeypatch, caplog):
    _, shop = await make_tenant(session)
    await grant_llm_consent(session, shop.id)
    gate = await open_gate(session, shop.id, sink=SessionCallLog(session))

    async def broken_flush(*args, **kwargs):
        raise RuntimeError("database gone")

    monkeypatch.setattr(session, "flush", broken_flush)
    turn = await _agent_call(_adapter(gate, Recorder(text="ok")))

    assert turn.blocks[0].content == "ok"
    assert "llm_call_log_write_failed" in caplog.text


def test_a_failing_sync_log_write_never_breaks_the_inspection(caplog):
    from juli_backend.services.llm_gate import SyncSessionCallLog

    class BrokenSession:
        def add(self, row):
            raise RuntimeError("database gone")

        def rollback(self):
            pass

    gate = OpenAIGate(
        shop_id=uuid.uuid4(),
        granted=frozenset(LLM_SCOPES),
        sync_sink=SyncSessionCallLog(BrokenSession()),  # type: ignore[arg-type]
    )
    recorder = Recorder(text='{"verdict": "aligned"}')
    result = _inspector(gate, recorder)(image_url=IMAGE_URL, title="t", description="d")
    assert result["verdict"] == "aligned" and len(recorder.requests) == 1
    assert "llm_call_log_write_failed" in caplog.text


def test_an_entry_has_no_field_for_content():
    fields = set(CallLogEntry.__dataclass_fields__)
    assert fields == {
        "shop_id",
        "purpose",
        "model",
        "endpoint",
        "status",
        "project",
        "input_tokens",
        "output_tokens",
        "request_id",
        "refusal_reason",
    }


# -- agent wiring --------------------------------------------------------------------


async def test_the_agent_leg_gate_reads_the_shops_consent(session):
    from juli_backend.services.agent import composition
    from juli_backend.workers.tasks import agent_workflow

    _, shop = await make_tenant(session)
    await grant_llm_consent(session, shop.id, (LLM_PROCESSING,))
    gate = await agent_workflow._open_llm_gate(session, object(), shop.id)  # type: ignore[arg-type]

    assert gate.granted == frozenset({LLM_PROCESSING})
    assert isinstance(gate.sink, SessionCallLog) and gate.sync_sink is None
    gated = composition.gated_llm_service(OpenAIResponsesAdapter(), gate)
    assert gated._gate is gate and gated._purpose == PURPOSE_AGENT_RUN
    fake = object()
    assert composition.gated_llm_service(fake, gate) is fake


def test_a_stand_in_session_gets_a_gate_that_grants_nothing():
    import asyncio

    from juli_backend.workers.tasks import agent_workflow

    gate = asyncio.run(agent_workflow._open_llm_gate(object(), object(), uuid.uuid4()))  # type: ignore[arg-type]
    assert gate.granted == frozenset()


def test_no_gate_means_no_inspector(monkeypatch):
    from juli_backend.services.agent import composition

    assert composition.build_image_inspector(None) is None
    gate = OpenAIGate(shop_id=uuid.uuid4(), granted=frozenset())
    assert composition.build_image_inspector(gate) is not None
    monkeypatch.delenv("OPENAI_API_KEY")
    assert composition.build_image_inspector(gate) is None


# -- migration 105 -------------------------------------------------------------------


def _migration_module():
    spec = importlib.util.spec_from_file_location("mig105", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_fits_alembic_and_the_deferred_tail_moved_onto_it():
    mig = _migration_module()
    assert mig.revision == "105_llm_call_log" and len(mig.revision) <= 32
    assert mig.down_revision == "104_shop_pseudonym_keys"
    # PR 5 put `106_write_platform_columns` on 105; the deferred tail moved onto 106.
    later = (MIGRATIONS / "versions/106_write_platform_columns.py").read_text("utf-8")
    assert f'down_revision: str | None = "{mig.revision}"' in later
    # Migration 107 then took the deferred tail.
    assert 'down_revision: str | None = "107_ops_pooled_consent"' in BACKFILL.read_text("utf-8")


def test_migration_vocabulary_matches_the_model_and_the_table_is_classified():
    assert _migration_module().STATUSES == STATUSES == ("sent", "refused", "error")
    assert TABLE_CLASSIFICATION_MAP[("public", "llm_call_log")] == "tenant_direct"


def test_the_app_role_may_only_select_and_insert():
    text = MIGRATION.read_text("utf-8")
    assert "GRANT SELECT, INSERT ON public.{TABLE} TO {APP_ROLE}" in text
    upgrade = text.split("def upgrade")[1].split("def downgrade")[0]
    for verb in ("UPDATE", "DELETE"):
        assert f"FOR {verb}" not in upgrade and verb not in upgrade.split("GRANT")[1]
    assert "FOR SELECT USING (shop_id = app_current_shop_id())" in text
    assert "FOR INSERT WITH CHECK (shop_id = app_current_shop_id())" in text
