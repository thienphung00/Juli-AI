"""Weekly improvement report from the local Search Console store (gsc_pull + index audit).

Each section ends in an action, so the report is a to-do list, not a dashboard:

1. Totals, last 7 final days vs the 7 before (clicks, impressions, CTR, position).
2. Subdomain leak — any impression on demo. / ops. URLs. Must fall to 0 after the noindex
   deploy; if it does not after ~4 weeks, use Search Console > Removals.
3. Low-CTR pages — enough impressions but CTR below what their position usually earns:
   rewrite title / meta description.
4. Striking-distance queries — average position 8-20 with real impressions: deepen the page
   that ranks (H2/H3 section, FAQ) or write a blog post that links to it.
5. Cannibalisation — one query split across several of our pages: pick one page, link the
   others to it.
6. Sitemap pages with no impressions in 28 days — check indexing (gsc_index_audit) and
   internal links.
7. Latest URL-inspection problems.

    python -m scripts.seo.gsc_report                # prints and writes reports/<date>.md
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import urllib.request
from datetime import date, timedelta

from scripts.seo import config
from scripts.seo.gsc_pull import connect

#: Rough organic CTR expected at a given average position (rounded industry curve). Only
#: used to rank pages for a title/description rewrite, never reported as a target.
EXPECTED_CTR = {
    1: 0.28,
    2: 0.15,
    3: 0.10,
    4: 0.07,
    5: 0.05,
    6: 0.04,
    7: 0.03,
    8: 0.025,
    9: 0.02,
    10: 0.018,
}


def expected_ctr(position: float) -> float:
    return EXPECTED_CTR.get(max(1, round(position)), 0.01)


def _window(db: sqlite3.Connection, days: int, offset: int = 0) -> tuple[str, str]:
    last = db.execute("SELECT max(date) FROM daily_totals").fetchone()[0]
    end = date.fromisoformat(last) - timedelta(days=offset)
    return str(end - timedelta(days=days - 1)), str(end)


def totals(db, start, end):
    c, i, p = db.execute(
        "SELECT sum(clicks), sum(impressions), sum(position*impressions)/nullif(sum(impressions),0)"
        " FROM daily_totals WHERE date BETWEEN ? AND ?",
        (start, end),
    ).fetchone()
    c, i = c or 0, i or 0
    return c, i, (c / i if i else 0.0), p


def fmt_delta(new, old, pct=True):
    if not old:
        return "—"
    d = (new - old) / old * 100 if pct else new - old
    return f"{d:+.1f}{'%' if pct else ''}"


def sitemap_urls() -> list[str]:
    try:
        req = urllib.request.Request(config.SITEMAP_URL, headers={"User-Agent": "juli-seo-report"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", resp.read().decode())
    except OSError:
        return []


def build(db: sqlite3.Connection, min_impr: int) -> str:
    if not db.execute("SELECT 1 FROM daily_totals LIMIT 1").fetchone():
        return (
            "# SEO report\n\nNo data yet — run "
            "`python -m scripts.seo.gsc_pull --backfill 28` first.\n"
        )
    s7, e7 = _window(db, 7)
    p7s, p7e = _window(db, 7, 7)
    s28, e28 = _window(db, 28)
    out = [
        f"# app-juli.com — SEO report {date.today()}",
        "",
        f"Data through {e7} (final). Property `{config.SITE_URL}`.",
        "",
    ]

    c, i, ctr, pos = totals(db, s7, e7)
    pc, pi, pctr, ppos = totals(db, p7s, p7e)
    out += [
        "## 1. Last 7 days vs previous 7",
        "",
        "| | last 7 | prev 7 | Δ |",
        "|---|---|---|---|",
        f"| Clicks | {c:.0f} | {pc:.0f} | {fmt_delta(c, pc)} |",
        f"| Impressions | {i:.0f} | {pi:.0f} | {fmt_delta(i, pi)} |",
        f"| CTR | {ctr:.2%} | {pctr:.2%} | {fmt_delta(ctr, pctr)} |",
        f"| Avg position | {pos or 0:.1f} | {ppos or 0:.1f} | "
        f"{fmt_delta(pos or 0, ppos or 0, pct=False)} (lower is better) |",
        "",
    ]

    hosts = "|".join(re.escape(h) for h in config.NOINDEX_HOSTS)
    leak = [
        r
        for r in db.execute(
            "SELECT page, sum(impressions), sum(clicks), max(date) FROM daily_rows"
            " WHERE date BETWEEN ? AND ? GROUP BY page ORDER BY 2 DESC",
            (s28, e28),
        )
        if re.match(rf"https?://({hosts})", r[0])
    ]
    out += ["## 2. Subdomain leak (must be empty)", ""]
    out += [
        f"- {p} — {im:.0f} impressions, {cl:.0f} clicks, last seen {d}" for p, im, cl, d in leak
    ] or ["None in the last 28 days. ✅"]
    if leak:
        out += [
            "",
            "**Action:** confirm `seo_live_check` shows noindex on these hosts; if impressions "
            "continue 4 weeks after the deploy, Search Console > Removals > New request > "
            "'Remove all URLs with this prefix' for each host.",
        ]
    out.append("")

    rows = db.execute(
        "SELECT page, sum(clicks), sum(impressions),"
        " sum(position*impressions)/sum(impressions) FROM daily_rows"
        " WHERE date BETWEEN ? AND ? GROUP BY page HAVING sum(impressions) >= ?",
        (s28, e28, min_impr),
    ).fetchall()
    low = sorted(
        [
            (p, cl, im, po, cl / im)
            for p, cl, im, po in rows
            if cl / im < 0.6 * expected_ctr(po) and po <= 10
        ],
        key=lambda r: r[2] * (expected_ctr(r[3]) - r[4]),
        reverse=True,
    )[:10]
    out += ["## 3. Low-CTR pages (28 days) → rewrite title / description", ""]
    out += [
        f"- {p} — pos {po:.1f}, {im:.0f} impr, CTR {ctr_:.2%} (typical ≈ {expected_ctr(po):.0%})"
        for p, cl, im, po, ctr_ in low
    ] or [f"None with ≥ {min_impr} impressions."]
    out.append("")

    sd = db.execute(
        "SELECT query, page, sum(impressions), sum(position*impressions)/sum(impressions) AS pos"
        " FROM daily_rows WHERE date BETWEEN ? AND ? GROUP BY query, page"
        " HAVING pos BETWEEN 8 AND 20 AND sum(impressions) >= ? ORDER BY 3 DESC LIMIT 15",
        (s28, e28, max(5, min_impr // 4)),
    ).fetchall()
    out += ["## 4. Striking-distance queries (pos 8–20) → deepen the page or add a linked post", ""]
    out += [f"- “{q}” — {im:.0f} impr, pos {po:.1f} → {p}" for q, p, im, po in sd] or ["None yet."]
    out.append("")

    can = db.execute(
        "SELECT query, count(DISTINCT page), group_concat(DISTINCT page), sum(impressions)"
        " FROM daily_rows WHERE date BETWEEN ? AND ? GROUP BY query"
        " HAVING count(DISTINCT page) > 1 AND sum(impressions) >= ? ORDER BY 4 DESC LIMIT 10",
        (s28, e28, max(5, min_impr // 4)),
    ).fetchall()
    out += ["## 5. Cannibalisation → choose one page per query", ""]
    out += [
        f"- “{q}” ({im:.0f} impr) split over {n} pages: {pages}" for q, n, pages, im in can
    ] or ["None."]
    out.append("")

    seen = {
        r[0].rstrip("/")
        for r in db.execute(
            "SELECT DISTINCT page FROM daily_rows WHERE date BETWEEN ? AND ?", (s28, e28)
        )
    }
    dark = [u for u in sitemap_urls() if u.rstrip("/") not in seen]
    out += ["## 6. Sitemap pages with no impressions in 28 days", ""]
    out += [f"- {u}" for u in dark] or ["None. ✅"]
    out.append("")

    last = db.execute("SELECT max(checked_at) FROM inspections").fetchone()[0]
    out += ["## 7. Latest URL inspection", ""]
    if last:
        for url, verdict, cov, idx, g, u in db.execute(
            "SELECT url, verdict, coverage_state, indexing_state, google_canonical, user_canonical"
            " FROM inspections WHERE checked_at = ? ORDER BY url",
            (last,),
        ):
            out.append(
                f"- {url} — {verdict} · {cov} · {idx}"
                + (f" · Google canonical {g}" if g and u and g != u else "")
            )
    else:
        out.append("Not run yet — `python -m scripts.seo.gsc_index_audit`.")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Weekly SEO improvement report.")
    ap.add_argument("--min-impressions", type=int, default=50)
    args = ap.parse_args(argv)
    text = build(connect(), args.min_impressions)
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.REPORT_DIR / f"{date.today()}.md"
    path.write_text(text)
    print(text)
    print("written to", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
