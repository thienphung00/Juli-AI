"""The one OpenAI gate: consent per input, payload allowlist, ZDR flags, ``llm_call_log``
(ADR-116 §5, D76). See ``MODULE.md`` and :mod:`.gate`."""

from __future__ import annotations

from juli_backend.services.llm_gate.call_log import (
    DEFAULT_PROJECT,
    CallLogEntry,
    MemoryCallLog,
    SessionCallLog,
    SyncSessionCallLog,
    project_label,
)
from juli_backend.services.llm_gate.gate import (
    ALLOWED_ENDPOINTS,
    OPENAI_BASE_URL,
    PURPOSE_AGENT_RUN,
    PURPOSE_CONTENT_DRAFT,
    PURPOSE_CONTENT_FRAMES,
    PURPOSE_CONTENT_SCORING,
    PURPOSE_CONTENT_TRANSCRIPTION,
    PURPOSE_IMAGE_INSPECTION,
    PURPOSES,
    REASON_NO_GATE,
    GateRefused,
    OpenAIGate,
    StreamingCall,
    open_gate,
    refuse_without_gate,
)
from juli_backend.services.llm_gate.payload import (
    IMAGE_REMOVED,
    LLM_IMAGES,
    LLM_MEDIA,
    LLM_PROCESSING,
    LLM_SCOPES,
    RESPONSES_ENDPOINT,
    TRANSCRIPTIONS_ENDPOINT,
    is_forbidden_key,
)

__all__ = [
    "ALLOWED_ENDPOINTS",
    "DEFAULT_PROJECT",
    "IMAGE_REMOVED",
    "LLM_IMAGES",
    "LLM_MEDIA",
    "LLM_PROCESSING",
    "LLM_SCOPES",
    "OPENAI_BASE_URL",
    "PURPOSES",
    "PURPOSE_AGENT_RUN",
    "PURPOSE_CONTENT_DRAFT",
    "PURPOSE_CONTENT_FRAMES",
    "PURPOSE_CONTENT_SCORING",
    "PURPOSE_CONTENT_TRANSCRIPTION",
    "PURPOSE_IMAGE_INSPECTION",
    "REASON_NO_GATE",
    "RESPONSES_ENDPOINT",
    "TRANSCRIPTIONS_ENDPOINT",
    "CallLogEntry",
    "GateRefused",
    "MemoryCallLog",
    "OpenAIGate",
    "SessionCallLog",
    "StreamingCall",
    "SyncSessionCallLog",
    "is_forbidden_key",
    "open_gate",
    "project_label",
    "refuse_without_gate",
]
