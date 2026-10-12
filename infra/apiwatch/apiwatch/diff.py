"""Snapshot diff -> ordered list of changes (pure; deterministic order)."""

from __future__ import annotations

from typing import Any

SECTION_ORDER = {"endpoints": 0, "webhooks": 1, "changelog": 2, "sdk": 3}


def _fields(value: Any) -> dict[str, dict[str, Any]]:
    """Accept both the full form ``{path: spec}`` and the compact form ``[path]``."""
    if isinstance(value, dict):
        return {k: (v if isinstance(v, dict) else {}) for k, v in value.items()}
    if isinstance(value, list):
        return {k: {} for k in value}
    return {}


def _describe(spec: dict[str, Any]) -> str:
    parts = []
    if spec.get("type"):
        parts.append(str(spec["type"]))
    if spec.get("required"):
        parts.append("bắt buộc")
    return f" ({', '.join(parts)})" if parts else ""


def field_changes(label: str, old: Any, new: Any) -> list[str]:
    a, b = _fields(old), _fields(new)
    lines = []
    for path in sorted(b.keys() - a.keys()):
        lines.append(f"{label} + `{path}`{_describe(b[path])}")
    for path in sorted(a.keys() - b.keys()):
        lines.append(f"{label} − `{path}`")
    for path in sorted(a.keys() & b.keys()):
        before, after = a[path], b[path]
        notes = []
        if before.get("type") and after.get("type") and before["type"] != after["type"]:
            notes.append(f"kiểu {before['type']} → {after['type']}")
        if "required" in before and "required" in after and before["required"] != after["required"]:
            notes.append("thành bắt buộc" if after["required"] else "thành không bắt buộc")
        if notes:
            lines.append(f"{label} ~ `{path}`: {', '.join(notes)}")
    return lines


def _set_change(label: str, old: Any, new: Any) -> list[str]:
    a, b = set(old or []), set(new or [])
    lines = [f"{label} + {x}" for x in sorted(b - a)]
    lines += [f"{label} − {x}" for x in sorted(a - b)]
    return lines


def _change(
    section: str, kind: str, key: str, record: dict[str, Any], **extra: Any
) -> dict[str, Any]:
    return {"section": section, "kind": kind, "key": key, "record": record, "details": [], **extra}


def diff_endpoints(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for key in sorted(new.keys() - old.keys()):
        out.append(
            _change(
                "endpoints", "added", key, new[key], deprecation=bool(new[key].get("deprecated"))
            )
        )
    for key in sorted(old.keys() - new.keys()):
        out.append(_change("endpoints", "removed", key, old[key], deprecation=False))
    for key in sorted(old.keys() & new.keys()):
        a, b = old[key], new[key]
        details = []
        if a.get("title") != b.get("title") and a.get("title") is not None:
            details.append(f"tên: {a.get('title')} → {b.get('title')}")
        details += _set_change("scope", a.get("scopes"), b.get("scopes"))
        details += _set_change("quyền app", a.get("permissions"), b.get("permissions"))
        details += field_changes("request", a.get("request"), b.get("request"))
        details += field_changes("response", a.get("response"), b.get("response"))
        became_deprecated = bool(b.get("deprecated")) and not a.get("deprecated")
        if became_deprecated:
            details.insert(0, "được đánh dấu deprecated/sunset trong mô tả")
        elif a.get("deprecated") and not b.get("deprecated"):
            details.insert(0, "không còn ghi deprecated")
        if details:
            change = _change("endpoints", "changed", key, b, deprecation=became_deprecated)
            change["details"] = details
            out.append(change)
    return out


def diff_webhooks(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for key in sorted(new.keys() - old.keys(), key=_code_order):
        out.append(_change("webhooks", "added", key, new[key], deprecation=False))
    for key in sorted(old.keys() - new.keys(), key=_code_order):
        out.append(_change("webhooks", "removed", key, old[key], deprecation=False))
    for key in sorted(old.keys() & new.keys(), key=_code_order):
        a, b = old[key], new[key]
        details = []
        if a.get("name") != b.get("name"):
            details.append(f"tên: {a.get('name')} → {b.get('name')}")
        details += field_changes("field", a.get("fields"), b.get("fields"))
        became_deprecated = bool(b.get("deprecated")) and not a.get("deprecated")
        if became_deprecated:
            details.insert(0, "được đánh dấu deprecated")
        if details:
            change = _change("webhooks", "changed", key, b, deprecation=became_deprecated)
            change["details"] = details
            out.append(change)
    return out


def _code_order(key: str) -> tuple[int, str]:
    return (int(key), key) if key.isdigit() else (10**9, key)


def diff_changelog(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    added = sorted(
        new.keys() - old.keys(), key=lambda k: (new[k].get("date") or "", k), reverse=True
    )
    for key in added:
        out.append(
            _change(
                "changelog", "added", key, new[key], deprecation=bool(new[key].get("deprecation"))
            )
        )
    for key in sorted(old.keys() & new.keys()):
        a, b = old[key], new[key]
        if a.get("sha") and b.get("sha") and a["sha"] != b["sha"]:
            change = _change("changelog", "updated", key, b, deprecation=bool(b.get("deprecation")))
            change["details"] = ["nội dung trang được sửa"]
            out.append(change)
    return out


def diff_sdk(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for repo in sorted(new):
        b = new[repo]
        a = old.get(repo)
        if a is None:
            continue  # newly watched repo: baseline only
        if b.get("latest") and b.get("latest") != a.get("latest"):
            fresh = [t for t in b.get("recent") or [] if t not in set(a.get("recent") or [])]
            change = _change("sdk", "release", repo, b, deprecation=False)
            change["details"] = [
                f"{a.get('latest') or '—'} → {b['latest']} ({b.get('published') or '?'})"
            ]
            if len(fresh) > 1:
                change["details"].append("các bản mới: " + ", ".join(fresh))
            out.append(change)
    return out


def diff_snapshots(old: dict[str, Any] | None, new: dict[str, Any]) -> list[dict[str, Any]]:
    if not old:
        return []
    changes = (
        diff_endpoints(old.get("endpoints") or {}, new.get("endpoints") or {})
        + diff_webhooks(old.get("webhooks") or {}, new.get("webhooks") or {})
        + diff_changelog(old.get("changelog") or {}, new.get("changelog") or {})
        + diff_sdk(old.get("sdk") or {}, new.get("sdk") or {})
    )
    return changes
