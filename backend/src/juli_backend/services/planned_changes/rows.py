"""The planned-changes sheet as data: columns, cell parsing and the per-row checks (pure, no I/O).

One row = one listing change of one product (p91 D-13). ``parse_sheet`` turns the cells into
:class:`PlannedRow`; ``check_rows`` validates them against a :class:`Context` (the shop's
products, the refs imported before, the days its products were last changed) and returns the
rejections (row not imported) and warnings (imported, but look). The checks:

- ``missing_ref`` / ``duplicate_ref`` / ``bad_ref``  the row's external reference;
- ``unknown_item``                                   the product is not in the shop;
- ``unknown_kind``                                   the change kind is not one of the six;
- ``title_too_long``                                 a title over 100 characters (D-4);
- ``empty_after`` / ``bad_variations`` / ``bad_value`` the new value is missing or unusable;
- ``bad_cost`` / ``bad_date`` / ``bad_window``       chi phí, date, measurement window (>= 3 days);
- ``unknown_depends`` / ``depends_cycle``            ``depends_on`` names a ref that does not exist;
- ``bad_decision`` / ``bad_status``                  a word the sheet does not know;
- ``done_needs_date`` / ``done_needs_approval`` / ``future_date``  a finished row must say when
  and must be approved (the shop's own record of a change already made);
- ``ref_exists_changed``                             the ref was imported before with other content.

Warnings: ``close_changes`` (two changes of one product on different days less than 3 days
apart, D-7), ``before_differs`` (the "trước" value is not what the shop shows now),
``depends_later`` (a dependency is scheduled after the row), ``window_default``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from juli_backend.services.shopee_analytics.fee_table import fold
from juli_backend.services.shopee_recommendations import config
from juli_backend.services.shopee_recommendations import listing as lst
from juli_backend.services.shopee_recommendations.kinds import KINDS, PLANNED_LISTING_KINDS

SHEET = "Đề xuất kế hoạch"
MIN_WINDOW_DAYS = 3
MAX_WINDOW_DAYS = 90
#: Two changes of one product on different days closer than this get a warning (D-7).
CLOSE_DAYS = 3
MAX_ROWS = 500
MAX_REF_CHARS = 32
MAX_COST = 2_000_000_000

# column key -> (header shown, accepted headers folded)
COLUMNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ref", "Mã (ref)", ("ma", "ref", "ma ref", "ma (ref)", "ma de xuat")),
    ("item_id", "Mã sản phẩm", ("ma san pham", "item id", "item_id", "id san pham", "ma sp")),
    ("kind", "Loại thay đổi", ("loai thay doi", "loai", "kind", "change kind")),
    ("before", "Trước", ("truoc", "hien tai", "before")),
    ("after", "Sau", ("sau", "moi", "after")),
    ("reason", "Lý do", ("ly do", "reason")),
    ("cost", "Chi phí (đ)", ("chi phi", "chi phi (d)", "cost")),
    ("date", "Ngày thực hiện", ("ngay thuc hien", "ngay", "date")),
    ("window", "Cửa sổ đo (ngày)", ("cua so do", "cua so do (ngay)", "so ngay do", "window")),
    ("depends_on", "Phụ thuộc (ref)", ("phu thuoc", "phu thuoc (ref)", "depends on", "depends_on")),
    (
        "decision",
        "Quyết định của shop",
        ("quyet dinh cua shop", "ory quyet dinh", "quyet dinh", "decision"),
    ),
    ("status", "Trạng thái", ("trang thai", "status")),
)
REQUIRED_COLUMNS = ("ref", "item_id", "kind")

KIND_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "ten", "ten san pham", "sua ten", "sua ten san pham", "tieu de"),
    "description_first_line": (
        "description_first_line",
        "mo ta",
        "dong dau mo ta",
        "sua dong dau mo ta",
        "mo ta dong dau",
    ),
    "cover_image": ("cover_image", "anh bia", "doi anh bia", "anh"),
    "variation_restructure": (
        "variation_restructure",
        "phan loai",
        "gom phan loai",
        "gop phan loai",
    ),
    "listing_hide": ("listing_hide", "an", "an san pham", "hide"),
    "listing_relist": (
        "listing_relist",
        "nhap hang",
        "dua tro lai",
        "hien thi lai",
        "relist",
        "dua san pham tro lai",
    ),
}
KIND_LABELS: dict[str, str] = {k: KINDS[k].label for k in PLANNED_LISTING_KINDS}

DECISIONS = {
    "approve": ("dong y", "ok", "approve", "approved", "chap nhan"),
    "reject": ("khong dong y", "khong", "tu choi", "reject", "rejected"),
    "change": ("de xuat chinh sua", "chinh sua", "sua", "change", "request change"),
}
DECISION_LABELS = {
    "approve": "đồng ý",
    "reject": "không đồng ý",
    "change": "đề xuất chỉnh sửa",
    None: "chưa quyết định",
}
STATUSES = {
    "pending": ("chua", "chua lam", "pending", "todo"),
    "in_progress": ("dang", "dang lam", "in progress", "in_progress"),
    "done": ("hoan thanh", "xong", "da lam", "done"),
}
STATUS_LABELS = {"pending": "chưa", "in_progress": "đang", "done": "hoàn thành"}

REJECTION_LABELS: dict[str, str] = {
    "missing_ref": "Thiếu mã (ref)",
    "bad_ref": "Mã (ref) sai",
    "duplicate_ref": "Trùng mã (ref)",
    "unknown_item": "Sản phẩm lạ",
    "unknown_kind": "Loại thay đổi lạ",
    "title_too_long": "Tên quá 100 ký tự",
    "empty_after": "Thiếu giá trị mới",
    "bad_variations": "Bảng phân loại sai",
    "bad_value": "Giá trị sai",
    "bad_cost": "Chi phí sai",
    "bad_date": "Ngày sai",
    "bad_window": "Cửa sổ đo sai",
    "unknown_depends": "Phụ thuộc vào mã lạ",
    "depends_cycle": "Phụ thuộc vòng",
    "bad_decision": "Quyết định lạ",
    "bad_status": "Trạng thái lạ",
    "done_needs_date": "Hoàn thành thiếu ngày",
    "done_needs_approval": "Hoàn thành nhưng chưa đồng ý",
    "future_date": "Ngày hoàn thành ở tương lai",
    "ref_exists_changed": "Mã đã nhập, nội dung đổi",
    "cannot_build": "Không dựng được thẻ",
}
WARNING_LABELS: dict[str, str] = {
    "close_changes": "Hai thay đổi cách nhau dưới 3 ngày",
    "before_differs": "Giá trị 'Trước' khác hiện tại",
    "depends_later": "Việc phụ thuộc xếp sau",
    "window_default": "Dùng cửa sổ đo mặc định",
    "in_progress_no_decision": "Đang làm nhưng chưa đồng ý",
}


@dataclass
class PlannedRow:
    row: int  # spreadsheet row number
    ref: str
    item_id: str
    kind: str | None  # None = unknown
    kind_text: str
    before_text: str
    after_text: str
    reason: str
    cost: int | None
    on: date | None
    window_days: int | None
    depends_on: tuple[str, ...]
    decision: str | None  # approve | reject | change | None
    status: str  # pending | in_progress | done
    inputs: dict[str, Any] = field(default_factory=dict)  # parsed after / before values
    problems: list[tuple[str, str, str]] = field(default_factory=list)  # (kind, column, detail)

    def content_hash(self) -> str:
        blob = {
            "item": self.item_id,
            "kind": self.kind,
            "after": self.inputs,
            "before": self.before_text.strip(),
            "reason": self.reason.strip(),
            "cost": self.cost,
            "window": self.window_days,
            "depends_on": sorted(self.depends_on),
        }
        return hashlib.sha256(
            json.dumps(blob, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

    def state(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "status": self.status,
            "executed_on": self.on.isoformat() if self.on else None,
        }


@dataclass(frozen=True)
class Problem:
    row: int
    ref: str
    kind: str
    column: str
    detail: str

    @property
    def label(self) -> str:
        return REJECTION_LABELS.get(self.kind) or WARNING_LABELS.get(self.kind, self.kind)


@dataclass
class Context:
    """What the checks need to know about the shop."""

    today: date
    known_items: Mapping[str, str]  # item_id -> current name
    current_titles: Mapping[str, str] = field(default_factory=dict)
    banned_terms: Sequence[str] = ()
    #: refs imported before -> (content hash, state)
    existing: Mapping[str, tuple[str, Mapping[str, Any]]] = field(default_factory=dict)
    #: item_id -> days a change of it was executed (from the shop's own executions)
    executed_days: Mapping[str, Sequence[date]] = field(default_factory=dict)


# ------------------------------------------------------------------------------- cells


def _clean(value: str | None) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def _multiline(value: str | None) -> str:
    return "\n".join(_clean(line) for line in (value or "").replace("\r", "").split("\n")).strip()


def parse_money(text: str) -> int | None:
    """``1.500.000`` / ``1500000`` / ``1,500,000`` / ``1.5tr`` -> đồng; None when unreadable."""
    t = fold(text).replace("d", "").replace("vnd", "").replace(" ", "")
    if not t:
        return None
    mult = 1
    if t.endswith("tr"):
        mult, t = 1_000_000, t[:-2]
    elif t.endswith("k"):
        mult, t = 1_000, t[:-1]
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", t):
        digits = re.sub(r"[.,]", "", t)
    elif re.fullmatch(r"\d+([.,]\d+)?", t):
        digits = t.replace(",", ".")
    else:
        return None
    try:
        value = float(digits) * mult
    except ValueError:
        return None
    return int(round(value))


def parse_date(text: str, today: date) -> date | None:
    """``dd/mm/yyyy``, ``yyyy-mm-dd``, ``dd/mm`` (this year) or an Excel serial number."""
    t = text.strip()
    if not t:
        return None
    if re.fullmatch(r"\d{5}(\.\d+)?", t):  # Excel serial day
        return date(1899, 12, 30) + timedelta(days=int(float(t)))
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?", t)
    parts: tuple[int, int, int] | None = None
    if m:
        parts = (int(m[1]), int(m[2]), int(m[3]))
    else:
        m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2,4}))?", t)
        if m:
            year = int(m[3]) if m[3] else today.year
            parts = (year + 2000 if year < 100 else year, int(m[2]), int(m[1]))
    if parts is None:
        return None
    try:
        return date(*parts)
    except ValueError:
        return None


def _word(text: str, table: Mapping[str, Sequence[str]]) -> str | None | bool:
    """The key whose words contain ``text`` (folded); None for empty; False for unknown."""
    t = fold(_clean(text))
    if not t:
        return None
    for key, words in table.items():
        if t in words:
            return key
    return False


def parse_kind(text: str) -> str | None:
    t = fold(_clean(text))
    for kind, words in KIND_ALIASES.items():
        if t in words:
            return kind
    return None


def parse_variations(text: str) -> dict[str, Any] | None:
    """The variation table: a JSON array (or ``{"variations": [...], "hide": [...]}``), or one
    variation per line ``tên | giá | SKU | tồn`` with an optional ``ẩn: id1, id2`` line."""
    raw = text.strip()
    if not raw:
        return None
    hide: list[str] = []
    rows: list[Any]
    if raw[0] in "[{":
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        if isinstance(data, dict):
            rows = data.get("variations") or []
            hide = [str(x).strip() for x in data.get("hide") or data.get("hide_items") or []]
        else:
            rows = data
        if not isinstance(rows, list):
            return None
    else:
        rows = []
        for line in re.split(r"[\n;]", raw):
            line = line.strip()
            if not line:
                continue
            if fold(line).startswith("an:"):
                hide += [x.strip() for x in re.split(r"[,\s]+", line.split(":", 1)[1]) if x.strip()]
                continue
            cells = [c.strip() for c in line.split("|")]
            if len(cells) < 2:
                return None
            price = parse_money(cells[1])
            row: dict[str, Any] = {"name": cells[0], "price": price}
            if len(cells) > 2 and cells[2]:
                row["sku"] = cells[2]
            if len(cells) > 3 and cells[3]:
                try:
                    row["stock"] = int(cells[3])
                except ValueError:
                    row["stock"] = cells[3]
            rows.append(row)
    clean: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            return None
        item = {k: r[k] for k in ("name", "price", "sku", "stock") if r.get(k) not in (None, "")}
        if isinstance(item.get("price"), str):
            item["price"] = parse_money(item["price"])
        clean.append(item)
    return {"variations": clean, "hide_items": hide}


# ------------------------------------------------------------------------------- sheet


def header_map(header: Sequence[str | None]) -> dict[str, int]:
    """Column key -> index, by folded header text."""
    folded = [fold(_clean(h)) if h else "" for h in header]
    found: dict[str, int] = {}
    for key, _label, accepted in COLUMNS:
        for i, h in enumerate(folded):
            if h and h in accepted and i not in found.values():
                found[key] = i
                break
    return found


def parse_sheet(
    rows: Sequence[Sequence[str | None]], today: date
) -> tuple[list[PlannedRow], list[str]]:
    """``(rows, missing required column keys)``. Row numbers are the sheet's (header = 1)."""
    if not rows:
        return [], list(REQUIRED_COLUMNS)
    cols = header_map(rows[0])
    missing = [k for k in REQUIRED_COLUMNS if k not in cols]
    if missing:
        return [], missing
    out: list[PlannedRow] = []
    for number, cells in enumerate(rows[1:], start=2):

        def cell(key: str, cells: Sequence[str | None] = cells) -> str:
            i = cols.get(key)
            return "" if i is None or i >= len(cells) else (cells[i] or "")

        if not any(_clean(c) for c in cells if c):
            continue
        out.append(_parse_row(number, cell, today))
    return out, []


