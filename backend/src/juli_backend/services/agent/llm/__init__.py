"""Juli-owned LLM service contract (ADR-071 decisions 1 and 4).

No provider code lands in this slice — see `MODULE.md` for the seam this
package keeps open for a stateless OpenAI Responses adapter (a later slice).
Import from the package root only.
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
from juli_backend.services.agent.llm.service import LLMService, Message, ToolDefinition

__all__ = [
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "DEFAULT_MODEL",
    "DEFAULT_REQUEST_TIMEOUT_SECONDS",
    "DEFAULT_TEMPERATURE",
    "AssistantTurn",
    "Block",
    "FinalResponse",
    "LLMConfig",
    "LLMConfigOverride",
    "LLMService",
    "Message",
    "TextBlock",
    "ToolCallBlock",
    "ToolDefinition",
    "Usage",
    "resolve_llm_config",
]
