"""The partner reviewer's request scope, as the client factories see it (fast track P64, D73).

A reviewer token (``VerifiedToken.reviewer_platform``) may really write -- but only to Juli's
own TikTok Shop sandbox, through ``SandboxWriteClientFactory`` (owner decision D73, Q4/Q6).
The reviewer gate (``api/reviewer.py``) marks every reviewer request with
:func:`mark_reviewer_session`; the production write paths refuse while it is set:

- ``ProductionWriteClientFactory`` raises :class:`ReviewerProductionWriteRefused` before a
  client exists;
- ``services/execution/production_write_resolver.resolve_write_capability`` and
  ``production_write.load_production_write_resources`` refuse the same way one layer up.

A context variable, like ``pagination_scope``: the mark lives in the request's own task
context, so it never reaches another request or a Celery worker (which is never driven by a
reviewer: the gate's allowlist enqueues only ``poll_shop``, a read).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_REVIEWER_SESSION: ContextVar[bool] = ContextVar("juli_tiktok_reviewer_session", default=False)


class ReviewerProductionWriteRefused(PermissionError):
    """A production write was asked for inside a partner reviewer request (D73 Q6 layer 2)."""


def mark_reviewer_session() -> None:
    """Mark the current request context as a reviewer's, for the rest of that context."""
    _REVIEWER_SESSION.set(True)


def reviewer_session_active() -> bool:
    return _REVIEWER_SESSION.get()


@contextmanager
def reviewer_session() -> Iterator[None]:
    """Scoped form of :func:`mark_reviewer_session` (tests, explicit reviewer work)."""
    token = _REVIEWER_SESSION.set(True)
    try:
        yield
    finally:
        _REVIEWER_SESSION.reset(token)


def refuse_reviewer_production_write(where: str) -> None:
    """Raise when the current context is a reviewer request (fail closed)."""
    if _REVIEWER_SESSION.get():
        raise ReviewerProductionWriteRefused(
            f"{where} refuses a partner reviewer request: a reviewer writes only to the "
            "sandbox shop through SandboxWriteClientFactory"
        )


__all__ = [
    "ReviewerProductionWriteRefused",
    "mark_reviewer_session",
    "refuse_reviewer_production_write",
    "reviewer_session",
    "reviewer_session_active",
]
