"""Tag changes that touch Juli, render the markdown report (Juli items first)."""

from __future__ import annotations

from typing import Any

from apiwatch.normalize import path_template, versionless

PLATFORM_NAMES = {"tiktok": "TikTok Shop", "shopee": "Shopee"}
MAX_DETAILS = 25
MAX_CHARS = 60_000  # GitHub issue bodies cap at 65,536 characters
JULI_LABEL = {
    "used": "Juli dùng",
    "planned": "Juli dự kiến dùng (D31)",
    "related": "phiên bản khác của endpoint Juli dùng",
}


def _endpoint_path(change: dict[str, Any]) -> str:
    record = change.get("record") or {}
    path = record.get("path") or change["key"].split(" ", 1)[-1]
    return path_template(path)


def juli_titles(usage: dict[str, Any], *snapshots: dict[str, Any] | None) -> set[str]:
    """Doc titles of the endpoints Juli calls (to match changelog prose)."""
    used = usage.get("endpoints") or set()
    titles = set()
    for snap in snapshots:
        for record in ((snap or {}).get("endpoints") or {}).values():
            if path_template(record.get("path") or "") in used and record.get("title"):
                titles.add(record["title"])
    return titles


def tag_juli(
    changes: list[dict[str, Any]],
    usage: dict[str, Any],
    *,
    titles: set[str] = frozenset(),
) -> None:
    used = usage.get("endpoints") or set()
    planned = usage.get("planned_endpoints") or set()
    used_versionless = {versionless(p) for p in used}
    used_hooks = usage.get("webhooks") or set()
    planned_hook_names = usage.get("planned_webhook_names") or set()
    for change in changes:
        tag, reason = None, ""
        record = change.get("record") or {}
        if change["section"] == "endpoints":
            path = _endpoint_path(change)
            if path in used:
                tag = "used"
            elif path in planned:
                tag = "planned"
            elif versionless(path) in used_versionless:
                tag, reason = "related", "Juli đang gọi phiên bản khác của endpoint này"
        elif change["section"] == "webhooks":
            if change["key"] in used_hooks:
                tag = "used"
            elif record.get("name") in planned_hook_names:
                tag = "planned"
        elif change["section"] == "changelog":
            paths = set(record.get("mentions_paths") or [])
            endpoint = record.get("endpoint")
            if endpoint:
                paths.add(path_template(endpoint.split(" ", 1)[-1]))
            hit_paths = sorted(paths & used)
            hit_titles = sorted(set(record.get("mentions_apis") or []) & titles)
            if hit_paths or hit_titles:
                tag = "used"
                reason = "nhắc tới: " + ", ".join([f"`{p}`" for p in hit_paths] + hit_titles)
            elif paths & planned:
                tag = "planned"
            elif record.get("webhook") and record["webhook"] in used_hooks:
                tag = "used"
        change["juli"] = tag
        if reason:
            change["juli_reason"] = reason


def _line(change: dict[str, Any], platform: str) -> list[str]:
    record = change.get("record") or {}
    section, kind = change["section"], change["kind"]
    verb = {
        "added": "mới",
        "removed": "bị gỡ",
        "changed": "thay đổi",
        "updated": "cập nhật",
        "release": "bản mới",
    }[kind]
    url = record.get("url")
    if section == "endpoints":
        name = record.get("title") or record.get("name") or ""
        head = f"**Endpoint {verb}** `{change['key']}` {name}".rstrip()
    elif section == "webhooks":
        label = "Webhook" if platform == "tiktok" else "Push"
        head = f"**{label} {verb}** code {change['key']} {record.get('name') or ''}".rstrip()
    elif section == "changelog":
        badges = f" [{', '.join(record['badges'])}]" if record.get("badges") else ""
        title = record.get("title") or change["key"]
        head = f"**Changelog {verb}** {record.get('date') or ''} {title}{badges}"
    else:
        head = f"**SDK {verb}** `{change['key']}`"
    if url:
        head += f" — [doc]({url})"
    if change.get("deprecation"):
        head += " — **deprecation/breaking**"
    if change.get("juli"):
        head += f" — _{JULI_LABEL[change['juli']]}_"
        if change.get("juli_reason"):
            head += f" ({change['juli_reason']})"
    lines = [f"- {head}"]
    details = change.get("details") or []
    for detail in details[:MAX_DETAILS]:
        lines.append(f"  - {detail}")
    if len(details) > MAX_DETAILS:
        lines.append(
            f"  - … và {len(details) - MAX_DETAILS} thay đổi field khác"
            " (xem snapshot diff trong PR)"
        )
    return lines


