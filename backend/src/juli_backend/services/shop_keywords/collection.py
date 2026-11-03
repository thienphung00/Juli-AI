"""The keyword collection format (ADR-119, D81.8): what the owner uploads each week.

The owner looks keywords up on shopeeanalytics.com in their own browser, logged in to a free
account (anonymous visitors get 5 lookups a day, then a login box and an empty table that
reads "Không có từ khóa khớp bộ lọc"). Juli's servers never fetch the site. The result is a
JSON Lines file, one object per looked-up seed keyword::

    {"source": "shopeeanalytics", "collected_on": "YYYY-MM-DD", "seed": "...",
     "status": "ok" | "blocked" | "no_match", "total_volume": int | null,
     "rows": [{"keyword": "...", "volume": int | null, "cpc_min": number | null,
               "cpc_max": number | null, "difficulty": number | null,
               "competition": number | null, "opportunity": number | null}]}

Numbers are plain JSON numbers (never "1.250"; a quoted number is refused). ``ok`` needs at
least one row; ``blocked`` (the site refused: the free quota ran out, the login box) and
``no_match`` (the owner saw the site answer with nothing for this seed) carry no rows and no
``total_volume``. An empty
result is ``blocked`` unless the owner marks it ``no_match``: it is never zero demand.

:func:`from_raw` converts the browser capture of 2026-11 -- ``{kw, sum, n, rows}`` with
Vietnamese thousands separators and rows as ``"keyword | volume | trend | min CPC | max CPC
| difficulty | competition | opportunity"`` strings -- into this format;
``scripts/shopeeanalytics_keywords.py`` is its command line.

:func:`metric_rows` turns one record into ``market_keyword_metrics`` rows (public lane).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from juli_backend.models.market import (
    KEYWORD_SOURCE_SHOPEEANALYTICS,
    KEYWORD_STATUS_BLOCKED,
    KEYWORD_STATUS_NO_MATCH,
    KEYWORD_STATUS_OK,
)

MAX_KEYWORD = 200
MAX_ROWS = 500
MAX_RECORDS = 500
#: What the site's table says when it shows nothing (blocked, or a real empty result).
NO_MATCH_TEXT = "Không có từ khóa khớp bộ lọc"
RAW_COLUMNS = (
    "keyword",
    "volume",
    "trend",
    "cpc_min",
    "cpc_max",
    "difficulty",
    "competition",
    "opportunity",
)
_SPACES = re.compile(r"\s+")


def normalize_keyword(text: str) -> str:
    """NFC, lower case, single spaces: how a keyword is stored and matched."""
    return _SPACES.sub(" ", unicodedata.normalize("NFC", text).strip().lower())


class CollectionRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keyword: str = Field(min_length=1, max_length=MAX_KEYWORD)
    volume: StrictInt | None = Field(default=None, ge=0)
    cpc_min: StrictInt | StrictFloat | None = Field(default=None, ge=0)
    cpc_max: StrictInt | StrictFloat | None = Field(default=None, ge=0)
    difficulty: StrictInt | StrictFloat | None = Field(default=None, ge=0, le=100)
    competition: StrictInt | StrictFloat | None = Field(default=None, ge=0, le=100)
    opportunity: StrictInt | StrictFloat | None = Field(default=None, ge=0)

    @field_validator("keyword")
    @classmethod
    def _keyword(cls, value: str) -> str:
        cleaned = normalize_keyword(value)
        if not cleaned:
            raise ValueError("keyword is empty")
        return cleaned


class CollectionRecord(BaseModel):
    """One looked-up seed keyword on one day."""

    model_config = ConfigDict(extra="forbid")
    source: Literal["shopeeanalytics"]
    collected_on: date
    seed: str = Field(min_length=1, max_length=MAX_KEYWORD)
    status: Literal["ok", "blocked", "no_match"]
    total_volume: StrictInt | None = Field(default=None, ge=0)
    rows: list[CollectionRow] = Field(default_factory=list, max_length=MAX_ROWS)

    @field_validator("seed")
    @classmethod
    def _seed(cls, value: str) -> str:
        cleaned = normalize_keyword(value)
        if not cleaned:
            raise ValueError("seed is empty")
        return cleaned

    @model_validator(mode="after")
    def _status_matches_rows(self) -> CollectionRecord:
        if self.status == KEYWORD_STATUS_OK and not self.rows:
            raise ValueError("status ok needs at least one row; an empty result is blocked")
        if self.status != KEYWORD_STATUS_OK and (self.rows or self.total_volume is not None):
            raise ValueError(f"status {self.status} carries no rows and no total_volume")
        return self


class CollectionError(ValueError):
    """A collection file that does not follow the format; ``errors`` names the lines."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors[:5]))
        self.errors = errors


def parse_records(objects: list[Any]) -> list[CollectionRecord]:
    """Validate decoded objects; every bad one is reported with its 1-based position."""
    if len(objects) > MAX_RECORDS:
        raise CollectionError([f"at most {MAX_RECORDS} records per upload"])
    records: list[CollectionRecord] = []
    errors: list[str] = []
    for n, obj in enumerate(objects, start=1):
        try:
            records.append(CollectionRecord.model_validate(obj))
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"]) or "record"
            errors.append(f"line {n}: {where}: {first['msg']}")
    if errors:
        raise CollectionError(errors)
    return records


