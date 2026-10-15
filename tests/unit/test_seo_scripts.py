"""P33-E: the Search Console monitoring scripts judge, store and report correctly (no network)."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from scripts.seo import gsc_index_audit, gsc_pull, gsc_report, seo_live_check

GOOD_HTML = """<html><head><title>Phân tích shop TikTok | Juli AI</title>
<meta name="description" content="Juli phân tích từng luồng truy cập.">
<link rel="canonical" href="https://app-juli.com/san-pham">
<meta property="og:title" content="t"><meta property="og:description" content="d">
<meta property="og:image" content="https://app-juli.com/og.png">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
{"@type":"Organization","name":"Juli"},{"@type":"WebSite","name":"Juli"}]}</script>
</head><body><h1>A</h1><h2>B</h2><h3>C</h3><h2>D</h2></body></html>"""


def test_parser_reads_title_meta_canonical_headings_and_jsonld():
    p = seo_live_check._PageParser()
    p.feed(GOOD_HTML)
    assert p.title.startswith("Phân tích shop")
    assert p.canonical == "https://app-juli.com/san-pham"
    assert p.headings == [1, 2, 3, 2]
    fails: list[str] = []
    assert seo_live_check._jsonld_types(p.jsonld, fails) >= {"Organization", "WebSite"}
    assert fails == []


def test_check_main_flags_missing_signals(monkeypatch):
    bad = "<html><head><title>x</title></head><body><h1>a</h1><h1>b</h1><h4>c</h4></body></html>"
    monkeypatch.setattr(seo_live_check, "fetch", lambda url, follow=False: (200, {}, bad, url))
    r = seo_live_check.check_main("https://app-juli.com/")
    joined = " | ".join(r.fails)
    for expected in (
        "2 <h1>",
        "missing meta description",
        "missing canonical",
        "missing og:image",
        "lacks Organization",
    ):
        assert expected in joined
    assert any("h1 -> h4" in w for w in r.warns)


def test_check_main_passes_a_good_page(monkeypatch):
    monkeypatch.setattr(
        seo_live_check, "fetch", lambda url, follow=False: (200, {}, GOOD_HTML, url)
    )
    assert seo_live_check.check_main("https://app-juli.com/san-pham").fails == []


def test_noindex_host_needs_noindex_and_crawlable_robots(monkeypatch):
    pages = {
        "https://demo.app-juli.com/robots.txt": (200, {}, "User-agent: *\nDisallow: /\n"),
        "https://demo.app-juli.com/": (200, {}, "<html></html>"),
    }
    monkeypatch.setattr(seo_live_check, "fetch", lambda url, follow=False: (*pages[url], url))
    r = seo_live_check.check_noindex("https://demo.app-juli.com/", {})
    assert any("Disallows" in f for f in r.fails)
    assert any("no noindex" in f for f in r.fails)

    pages["https://demo.app-juli.com/robots.txt"] = (200, {}, "User-agent: *\nAllow: /\n")
    pages["https://demo.app-juli.com/"] = (200, {"x-robots-tag": "noindex, nofollow"}, "")
    assert seo_live_check.check_noindex("https://demo.app-juli.com/", {}).fails == []


def test_host_behind_cloudflare_access_counts_as_out_of_the_index(monkeypatch):
    monkeypatch.setattr(
        seo_live_check,
        "fetch",
        lambda url, follow=False: (
            302,
            {"location": "https://juli.cloudflareaccess.com/x"},
            "",
            url,
        ),
    )
    r = seo_live_check.check_noindex("https://ops.app-juli.com/", {})
    assert r.fails == [] and r.info["robots_txt"].startswith("behind login")


def test_index_audit_expectations():
    ok = {
        "verdict": "PASS",
        "indexingState": "INDEXING_ALLOWED",
        "robotsTxtState": "ALLOWED",
        "pageFetchState": "SUCCESSFUL",
        "googleCanonical": "https://app-juli.com/",
        "userCanonical": "https://app-juli.com/",
    }
    assert gsc_index_audit.judge_main("https://app-juli.com/", ok) == []
    moved = {**ok, "googleCanonical": "https://app-juli.com/san-pham"}
    assert "another canonical" in gsc_index_audit.judge_main("https://app-juli.com/", moved)[0]
    assert gsc_index_audit.judge_noindex({"verdict": "PASS"})[0].startswith("STILL INDEXED")
    assert (
        gsc_index_audit.judge_noindex(
            {
                "verdict": "NEUTRAL",
                "lastCrawlTime": "2026-10-20T00:00:00Z",
                "indexingState": "BLOCKED_BY_HTTP_HEADER",
            }
        )
        == []
    )
    assert gsc_index_audit.judge_noindex({"verdict": "NEUTRAL"}) == []  # never crawled


def _seed(db: sqlite3.Connection) -> None:
    db.executescript(gsc_pull.SCHEMA)
    end = date(2026, 11, 20)
    for k in range(28):
        d = str(end - timedelta(days=k))
        db.execute(
            "INSERT INTO daily_totals VALUES (?,?,?,?,?,?,?)",
            (d, "MOBILE", "vnm", 10 if k < 7 else 5, 400, 0.025, 6.0),
        )
        rows = [
            (d, "https://app-juli.com/", "juli ai", "MOBILE", 8, 40, 0.2, 1.2),
            (d, "https://app-juli.com/san-pham", "phần mềm tiktok shop", "MOBILE", 0, 30, 0.0, 4.0),
            (d, "https://app-juli.com/blog/chi-so", "ctor là gì", "MOBILE", 0, 6, 0.0, 12.0),
            (
                d,
                "https://app-juli.com/san-pham/phan-tich-shop",
                "ctor là gì",
                "MOBILE",
                0,
                3,
                0.0,
                15.0,
            ),
            (d, "https://demo.app-juli.com/decisions", "juli demo", "MOBILE", 1, 2, 0.5, 3.0),
        ]
        db.executemany("INSERT INTO daily_rows VALUES (?,?,?,?,?,?,?,?)", rows)


def test_report_sections_turn_data_into_actions(monkeypatch):
    db = sqlite3.connect(":memory:")
    _seed(db)
    monkeypatch.setattr(
        gsc_report,
        "sitemap_urls",
        lambda: ["https://app-juli.com/", "https://app-juli.com/ket-noi/tiktok-shop"],
    )
    text = gsc_report.build(db, 50)
    assert "| Clicks | 70 | 35 | +100.0% |" in text
    assert "https://demo.app-juli.com/decisions" in text.split("## 3.")[0]  # subdomain leak
    assert "https://app-juli.com/san-pham — pos 4.0" in text  # low CTR at position 4
    assert "“ctor là gì”" in text  # striking distance + cannibalisation
    assert "split over 2 pages" in text
    assert "https://app-juli.com/ket-noi/tiktok-shop" in text.split("## 6.")[1]
    assert "Not run yet" in text


def test_report_without_data_says_what_to_run():
    db = sqlite3.connect(":memory:")
    db.executescript(gsc_pull.SCHEMA)
    assert "gsc_pull --backfill 28" in gsc_report.build(db, 50)
