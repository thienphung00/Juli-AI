"""Juli-owned LLM service contract (ADR-071 decisions 1 and 4).

Neutral block vocabulary, the `LLMService` protocol, fail-closed `LLMConfig`
resolution, and the scripted `FakeLLMService` double — all re-exported here.

The concrete provider adapter (`openai_adapter.OpenAIResponsesAdapter`) is
**not** re-exported: callers depend on the `LLMService` protocol, and reaching
a provider-touching class requires naming its module explicitly. It speaks the
Responses API over `httpx` and imports no vendor SDK — the `openai` package is
not a declared dependency. See `MODULE.md`.
"""

from __future__ import annotations

from juli_backend.services.agent.llm.blocks import (
    AssistantTurn,
    Block,
    FinalResponse,
    TextBlock,
    ToolCallBlock,
    Usage,
)
from juli_backend.services.agent.llm.config import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_TEMPERATURE,
    LLMConfig,
    LLMConfigOverride,
    resolve_llm_config,
)
from juli_backend.services.agent.llm.fake import (
    FakeLLMService,
    RecordedCall,
    ScriptExhaustedError,
)
from juli_backend.services.agent.llm.service import LLMService, Message, ToolDefinition

__all__ = [
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "DEFAULT_MODEL",
    "DEFAULT_REQUEST_TIMEOUT_SECONDS",
    "DEFAULT_TEMPERATURE",
    "AssistantTurn",
    "Block",
    "FakeLLMService",
    "FinalResponse",
    "LLMConfig",
    "LLMConfigOverride",
    "LLMService",
    "Message",
    "RecordedCall",
    "ScriptExhaustedError",
    "TextBlock",
    "ToolCallBlock",
    "ToolDefinition",
    "Usage",
    "resolve_llm_config",
]
