"""Every routed queue must be consumed by the deployed worker (issue #1205).

The defect this pins: `celery_app.py`'s `task_routes` sent the two agent tasks to
a dedicated `agent_runs` queue (ADR-074 decision 4), while
`infra/systemd/juli-celery-worker.service` started celery with **no `-Q` flag**,
so the worker consumed only the default `celery` queue. Both halves were
internally consistent — routing was correct, the worker booted cleanly — and they
disagreed only in production: every agent run returned a `celery_task_id`, then
sat at `status=queued` with zero events forever.

Nothing reconciled the application's routing with the deployment's subscription.
This test is that reconciliation, so adding a queue to `task_routes` without a
consumer fails here instead of silently stranding tasks on a live host.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_UNIT = REPO_ROOT / "infra/systemd/juli-celery-worker.service"

#: Celery's default queue, consumed when no -Q is given and required by every
#: non-agent task. Listing `-Q` at all makes it explicit, so it must stay named.
DEFAULT_QUEUE = "celery"


def _routed_queues() -> set[str]:
    """Queue names the application actually routes tasks to."""
    from juli_backend.workers.celery_app import celery_app

    routes = celery_app.conf.task_routes or {}
    return {
        spec["queue"] for spec in routes.values() if isinstance(spec, dict) and spec.get("queue")
    }


def _unit_consumed_queues() -> set[str]:
    """Queue names the deployed worker subscribes to, parsed from its ExecStart.

    Reads the unit file rather than a copy of the flag, so the assertion is
    against the artifact that is actually installed on the host.
    """
    text = WORKER_UNIT.read_text(encoding="utf-8")
    # Join the line-continued ExecStart into one logical line first.
    joined = re.sub(r"\\\s*\n\s*", " ", text)
    match = re.search(r"^ExecStart=.*$", joined, re.MULTILINE)
    assert match, "no ExecStart= line in the worker unit"
    exec_start = match.group(0)
    q = re.search(r"(?:-Q|--queues)[=\s]+([A-Za-z0-9_,\-]+)", exec_start)
    if not q:
        return set()
    return {name.strip() for name in q.group(1).split(",") if name.strip()}


def test_worker_unit_declares_a_queue_list():
    """With no -Q, celery silently consumes only the default queue -- which is
    exactly how `agent_runs` ended up with no consumer."""
    assert _unit_consumed_queues(), (
        "juli-celery-worker.service starts celery with no -Q flag, so it consumes "
        "only the default queue. Any task routed elsewhere is stranded."
    )


def test_every_routed_queue_is_consumed_by_the_worker():
    routed = _routed_queues()
    consumed = _unit_consumed_queues()
    missing = routed - consumed
    assert not missing, (
        f"task_routes send tasks to {sorted(missing)}, which the deployed worker does "
        f"not consume (it subscribes to {sorted(consumed)}). Tasks routed to an "
        "unconsumed queue enqueue successfully and then never run -- add the queue to "
        "-Q in infra/systemd/juli-celery-worker.service."
    )


def test_default_queue_is_still_consumed():
    """Adding -Q is what makes this necessary: naming only `agent_runs` would
    strand every ordinary task instead. The fix must not trade one silent
    breakage for another."""
    assert DEFAULT_QUEUE in _unit_consumed_queues(), (
        f"the worker must keep consuming the default {DEFAULT_QUEUE!r} queue; "
        "every non-agent task routes there"
    )


@pytest.mark.parametrize(
    "task_name",
    ["juli_backend.run_agent_workflow", "juli_backend.resume_agent_workflow"],
)
def test_the_two_agent_tasks_route_to_a_consumed_queue(task_name):
    """Named explicitly: these are the two whose stranding produced runs stuck at
    `queued` with zero events."""
    from juli_backend.workers.celery_app import celery_app

    routes = celery_app.conf.task_routes or {}
    queue = routes.get(task_name, {}).get("queue")
    assert queue, f"{task_name} has no routed queue"
    assert queue in _unit_consumed_queues(), (
        f"{task_name} routes to {queue!r}, which the worker unit does not consume"
    )
