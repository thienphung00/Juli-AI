"""P92 B-4 "Tiêu đề": the keyword table of one product.

Rows come from what Juli really stores, and a source it does not have is returned absent with its
reason -- never filled in:

- ``title`` -- the keyword seeds of the product (Từ khoá, ADR-119) and the phrases of its current
  title that have collected numbers;
- ``suggestion`` -- the other keywords the lookups of the product's seeds listed (shopeeanalytics
  search suggestions, collected by the owner);
- ``competitor`` -- 2-3-word phrases that most of the top search titles of the product's seeds
  share (``market_listing_snapshots``);
- ``ads`` -- the keywords of the shop's own ads keyword report for the product (placed orders).

Every row has ``volume`` / ``difficulty`` / CPC from ``market_keyword_metrics`` when the keyword was
looked up ("chưa tra" otherwise, never 0), ``in_title`` (is it in the current title) and where it
came from. The market tables are the public lane: if the role cannot read them the sources that
need them come back absent with that reason.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories import (
    MarketKeywordMetricsReadRepo,
    MarketListingsReadRepo,
)
from juli_backend.services.shopee_analytics import loaders
from juli_backend.services.shopee_analytics.fee_table import fold
from juli_backend.services.shopee_analytics.windows import Window

MAX_NGRAM = 3
MAX_SEEDS_FOR_COMPETITORS = 6
COMPETITOR_MIN_TITLES = 3
COMPETITOR_MIN_SHARE = 0.3
MAX_ROWS = 80
STOPWORDS = frozenset(
    {"cho", "va", "cua", "voi", "cac", "mot", "loai", "bo", "set", "combo", "hop", "cai", "chiec"}
)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)

SOURCE_LABELS = {
    "title": "Tiêu đề hiện tại",
    "suggestion": "Gợi ý tìm kiếm",
    "competitor": "Tiêu đề đối thủ",
    "ads": "Báo cáo quảng cáo",
}
ABSENT_REASONS = {
    "title_no_seed": "Sản phẩm chưa có từ khoá gốc (Ops tạo ở trang Từ khoá).",
    "suggestion_none": "Chưa có lượt tra từ khoá liên quan nào cho các từ khoá gốc của sản phẩm.",
    "competitor_none": "Chưa thu thập tiêu đề tìm kiếm cho các từ khoá gốc của sản phẩm.",
    "ads_none": "Báo cáo từ khoá quảng cáo chưa có dòng nào cho sản phẩm này.",
    "market_closed": "Không đọc được dữ liệu thị trường bằng quyền hiện tại.",
}


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def ngrams(text: str, max_n: int = MAX_NGRAM) -> list[str]:
    """Phrases of 1..max_n consecutive words of ``text``, in their original spelling."""
    ws = words(text)
    out: list[str] = []
    for n in range(1, max_n + 1):
        for i in range(len(ws) - n + 1):
            out.append(" ".join(ws[i : i + n]))
    return list(dict.fromkeys(out))


def competitor_phrases(titles: Sequence[str]) -> list[tuple[str, int]]:
    """2-3-word phrases in at least ``max(3, 30 %)`` of the titles: ``(phrase, titles)``."""
    if len(titles) < COMPETITOR_MIN_TITLES:
        return []
    need = max(COMPETITOR_MIN_TITLES, int(len(titles) * COMPETITOR_MIN_SHARE + 0.9999))
    seen: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for title in titles:
        grams = {g for g in ngrams(title) if len(words(g)) >= 2}
        for g in grams:
            key = fold(g)
            toks = key.split()
            if toks[0] in STOPWORDS or toks[-1] in STOPWORDS:
                continue
            seen.setdefault(key, g.lower())
            counts[key] += 1
    return sorted(
        ((seen[k], n) for k, n in counts.items() if n >= need), key=lambda kv: (-kv[1], kv[0])
    )


def _number(value: Any) -> Any:
    if value is None:
        return None
    f = float(value)
    return int(f) if f == int(f) else f


async def keyword_table(
    session: AsyncSession,
    shop_id: Any,
    item_id: str,
    *,
    title: str,
    as_of: date,
) -> dict[str, Any]:
    in_title_folded = fold(title)
    seeds = await loaders.load_keyword_seeds(session, shop_id, item_id)
    seed_words = list(dict.fromkeys(s.keyword for s in seeds))
    roles = {s.keyword: s.role for s in seeds}

    # the shop's own ads keyword report
    window = Window(as_of - timedelta(days=29), as_of)
    reports = await loaders.load_ads_reports(session, shop_id, window)
    acc: dict[str, dict[str, float]] = defaultdict(
        lambda: {"spend": 0.0, "clicks": 0.0, "orders": 0.0, "gmv": 0.0}
    )
    names: dict[str, str] = {}
    for r in reports.keyword_rows:
        if r.item_id != item_id or "›" not in r.campaign:
            continue
        kw = r.campaign.split("›", 1)[1].strip()
        if not kw:
            continue
        names.setdefault(fold(kw), kw)
        a = acc[fold(kw)]
        a["spend"] += float(r.spend)
        a["clicks"] += float(r.clicks)
        a["orders"] += float(r.orders)
        a["gmv"] += float(r.gmv)

    # -- the public market lane (volumes, suggestions, competitor titles), guarded: a role that
    #    cannot read it must not poison the transaction
    market: dict[str, Any] = {}
    related: list[Any] = []
    competitor_titles: dict[str, list[str]] = {}
    market_ok = True
    title_grams = ngrams(title)
    try:
        async with session.begin_nested():
            repo = MarketKeywordMetricsReadRepo(session)
            market = {
                m.keyword: m
                for m in await repo.latest([*seed_words, *title_grams, *names.values()])
            }
            related = await repo.related(seed_words)
            competitor_titles = await MarketListingsReadRepo(session).top_titles(
                seed_words[:MAX_SEEDS_FOR_COMPETITORS]
            )
    except Exception:
        market_ok = False
        market, related, competitor_titles = {}, [], {}

    rows: dict[str, dict[str, Any]] = {}

    def add(keyword: str, source: str, **extra: Any) -> dict[str, Any]:
        key = fold(keyword)
        row = rows.get(key)
        if row is None:
            m = market.get(keyword)
            row = {
                "keyword": keyword,
                "sources": [],
                "volume": None if m is None else m.volume,
                "difficulty": None if m is None else _number(m.difficulty),
                "cpc_min": None if m is None else _number(m.cpc_min),
                "cpc_max": None if m is None else _number(m.cpc_max),
                "volume_status": "ok" if m is not None and m.volume is not None else "chua_tra",
                "in_title": key in in_title_folded,
                "role": roles.get(keyword),
                "competitor_titles": None,
                "ads": None,
            }
            rows[key] = row
        if source not in row["sources"]:
            row["sources"].append(source)
        row.update({k: v for k, v in extra.items() if v is not None})
        return row

    # title: the product's seeds, and phrases of the current title that have numbers
    for kw in seed_words:
        add(kw, "title")
    for gram in title_grams:
        if gram in market and fold(gram) not in {fold(k) for k in seed_words}:
            add(gram, "title")
    # suggestions
    for m in related:
        market.setdefault(m.keyword, m)
        add(m.keyword, "suggestion")
    # competitor phrases
    pool: list[str] = []
    for titles in competitor_titles.values():
        pool.extend(titles)
    for phrase, n in competitor_phrases(pool):
        add(phrase, "competitor", competitor_titles=n)
    for key, a in acc.items():
        add(
            names[key],
            "ads",
            ads={
                **{k: _number(v) for k, v in a.items()},
                "roas": round(a["gmv"] / a["spend"], 2) if a["spend"] else None,
                "basis": "đơn đã đặt",
            },
        )

    ordered = sorted(
        rows.values(),
        key=lambda r: (-(r["volume"] or -1), not r["in_title"], fold(r["keyword"])),
    )[:MAX_ROWS]
    present = {s: sum(1 for r in rows.values() if s in r["sources"]) for s in SOURCE_LABELS}
    absent_reason = {
        "title": None if present["title"] else ABSENT_REASONS["title_no_seed"],
        "suggestion": None
        if present["suggestion"]
        else ABSENT_REASONS["suggestion_none" if market_ok else "market_closed"],
        "competitor": None
        if present["competitor"]
        else ABSENT_REASONS["competitor_none" if market_ok else "market_closed"],
        "ads": None if present["ads"] else ABSENT_REASONS["ads_none"],
    }
    return {
        "item_id": item_id,
        "title": title,
        "title_chars": len(title),
        "max_title_chars": 100,
        "keywords": ordered,
        "sources": [
            {
                "key": key,
                "label": label,
                "present": bool(present[key]),
                "count": present[key],
                "reason": absent_reason[key],
            }
            for key, label in SOURCE_LABELS.items()
        ],
    }


__all__ = ["SOURCE_LABELS", "competitor_phrases", "keyword_table", "ngrams"]
