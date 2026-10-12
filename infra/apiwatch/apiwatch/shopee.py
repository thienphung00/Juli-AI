"""Shopee Open Platform v2: public doc JSON at open.shopee.com/opservice/api/v1/.

Sources (no login): ``doc/module/?version=2`` (module + API tree),
``doc/api/?api_name=v2.x.y&version=2`` (one API), ``push/category`` and
``push/doc?push_api_id=N`` (push catalog), ``developer_guide/list`` (guides).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from apiwatch.fetch import Fetcher, FetchError
from apiwatch.normalize import flatten_tree, looks_deprecated, short_hash

BASE = "https://open.shopee.com/opservice/api/v1"
DOC_URL = "https://open.shopee.com/documents/v2/{name}?module={module}&type=1"
SDK_REPOS = ("congminh1254/shopee-sdk",)
_METHOD = {1: "POST", 2: "GET"}


def _loads(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value) if value.strip() else None
        except ValueError:
            return None
    return value


def _ymd(epoch: Any) -> str:
    try:
        return datetime.fromtimestamp(int(epoch), tz=UTC).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def api_names(modules: dict[str, Any]) -> list[tuple[str, str, int]]:
    """``[(api_name, module_name, module_id)]`` for every live API in the tree."""
    out = []
    for module in modules.get("modules") or []:
        if module.get("type") != 1:
            continue
        for item in module.get("items") or []:
            if item.get("type") == 1 and item.get("status", 1) == 1 and item.get("name"):
                # Keep the name as published: the per-API endpoint needs it verbatim
                # (one name carries a leading space).
                out.append((str(item["name"]), module["module_name"], module["module_id"]))
    return sorted(set(out))


def fetch_raw(fetcher: Fetcher, *, limit: int | None = None) -> dict[str, Any]:
    raw: dict[str, Any] = {"errors": {}, "apis": {}, "push": {}}
    try:
        raw["modules"] = fetcher.get_json(f"{BASE}/doc/module/", params={"version": 2})
    except FetchError as exc:
        raw["errors"]["modules"] = str(exc)
        raw["modules"] = None
    names = api_names(raw["modules"] or {})
    for name, _module, _mid in names[:limit] if limit else names:
        try:
            raw["apis"][name] = fetcher.get_json(
                f"{BASE}/doc/api/", params={"api_name": name, "version": 2}
            )
        except FetchError as exc:
            raw["apis"][name] = {"__error__": str(exc)}
    try:
        raw["push_category"] = fetcher.get_json(f"{BASE}/push/category")
    except FetchError as exc:
        raw["errors"]["push_category"] = str(exc)
        raw["push_category"] = None
    for category in (raw.get("push_category") or {}).get("category") or []:
        for push in category.get("push") or []:
            pid = push.get("push_api_id")
            try:
                raw["push"][str(pid)] = fetcher.get_json(
                    f"{BASE}/push/doc", params={"push_api_id": pid}
                )
            except FetchError as exc:
                raw["push"][str(pid)] = {"__error__": str(exc)}
    try:
        raw["guides"] = fetcher.get_json(
            f"{BASE}/developer_guide/list", params={"language_code": "en"}
        )
    except FetchError as exc:
        raw["errors"]["guides"] = str(exc)
        raw["guides"] = None
    return raw


def normalize_api(doc: dict[str, Any], module_name: str) -> tuple[str, dict[str, Any]]:
    path = str(doc.get("path") or "").strip()
    method = _METHOD.get(doc.get("method"), "GET" if doc.get("is_get_method") else "POST")
    params = _loads(doc.get("params")) or {}
    name = str(doc.get("api_name") or "").strip()
    record = {
        "name": name,
        "module": module_name,
        "path": path,
        "method": method,
        "deprecated": looks_deprecated(doc.get("define"), name),
        "permissions": sorted({str(p) for p in doc.get("api_permission") or []}),
        "request": flatten_tree(params.get("request_params")),
        "response": flatten_tree(params.get("response_params"), with_required=False),
        "url": DOC_URL.format(name=name, module=doc.get("module_id", "")),
    }
    return f"{method} {path}", record


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    endpoints: dict[str, Any] = {}
    changelog: dict[str, Any] = {}
    failed: list[str] = []
    module_of = {name: module for name, module, _ in api_names(raw.get("modules") or {})}
    for name, doc in sorted((raw.get("apis") or {}).items()):
        if not isinstance(doc, dict) or "__error__" in doc or not doc.get("path"):
            failed.append({"section": "endpoints", "name": name.strip()})
            failed.append({"section": "changelog", "api": name.strip()})
            continue
        key, record = normalize_api(doc, module_of.get(name, str(doc.get("module_name") or "")))
        endpoints[key] = record
        for log in doc.get("update_log_list") or []:
            text = str(log.get("content") or "").strip()
            date = str(log.get("date") or "")
            entry_key = f"api:{record['name']}:{date}:{short_hash(text)}"
            changelog[entry_key] = {
                "date": date,
                "title": f"{record['name']}: {text[:300]}",
                "endpoint": key,
                "api": record["name"],
                "deprecation": looks_deprecated(text),
            }

    webhooks: dict[str, Any] = {}
    category_of: dict[str, str] = {}
    for category in (raw.get("push_category") or {}).get("category") or []:
        for push in category.get("push") or []:
            category_of[str(push.get("push_api_id"))] = category.get("category_name", "")
    for pid, doc in sorted((raw.get("push") or {}).items()):
        api = (doc or {}).get("push_api") if isinstance(doc, dict) else None
        if not api:
            failed.append(
                {"section": "webhooks", "push_api_id": int(pid) if pid.isdigit() else pid}
            )
            continue
        code = str(api.get("push_code"))
        name = str(api.get("push_api_name") or "")
        webhooks[code] = {
            "name": name,
            "push_api_id": api.get("push_api_id"),
            "category": category_of.get(pid, ""),
            "deprecated": looks_deprecated(api.get("description"), name),
            "fields": flatten_tree(_loads(api.get("push_params")) or [], with_required=False),
        }
        for log in doc.get("update_logs") or []:
            text = str(log.get("description") or "").strip()
            changelog[f"push:{name}:{log.get('ctime')}"] = {
                "date": _ymd(log.get("ctime")),
                "title": f"push {name} (code {code}): {text[:300]}",
                "webhook": code,
                "deprecation": looks_deprecated(text),
            }

    def walk_guides(items: list[dict[str, Any]], trail: str) -> None:
        for item in items or []:
            title = str(item.get("item_name") or "").strip()
            if item.get("children"):
                walk_guides(item["children"], f"{trail}{title} > ")
            elif item.get("item_type") == 2 and item.get("status", 1) == 1:
                changelog[f"guide:{item.get('item_id')}"] = {
                    "date": _ymd(item.get("release_time")),
                    "title": f"guide: {trail}{title}",
                    "deprecation": looks_deprecated(title),
                }

    walk_guides((raw.get("guides") or {}).get("developer_guide_list") or [], "")
    # A whole source down: every record of that section is "unknown", not "removed".
    if raw.get("modules") is None:
        failed.append({"section": "endpoints"})
    if raw.get("push_category") is None:
        failed.append({"section": "webhooks"})
    if raw.get("guides") is None or raw.get("modules") is None or raw.get("push_category") is None:
        failed.append({"section": "changelog"})

    return {
        "endpoints": endpoints,
        "webhooks": webhooks,
        "changelog": changelog,
        "_failed": failed,
        "_errors": dict(sorted((raw.get("errors") or {}).items())),
    }
