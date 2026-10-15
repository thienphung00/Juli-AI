"""Index audit with the URL Inspection API: is every main-site page indexed the way we
intend, and is every subdomain page out of the index?

Expectations (D43; owner 2026-10-15 "de-index the subdomains, Google indexes only the main
domain"):

- every URL in https://app-juli.com/sitemap.xml: verdict PASS, indexingState
  INDEXING_ALLOWED, robotsTxtState ALLOWED, pageFetchState SUCCESSFUL, and Google's chosen
  canonical == the page's declared canonical == the URL itself;
- every sample URL on demo. / ops. (config.NOINDEX_HOSTS): NOT indexed — verdict NEUTRAL or
  FAIL with indexingState BLOCKED_BY_META_TAG / BLOCKED_BY_HTTP_HEADER, or never crawled. A
  PASS here means the subdomain is still in Google: request removal in the Search Console UI
  (Removals is not available through the API).

Quota: 2,000 inspections / day / site; the audit uses ~15. Results are appended to the
`inspections` table so the report can show the trend.

    python -m scripts.seo.gsc_index_audit            # exit 1 if any expectation fails
    python -m scripts.seo.gsc_index_audit --extra https://app-juli.com/blog/x
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import UTC, datetime

from scripts.seo import config
from scripts.seo.gsc_client import GSC
from scripts.seo.gsc_pull import connect

INDEXED = "PASS"
BLOCKED = {"BLOCKED_BY_META_TAG", "BLOCKED_BY_HTTP_HEADER"}


def sitemap_urls() -> list[str]:
    req = urllib.request.Request(config.SITEMAP_URL, headers={"User-Agent": "juli-seo-audit"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", resp.read().decode())


def judge_main(url: str, ix: dict) -> list[str]:
    problems = []
    if ix.get("verdict") != INDEXED:
        problems.append(f"not indexed: {ix.get('verdict')} / {ix.get('coverageState')}")
    if ix.get("indexingState") not in (None, "INDEXING_ALLOWED"):
        problems.append(f"indexingState {ix.get('indexingState')} on a main-site page")
    if ix.get("robotsTxtState") == "DISALLOWED":
        problems.append("blocked by robots.txt")
    if ix.get("pageFetchState") not in (None, "SUCCESSFUL"):
        problems.append(f"fetch {ix.get('pageFetchState')}")
    g, u = ix.get("googleCanonical"), ix.get("userCanonical")
    if g and u and g.rstrip("/") != u.rstrip("/"):
        problems.append(f"Google chose another canonical: {g} (declared {u})")
    if u and u.rstrip("/") != url.rstrip("/"):
        problems.append(f"declared canonical is not self: {u}")
    return problems


def judge_noindex(ix: dict) -> list[str]:
    if ix.get("verdict") == INDEXED:
        return ["STILL INDEXED — request removal in Search Console > Removals"]
    if ix.get("lastCrawlTime") and ix.get("indexingState") not in BLOCKED:
        return [f"crawled but no noindex seen (indexingState {ix.get('indexingState')})"]
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="URL Inspection audit for app-juli.com.")
    ap.add_argument("--extra", nargs="*", default=[], help="more main-site URLs to inspect")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    gsc = GSC()
    db = connect()
    now = datetime.now(UTC).isoformat(timespec="seconds")
    targets = [(u, "main") for u in sitemap_urls() + args.extra] + [
        (f"https://{h}{p}", "noindex")
        for h in config.NOINDEX_HOSTS
        for p in config.NOINDEX_SAMPLE_PATHS
    ]
    report, failing = [], 0
    for url, kind in targets:
        res = gsc.inspect(url)
        ix = res.get("indexStatusResult", {})
        rich = res.get("richResultsResult", {})
        problems = judge_main(url, ix) if kind == "main" else judge_noindex(ix)
        failing += bool(problems)
        with db:
            db.execute(
                "INSERT INTO inspections VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    now,
                    url,
                    ix.get("verdict"),
                    ix.get("coverageState"),
                    ix.get("indexingState"),
                    ix.get("robotsTxtState"),
                    ix.get("pageFetchState"),
                    ix.get("googleCanonical"),
                    ix.get("userCanonical"),
                    ix.get("lastCrawlTime"),
                    ix.get("crawledAs"),
                    json.dumps(rich, ensure_ascii=False) if rich else None,
                    res.get("inspectionResultLink"),
                ),
            )
        report.append(
            {
                "url": url,
                "kind": kind,
                "problems": problems,
                "index": ix,
                "rich_results": rich.get("verdict"),
            }
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for r in report:
            ix = r["index"]
            mark = "FAIL" if r["problems"] else "ok  "
            print(
                f"{mark} [{r['kind']}] {r['url']}  {ix.get('verdict')} · {ix.get('coverageState')}"
                f" · crawled {ix.get('lastCrawlTime', '-')}"
            )
            for p in r["problems"]:
                print(f"     ✗ {p}")
        print(f"\n{len(report)} URLs inspected, {failing} failing")
    return 1 if failing else 0


if __name__ == "__main__":
    raise SystemExit(main())
