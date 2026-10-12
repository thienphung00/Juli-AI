"""Assemble, carry over, size-check and serialize a platform snapshot.

The committed snapshot is deterministic: sorted keys, no fetch timestamps, no
source status (that goes to the report), so an unchanged platform produces a
byte-identical file and a changed one a minimal diff.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apiwatch import SCHEMA_VERSION

SECTIONS = ("endpoints", "webhooks", "changelog")
MAX_BYTES = 5 * 1024 * 1024


def _matches(record: dict[str, Any], key: str, failure: dict[str, Any]) -> bool:
    for field, value in failure.items():
        if field == "section":
            continue
        if field == "key":
            if key != value:
                return False
        elif record.get(field) != value:
            return False
    return True


def carry_over(
    old: dict[str, Any] | None, new: dict[str, Any], failed: list[dict[str, Any]]
) -> int:
    """Keep the old record for anything this run could not fetch. Returns the count.

    A failure names its section and the record fields that identify it (``url``,
    ``name``, ``title``, ``key``...); a failure with only a section covers the
    whole section (a source that was down).
    """
    if not old:
        return 0
    kept = 0
    for section in SECTIONS:
        failures = [f for f in failed if f.get("section") == section]
        if not failures:
            continue
        for key, record in (old.get(section) or {}).items():
            if key in new[section]:
                continue
            if any(_matches(record, key, f) for f in failures):
                new[section][key] = record
                kept += 1
    old_sdk = old.get("sdk") or {}
    for repo, record in old_sdk.items():
        new.setdefault("sdk", {}).setdefault(repo, record)
    return kept


def build(
    platform: str,
    normalized: dict[str, Any],
    sdk: dict[str, Any],
    old: dict[str, Any] | None,
    sdk_repos: tuple[str, ...] = (),
) -> tuple[dict[str, Any], int]:
    snap: dict[str, Any] = {
        "platform": platform,
        "schema_version": SCHEMA_VERSION,
        "compact": False,
        "endpoints": dict(normalized.get("endpoints") or {}),
        "webhooks": dict(normalized.get("webhooks") or {}),
        "changelog": dict(normalized.get("changelog") or {}),
        "sdk": dict(sdk or {}),
    }
    kept = carry_over(old, snap, list(normalized.get("_failed") or []))
    if sdk_repos:  # drop repos no longer watched
        snap["sdk"] = {r: v for r, v in snap["sdk"].items() if r in sdk_repos}
    return snap, kept


def compact(snap: dict[str, Any]) -> dict[str, Any]:
    """Field paths only (types and required flags dropped) — the >5 MB fallback."""
    out = json.loads(json.dumps(snap))
    out["compact"] = True
    for record in out["endpoints"].values():
        for part in ("request", "response"):
            if isinstance(record.get(part), dict):
                record[part] = sorted(record[part])
    for record in out["webhooks"].values():
        if isinstance(record.get("fields"), dict):
            record["fields"] = sorted(record["fields"])
    return out


def dumps(snap: dict[str, Any]) -> str:
    return json.dumps(snap, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def fit(snap: dict[str, Any], max_bytes: int = MAX_BYTES) -> tuple[dict[str, Any], str]:
    text = dumps(snap)
    if len(text.encode("utf-8")) <= max_bytes:
        return snap, text
    small = compact(snap)
    return small, dumps(small)


def load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
