"""`ServiceData` on the unit tests' SQLite: the SAME named SELECTs and the same analytics-service
reads, with only the dialect adapted (Postgres casts, `string_agg`, `now() - interval`) and the
values typed back as Postgres returns them (date, bool, Decimal). No query is rewritten by hand;
the figures come from the production SQL text. The Postgres subset of the bank runs the real
`ServiceData` unchanged (`tests/integration/analytics_agent/test_chat_bank_pg.py`)."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from juli_backend.services.analytics_agent.data_service import ServiceData

_DIALECT: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(\w+)::date"), r"date(\1)"),
    (re.compile(r"string_agg\(distinct (\w+), ','\)"), r"group_concat(distinct \1)"),
    (re.compile(r"cast\(:(\w) as date\) \+ 1"), r"date(:\1, '+1 day')"),
    (re.compile(r"cast\(:(\w) as date\)"), r"date(:\1)"),
    (re.compile(r"now\(\) - interval '(\d+) days'"), r"datetime('now', '-\1 days')"),
    (re.compile(r"(\w+)::text"), r"\1"),
)
_DATE_KEYS = {"day", "planned_start"}
_BOOL_KEYS = {"complete"}
_MONEY_KEYS = {"gmv", "ads_spend", "ads_gmv", "voucher_cost", "c"}


def to_sqlite(sql: str) -> str:
    for rx, sub in _DIALECT:
        sql = rx.sub(sub, sql)
    return sql


def _typed(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for k, v in row.items():
        if k in _DATE_KEYS and isinstance(v, str):
            out[k] = date.fromisoformat(v[:10])
        elif k in _DATE_KEYS and isinstance(v, datetime):
            out[k] = v.date()
        elif k in _BOOL_KEYS and isinstance(v, int):
            out[k] = bool(v)
        elif k in _MONEY_KEYS and isinstance(v, int | float):
            out[k] = Decimal(str(v))
    return out


class SqliteServiceData(ServiceData):
    async def _q(self, sql: str, **p: Any) -> list[dict[str, Any]]:
        params = {k: (v.hex if isinstance(v, uuid.UUID) else v) for k, v in p.items()}
        async with self._f() as s:
            try:
                res = await s.execute(text(to_sqlite(sql)), {"s": self.shop.hex, **params})
                return [_typed(dict(r._mapping)) for r in res]
            finally:
                await s.rollback()
