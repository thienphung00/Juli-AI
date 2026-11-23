"""S-E110 (batch-1123-a2): the fields Seller Centre's list shows for a saved voucher / combo are
compared with what the card asked for (the forward fill job's payload, built from the card spec).

Result ``{"result": "match" | "mismatch" | None, "diffs": [{field, label_vi, card_value,
seen_value}]}``. ``None`` = nothing comparable was read yet. Only fields BOTH sides know are
compared (a list that does not show a field never produces a false mismatch).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.platform_data import PlatformPromotion

LABELS = {
    "time": "Thời gian",
    "discount": "Mức giảm",
    "min_spend": "Đơn tối thiểu",
    "usage": "Lượt sử dụng tối đa",
    "products": "Số sản phẩm",
    "tiers": "Mức ưu đãi",
}
PROMO_TYPE = {"voucher": "voucher", "combo": "bundle"}
_SHOPEE_TIME = re.compile(r"^(\d{1,2}):(\d{2}) (\d{1,2})-(\d{1,2})-(\d{4})$")


def _when(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None, second=0, microsecond=0)
    text = str(value or "").strip()
    m = _SHOPEE_TIME.match(text)
    if m:
        hh, mm, dd, mo, yy = (int(x) for x in m.groups())
        return datetime(yy, mo, dd, hh, mm)
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None, second=0, microsecond=0)
    except ValueError:
        return None


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tiers(raw: Any) -> list[tuple[int, float]] | None:
    out: list[tuple[int, float]] = []
    for t in raw or []:
        if not isinstance(t, dict) or _num(t.get("qty")) is None or _num(t.get("value")) is None:
            return None
        out.append((int(_num(t.get("qty")) or 0), float(_num(t.get("value")) or 0)))
    return sorted(out) or None


def expected_of(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The card's side, from the forward job payload (``kind``: ``voucher`` | ``combo``)."""
    out: dict[str, Any] = {}
    start, end = _when(payload.get("starts_at")), _when(payload.get("ends_at"))
    if start or end:
        out["time"] = (start, end)
    if payload.get("product_ids"):
        out["products"] = len(payload["product_ids"])
    if kind == "voucher":
        d = payload.get("discount") or {}
        if _num(d.get("value")) is not None:
            out["discount"] = (str(d.get("type")), float(d["value"]))
        if _num(payload.get("min_spend")) is not None:
            out["min_spend"] = float(payload["min_spend"])
        if _num(payload.get("usage_total")) is not None:
            out["usage"] = float(payload["usage_total"])
    else:
        tiers = _tiers(payload.get("tiers"))
        if tiers:
            out["tiers"] = (str(payload.get("discount_type") or ""), tiers)
    return out


def observed_of(kind: str, row: PlatformPromotion) -> dict[str, Any]:
    """What the list row shows (only the fields it carries)."""
    x = row.extra or {}
    out: dict[str, Any] = {"time": (_when(row.starts_at), _when(row.ends_at))}
    count = _num(x.get("product_count", x.get("item_count")))
    if count is not None:
        out["products"] = int(count)
    if kind == "voucher":
        if _num(x.get("discount_percent")) is not None:
            out["discount"] = ("percent", float(x["discount_percent"]))
        elif _num(x.get("discount_amount")) is not None:
            out["discount"] = ("amount", float(x["discount_amount"]))
        if _num(x.get("min_spend")) is not None:
            out["min_spend"] = float(x["min_spend"])
        if _num(x.get("usage_limit")) is not None:
            out["usage"] = float(x["usage_limit"])
    else:
        tiers = _tiers(x.get("tiers"))
        if tiers:
            out["tiers"] = (str(x.get("discount_type") or ""), tiers)
    return out


def _fmt_time(v: tuple[datetime | None, datetime | None]) -> str:
    def one(d: datetime | None) -> str:
        return "?" if d is None else f"{d:%H:%M %d/%m/%Y}"

    return f"{one(v[0])} – {one(v[1])}"


def _fmt(field: str, v: Any) -> str:
    if field == "time":
        return _fmt_time(v)
    if field == "discount":
        return f"{v[1]:g}%" if v[0] == "percent" else f"{v[1]:,.0f}đ".replace(",", ".")
    if field == "tiers":
        return "; ".join(f"mua {q} giảm {val:g}" for q, val in v[1])
    if field in ("min_spend",):
        return f"{v:,.0f}đ".replace(",", ".")
    return f"{v:g}"


def _same(field: str, want: Any, seen: Any) -> bool:
    if field == "time":
        # a side the list does not show (None) is not compared
        return all(w is None or s is None or w == s for w, s in zip(want, seen, strict=True))
    if field == "discount":
        return bool(want[1] == seen[1] and (want[0] == seen[0] or "" in (want[0], seen[0])))
    if field == "tiers":
        return bool(want[1] == seen[1])
    return bool(want == seen)


def compare(expected: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    diffs: list[dict[str, Any]] = []
    compared = 0
    for field in LABELS:
        if field not in expected or field not in observed:
            continue
        compared += 1
        if not _same(field, expected[field], observed[field]):
            diffs.append(
                {
                    "field": field,
                    "label_vi": LABELS[field],
                    "card_value": _fmt(field, expected[field]),
                    "seen_value": _fmt(field, observed[field]),
                }
            )
    result = None if compared == 0 else ("mismatch" if diffs else "match")
    return {"result": result, "diffs": diffs}


async def observed_row(
    session: AsyncSession,
    shop_id: uuid.UUID,
    kind: str,
    target: dict[str, Any],
    since: datetime,
) -> PlatformPromotion | None:
    """The newest list row (captured after ``since``) of the object the read-back targets: by id,
    else code, else name."""
    rows = (
        await session.scalars(
            select(PlatformPromotion)
            .where(
                PlatformPromotion.shop_id == shop_id,
                PlatformPromotion.promo_type == PROMO_TYPE[kind],
                PlatformPromotion.captured_at >= since,
            )
            .order_by(PlatformPromotion.captured_at.desc())
            .limit(400)
        )
    ).all()
    oid = str(target.get("voucher_id") or target.get("combo_id") or target.get("id") or "")
    code = str(target.get("voucher_code") or target.get("code") or "").upper()
    suffix = str(target.get("code_suffix") or "").upper()
    name = str(target.get("name") or target.get("combo_name") or "").casefold().strip()
    for r in rows:
        x = r.extra or {}
        if oid and oid in (str(x.get("voucher_id")), str(x.get("combo_id")), str(x.get("id"))):
            return r
    for r in rows:
        have = str((r.extra or {}).get("voucher_code") or "").upper()
        if have and ((code and have == code) or (suffix and have.endswith(suffix))):
            return r
    for r in rows:
        if name and r.program_name.casefold().strip() == name:
            return r
    return None
