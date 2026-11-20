"""CI rule: OpenAI is reached only through the gate, and never its state / storage APIs
(ADR-116 §5, D76).

Scans every ``.py`` file under ``backend/src`` and fails on

- any call or URL to OpenAI ``files``, ``vector_stores``, ``assistants``, ``threads``,
  ``conversations``, ``batches``, ``fine_tuning`` or ``evals`` (data kept at OpenAI);
- any ``api.openai.com`` outside ``services/llm_gate/`` (a call that bypasses the gate,
  its consent check and its ``llm_call_log`` row);
- any ``api.anthropic.com`` or ``api.typesafe.ai`` outside ``services/llm_gate/`` (the
  analytics agent's Anthropic Messages and TypeSafe System One calls, same gate).

The patterns are proved on planted snippets, so a rule that silently matches nothing
cannot pass.
"""

from __future__ import annotations

import re
from pathlib import Path

from juli_backend.services.llm_gate import ALLOWED_ENDPOINTS, VENDOR_ENDPOINTS

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "backend/src"
GATE_DIR = SRC / "juli_backend/services/llm_gate"

STATEFUL_APIS = (
    "files",
    "vector_stores",
    "assistants",
    "threads",
    "conversations",
    "batches",
    "fine_tuning",
    "evals",
)
#: ``/v1/files`` as a path, or ``client.files.create`` / ``beta.threads`` as an SDK call.
STATEFUL_RE = re.compile(
    r"/v1/(?:" + "|".join(STATEFUL_APIS) + r")\b"
    r"|\b(?:openai|client|beta)\.(?:" + "|".join(STATEFUL_APIS) + r")\b",
    re.IGNORECASE,
)
DIRECT_HOST_RE = re.compile(r"api\.openai\.com", re.IGNORECASE)
VENDOR_HOST_RE = re.compile(r"api\.anthropic\.com|api\.typesafe\.ai", re.IGNORECASE)


def _sources() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _violations(pattern: re.Pattern[str], *, skip: Path | None = None) -> list[str]:
    out = []
    for path in _sources():
        if skip is not None and skip in path.parents:
            continue
        for number, line in enumerate(path.read_text("utf-8").splitlines(), start=1):
            if pattern.search(line):
                out.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
    return out


def test_no_call_to_an_openai_state_or_storage_api():
    assert _violations(STATEFUL_RE) == []


def test_api_openai_com_appears_only_in_the_gate():
    assert _violations(DIRECT_HOST_RE, skip=GATE_DIR) == []
    assert any(DIRECT_HOST_RE.search(p.read_text("utf-8")) for p in GATE_DIR.glob("*.py"))


def test_api_anthropic_com_and_api_typesafe_ai_appear_only_in_the_gate():
    assert _violations(VENDOR_HOST_RE, skip=GATE_DIR) == []
    gate_text = "\n".join(p.read_text("utf-8") for p in GATE_DIR.glob("*.py"))
    assert "api.anthropic.com" in gate_text
    assert "api.typesafe.ai" in gate_text


def test_the_gate_allows_only_responses_and_transcriptions():
    assert ALLOWED_ENDPOINTS == {"/v1/responses", "/v1/audio/transcriptions"}


def test_the_gate_allows_only_anthropic_messages_and_system_one():
    assert VENDOR_ENDPOINTS == {
        ("https://api.anthropic.com", "/v1/messages"),
        ("https://api.typesafe.ai", "/v1/systemone"),
    }


def test_the_patterns_catch_planted_violations():
    for planted in (
        'client.post("/v1/files", files=upload)',
        "httpx.post('https://api.openai.com/v1/vector_stores')",
        "openai.assistants.create(model=m)",
        "client.beta.threads.create()",
        '"/v1/conversations"',
        "client.batches.create(input_file_id=f)",
        "POST /v1/fine_tuning/jobs",
        "client.evals.create()",
    ):
        assert STATEFUL_RE.search(planted), planted
    for harmless in ("self._files = files", "multipart files={'file': x}", "thread_id = 1"):
        assert not STATEFUL_RE.search(harmless), harmless
    assert DIRECT_HOST_RE.search('"https://api.openai.com/v1/responses"')
    for planted in (
        'httpx.post("https://api.anthropic.com/v1/messages")',
        "BASE = 'https://API.TYPESAFE.AI'",
    ):
        assert VENDOR_HOST_RE.search(planted), planted
    for harmless in ("import anthropic_port", "noreply@anthropic.com", "typesafe_answer = 1"):
        assert not VENDOR_HOST_RE.search(harmless), harmless
