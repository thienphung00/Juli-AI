"""Live on-page and indexing-signal check for app-juli.com — no Google credentials needed.

Run it right after every deploy. It reads the sitemap, fetches every URL as Googlebot
would see the raw HTML, and checks the D43 rules; then it fetches sample URLs on the
noindex hosts (demo., ops.) and checks they say noindex in a way Google can see.

    python -m scripts.seo.seo_live_check           # human summary, exit 1 on any FAIL
    python -m scripts.seo.seo_live_check --json    # machine-readable

Checks per main-site URL: HTTP 200 without redirect, no noindex (header or meta), exactly
one <h1>, no skipped heading level, title present and <= 60 chars, description present and
<= 155 chars, absolute self canonical, og:title / og:description / og:image, every JSON-LD
block parses and Organization + WebSite are present, titles and descriptions unique across
the site. Per noindex-host URL: `X-Robots-Tag` or meta robots contains noindex, and robots.txt
does not Disallow the path (a disallowed page is never fetched, so Google never sees the
noindex and the URL can stay indexed).
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urlsplit

from scripts.seo import config

UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html) juli-seo-check"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(url: str, follow: bool = False) -> tuple[int, dict[str, str], str, str]:
    """Return (status, lower-cased headers, body, final url)."""
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "vi"})
    try:
        with opener.open(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, body, resp.url
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, body, url


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self.canonical: str | None = None
        self.headings: list[int] = []
        self.jsonld: list[str] = []
        self._in_title = False
        self._in_jsonld = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = a.get("name") or a.get("property")
            if key:
                self.meta[key.lower()] = a.get("content", "")
        elif tag == "link" and a.get("rel", "").lower() == "canonical":
            self.canonical = a.get("href")
        elif re.fullmatch(r"h[1-6]", tag):
            self.headings.append(int(tag[1]))
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in_jsonld, self._buf = True, []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_jsonld:
            self.jsonld.append("".join(self._buf))
            self._in_jsonld = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_jsonld:
            self._buf.append(data)


@dataclass
class Result:
    url: str
    kind: str  # "main" | "noindex"
    fails: list[str] = field(default_factory=list)
    warns: list[str] = field(default_factory=list)
    info: dict[str, object] = field(default_factory=dict)


def _jsonld_types(blocks: list[str], fails: list[str]) -> set[str]:
    types: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            t = node.get("@type")
            for v in t if isinstance(t, list) else [t]:
                if isinstance(v, str):
                    types.add(v)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for raw in blocks:
        try:
            walk(json.loads(raw))
        except json.JSONDecodeError as exc:
            fails.append(f"JSON-LD does not parse: {exc.msg}")
    return types


def check_main(url: str) -> Result:
    r = Result(url, "main")
    status, headers, body, _ = fetch(url)
    r.info["status"] = status
    if status != 200:
        r.fails.append(f"HTTP {status} (sitemap URLs must answer 200 without redirect)")
        return r
    robots = headers.get("x-robots-tag", "").lower()
    p = _PageParser()
    p.feed(body)
    meta_robots = p.meta.get("robots", "").lower()
    if "noindex" in robots or "noindex" in meta_robots:
        r.fails.append("main-site page says noindex")
    h1 = p.headings.count(1)
    if h1 != 1:
        r.fails.append(f"{h1} <h1> elements (want exactly 1)")
    for prev, cur in zip(p.headings, p.headings[1:]):
        if cur > prev + 1:
            r.warns.append(f"heading jumps h{prev} -> h{cur}")
            break
    title = " ".join(p.title.split())
    desc = p.meta.get("description", "").strip()
    r.info.update(title=title, description=desc, canonical=p.canonical, headings=len(p.headings))
    if not title:
        r.fails.append("missing <title>")
    elif len(title) > config.TITLE_MAX:
        r.warns.append(f"title {len(title)} chars > {config.TITLE_MAX}")
    if not desc:
        r.fails.append("missing meta description")
    elif len(desc) > config.DESCRIPTION_MAX:
        r.warns.append(f"description {len(desc)} chars > {config.DESCRIPTION_MAX}")
    if not p.canonical:
        r.fails.append("missing canonical")
    elif p.canonical.rstrip("/") != url.rstrip("/"):
        r.fails.append(f"canonical points elsewhere: {p.canonical}")
    for og in ("og:title", "og:description", "og:image"):
        if not p.meta.get(og):
            r.fails.append(f"missing {og}")
    types = _jsonld_types(p.jsonld, r.fails)
    r.info["jsonld"] = sorted(types)
    for needed in ("Organization", "WebSite"):
        if needed not in types:
            r.fails.append(f"JSON-LD lacks {needed}")
    words = len(
        re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", body, flags=re.S).split()
    )
    r.info["words"] = words
    return r


def _robots_for(host: str) -> tuple[urllib.robotparser.RobotFileParser, str]:
    """Fetch robots.txt with our own UA (urllib's default UA is 403'd by Cloudflare, and
    RobotFileParser.read() turns any 401/403 into "disallow all" — a false alarm)."""
    rp = urllib.robotparser.RobotFileParser()
    status, headers, body, _ = fetch(f"https://{host}/robots.txt")
    if status == 200:
        rp.parse(body.splitlines())
        return rp, "ok"
    location = headers.get("location", "")
    if 300 <= status < 400 and urlsplit(location).netloc not in ("", host):
        rp.parse([])
        return rp, f"behind login ({status} -> {urlsplit(location).netloc})"
    rp.parse([])  # 404 / other: Google treats a missing robots.txt as "crawl everything"
    return rp, f"robots.txt HTTP {status}"


def check_noindex(
    url: str, robots_cache: dict[str, tuple[urllib.robotparser.RobotFileParser, str]]
) -> Result:
    r = Result(url, "noindex")
    host = urlsplit(url).netloc
    if host not in robots_cache:
        robots_cache[host] = _robots_for(host)
    rp, state = robots_cache[host]
    r.info["robots_txt"] = state
    if state.startswith("behind login"):
        # Cloudflare Access: Google is redirected to a login page and can never index the
        # host's content. That is a valid way to stay out of the index.
        return r
    if not rp.can_fetch("Googlebot", url):
        r.fails.append("robots.txt Disallows this URL — Google cannot see its noindex")
    status, headers, body, _ = fetch(url, follow=True)
    p = _PageParser()
    p.feed(body)
    header = headers.get("x-robots-tag", "").lower()
    meta = p.meta.get("robots", "").lower() + " " + p.meta.get("googlebot", "").lower()
    r.info.update(status=status, x_robots_tag=header or None, meta_robots=meta.strip() or None)
    if "noindex" not in header and "noindex" not in meta:
        r.fails.append("no noindex in X-Robots-Tag or meta robots")
    return r


def sitemap_urls(sitemap: str) -> list[str]:
    status, _, body, _ = fetch(sitemap, follow=True)
    if status != 200:
        raise SystemExit(f"sitemap {sitemap} answered HTTP {status}")
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    results = [check_main(u) for u in sitemap_urls(config.SITEMAP_URL)]
    seen: dict[tuple[str, str], str] = {}
    for r in results:
        for key in ("title", "description"):
            val = str(r.info.get(key) or "")
            if val and (key, val) in seen:
                r.fails.append(f"duplicate {key} with {seen[(key, val)]}")
            seen.setdefault((key, val), r.url)
    cache: dict[str, tuple[urllib.robotparser.RobotFileParser, str]] = {}
    for host in config.NOINDEX_HOSTS:
        for path in config.NOINDEX_SAMPLE_PATHS:
            results.append(check_noindex(f"https://{host}{path}", cache))

    if args.json:
        print(json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=1))
    else:
        for r in results:
            mark = "FAIL" if r.fails else ("WARN" if r.warns else "ok  ")
            extra = f" words={r.info.get('words')}" if r.kind == "main" else ""
            print(f"{mark} [{r.kind}] {r.url}{extra}")
            for f in r.fails:
                print(f"     ✗ {f}")
            for w in r.warns:
                print(f"     ! {w}")
        n_fail = sum(1 for r in results if r.fails)
        print(f"\n{len(results)} URLs, {n_fail} failing")
    return 1 if any(r.fails for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
