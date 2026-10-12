"""TikTok Shop Partner Center docs (docv2): the JSON API behind the public doc site.

The doc site (partner.tiktokshop.com/docv2) is a client-rendered app; its own
data calls work without login:

* ``/api/v1/document/tree?workspace_id=3`` — every page: id, name, parent,
  ``doc_type`` (1 API reference, 2 guide incl. webhook pages, 3 changelog,
  10 API overview), ``document_path`` (the docv2 slug), ``update_time``, badges.
  The tree lists only the NEWEST version of each API.
* ``/api/v1/document/api_external/list?document_id=X&api_config_version=2`` —
  every published version of that API (older versions Juli may still pin).
* ``/api/v1/document/api_meta?src_document_id=X`` — one API version: path,
  method, header/query/path/body params, response params (flat list, depth as a
  ``^`` prefix), scopes. Some ids answer with ``document_api_meta: null`` (the
  "errors" a previous scrape saw); those are recorded and their last snapshot
  record is kept.
* ``/api/v1/document/detail?document_id=X&workspace_id=3`` — markdown content of
  a guide/webhook/changelog page.

Workspace 3 is production docv2 (4 is the test environment), from the site's JS.
The official TikTok Shop SDK is generated per app inside Partner Center (login),
so there is no public release feed; the watcher tracks the most-used community
SDK and TikTok's official API-for-Business SDK (ads spend, D31.9) instead.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from apiwatch.fetch import Fetcher, FetchError
from apiwatch.normalize import (
    api_path_mentions,
    extract_json_blocks,
    flatten_caret_list,
    json_field_paths,
    looks_deprecated,
    markdown_table_fields,
    path_template,
    short_hash,
)

BASE = "https://partner.tiktokshop.com/api/v1/document"
PAGE_URL = "https://partner.tiktokshop.com/docv2/page/{slug}"
WORKSPACE = 3
SDK_REPOS = ("EcomPHP/tiktokshop-php", "tiktok/tiktok-business-api-sdk")
_METHOD = {1: "POST", 2: "GET", 3: "PUT", 4: "DELETE"}
_RELEASE_DATE = re.compile(r"Release date:\s*\**\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
_WEBHOOK_CODE = re.compile(r"^\s*\((\d+)\)")
_VERSION = re.compile(r"^/[a-z_]+/(\d{6})/")
_BADGES_DEPRECATION = {"deprecation", "breaking change", "sunset"}


def _ymd(epoch: Any) -> str:
    try:
        return datetime.fromtimestamp(int(epoch), tz=UTC).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def _ok(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("code") != 0:
        code = payload.get("code") if isinstance(payload, dict) else None
        message = payload.get("message") if isinstance(payload, dict) else None
        raise FetchError(f"doc API answered code={code} message={message}")
    return payload.get("data") or {}


class Tree:
    """Index over the document tree."""

    def __init__(self, nodes: list[dict[str, Any]]):
        self.nodes = [n for n in nodes if isinstance(n, dict) and n.get("document_id")]
        self.by_id = {n["document_id"]: n for n in self.nodes}

    def trail(self, node: dict[str, Any]) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        current: dict[str, Any] | None = node
        while current and current["document_id"] not in seen:
            seen.add(current["document_id"])
            names.append(str(current.get("name") or "").strip())
            current = self.by_id.get(current.get("parent_id") or "")
        return list(reversed(names))

    def leaves(self, doc_type: int) -> list[dict[str, Any]]:
        return sorted(
            (n for n in self.nodes if n.get("doc_type") == doc_type and not n.get("is_dir")),
            key=lambda n: n["document_id"],
        )

    def api_docs(self) -> list[dict[str, Any]]:
        return [n for n in self.leaves(1) if n.get("is_api_doc")]

    def webhook_docs(self) -> list[dict[str, Any]]:
        return [n for n in self.leaves(2) if self.trail(n)[0] == "Webhooks"]

    def changelog_docs(self) -> list[dict[str, Any]]:
        return self.leaves(3)


def fetch_raw(fetcher: Fetcher, *, limit: int | None = None) -> dict[str, Any]:
    raw: dict[str, Any] = {"errors": {}, "versions": {}, "meta": {}, "pages": {}}
    try:
        tree_data = _ok(fetcher.get_json(f"{BASE}/tree", params={"workspace_id": WORKSPACE}))
        raw["tree"] = tree_data.get("document_tree") or []
    except FetchError as exc:
        raw["errors"]["tree"] = str(exc)
        raw["tree"] = None
        return raw
    tree = Tree(raw["tree"])
    apis = tree.api_docs()
    for node in apis[:limit] if limit else apis:
        doc_id = node["document_id"]
        try:
            listing = _ok(
                fetcher.get_json(
                    f"{BASE}/api_external/list",
                    params={"document_id": doc_id, "api_config_version": 2},
                )
            )
            versions = listing.get("api_external_list") or []
        except FetchError as exc:
            raw["errors"][f"versions:{doc_id}"] = str(exc)
            versions = []
        listed = {
            str(v["external_doc_id"]): str(v.get("document_path") or "")
            for v in versions
            if v.get("external_doc_id")
        }
        if not listed:
            listed = {doc_id: str(node.get("document_path") or "")}
        raw["versions"][doc_id] = [{"id": i, "slug": listed[i]} for i in sorted(listed)]
        for version in raw["versions"][doc_id]:
            version_id = version["id"]
            if version_id in raw["meta"]:
                continue
            try:
                raw["meta"][version_id] = _ok(
                    fetcher.get_json(f"{BASE}/api_meta", params={"src_document_id": version_id})
                )
            except FetchError as exc:
                raw["meta"][version_id] = {"__error__": str(exc)}
    pages = tree.webhook_docs() + tree.changelog_docs()
    for node in pages[:limit] if limit else pages:
        doc_id = node["document_id"]
        try:
            raw["pages"][doc_id] = _ok(
                fetcher.get_json(
                    f"{BASE}/detail", params={"document_id": doc_id, "workspace_id": WORKSPACE}
                )
            )
        except FetchError as exc:
            raw["pages"][doc_id] = {"__error__": str(exc)}
    return raw


def normalize_api_meta(meta: dict[str, Any], module: str) -> tuple[str, dict[str, Any]] | None:
    api = meta.get("document_api_meta")
    if not isinstance(api, dict) or not api.get("interface_path"):
        return None
    path = path_template_keep_names(str(api["interface_path"]))
    method = _METHOD.get(api.get("method"), "POST" if api.get("is_post_method") else "GET")
    version_match = _VERSION.match(path)
    request: dict[str, Any] = {}
    for location, key in (
        ("path", "request_path_param"),
        ("query", "request_query_param"),
        ("header", "request_header_param"),
        ("body", "request_body_param"),
    ):
        for field, spec in flatten_caret_list(api.get(key) or []).items():
            request[f"{location}.{field}"] = spec
    response = flatten_caret_list(api.get("response_param") or [], with_required=False)
    title = str(api.get("title") or "").strip()
    record = {
        "title": title,
        "module": module,
        "path": path,
        "method": method,
        "version": version_match.group(1) if version_match else "",
        "deprecated": looks_deprecated(title, str(api.get("env_desc") or "")),
        "scopes": sorted(
            {
                str(s.get("package_name"))
                for s in api.get("scope_list") or []
                if s.get("package_name")
            }
        ),
        "request": request,
        "response": response,
        "url": PAGE_URL.format(slug=api.get("document_path") or meta.get("document_id", "")),
    }
    return f"{method} {path}", record


def path_template_keep_names(path: str) -> str:
    """Keep the documented placeholder names (readable), trim a trailing slash."""
    text = path.strip()
    return text.rstrip("/") if len(text) > 1 else text


def _mentions(text: str, titles: list[str]) -> list[str]:
    found = []
    for title in titles:
        if re.search(rf"(?<![A-Za-z]){re.escape(title)}(?![A-Za-z])", text, flags=re.IGNORECASE):
            found.append(title)
    return sorted(set(found))


def _webhook_fields(content: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for block in extract_json_blocks(content):
        if isinstance(block, dict) and "data" in block:
            fields.update(json_field_paths(block))
            break
    for path, spec in markdown_table_fields(content).items():
        key = path if path in fields else f"data.{path}"
        if key not in fields:
            fields[key] = spec
    return dict(sorted(fields.items()))


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("tree") is None:
        return {
            "endpoints": {},
            "webhooks": {},
            "changelog": {},
            "_failed": [{"section": s} for s in ("endpoints", "webhooks", "changelog")],
            "_errors": raw.get("errors", {}),
        }
    tree = Tree(raw["tree"])
    endpoints: dict[str, Any] = {}
    failed: list[str] = []
    for node in tree.api_docs():
        trail = tree.trail(node)
        module = trail[1] if len(trail) > 2 else (trail[0] if trail else "")
        if f"versions:{node['document_id']}" in (raw.get("errors") or {}):
            # Older versions unknown this run: keep every record with this title.
            failed.append({"section": "endpoints", "title": str(node.get("name") or "").strip()})
        for version in (raw.get("versions") or {}).get(node["document_id"], []):
            meta = (raw.get("meta") or {}).get(version["id"])
            result = None
            if isinstance(meta, dict) and "__error__" not in meta:
                result = normalize_api_meta(meta, module)
            if result is None:
                failed.append(
                    {
                        "section": "endpoints",
                        "url": PAGE_URL.format(slug=version["slug"] or version["id"]),
                    }
                )
                continue
            key, record = result
            if key in endpoints:  # two doc ids for one path: keep the newer tree node's
                continue
            endpoints[key] = record

    titles = sorted({e["title"] for e in endpoints.values() if e["title"]}, key=len, reverse=True)
    webhooks: dict[str, Any] = {}
    changelog: dict[str, Any] = {}
    pages = raw.get("pages") or {}
    for node in tree.webhook_docs():
        page = pages.get(node["document_id"])
        name = str(node.get("name") or "").strip()
        match = _WEBHOOK_CODE.match(name)
        if not isinstance(page, dict) or "__error__" in page:
            failed.append(
                {
                    "section": "webhooks",
                    "url": PAGE_URL.format(slug=node.get("document_path") or node["document_id"]),
                }
            )
            continue
        content = str(page.get("content") or "")
        code = match.group(1) if match else ""
        for block in extract_json_blocks(content):
            if isinstance(block, dict) and isinstance(block.get("type"), int):
                code = code or str(block["type"])
                break
        if not code:  # overview pages under "Webhooks" with no event code
            continue
        trail = tree.trail(node)
        webhooks[code] = {
            "name": _WEBHOOK_CODE.sub("", name).strip(),
            "category": trail[1] if len(trail) > 2 else "",
            "deprecated": looks_deprecated(name),
            "fields": _webhook_fields(content),
            "url": PAGE_URL.format(slug=node.get("document_path") or node["document_id"]),
        }
    for node in tree.changelog_docs():
        page = pages.get(node["document_id"])
        if not isinstance(page, dict) or "__error__" in page:
            failed.append({"section": "changelog", "key": node["document_id"]})
            continue
        content = str(page.get("content") or "")
        release = _RELEASE_DATE.search(content)
        badges = sorted(
            {
                str(k.get("keyword")).strip()
                for k in node.get("keywords") or []
                if str(k.get("keyword") or "").strip()
            }
        )
        title = str(node.get("name") or "").strip()
        trail = tree.trail(node)
        changelog[node["document_id"]] = {
            "date": release.group(1) if release else _ymd(node.get("update_time")),
            "title": title,
            "category": trail[1] if len(trail) > 2 else "",
            "badges": badges,
            "deprecation": looks_deprecated(title, content[:4000])
            or bool({b.lower() for b in badges} & _BADGES_DEPRECATION),
            "mentions_paths": api_path_mentions(content),
            "mentions_apis": _mentions(content, titles),
            "sha": short_hash(content),
            "url": PAGE_URL.format(slug=node.get("document_path") or node["document_id"]),
        }
    return {
        "endpoints": endpoints,
        "webhooks": webhooks,
        "changelog": changelog,
        "_failed": failed,
        "_errors": dict(sorted((raw.get("errors") or {}).items())),
    }


__all__ = ["fetch_raw", "normalize", "path_template", "SDK_REPOS"]
