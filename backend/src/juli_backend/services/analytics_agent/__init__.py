"""Analytics agent engine (batch-1120 T1): a Vietnamese seller question or one of 5 templates ->
intent -> Jev routing -> deterministic chain or data answer -> gated card -> explanation -> events.

Pure read-only service. LLM and Jev only through `LLMPort` / `JevPort` (implemented by T3 on T2's
gate).
See `MODULE.md`.
"""

from juli_backend.services.analytics_agent.engine import run
from juli_backend.services.analytics_agent.labels import labels_for, shopee_labels, tiktok_labels
from juli_backend.services.analytics_agent.types import (
    TEMPLATES,
    AnswerResult,
    AskRequest,
    EventSink,
    JevPort,
    LabelTable,
    LLMPort,
    Template,
    Usage,
)

__all__ = [
    "TEMPLATES",
    "AnswerResult",
    "AskRequest",
    "EventSink",
    "JevPort",
    "LLMPort",
    "LabelTable",
    "Template",
    "Usage",
    "labels_for",
    "run",
    "shopee_labels",
    "tiktok_labels",
]
