"""Per-post Search Console section of the weekly report (D56 G6).

`gsc_report.build` appends this as section 8, so the launchd weekly job (`run.sh weekly`
→ `python -m scripts.seo.gsc_report`) picks it up with no schedule change.

For every `/blog/*` and `/cong-cu/*` URL on the main origin with data in the last 28 days,
and every published post in `posts.ts`: impressions, clicks, CTR and average position over
the last 7 and 28 final days, the top new queries (a query whose first impression on that
URL falls in the last 7 days), and flags:

- impressions ≥ 100 and CTR < 1 % (28 days)     → "viết lại title/meta"
- average position 11–20 (28 days)              → "bổ sung nội dung, link nội bộ"
- a query with impressions on ≥ 2 of our URLs   → "trùng ý định, cân nhắc gộp"
- published ≥ 56 days ago and not updated since the 8-week mark
                                                → "đến hạn xem lại 8 tuần"
  (bump `updatedAt` in posts.ts after the review to clear it).

Post dates come from `apps/landing/src/content/blog/posts.ts`, read with a regex: each
entry's `slug:`, `status:`, `publishedAt:` and `updatedAt:` string literals, in that file's
order (an entry starts at `slug: "`). `JULI_BLOG_POSTS_TS` overrides the path.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from scripts.seo import config

REPO_ROOT = Path(__file__).resolve().parents[2]
POSTS_TS = Path(
    os.environ.get("JULI_BLOG_POSTS_TS", REPO_ROOT / "apps/landing/src/content/blog/posts.ts")
)

PREFIXES = ("/blog/", "/cong-cu/")

LOW_CTR_MIN_IMPRESSIONS = 100
LOW_CTR = 0.01
STRIKING = (11.0, 20.0)
REVIEW_AFTER_DAYS = 56

FLAG_LOW_CTR = "viết lại title/meta"
FLAG_STRIKING = "bổ sung nội dung, link nội bộ"
FLAG_OVERLAP = "trùng ý định, cân nhắc gộp"
FLAG_REVIEW = "đến hạn xem lại 8 tuần"


@dataclass(frozen=True)
class Post:
    slug: str
    status: str
    published_at: date
    updated_at: date


@dataclass(frozen=True)
class Stats:
    impressions: float = 0.0
    clicks: float = 0.0
    position: float | None = None

    @property
    def ctr(self) -> float:
        return self.clicks / self.impressions if self.impressions else 0.0


@dataclass
class PageReport:
    path: str
    last7: Stats
    last28: Stats
    new_queries: list[tuple[str, float]] = field(default_factory=list)
    overlap: list[str] = field(default_factory=list)
    post: Post | None = None
    flags: list[str] = field(default_factory=list)


def _field(chunk: str, name: str) -> str | None:
    m = re.search(rf'\b{name}:\s*"([^"]*)"', chunk)
    return m.group(1) if m else None


def parse_posts(text: str) -> dict[str, Post]:
    """slug → Post from the source of posts.ts (see the module docstring)."""
    posts: dict[str, Post] = {}
    for chunk in re.split(r'(?=\bslug:\s*")', text)[1:]:
        slug, status = _field(chunk, "slug"), _field(chunk, "status")
        published, updated = _field(chunk, "publishedAt"), _field(chunk, "updatedAt")
        if not (slug and status and published):
            continue
        posts[slug] = Post(
            slug,
            status,
            date.fromisoformat(published),
            date.fromisoformat(updated or published),
        )
    return posts


def load_posts(path: Path = POSTS_TS) -> dict[str, Post]:
    try:
        return parse_posts(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def path_of(url: str) -> str | None:
    """Path of a main-origin URL (no trailing slash), else None."""
    parts = urlsplit(url)
    if f"{parts.scheme}://{parts.netloc}" != config.MAIN_ORIGIN:
        return None
    return parts.path.rstrip("/") or "/"


def is_post_path(path: str) -> bool:
    return path.startswith(PREFIXES)


def flags_for(last28: Stats, overlap: list[str], post: Post | None, today: date) -> list[str]:
    """The G6 flags for one URL (pure)."""
    out: list[str] = []
    if last28.impressions >= LOW_CTR_MIN_IMPRESSIONS and last28.ctr < LOW_CTR:
        out.append(FLAG_LOW_CTR)
    if last28.position is not None and STRIKING[0] <= last28.position <= STRIKING[1]:
        out.append(FLAG_STRIKING)
    if overlap:
        out.append(FLAG_OVERLAP)
    if post and post.status == "published":
        due = post.published_at + timedelta(days=REVIEW_AFTER_DAYS)
        if today >= due and post.updated_at < due:
            out.append(FLAG_REVIEW)
    return out


def _stats(db: sqlite3.Connection, start: str, end: str) -> dict[str, Stats]:
    out: dict[str, list[float]] = {}
    for page, impr, clicks, pos_x_impr in db.execute(
        "SELECT page, sum(impressions), sum(clicks), sum(position*impressions)"
        " FROM daily_rows WHERE date BETWEEN ? AND ? GROUP BY page",
        (start, end),
    ):
        path = path_of(page)
        if path is None:
            continue
        acc = out.setdefault(path, [0.0, 0.0, 0.0])
        acc[0] += impr or 0
        acc[1] += clicks or 0
        acc[2] += pos_x_impr or 0
    return {p: Stats(i, c, (px / i) if i else None) for p, (i, c, px) in out.items()}


def _new_queries(
    db: sqlite3.Connection, s7: str, e7: str, limit: int = 3
) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, dict[str, float]] = {}
    for page, query, impr in db.execute(
        # First seen in the window = no row for that page × query before it.
        "SELECT page, query, sum(impressions) FROM daily_rows"
        " WHERE date <= ? GROUP BY page, query HAVING min(date) >= ?",
        (e7, s7),
    ):
        path = path_of(page)
        if path is not None and impr:
            q = out.setdefault(path, {})
            q[query] = q.get(query, 0) + impr
    return {p: sorted(qs.items(), key=lambda kv: (-kv[1], kv[0]))[:limit] for p, qs in out.items()}


def _overlaps(db: sqlite3.Connection, start: str, end: str) -> dict[str, list[str]]:
    """path → queries that also bring impressions to another of our URLs."""
    pages_by_query: dict[str, set[str]] = {}
    for page, query in db.execute(
        "SELECT DISTINCT page, query FROM daily_rows"
        " WHERE date BETWEEN ? AND ? AND impressions > 0",
        (start, end),
    ):
        path = path_of(page)
        if path is not None:
            pages_by_query.setdefault(query, set()).add(path)
    out: dict[str, list[str]] = {}
    for query, paths in pages_by_query.items():
        if len(paths) >= 2:
            for path in paths:
                out.setdefault(path, []).append(query)
    return {p: sorted(qs) for p, qs in out.items()}


def page_reports(
    db: sqlite3.Connection,
    windows: tuple[str, str, str, str],
    posts: dict[str, Post],
    today: date,
) -> list[PageReport]:
    s7, e7, s28, e28 = windows
    st7, st28 = _stats(db, s7, e7), _stats(db, s28, e28)
    new_q, overlap = _new_queries(db, s7, e7), _overlaps(db, s28, e28)
    paths = {p for p in st28 if is_post_path(p)}
    paths |= {f"/blog/{slug}" for slug, post in posts.items() if post.status == "published"}
    reports = []
    for path in sorted(paths):
        post = posts.get(path.removeprefix("/blog/")) if path.startswith("/blog/") else None
        r = PageReport(
            path,
            st7.get(path, Stats()),
            st28.get(path, Stats()),
            new_q.get(path, []),
            overlap.get(path, []),
            post,
        )
        r.flags = flags_for(r.last28, r.overlap, post, today)
        reports.append(r)
    return reports


def _cell(s: Stats) -> str:
    pos = f"{s.position:.1f}" if s.position is not None else "–"
    return f"{s.impressions:.0f} / {s.clicks:.0f} / {s.ctr:.1%} / {pos}"


def section(
    db: sqlite3.Connection,
    windows: tuple[str, str, str, str],
    today: date,
    posts: dict[str, Post] | None = None,
) -> list[str]:
    """Markdown lines of section 8."""
    reports = page_reports(db, windows, load_posts() if posts is None else posts, today)
    out = [
        "## 8. Bài blog và công cụ (7 / 28 ngày) → việc cần làm theo từng bài",
        "",
        "Mỗi ô: hiển thị / nhấp / CTR / vị trí TB.",
        "",
    ]
    if not reports:
        return [*out, "Chưa có bài nào được đăng hoặc có dữ liệu.", ""]
    out += [
        "| Trang | 7 ngày | 28 ngày | Truy vấn mới (7 ngày) | Cờ |",
        "|---|---|---|---|---|",
    ]
    for r in reports:
        queries = ", ".join(f"“{q}” ({i:.0f})" for q, i in r.new_queries) or "–"
        out.append(
            f"| {r.path} | {_cell(r.last7)} | {_cell(r.last28)} | {queries} | "
            f"{'; '.join(r.flags) or '–'} |"
        )
    overlapping = [r for r in reports if r.overlap]
    if overlapping:
        out += ["", "Truy vấn trùng (28 ngày):"]
        out += [f"- {r.path}: " + ", ".join(f"“{q}”" for q in r.overlap) for r in overlapping]
    out.append("")
    return out