def _parse_row(number: int, cell: Any, today: date) -> PlannedRow:
    problems: list[tuple[str, str, str]] = []
    ref = _clean(cell("ref"))
    kind_text = _clean(cell("kind"))
    kind = parse_kind(kind_text)
    cost_text = _clean(cell("cost"))
    cost = parse_money(cost_text) if cost_text else None
    if cost_text and (cost is None or not 0 <= cost <= MAX_COST):
        problems.append(("bad_cost", "Chi phí", cost_text))
        cost = None
    date_text = _clean(cell("date"))
    on = parse_date(date_text, today) if date_text else None
    if date_text and on is None:
        problems.append(("bad_date", "Ngày thực hiện", date_text))
    window_text = _clean(cell("window"))
    window: int | None = None
    if window_text:
        try:
            window = int(float(window_text))
        except ValueError:
            window = None
        if window is None or not MIN_WINDOW_DAYS <= window <= MAX_WINDOW_DAYS:
            problems.append(("bad_window", "Cửa sổ đo", window_text))
            window = None
    deps = tuple(d.strip().upper() for d in re.split(r"[,;\s]+", cell("depends_on")) if d.strip())
    decision = _word(cell("decision"), DECISIONS)
    if decision is False:
        problems.append(("bad_decision", "Quyết định", _clean(cell("decision"))))
        decision = None
    status = _word(cell("status"), STATUSES)
    if status is False:
        problems.append(("bad_status", "Trạng thái", _clean(cell("status"))))
        status = "pending"
    row = PlannedRow(
        row=number,
        ref=ref.upper(),
        item_id=re.sub(r"\.0$", "", _clean(cell("item_id"))),
        kind=kind,
        kind_text=kind_text,
        before_text=_multiline(cell("before")),
        after_text=_multiline(cell("after")),
        reason=_multiline(cell("reason")),
        cost=cost,
        on=on,
        window_days=window,
        depends_on=deps,
        decision=decision if isinstance(decision, str) else None,
        status=status if isinstance(status, str) else "pending",
        problems=problems,
    )
    _parse_after(row)
    return row