def parse_jsonl(text: str) -> list[CollectionRecord]:
    """A JSON Lines collection file; blank lines are skipped."""
    objects: list[Any] = []
    errors: list[str] = []
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            objects.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append(f"line {n}: not JSON ({exc.msg})")
    if errors:
        raise CollectionError(errors)
    return parse_records(objects)


# --------------------------------------------------------------------------- raw capture


def vn_number(text: str | None) -> int | float | None:
    """ "1.250" -> 1250, "1,5" -> 1.5, "" -> None (Vietnamese separators)."""
    if text is None:
        return None
    cleaned = text.strip().replace(" ", "")
    if not cleaned or cleaned in {"-", "—"}:
        return None
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return int(value) if value.is_integer() else value


def _as_int(value: float | None) -> int | None:
    return None if value is None else int(round(value))


def _raw_row(line: str) -> dict[str, Any] | None:
    parts = [p.strip() for p in line.split("|")]
    if len(parts) != len(RAW_COLUMNS) or not parts[0] or NO_MATCH_TEXT in line:
        return None
    cells = dict(zip(RAW_COLUMNS, parts))
    return {
        "keyword": cells["keyword"],
        "volume": _as_int(vn_number(cells["volume"])),
        "cpc_min": vn_number(cells["cpc_min"]),
        "cpc_max": vn_number(cells["cpc_max"]),
        "difficulty": vn_number(cells["difficulty"]),
        "competition": vn_number(cells["competition"]),
        "opportunity": vn_number(cells["opportunity"]),
    }


def from_raw(
    raw: dict[str, Any], *, collected_on: date, no_match: frozenset[str] = frozenset()
) -> CollectionRecord:
    """One raw capture line -> one record. Empty -> ``blocked`` unless marked ``no_match``."""
    seed = normalize_keyword(str(raw.get("kw") or ""))
    lines = [str(r) for r in raw.get("rows") or []]
    rows = [row for row in (_raw_row(line) for line in lines) if row is not None]
    if rows:
        return CollectionRecord.model_validate(
            {
                "source": KEYWORD_SOURCE_SHOPEEANALYTICS,
                "collected_on": collected_on,
                "seed": seed,
                "status": KEYWORD_STATUS_OK,
                "total_volume": _as_int(vn_number(str(raw.get("sum") or ""))),
                "rows": rows,
            }
        )
    status = KEYWORD_STATUS_NO_MATCH if seed in no_match else KEYWORD_STATUS_BLOCKED
    return CollectionRecord.model_validate(
        {
            "source": KEYWORD_SOURCE_SHOPEEANALYTICS,
            "collected_on": collected_on,
            "seed": seed,
            "status": status,
        }
    )


def dump_jsonl(records: list[CollectionRecord]) -> str:
    return "".join(
        json.dumps(r.model_dump(mode="json"), ensure_ascii=False) + "\n" for r in records
    )


# --------------------------------------------------------------------------- table rows


@dataclass(frozen=True)
class MetricRow:
    """One ``market_keyword_metrics`` row, before it is written."""

    keyword: str
    seed: str
    collected_on: date
    status: str
    volume: int | None = None
    cpc_min: float | None = None
    cpc_max: float | None = None
    difficulty: float | None = None
    competition: float | None = None
    opportunity: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def metric_rows(record: CollectionRecord) -> list[MetricRow]:
    """The seed's own row (with ``total_volume``) first, then its related keywords.

    A refused or empty lookup is one row ``keyword = seed`` with no numbers. When the site's
    table did not list the seed itself, its row still exists, numbers unknown (``listed``
    false), so the lookup is recorded without inventing a volume.
    """
    if record.status != KEYWORD_STATUS_OK:
        return [MetricRow(record.seed, record.seed, record.collected_on, record.status)]
    seen: dict[str, CollectionRow] = {}
    for row in record.rows:
        seen.setdefault(row.keyword, row)
    own = seen.pop(record.seed, None)
    extra = {"total_volume": record.total_volume, "listed": own is not None}
    out = [_metric(record, own, extra) if own else _unlisted(record, extra)]
    out.extend(_metric(record, row, {}) for row in seen.values())
    return out


def _metric(record: CollectionRecord, row: CollectionRow, extra: dict[str, Any]) -> MetricRow:
    return MetricRow(
        keyword=row.keyword,
        seed=record.seed,
        collected_on=record.collected_on,
        status=KEYWORD_STATUS_OK,
        volume=row.volume,
        cpc_min=row.cpc_min,
        cpc_max=row.cpc_max,
        difficulty=row.difficulty,
        competition=row.competition,
        opportunity=row.opportunity,
        extra=extra,
    )


def _unlisted(record: CollectionRecord, extra: dict[str, Any]) -> MetricRow:
    return MetricRow(record.seed, record.seed, record.collected_on, KEYWORD_STATUS_OK, extra=extra)


__all__ = [
    "KEYWORD_STATUS_BLOCKED",
    "NO_MATCH_TEXT",
    "CollectionError",
    "CollectionRecord",
    "CollectionRow",
    "MetricRow",
    "dump_jsonl",
    "from_raw",
    "metric_rows",
    "normalize_keyword",
    "parse_jsonl",
    "parse_records",
    "vn_number",
]