def summary_counts(changes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {"total": len(changes), "juli": 0, "deprecation": 0}
    for change in changes:
        key = f"{change['section']}_{change['kind']}"
        counts[key] = counts.get(key, 0) + 1
        counts["juli"] += 1 if change.get("juli") in ("used", "related") else 0
        counts["deprecation"] += 1 if change.get("deprecation") else 0
    return counts


def render(
    platform: str,
    changes: list[dict[str, Any]],
    *,
    date: str,
    errors: dict[str, str],
    failed_count: int,
    kept_count: int,
    stats: dict[str, int],
    baseline: bool = False,
) -> str:
    name = PLATFORM_NAMES.get(platform, platform)
    counts = summary_counts(changes)
    out = [f"# apiwatch · {name} · {date}", ""]
    out.append(
        f"Snapshot: {stats.get('endpoints', 0)} endpoint, {stats.get('webhooks', 0)} webhook/push, "
        f"{stats.get('changelog', 0)} mục changelog, {stats.get('sdk', 0)} SDK."
    )
    if baseline:
        out.append("")
        out.append("Lần chạy đầu: đây là snapshot gốc, chưa có gì để so sánh.")
    if errors:
        out += ["", "**Nguồn lỗi** (phần đó giữ nguyên snapshot cũ, không tính là bị gỡ):"]
        out += [f"- `{k}`: {v}" for k, v in sorted(errors.items())]
    if failed_count:
        out += [
            "",
            f"{failed_count} trang doc không lấy được lần này; giữ bản cũ cho {kept_count} mục.",
        ]
    out += [
        "",
        f"**{counts['total']} thay đổi**, {counts['juli']} liên quan Juli, "
        f"{counts['deprecation']} deprecation/breaking. Cách xử lý: `docs/runbooks/apiwatch.md`.",
    ]

    def block(title: str, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        out.extend(["", f"## {title} ({len(items)})", ""])
        for change in items:
            out.extend(_line(change, platform))

    juli = [c for c in changes if c.get("juli") in ("used", "related")]
    rest = [c for c in changes if c not in juli]
    block("Juli dùng — xử lý trước", juli)
    block("Deprecation / breaking", [c for c in rest if c.get("deprecation")])
    rest = [c for c in rest if not c.get("deprecation")]
    block("Juli dự kiến dùng (D31)", [c for c in rest if c.get("juli") == "planned"])
    rest = [c for c in rest if c.get("juli") != "planned"]
    block(
        "Endpoint bị gỡ",
        [c for c in rest if c["section"] == "endpoints" and c["kind"] == "removed"],
    )
    block(
        "Endpoint thay đổi",
        [c for c in rest if c["section"] == "endpoints" and c["kind"] == "changed"],
    )
    block("Endpoint mới", [c for c in rest if c["section"] == "endpoints" and c["kind"] == "added"])
    block("Webhook / push", [c for c in rest if c["section"] == "webhooks"])
    block("Changelog", [c for c in rest if c["section"] == "changelog"])
    block("SDK", [c for c in rest if c["section"] == "sdk"])

    text = "\n".join(out) + "\n"
    if len(text) > MAX_CHARS:
        cut = text[:MAX_CHARS].rsplit("\n", 1)[0]
        text = cut + "\n\n… (báo cáo bị cắt; bản đầy đủ nằm trong artifact của workflow run)\n"
    return text