def _parse_after(row: PlannedRow) -> None:
    kind, text = row.kind, row.after_text
    if kind == "title":
        row.inputs = {"title": _clean(text)}
        if not row.inputs["title"]:
            row.problems.append(("empty_after", "Sau", ""))
        elif len(row.inputs["title"]) > config.MAX_TITLE_CHARS:
            row.problems.append(
                ("title_too_long", "Sau", f"{len(row.inputs['title'])} > {config.MAX_TITLE_CHARS}")
            )
    elif kind == "description_first_line":
        row.inputs = {"first_line": _clean(text)}
        if not row.inputs["first_line"]:
            row.problems.append(("empty_after", "Sau", ""))
    elif kind == "cover_image":
        row.inputs = {"image_ref": _clean(text)}
        if not row.inputs["image_ref"]:
            row.problems.append(("empty_after", "Sau", ""))
    elif kind == "variation_restructure":
        parsed = parse_variations(text)
        if parsed is None:
            row.problems.append(("bad_variations", "Sau", _clean(text)[:60]))
            return
        row.inputs = {"variations": parsed["variations"], "hide_items": parsed["hide_items"]}
        why = lst.check_planned("variation_restructure", row.inputs, ())
        if why:
            row.problems.append(("bad_variations", "Sau", why.split(":", 1)[-1]))
    elif kind == "listing_relist":
        t = _clean(text)
        digits = re.sub(r"\D", "", t)
        row.inputs = {"stock": int(digits)} if digits else {}
    elif kind == "listing_hide":
        row.inputs = {}


