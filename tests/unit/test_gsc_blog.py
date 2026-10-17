"""Per-post weekly Search Console section (D56 G6): flag logic and the report on a temp DB."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from scripts.seo import gsc_blog, gsc_pull, gsc_report
from scripts.seo.gsc_blog import (
    FLAG_LOW_CTR,
    FLAG_OVERLAP,
    FLAG_REVIEW,
    FLAG_STRIKING,
    Post,
    Stats,
    flags_for,
)

TODAY = date(2026, 12, 23)
END = date(2026, 12, 20)  # last final day in the fixture
ORIGIN = "https://app-juli.com"


def _post(published: str, updated: str | None = None, status: str = "published") -> Post:
    return Post(
        "x", status, date.fromisoformat(published), date.fromisoformat(updated or published)
    )


# --- flags_for (pure) -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("impressions", "clicks", "flagged"),
    [(100, 0, True), (100, 0.99, True), (100, 1, False), (99, 0, False), (500, 4, True)],
)
def test_low_ctr_needs_100_impressions_and_ctr_below_1_percent(impressions, clicks, flagged):
    flags = flags_for(Stats(impressions, clicks, 5.0), [], None, TODAY)
    assert (FLAG_LOW_CTR in flags) is flagged


@pytest.mark.parametrize(
    ("position", "flagged"),
    [(10.9, False), (11.0, True), (15.0, True), (20.0, True), (20.1, False), (None, False)],
)
def test_striking_distance_is_average_position_11_to_20(position, flagged):
    assert (FLAG_STRIKING in flags_for(Stats(10, 1, position), [], None, TODAY)) is flagged


def test_overlap_flag_when_a_query_is_shared():
    assert flags_for(Stats(), ["ctor là gì"], None, TODAY) == [FLAG_OVERLAP]
    assert flags_for(Stats(), [], None, TODAY) == []


def test_review_due_at_56_days_until_updated_after_the_mark():
    due = TODAY - timedelta(days=56)
    assert FLAG_REVIEW in flags_for(Stats(), [], _post(str(due)), TODAY)
    assert FLAG_REVIEW not in flags_for(Stats(), [], _post(str(due + timedelta(days=1))), TODAY)
    # Reviewed: updatedAt bumped on or after the 8-week mark clears the flag.
    assert FLAG_REVIEW not in flags_for(Stats(), [], _post(str(due), str(TODAY)), TODAY)
    # A draft is never due.
    assert FLAG_REVIEW not in flags_for(Stats(), [], _post(str(due), status="draft"), TODAY)


def test_parse_posts_reads_slug_status_and_dates():
    text = """
    const academy = (title: string) => ({ title });
    export const BLOG_POSTS = [
      { slug: "a", status: "published", title: "A",
        publishedAt: "2026-10-17", updatedAt: "2026-10-20" },
      {
        slug: "b",
        status: "draft",
        publishedAt: "2026-10-16",
        updatedAt: "2026-10-16",
        sources: [{ title: "T", url: "https://x" }],
      },
    ];
    """
    posts = gsc_blog.parse_posts(text)
    assert posts == {
        "a": Post("a", "published", date(2026, 10, 17), date(2026, 10, 20)),
        "b": Post("b", "draft", date(2026, 10, 16), date(2026, 10, 16)),
    }


def test_parse_posts_reads_the_real_posts_ts():
    posts = gsc_blog.load_posts()
    assert posts["gmv-la-gi-tiktok-shop"].status == "published"
    assert posts["gmv-la-gi-tiktok-shop"].published_at >= date(2026, 10, 1)
    assert all(p.updated_at >= p.published_at for p in posts.values())


def test_path_of_keeps_only_the_main_origin():
    assert gsc_blog.path_of(f"{ORIGIN}/blog/a/") == "/blog/a"
    assert gsc_blog.path_of(f"{ORIGIN}/") == "/"
    assert gsc_blog.path_of("https://demo.app-juli.com/blog/a") is None


# --- section 8 on a temp SQLite store ----------------------------------------------------


POSTS = {
    "gmv": Post("gmv", "published", date(2026, 10, 17), date(2026, 10, 17)),
    "ctor": Post("ctor", "published", date(2026, 12, 1), date(2026, 12, 1)),
    "cu": Post("cu", "published", date(2026, 10, 1), date(2026, 12, 1)),
    "nhap": Post("nhap", "draft", date(2026, 10, 1), date(2026, 10, 1)),
}


@pytest.fixture
def db(tmp_path):
    con = sqlite3.connect(tmp_path / "gsc.sqlite")
    con.executescript(gsc_pull.SCHEMA)
    for k in range(28):
        d = str(END - timedelta(days=k))
        con.execute(
            "INSERT INTO daily_totals VALUES (?,?,?,?,?,?,?)",
            (d, "MOBILE", "vnm", 2, 40, 0.05, 8.0),
        )
        rows = [
            # 280 impressions, no clicks, position 15 → rewrite title/meta + strengthen.
            (d, f"{ORIGIN}/blog/gmv", "gmv là gì", "MOBILE", 0, 10, 0.0, 15.0),
            # Healthy, but "ctor là gì" also brings impressions to a product page → overlap.
            (d, f"{ORIGIN}/blog/ctor", "ctor là gì", "MOBILE", 1, 5, 0.2, 5.0),
            (d, f"{ORIGIN}/san-pham/phan-tich-shop", "ctor là gì", "MOBILE", 0, 2, 0.0, 9.0),
            (d, f"{ORIGIN}/cong-cu/tinh-gmv", "tính gmv", "MOBILE", 1, 4, 0.25, 3.0),
            # Subdomain URL: never in the blog section.
            (d, "https://demo.app-juli.com/blog/gmv", "gmv là gì", "MOBILE", 0, 1, 0.0, 30.0),
        ]
        if k < 3:  # first seen 3 days ago → a new query
            rows.append((d, f"{ORIGIN}/blog/ctor", "ctor thấp", "MOBILE", 0, 6, 0.0, 7.0))
        con.executemany("INSERT INTO daily_rows VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit()
    yield con
    con.close()


def _windows(db):
    return (*gsc_report._window(db, 7), *gsc_report._window(db, 28))


def test_page_reports_stats_new_queries_and_flags(db):
    reports = {r.path: r for r in gsc_blog.page_reports(db, _windows(db), POSTS, TODAY)}
    # Published posts without data are still listed (review date); drafts and product pages not.
    assert sorted(reports) == ["/blog/ctor", "/blog/cu", "/blog/gmv", "/cong-cu/tinh-gmv"]

    gmv = reports["/blog/gmv"]
    assert (gmv.last7.impressions, gmv.last28.impressions, gmv.last28.clicks) == (70, 280, 0)
    assert gmv.last28.position == pytest.approx(15.0)
    assert gmv.flags == [FLAG_LOW_CTR, FLAG_STRIKING, FLAG_REVIEW]

    ctor = reports["/blog/ctor"]
    assert ctor.new_queries == [("ctor thấp", 18)]
    assert ctor.overlap == ["ctor là gì"]
    assert ctor.flags == [FLAG_OVERLAP]
    assert ctor.last7.ctr == pytest.approx(7 / 53)

    assert reports["/blog/cu"].flags == []  # reviewed: updatedAt after the 8-week mark
    assert reports["/blog/cu"].last28 == Stats()
    assert reports["/cong-cu/tinh-gmv"].flags == []
    assert reports["/cong-cu/tinh-gmv"].post is None


def test_weekly_report_has_section_8(db, monkeypatch):
    monkeypatch.setattr(gsc_report, "sitemap_urls", lambda: [])
    text = gsc_report.build(db, 50, today=TODAY, posts=POSTS)
    blog = text.split("## 8.")[1]
    assert (
        "| /blog/gmv | 70 / 0 / 0.0% / 15.0 | 280 / 0 / 0.0% / 15.0 | – | "
        "viết lại title/meta; bổ sung nội dung, link nội bộ; đến hạn xem lại 8 tuần |"
    ) in blog
    assert "“ctor thấp” (18)" in blog
    assert "- /blog/ctor: “ctor là gì”" in blog
    assert "demo.app-juli.com" not in blog
    assert "/blog/nhap" not in blog


def test_section_without_posts_or_data(tmp_path):
    con = sqlite3.connect(tmp_path / "empty.sqlite")
    con.executescript(gsc_pull.SCHEMA)
    lines = gsc_blog.section(
        con, ("2026-12-14", "2026-12-20", "2026-11-23", "2026-12-20"), TODAY, {}
    )
    assert "Chưa có bài nào được đăng hoặc có dữ liệu." in lines
