"""The crash handler must name what it saw, and tell anyone watching.

Two defects in one function, both found on the gate #1226 walk:

**#1390 — it named a cause it did not observe.** Every unhandled exception was
recorded `worker_lost`. Runs `b354d2d6`, `f6f2695e` and `f5c1f9bf` were all
labelled that way while the worker was healthy throughout (`NRestarts=0`, the
Celery task itself completing normally); what actually happened each time was a
vendor rejection inside the tool dispatch. `worker_lost` means the process died
and the reaper stamped the row — it is what an operator pages on — so a vendor
4xx wearing that label sends them to inspect a worker that is fine.

**#1396 — it committed the terminal event and never published it.** The normal
path (`PersistingEventSink.emit`) INSERTs then PUBLISHes to the Redis channel
the SSE endpoint subscribes to. The crash path only INSERTed. So on precisely
the runs that failed, the terminal event was durable and invisible: every
connected stream sat on heartbeats forever while the run was already dead. All
three walks above had to be diagnosed by querying Postgres by hand.

The publish test here is deliberately **producer-side** — it drives the real
`_emit_crash_terminal_event` and asserts a publish happened, rather than
testing the helper in isolation. This lane has shipped a consumer without its
producer four times (#1379, #1382, #1389 twice); a helper that exists and is
never called is exactly that shape.
"""

from __future__ import annotations

import uuid

import pytest

from juli_backend.services.agent.crash_classification import classify_crash_stop_reason
from juli_backend.services.agent.status import StopReason


class TestClassificationNamesOnlyWhatItObserved:
    def test_a_vendor_api_error_is_a_tool_error(self):
        from juli_backend.integrations.tiktok import TikTokAPIError

        exc = TikTokAPIError(12052104, "missing product attribute ID 100107")

        assert classify_crash_stop_reason(exc) is StopReason.TOOL_ERROR_UNRECOVERABLE

    def test_a_vendor_http_error_is_a_tool_error(self):
        from requests import HTTPError

        exc = HTTPError("400 Client Error: Bad Request")

        assert classify_crash_stop_reason(exc) is StopReason.TOOL_ERROR_UNRECOVERABLE

    def test_a_provider_error_is_an_llm_error(self):
        from juli_backend.services.agent.llm.openai_adapter import LLMProviderError

        exc = LLMProviderError("OpenAI Responses API returned HTTP 500")

        assert classify_crash_stop_reason(exc) is StopReason.LLM_ERROR

    def test_an_unrecognised_exception_falls_to_the_residual_bucket(self):
        """Not a claim that a worker was lost — the one terminal value
        available for "crashed for a reason we cannot name". A run must always
        end terminal (#1210), so guessing a specific reason would be worse than
        the vague one: the specific reasons are what alerting keys on."""
        assert classify_crash_stop_reason(RuntimeError("something else")) is (
            StopReason.WORKER_LOST
        )

    def test_classification_never_raises(self):
        """It runs inside a crash handler whose whole job is to stop a run
        being stranded non-terminal. Failing there would strand the run."""

        class _Awkward(Exception):
            def __class_getitem__(cls, item):  # pragma: no cover - defensive shape
                raise AssertionError("should not be reached")

        assert classify_crash_stop_reason(_Awkward()) is StopReason.WORKER_LOST


class TestTheCrashHandlerPublishes:
    """Producer-side: the real handler must publish, not merely be able to."""

    @pytest.mark.asyncio
    async def test_the_terminal_event_reaches_the_publisher(self, monkeypatch):
        from juli_backend.workers.tasks import agent_workflow

        published: list[tuple[str, str]] = []

        class _Publisher:
            async def publish(self, channel, message):
                published.append((channel, message))

        run_id = uuid.uuid4()
        captured = _install_fake_session(monkeypatch, agent_workflow, run_id)
        monkeypatch.setattr(agent_workflow, "_resolve_event_publisher", lambda: _Publisher())

        from juli_backend.integrations.tiktok import TikTokAPIError

        await agent_workflow._emit_crash_terminal_event(
            captured["session"], run_id, TikTokAPIError(12052104, "missing attribute")
        )

        assert published, (
            "the terminal event was committed but never published — connected SSE "
            "streams would hang on heartbeats forever (#1396)"
        )
        channel, message = published[0]
        assert str(run_id) in channel
        assert "workflow.failed" in message
        assert "tool_error_unrecoverable" in message, (
            "the published event must carry the classified reason (#1390)"
        )

    @pytest.mark.asyncio
    async def test_a_publish_failure_does_not_strand_the_run(self, monkeypatch):
        """Publish is best-effort by contract (ADR-074 d.3). The row is already
        committed; a broker outage must not re-raise into the crash handler."""
        from juli_backend.workers.tasks import agent_workflow

        class _BrokenPublisher:
            async def publish(self, channel, message):
                raise ConnectionError("redis is down")

        run_id = uuid.uuid4()
        captured = _install_fake_session(monkeypatch, agent_workflow, run_id)
        monkeypatch.setattr(agent_workflow, "_resolve_event_publisher", lambda: _BrokenPublisher())

        await agent_workflow._emit_crash_terminal_event(
            captured["session"], run_id, RuntimeError("boom")
        )

        assert captured["run"].status == "failed", "the run still ends terminal"
        assert captured["committed"], "the row still commits"


def _install_fake_session(monkeypatch, agent_workflow, run_id):
    """Minimal stand-ins for the session factory the handler opens."""
    state: dict = {"committed": False}

    class _Run:
        def __init__(self):
            self.id = run_id
            self.status = "running"
            self.stop_reason = None
            self.completed_at = None
            self.required_steps_completed = None
            self.action_card_id = None

    run = _Run()

    class _Result:
        def scalar_one(self):
            return 0

    class _Session:
        async def rollback(self):
            return None

        async def get(self, model, key):
            return run

        async def execute(self, *a, **k):
            return _Result()

        def add(self, row):
            state["row"] = row

        async def commit(self):
            state["committed"] = True

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    session = _Session()
    monkeypatch.setattr(agent_workflow, "_ensure_session_factory", lambda: lambda: session)
    state["session"] = session
    state["run"] = run
    return state