# ------------------------------------------------------------------------------- checks


@dataclass
class Checked:
    rows: list[PlannedRow]
    rejected: dict[int, list[Problem]]
    warnings: list[Problem]
    #: refs in a safe creation order (dependencies first); rejected rows are not in it
    order: list[str]


def check_rows(rows: list[PlannedRow], ctx: Context) -> Checked:
    rejected: dict[int, list[Problem]] = defaultdict(list)
    warnings: list[Problem] = []

    def reject(r: PlannedRow, kind: str, column: str, detail: str = "") -> None:
        rejected[r.row].append(Problem(r.row, r.ref, kind, column, detail))

    def warn(r: PlannedRow, kind: str, column: str, detail: str = "") -> None:
        warnings.append(Problem(r.row, r.ref, kind, column, detail))

    if len(rows) > MAX_ROWS:
        for r in rows[MAX_ROWS:]:
            reject(r, "bad_value", "", f"quá {MAX_ROWS} dòng")
    seen: dict[str, int] = {}
    for r in rows:
        for kind, column, detail in r.problems:
            reject(r, kind, column, detail)
        if not r.ref:
            reject(r, "missing_ref", "Mã (ref)")
        elif not re.fullmatch(r"[A-Z0-9][A-Z0-9_\-.]*", r.ref) or len(r.ref) > MAX_REF_CHARS:
            reject(r, "bad_ref", "Mã (ref)", r.ref)
        elif r.ref in seen:
            reject(r, "duplicate_ref", "Mã (ref)", f"dòng {seen[r.ref]}")
        else:
            seen[r.ref] = r.row
        if r.item_id not in ctx.known_items:
            reject(r, "unknown_item", "Mã sản phẩm", r.item_id)
        if r.kind is None:
            reject(r, "unknown_kind", "Loại thay đổi", r.kind_text)
        elif r.kind == "title" and r.inputs.get("title") and ctx.banned_terms:
            if not lst.is_clean(r.inputs["title"], ctx.banned_terms):
                reject(r, "bad_value", "Sau", "từ không được dùng")
        elif r.kind == "description_first_line" and r.inputs.get("first_line"):
            why = lst.check_planned(r.kind, r.inputs, ctx.banned_terms)
            if why:
                reject(r, "bad_value", "Sau", why)
        if r.status == "done":
            if r.on is None:
                reject(r, "done_needs_date", "Ngày thực hiện")
            elif r.on > ctx.today:
                reject(r, "future_date", "Ngày thực hiện", r.on.isoformat())
            if r.decision != "approve":
                reject(r, "done_needs_approval", "Quyết định")
        elif r.status == "in_progress" and r.decision != "approve":
            warn(r, "in_progress_no_decision", "Trạng thái")
        if r.window_days is None and not any(p.kind == "bad_window" for p in rejected[r.row]):
            warn(r, "window_default", "Cửa sổ đo")
        if r.kind and r.item_id in ctx.current_titles and r.kind == "title" and r.before_text:
            if _clean(r.before_text) != _clean(ctx.current_titles[r.item_id]):
                warn(r, "before_differs", "Trước")
        prior = ctx.existing.get(r.ref)
        if prior is not None and prior[0] != r.content_hash():
            reject(r, "ref_exists_changed", "Mã (ref)", r.ref)
        elif prior is not None and state_move(prior[1], r.state()) == "invalid":
            reject(r, "ref_exists_changed", "Quyết định / Trạng thái", "không lùi được trạng thái")
    # depends_on: known in this file or imported before; no self / cycles
    refs = {
        r.ref
        for r in rows
        if r.ref and not any(p.kind in ("missing_ref", "bad_ref") for p in rejected[r.row])
    }
    known_refs = refs | set(ctx.existing)
    by_ref = {r.ref: r for r in rows if r.ref}
    for r in rows:
        for d in r.depends_on:
            if d not in known_refs:
                reject(r, "unknown_depends", "Phụ thuộc", d)
            elif d == r.ref:
                reject(r, "depends_cycle", "Phụ thuộc", d)
            elif d in by_ref and by_ref[d].on and r.on and by_ref[d].on > r.on:
                warn(r, "depends_later", "Phụ thuộc", d)
    order = _topological(rows, rejected, reject)
    _close_changes(rows, ctx, rejected, warn)
    return Checked(rows, {k: v for k, v in rejected.items() if v}, warnings, order)


