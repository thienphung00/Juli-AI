"""Agent-run transport services: the SSE event stream, confirmation decisions,
and the polled run list (ADR-074, ADR-075, ADR-083).

``api/routes/agent_runs.py`` is the HTTP skin over this package. Everything
that is not HTTP -- ordering guarantees, the consent-binding ladder, the
read model -- lives here so it can be tested without FastAPI and so the route
module stays thin.

Why a package under ``services`` and not helpers inside the route module: the
import-boundary contract (``.importlinter.toml``) lets ``api`` reach only
``juli_backend.<package>.<child>``. The vocabulary this transport needs --
``WorkflowRunStatus``, the terminal event types, the Redis channel format,
``compute_params_sha`` -- sits three and four levels deep under
``services.agent``. The route used to *reproduce* each of those locally and
carry a drift test per copy. A depth-2 service package can import the real
definitions, so there is nothing left to drift.
"""

from __future__ import annotations

from juli_backend.services.agent_runs.confirmations import (
    ERROR_CONFIRMATION_ALREADY_DECIDED,
    ERROR_CONFIRMATION_EXPIRED,
    ERROR_CONFIRMATION_NOT_FOUND,
    ERROR_INVALID_DECISION,
    ERROR_OPTION_ID_REQUIRED,
    ERROR_PARAMS_SHA_MISMATCH,
    ERROR_RUN_NOT_AWAITING_CONFIRMATION,
    ERROR_RUN_STATE_NOT_RECONSTRUCTABLE,
    ERROR_UNKNOWN_OPTION_ID,
    PENDING_CONFIRMATION_STATUS,
    WAITING_APPROVAL_RUN_STATUS,
    ConfirmationDecision,
    ConfirmationRejected,
    decide_confirmation,
    transition_confirmation_or_none,
)
from juli_backend.services.agent_runs.events import (
    DEFAULT_HEARTBEAT_INTERVAL_S,
    DEFAULT_POLL_INTERVAL_S,
    TERMINAL_EVENT_TYPES,
    TERMINAL_RUN_STATUSES,
    EventSubscriber,
    EventSubscription,
    RedisEventSubscriber,
    event_stream,
    resolve_after_seq,
    resolve_redis_event_subscriber,
    run_events_channel,
    run_events_database_url,
)
from juli_backend.services.agent_runs.listing import PendingDecision, RunListItem, list_runs

__all__ = [
    "DEFAULT_HEARTBEAT_INTERVAL_S",
    "DEFAULT_POLL_INTERVAL_S",
    "ERROR_CONFIRMATION_ALREADY_DECIDED",
    "ERROR_CONFIRMATION_EXPIRED",
    "ERROR_CONFIRMATION_NOT_FOUND",
    "ERROR_INVALID_DECISION",
    "ERROR_OPTION_ID_REQUIRED",
    "ERROR_PARAMS_SHA_MISMATCH",
    "ERROR_RUN_NOT_AWAITING_CONFIRMATION",
    "ERROR_RUN_STATE_NOT_RECONSTRUCTABLE",
    "ERROR_UNKNOWN_OPTION_ID",
    "PENDING_CONFIRMATION_STATUS",
    "TERMINAL_EVENT_TYPES",
    "TERMINAL_RUN_STATUSES",
    "WAITING_APPROVAL_RUN_STATUS",
    "ConfirmationDecision",
    "ConfirmationRejected",
    "EventSubscriber",
    "EventSubscription",
    "PendingDecision",
    "RedisEventSubscriber",
    "RunListItem",
    "decide_confirmation",
    "event_stream",
    "list_runs",
    "resolve_after_seq",
    "resolve_redis_event_subscriber",
    "run_events_channel",
    "run_events_database_url",
    "transition_confirmation_or_none",
]
