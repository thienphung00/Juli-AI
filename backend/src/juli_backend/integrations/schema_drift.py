"""Runtime API schema drift reporting, shared by every platform client (D31.10).

A platform can drop, rename or add a response field without notice. A client that
reads ``row.get("gmv")`` then silently gets ``None`` and the numbers go quietly
wrong. Instead, after a successful call, the client passes the response payload
and the fields it relies on to :func:`report_schema_drift`, which logs ONE
structured ``api_schema_drift`` warning per (platform, endpoint, drift) per process:

* ``missing``    — expected fields absent from the payload (Juli reads them);
* ``unexpected`` — fields present under the same parent objects that are neither
  expected nor documented (the platform added something; usually harmless, worth a
  look against the weekly ``apiwatch`` report).

Field paths use ``a.b`` for members and ``a[].b`` for members of the objects in
array ``a``. A field under a list counts as present when ANY item has it (optional
per-row fields are not "missing"), and an empty or absent list proves nothing about
its children, so they are not reported.

The check never raises and never changes the payload: a drift report is a signal,
never a failure.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

EVENT = "api_schema_drift"
MAX_LIST_ITEMS = 50
MAX_REPORTED_FIELDS = 50

_seen: set[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = set()
_seen_lock = threading.Lock()


@dataclass(frozen=True, slots=True)
class SchemaDrift:
    platform: str
    endpoint: str
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]


def _split(path: str) -> tuple[str, str]:
    parent, _, name = path.rpartition(".")
    return parent, name


def _containers(payload: Any, parent: str) -> list[dict[str, Any]] | None:
    """The dicts at ``parent`` (fanning out over ``[]`` segments).

    ``None`` when the parent cannot be observed (absent, null, an empty list).
    """
    nodes: list[Any] = [payload]
    if parent:
        for segment in parent.split("."):
            is_list = segment.endswith("[]")
            key = segment[:-2] if is_list else segment
            nxt: list[Any] = []
            for node in nodes:
                if not isinstance(node, dict) or key not in node:
                    continue
                value = node[key]
                if is_list:
                    if isinstance(value, list):
                        nxt.extend(value[:MAX_LIST_ITEMS])
                elif value is not None:
                    nxt.append(value)
            nodes = nxt
    dicts = [n for n in nodes if isinstance(n, dict)]
    return dicts or None


def find_drift(
    payload: Any,
    expected: Iterable[str],
    documented: Iterable[str] = (),
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``(missing, unexpected)`` field paths for one payload. Pure."""
    expected_set = {p for p in expected if p}
    known_by_parent: dict[str, set[str]] = {}
    for path in expected_set | {p for p in documented if p}:
        # Every ancestor is known too: ``skus[].price.sale_price`` makes ``skus``
        # known at the root and ``price`` known under ``skus[]``.
        while path:
            parent, name = _split(path)
            known_by_parent.setdefault(parent, set()).add(name.removesuffix("[]"))
            path = parent
    parents = {_split(p)[0] for p in expected_set}

    observed: dict[str, set[str] | None] = {}
    for parent in parents:
        dicts = _containers(payload, parent)
        observed[parent] = None if dicts is None else {k for d in dicts for k in d}

    missing = []
    for path in sorted(expected_set):
        parent, name = _split(path)
        keys = observed.get(parent)
        if keys is not None and name not in keys:
            missing.append(path)
    unexpected = []
    for parent in sorted(parents):
        keys = observed.get(parent)
        if keys is None:
            continue
        for name in sorted(keys - known_by_parent.get(parent, set())):
            unexpected.append(f"{parent}.{name}" if parent else name)
    return tuple(missing), tuple(sorted(unexpected))


def report_schema_drift(
    platform: str,
    endpoint: str,
    payload: Any,
    expected: Iterable[str],
    *,
    documented: Iterable[str] = (),
    log: logging.Logger | None = None,
) -> SchemaDrift | None:
    """Compare ``payload`` with the fields a client relies on; log drift once.

    Returns the drift (also when it was already logged this process), or ``None``
    when the payload matches. Never raises.
    """
    try:
        missing, unexpected = find_drift(payload, expected, documented)
        if not missing and not unexpected:
            return None
        drift = SchemaDrift(platform, endpoint, missing, unexpected)
        key = (platform, endpoint, missing, unexpected)
        with _seen_lock:
            first = key not in _seen
            _seen.add(key)
        if first:
            (log or logger).warning(
                EVENT,
                extra={
                    "event": EVENT,
                    "platform": platform,
                    "endpoint": endpoint,
                    "missing_fields": list(missing[:MAX_REPORTED_FIELDS]),
                    "unexpected_fields": list(unexpected[:MAX_REPORTED_FIELDS]),
                    "missing_count": len(missing),
                    "unexpected_count": len(unexpected),
                },
            )
        return drift
    except Exception:  # a drift check must never break the call it watches
        logger.debug("schema drift check failed", exc_info=True)
        return None


def reset_seen() -> None:
    """Forget what was logged (tests)."""
    with _seen_lock:
        _seen.clear()