def state_move(prior: Mapping[str, Any], new: Mapping[str, Any]) -> str:
    """``same`` / ``advance`` / ``invalid`` for a re-imported ref: a card moves forward only
    (no decision -> a decision -> done); a rejected or edit-requested card stays as decided."""
    if dict(prior) == dict(new):
        return "same"
    p_dec, n_dec = prior.get("decision"), new.get("decision")
    p_done = prior.get("status") == "done"
    n_done = new.get("status") == "done"
    if p_done:
        return "invalid"
    if p_dec is not None and n_dec != p_dec:
        return "invalid"
    if prior.get("status") == "in_progress" and new.get("status") == "pending":
        return "invalid"
    if n_done and n_dec != "approve":
        return "invalid"
    return "advance"


def _topological(rows: list[PlannedRow], rejected: Mapping[int, Any], reject: Any) -> list[str]:
    live = {r.ref: r for r in rows if r.ref and not rejected.get(r.row)}
    order: list[str] = []
    state: dict[str, int] = {}

    def visit(ref: str, stack: tuple[str, ...]) -> None:
        if state.get(ref) == 2 or ref not in live:
            return
        if state.get(ref) == 1:
            reject(live[ref], "depends_cycle", "Phụ thuộc", " → ".join((*stack, ref)))
            return
        state[ref] = 1
        for d in live[ref].depends_on:
            visit(d, (*stack, ref))
        state[ref] = 2
        order.append(ref)

    for ref in live:
        visit(ref, ())
    return [ref for ref in order if not rejected.get(live[ref].row)]


def _close_changes(
    rows: list[PlannedRow], ctx: Context, rejected: Mapping[int, Any], warn: Any
) -> None:
    """D-7: two changes of one product on different days less than ``CLOSE_DAYS`` apart."""
    days: dict[str, list[tuple[date, PlannedRow | None]]] = defaultdict(list)
    for item, found in ctx.executed_days.items():
        days[item] += [(d, None) for d in found]
    for r in rows:
        if r.on and not rejected.get(r.row):
            days[r.item_id].append((r.on, r))
    for item, entries in days.items():
        entries.sort(key=lambda e: e[0])
        for (d1, r1), (d2, r2) in zip(entries, entries[1:], strict=False):
            gap = (d2 - d1).days
            if 0 < gap < CLOSE_DAYS:
                for r, other in ((r1, d2), (r2, d1)):
                    if r is not None:
                        warn(
                            r,
                            "close_changes",
                            "Ngày thực hiện",
                            f"{other.isoformat()} ({gap} ngày)",
                        )
