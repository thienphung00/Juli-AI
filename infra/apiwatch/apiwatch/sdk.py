"""Latest releases of the SDK repos on GitHub (public REST API).

A token (GITHUB_TOKEN / GH_TOKEN) is used only to lift GitHub's anonymous rate
limit; it is never sent to TikTok or Shopee.
"""

from __future__ import annotations

import os
from typing import Any

from apiwatch.fetch import Fetcher, FetchError

API = "https://api.github.com/repos/{repo}"
KEEP = 10


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def normalize_releases(
    repo: str, releases: list[dict[str, Any]], tags: list[dict[str, Any]]
) -> dict[str, Any]:
    published = [r for r in releases or [] if not r.get("draft") and r.get("tag_name")]
    published.sort(key=lambda r: (r.get("published_at") or "", r["tag_name"]), reverse=True)
    if published:
        latest = published[0]
        return {
            "latest": latest["tag_name"],
            "published": str(latest.get("published_at") or "")[:10],
            "prerelease": bool(latest.get("prerelease")),
            "recent": [r["tag_name"] for r in published[:KEEP]],
            "url": f"https://github.com/{repo}/releases",
        }
    names = [t["name"] for t in tags or [] if t.get("name")]
    return {
        "latest": names[0] if names else "",
        "published": "",
        "prerelease": False,
        "recent": names[:KEEP],
        "url": f"https://github.com/{repo}/tags",
    }


def fetch(fetcher: Fetcher, repos: tuple[str, ...]) -> tuple[dict[str, Any], dict[str, str]]:
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for repo in repos:
        try:
            releases = fetcher.get_json(
                API.format(repo=repo) + "/releases", params={"per_page": 20}, headers=_headers()
            )
            tags: list[dict[str, Any]] = []
            if not releases:
                tags = fetcher.get_json(
                    API.format(repo=repo) + "/tags", params={"per_page": KEEP}, headers=_headers()
                )
            record = normalize_releases(repo, releases, tags)
            if not record["latest"]:  # no releases, no tags: track the default branch head
                commits = fetcher.get_json(
                    API.format(repo=repo) + "/commits", params={"per_page": 1}, headers=_headers()
                )
                if commits:
                    head = commits[0]
                    record["latest"] = "commit " + str(head.get("sha") or "")[:10]
                    record["published"] = str(
                        ((head.get("commit") or {}).get("committer") or {}).get("date") or ""
                    )[:10]
                    record["recent"] = [record["latest"]]
                    record["url"] = f"https://github.com/{repo}/commits"
            out[repo] = record
        except FetchError as exc:
            errors[f"sdk:{repo}"] = str(exc)
    return out, errors
