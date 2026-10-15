"""Daily Search Analytics pull into a local SQLite store.

Follows the Search Console API guide "Getting all your data": query ONE final day at a
time (default: 3 days ago, data is final after ~2-3 days), page through 25,000-row pages,
and keep two shapes because page/query grouping drops rows:

- `daily_totals`   date × device × country, aggregation by property (accurate counts)
- `daily_rows`     date × page × query × device (detail, may omit anonymised queries)

Re-running a day replaces it, so a cron that runs daily and a backfill can overlap.

    python -m scripts.seo.gsc_pull                      # the latest final day
    python -m scripts.seo.gsc_pull --backfill 90        # the last 90 final days
    python -m scripts.seo.gsc_pull --date 2026-10-12
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import date, timedelta

from scripts.seo import config
from scripts.seo.gsc_client import GSC

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_totals (
  date TEXT, device TEXT, country TEXT,
  clicks REAL, impressions REAL, ctr REAL, position REAL,
  PRIMARY KEY (date, device, country));
CREATE TABLE IF NOT EXISTS daily_rows (
  date TEXT, page TEXT, query TEXT, device TEXT,
  clicks REAL, impressions REAL, ctr REAL, position REAL);
CREATE INDEX IF NOT EXISTS daily_rows_date ON daily_rows(date);
CREATE INDEX IF NOT EXISTS daily_rows_page ON daily_rows(page);
CREATE TABLE IF NOT EXISTS inspections (
  checked_at TEXT, url TEXT, verdict TEXT, coverage_state TEXT, indexing_state TEXT,
  robots_txt_state TEXT, page_fetch_state TEXT, google_canonical TEXT, user_canonical TEXT,
  last_crawl_time TEXT, crawled_as TEXT, rich_results TEXT, link TEXT);
"""


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(config.DB_PATH)
    db.executescript(SCHEMA)
    return db


def latest_available(gsc: GSC) -> date | None:
    """Guide: test for data first — group by date over the last 10 days, no filters."""
    end = date.today()
    rows = gsc.query(
        {"startDate": str(end - timedelta(days=10)), "endDate": str(end), "dimensions": ["date"]}
    )
    return date.fromisoformat(rows[-1]["keys"][0]) if rows else None


def pull_day(gsc: GSC, db: sqlite3.Connection, day: date) -> tuple[int, int]:
    d = str(day)
    totals = gsc.query(
        {
            "startDate": d,
            "endDate": d,
            "dimensions": ["device", "country"],
            "aggregationType": "byProperty",
            "type": "web",
        }
    )
    detail = gsc.query(
        {"startDate": d, "endDate": d, "dimensions": ["page", "query", "device"], "type": "web"}
    )
    with db:
        db.execute("DELETE FROM daily_totals WHERE date = ?", (d,))
        db.execute("DELETE FROM daily_rows WHERE date = ?", (d,))
        db.executemany(
            "INSERT INTO daily_totals VALUES (?,?,?,?,?,?,?)",
            [
                (d, *r["keys"], r["clicks"], r["impressions"], r["ctr"], r["position"])
                for r in totals
            ],
        )
        db.executemany(
            "INSERT INTO daily_rows VALUES (?,?,?,?,?,?,?,?)",
            [
                (d, *r["keys"], r["clicks"], r["impressions"], r["ctr"], r["position"])
                for r in detail
            ],
        )
    return len(totals), len(detail)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Pull Search Console performance data into SQLite.")
    ap.add_argument("--date", type=date.fromisoformat)
    ap.add_argument("--backfill", type=int, default=0, help="also pull this many earlier days")
    args = ap.parse_args(argv)

    gsc = GSC()
    db = connect()
    last = args.date or latest_available(gsc)
    if last is None:
        print("No Search Analytics data yet for", config.SITE_URL, "(new property: wait 2-3 days).")
        return 0
    final = min(last, date.today() - timedelta(days=config.FINAL_DATA_LAG_DAYS))
    days = [final - timedelta(days=i) for i in range(args.backfill + 1)]
    for day in sorted(days):
        n_tot, n_rows = pull_day(gsc, db, day)
        print(f"{day}: {n_tot} total rows, {n_rows} page×query rows")
    print("stored in", config.DB_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
