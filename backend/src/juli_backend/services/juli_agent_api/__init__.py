"""The Juli tab's HTTP-facing service: asks, the answer's event stream, history, card send.

``api/routes/juli_agent.py`` is the HTTP skin over this package. The analytics engine (T1,
``services/analytics_agent``) and the LLM gate ports (T2, ``services/llm_gate``) are reached only
through ``engine.py``. See ``MODULE.md``.
"""

from __future__ import annotations

from juli_backend.services.juli_agent_api import config
from juli_backend.services.juli_agent_api.cards import (
    ERROR_CARD_REFUSED,
    ERROR_DRAFT_ALREADY_SENT,
    ERROR_DRAFT_DISMISSED,
    ERROR_NOT_SENDABLE,
    ERROR_UNKNOWN_VERSION,
    ORIGIN_AGENT,
    CardCreator,
    create_via_manual,
    dismiss_card,
    send_card,
)
from juli_backend.services.juli_agent_api.chat import (
    ERROR_BAD_ASK,
    ERROR_BUSY,
    ERROR_LIMITED,
    ERROR_NO_PENDING_CHOICE,
    ERROR_NOT_FOUND,
    ERROR_UNKNOWN_TEMPLATE,
    AskStarted,
    ChatError,
    check_limits,
    get_conversation,
    list_conversations,
    other_platforms,
    owned_answer,
    request_cancel,
    start_ask,
)
from juli_backend.services.juli_agent_api.engine import (
    AnalyticsAgentEngine,
    Engine,
    EngineUnavailable,
    Ports,
    PortsFactory,
    TemplateInfo,
    gate_ports,
    get_engine,
    get_ports_factory,
    read_only_session_factory,
    set_engine,
    set_ports_factory,
)
from juli_backend.services.juli_agent_api.events import (
    TERMINAL_EVENT_TYPES,
    PersistingSink,
    event_stream,
    resolve_after,
)
from juli_backend.services.juli_agent_api.runner import cancel_local, execute, schedule

__all__ = [
    "ERROR_BAD_ASK",
    "ERROR_BUSY",
    "ERROR_CARD_REFUSED",
    "ERROR_DRAFT_ALREADY_SENT",
    "ERROR_DRAFT_DISMISSED",
    "ERROR_LIMITED",
    "ERROR_NOT_FOUND",
    "ERROR_NOT_SENDABLE",
    "ERROR_NO_PENDING_CHOICE",
    "ERROR_UNKNOWN_TEMPLATE",
    "ERROR_UNKNOWN_VERSION",
    "ORIGIN_AGENT",
    "TERMINAL_EVENT_TYPES",
    "AnalyticsAgentEngine",
    "AskStarted",
    "CardCreator",
    "ChatError",
    "Engine",
    "EngineUnavailable",
    "PersistingSink",
    "Ports",
    "PortsFactory",
    "TemplateInfo",
    "cancel_local",
    "check_limits",
    "config",
    "create_via_manual",
    "dismiss_card",
    "event_stream",
    "execute",
    "gate_ports",
    "get_conversation",
    "get_engine",
    "get_ports_factory",
    "list_conversations",
    "other_platforms",
    "owned_answer",
    "read_only_session_factory",
    "request_cancel",
    "resolve_after",
    "schedule",
    "send_card",
    "set_engine",
    "set_ports_factory",
    "start_ask",
]
