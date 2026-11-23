"""The minimum Juli Connector version the ingest routes accept (R7 / P3).

One place: ``check`` is called once from the ingest auth dependency. A request that names
its version (``X-Connector-Version`` header, or the body's ``source_version`` when the header
is absent) and is older than the minimum is refused with ``connector_upgrade_required``
before anything is written.

A request that names no (parseable) version is refused too when its token was made by a Juli
Connector (``from_connector``: an install id, or the Connector's own "Juli Connector <v>" label):
every Connector since 0.3.24 sends the header on every call, so a silent one is older. Tokens made
for the export loader scripts (``scripts/load_shopee_exports.py``) send no Connector version and
stay allowed (batch-1123-a C5a).
"""

from __future__ import annotations

import os
import re

DEFAULT_MIN_VERSION = "0.3.31"
#: The label a Juli Connector gives its token at pairing (``Juli Connector <version>``).
CONNECTOR_LABEL_PREFIX = "Juli Connector"
ENV_MIN_VERSION = "CONNECTOR_MIN_VERSION"
UPGRADE_CODE = "connector_upgrade_required"

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def parse(version: str | None) -> tuple[int, int, int] | None:
    """``0.3.25`` -> (0, 3, 25); anything that is not a dotted version -> None."""
    match = _VERSION.match((version or "").strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def minimum() -> str:
    """The minimum (env ``CONNECTOR_MIN_VERSION``); the default when unset or malformed."""
    raw = os.environ.get(ENV_MIN_VERSION, "").strip()
    return raw if parse(raw) is not None else DEFAULT_MIN_VERSION


def is_too_old(version: str | None) -> bool:
    """True only for a present, parseable version below the minimum."""
    got = parse(version)
    if got is None:
        return False
    floor = parse(minimum())
    return floor is not None and got < floor


def made_by_connector(install_id: str | None, client_label: str | None) -> bool:
    """A token a Juli Connector paired: it sent an install id, or kept its default label."""
    return bool(install_id) or (client_label or "").startswith(CONNECTOR_LABEL_PREFIX)


def refuses(version: str | None, *, from_connector: bool) -> bool:
    """True when the ingest routes must answer 426: a version below the minimum, or a Connector
    token whose request names no parseable version."""
    if parse(version) is None:
        return from_connector
    return is_too_old(version)
