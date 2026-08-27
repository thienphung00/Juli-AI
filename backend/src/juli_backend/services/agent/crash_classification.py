"""Classify a crashed agent task into an honest terminal stop reason (#1390).

`workers/tasks/agent_workflow.py`'s catch-all crash handler used to hardcode
`StopReason.WORKER_LOST` for every unhandled exception. That names a cause it
did not observe: gate #1226 walk runs `b354d2d6`, `f6f2695e` and `f5c1f9bf` all
recorded `worker_lost` while the worker was healthy throughout
(`NRestarts=0`, the Celery task itself completing normally). What actually
happened each time was a vendor rejection inside the tool dispatch.

`worker_lost` has a specific meaning — the process died and the reaper stamped
the row — and it is the signal an operator would page on. Collapsing a vendor
4xx into it sends them to look at a worker that is fine.

**Why this lives in `services` and not in `workers`.** Recognising a vendor
exception means naming types from `integrations`, and `.importlinter.toml`
gives `workers` no edge to that package at any depth. `services` has one, and
already owns the tool dispatch these exceptions escape from, so the knowledge
belongs here and the worker calls in.
"""

from __future__ import annotations

import logging

from juli_backend.services.agent.status import StopReason

logger = logging.getLogger(__name__)


def classify_crash_stop_reason(exc: BaseException) -> StopReason:
    """The terminal `StopReason` for an exception that escaped a run.

    Errs toward the residual bucket: a cause is only named when it is
    recognised, never guessed. Returning the wrong specific reason would be a
    worse outcome than returning the vague one, because the specific reasons
    are what alerting keys on.
    """
    # Imported lazily and defensively: this module must classify, never fail.
    # A missing optional dependency or a renamed vendor exception has to
    # degrade to the residual bucket, not raise inside a crash handler whose
    # whole job is to stop a run being stranded non-terminal (#1210).
    try:
        from juli_backend.integrations.tiktok import TikTokAPIError

        if isinstance(exc, TikTokAPIError):
            return StopReason.TOOL_ERROR_UNRECOVERABLE
    except ImportError:  # pragma: no cover - defensive
        pass

    try:
        from juli_backend.services.agent.llm.openai_adapter import LLMProviderError

        if isinstance(exc, LLMProviderError):
            return StopReason.LLM_ERROR
    except ImportError:  # pragma: no cover - defensive
        pass

    try:
        from requests import HTTPError, RequestException

        if isinstance(exc, HTTPError | RequestException):
            return StopReason.TOOL_ERROR_UNRECOVERABLE
    except ImportError:  # pragma: no cover - defensive
        pass

    # Residual bucket. NOT a claim that a worker was lost — it is the one
    # terminal value available for "crashed for a reason we cannot name", and
    # a run must always end terminal (#1210). A dedicated stop reason for this
    # case would need a migration and TypeScript parity; recorded on #1390 as
    # the remaining imprecision rather than papered over here.
    logger.info(
        "agent_crash_stop_reason_unclassified",
        extra={"exception_type": f"{type(exc).__module__}.{type(exc).__name__}"},
    )
    return StopReason.WORKER_LOST


__all__ = ["classify_crash_stop_reason"]
