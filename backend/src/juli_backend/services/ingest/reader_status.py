"""C2 (batch-1123-a): one status per reader per run, from the Connector's outcome note.

The Connector's run report (``POST /v1/ingest/connector-ticks``) names each reader's outcome as
a short note (Connector 0.3.20+: ``done:order_lines=posted``, ``done:order_lines=empty``,
``no_orders``, ``blocked:login``, ``waiting_budget``, ``error:orders:0_rows:<step>``,
``timeout``, ``needs_template:<note>``, ``partial:page_cap`` ...). ``status_of`` folds each into
``ok`` / ``empty`` / ``blocked`` / ``error`` plus the reason, so Ops reads one vocabulary and the
audit row keeps both (``readers`` beside ``outcomes``). Metadata only.
"""

from __future__ import annotations

from typing import Literal, TypedDict

Status = Literal["ok", "empty", "blocked", "error"]

#: A reader that ran and found nothing to send (no order, no product, no campaign).
_EMPTY = frozenset({"no_orders", "no_new_orders", "no_items", "no_campaigns", "no_group_campaigns"})
#: A reader the run did not start: the day's budget ran out first.
_WAITING = "waiting_budget"
#: Per-dataset results inside a ``done:`` note (the Connector's post outcome).
_ACCEPTED = frozenset({"posted", "queued"})
_NOTHING = frozenset({"empty", "ignored"})
_REFUSED = frozenset({"rejected", "drift", "refused", "unpaired", "stopped"})
#: Mapped but not sent by design (``HELD_DATASETS``): neither an error nor data.
_HELD = "held"


class ReaderStatus(TypedDict):
    status: Status
    reason: str | None


def status_of(outcome: str) -> ReaderStatus:
    note = outcome.strip()
    head, _, rest = note.partition("|")
    if head in _EMPTY:
        return {"status": "empty", "reason": head}
    if head == _WAITING:
        return {"status": "blocked", "reason": "budget"}
    if head.startswith("blocked:"):
        return {"status": "blocked", "reason": head.removeprefix("blocked:") or None}
    if head in ("fresh", "skipped"):
        return {"status": "ok", "reason": head}
    if head == "done" or head.startswith("done:"):
        return _done(head.removeprefix("done").removeprefix(":"), rest)
    return {"status": "error", "reason": note[:160] or None}


def _done(summary: str, note: str) -> ReaderStatus:
    """``done:<dataset>=<post outcome>,...``: an upload Juli refused is an error; any accepted
    upload is ok; only empty / not-yet-finished (``ignored``) answers is empty."""
    results = [
        value
        for key, _, value in (pair.partition("=") for pair in summary.split(",") if pair)
        if not key.startswith("ads_entries_skipped") and value != _HELD
    ]
    if any(v in _REFUSED for v in results):
        return {"status": "error", "reason": summary[:160]}
    if any(v in _ACCEPTED for v in results):
        return {"status": "ok", "reason": None}
    if (results and all(v in _NOTHING for v in results)) or note in _EMPTY:
        return {"status": "empty", "reason": note or "empty"}
    return {"status": "ok", "reason": None}


def statuses(outcomes: dict[str, str]) -> dict[str, ReaderStatus]:
    return {reader: status_of(str(outcome)) for reader, outcome in outcomes.items()}
