"""Cached formula results for the xlsx exports.

openpyxl writes every formula cell as ``<f>..</f><v/>`` with no result, so Protected View, mobile
viewers and file previews (which do not recalculate) show 0 or blank. This module evaluates the
workbook's own formulas in memory and writes each result into the sheet XML ``<v>`` beside the
formula. It only evaluates what is already in the workbook: it computes no number of its own, the
formulas and ``fullCalcOnLoad`` stay, and Excel still recalculates on open.

Supported: numbers, "text", TRUE/FALSE, cell and range refs (``$``, ``'Sheet name'!``), the
operators ``+ - * / ^ & % = <> < > <= >=``, and IF IFERROR ISNUMBER AND OR SUM MAX MIN N ABS. A
formula the evaluator cannot compute (unknown function, circular reference, array formula) gets NO
cached value, never a 0; ``save_bytes(strict=True)`` raises instead so a test can fail on it.
No ``eval``/``exec``: a small tokenizer and recursive-descent parser.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from openpyxl import Workbook
from openpyxl.utils import column_index_from_string, get_column_letter

logger = logging.getLogger(__name__)

_EPOCH = datetime(1899, 12, 30)


def escape(text: str) -> str:
    """XML-escape text for an element body (our own output; nothing is parsed here)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class UnsupportedFormula(Exception):
    """The evaluator cannot compute this formula (not an Excel error value)."""


@dataclass(frozen=True)
class XlError:
    """An Excel error value such as ``#DIV/0!``."""

    code: str


DIV0 = XlError("#DIV/0!")
VALUE = XlError("#VALUE!")
REF = XlError("#REF!")
NUM = XlError("#NUM!")

Scalar = None | float | str | bool | XlError


class _Range(list[Any]):
    """The non-empty values of a multi-cell reference."""


# ----------------------------------------------------------------------------------- tokenizer

_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<str>"(?:[^"]|"")*")
  | (?P<func>[A-Za-z_][A-Za-z0-9_.]*)(?=\()
  | (?P<sheet>(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)
  | (?P<cell>\$?[A-Za-z]{1,3}\$?\d+)
  | (?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<bool>TRUE|FALSE)
  | (?P<op><>|<=|>=|[-+*/^&=<>%(),:])
    """,
    re.VERBOSE | re.IGNORECASE,
)
_CELL = re.compile(r"\$?([A-Za-z]{1,3})\$?(\d+)")


def _tokenize(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None:
            raise UnsupportedFormula(f"cannot read {text[pos : pos + 12]!r}")
        pos = m.end()
        kind = m.lastgroup or ""
        if kind != "ws":
            out.append((kind, m.group()))
    return out


# --------------------------------------------------------------------------------------- parser

Node = tuple[Any, ...]


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], sheet: str) -> None:
        self.t = tokens
        self.i = 0
        self.sheet = sheet

    def _peek(self) -> tuple[str, str]:
        return self.t[self.i] if self.i < len(self.t) else ("end", "")

    def _next(self) -> tuple[str, str]:
        tok = self._peek()
        self.i += 1
        return tok

    def _op(self, *ops: str) -> str | None:
        kind, val = self._peek()
        if kind == "op" and val in ops:
            self.i += 1
            return val
        return None

    def parse(self) -> Node:
        node = self._compare()
        if self.i != len(self.t):
            raise UnsupportedFormula(f"unexpected {self._peek()[1]!r}")
        return node

    def _compare(self) -> Node:
        node = self._concat()
        while (op := self._op("=", "<>", "<=", ">=", "<", ">")) is not None:
            node = ("bin", op, node, self._concat())
        return node

    def _concat(self) -> Node:
        node = self._add()
        while self._op("&") is not None:
            node = ("bin", "&", node, self._add())
        return node

    def _add(self) -> Node:
        node = self._mul()
        while (op := self._op("+", "-")) is not None:
            node = ("bin", op, node, self._mul())
        return node

    def _mul(self) -> Node:
        node = self._pow()
        while (op := self._op("*", "/")) is not None:
            node = ("bin", op, node, self._pow())
        return node

    def _pow(self) -> Node:
        node = self._unary()
        while self._op("^") is not None:
            node = ("bin", "^", node, self._unary())
        return node

    def _unary(self) -> Node:
        op = self._op("-", "+")
        if op is not None:
            inner = self._unary()
            return ("neg", inner) if op == "-" else inner
        node = self._primary()
        while self._op("%") is not None:
            node = ("pct", node)
        return node

    def _primary(self) -> Node:
        kind, val = self._next()
        if kind == "num":
            return ("num", float(val))
        if kind == "str":
            return ("str", val[1:-1].replace('""', '"'))
        if kind == "bool":
            return ("bool", val.upper() == "TRUE")
        if kind == "func":
            return self._call(val.upper())
        if kind == "op" and val == "(":
            node = self._compare()
            if self._op(")") is None:
                raise UnsupportedFormula("missing )")
            return node
        if kind == "sheet":
            name = val[:-1]
            if name.startswith("'"):
                name = name[1:-1].replace("''", "'")
            return self._ref(name, self._next())
        if kind == "cell":
            return self._ref(self.sheet, (kind, val))
        raise UnsupportedFormula(f"unexpected {val!r}" if val else "formula ends early")

    def _ref(self, sheet: str, first: tuple[str, str]) -> Node:
        if first[0] != "cell":
            raise UnsupportedFormula("whole row/column or name reference")
        c1, r1 = _split_cell(first[1])
        c2, r2 = c1, r1
        if self._op(":") is not None:
            nxt = self._next()
            if nxt[0] != "cell":
                raise UnsupportedFormula("whole row/column reference")
            c2, r2 = _split_cell(nxt[1])
        return ("ref", sheet, min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))

    def _call(self, name: str) -> Node:
        if self._op("(") is None:
            raise UnsupportedFormula(f"{name} without (")
        args: list[Node] = []
        if self._op(")") is not None:
            return ("call", name, args)
        while True:
            if self._peek() == ("op", ",") or self._peek() == ("op", ")"):
                raise UnsupportedFormula(f"{name} has an empty argument")
            args.append(self._compare())
            if self._op(",") is not None:
                continue
            if self._op(")") is not None:
                return ("call", name, args)
            raise UnsupportedFormula(f"{name} arguments")


def _split_cell(text: str) -> tuple[int, int]:
    m = _CELL.fullmatch(text)
    if m is None:
        raise UnsupportedFormula(f"bad cell {text!r}")
    return column_index_from_string(m.group(1).upper()), int(m.group(2))


def parse_formula(text: str, sheet: str) -> Node:
    """Parse a formula string (with or without the leading ``=``) into an expression tree."""
    return _Parser(_tokenize(text[1:] if text.startswith("=") else text), sheet).parse()


# ----------------------------------------------------------------------------- value semantics


def _serial(v: date | datetime) -> float:
    d = v if isinstance(v, datetime) else datetime(v.year, v.month, v.day)
    delta = d - _EPOCH
    return delta.days + delta.seconds / 86400


def _raw(v: Any) -> Scalar:
    """A stored (non-formula) cell value as an Excel value."""
    if v is None or isinstance(v, (str, bool)):
        return v
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    if isinstance(v, (date, datetime)):
        return _serial(v)
    if isinstance(v, timedelta):
        return v.total_seconds() / 86400
    raise UnsupportedFormula(f"cell value of type {type(v).__name__}")


def _num(v: Scalar) -> float | XlError:
    if isinstance(v, XlError):
        return v
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, str):
        try:
            return float(v.strip().replace(",", "")) if v.strip() else VALUE
        except ValueError:
            return VALUE
    return v


def _text(v: Scalar) -> str | XlError:
    if isinstance(v, XlError):
        return v
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, str):
        return v
    return str(int(v)) if v == int(v) and abs(v) < 1e15 else format(v, ".15g")


def _truth(v: Scalar) -> bool | XlError:
    if isinstance(v, XlError):
        return v
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        up = v.strip().upper()
        return True if up == "TRUE" else False if up == "FALSE" else VALUE
    return v != 0


def _rank(v: Scalar) -> int:
    return 2 if isinstance(v, bool) else 1 if isinstance(v, str) else 0


def _compare(op: str, a: Scalar, b: Scalar) -> bool | XlError:
    for side in (a, b):
        if isinstance(side, XlError):
            return side
    if a is None and b is None:
        a = b = 0.0
    elif a is None:
        a = "" if isinstance(b, str) else False if isinstance(b, bool) else 0.0
    elif b is None:
        b = "" if isinstance(a, str) else False if isinstance(a, bool) else 0.0
    ka: Any
    kb: Any
    if _rank(a) != _rank(b):
        ka, kb = _rank(a), _rank(b)
    elif isinstance(a, str) and isinstance(b, str):
        ka, kb = a.lower(), b.lower()
    else:
        ka, kb = a, b
    return {
        "=": ka == kb,
        "<>": ka != kb,
        "<": ka < kb,
        ">": ka > kb,
        "<=": ka <= kb,
        ">=": ka >= kb,
    }[op]


def _arith(op: str, a: Scalar, b: Scalar) -> float | XlError:
    x, y = _num(a), _num(b)
    if isinstance(x, XlError):
        return x
    if isinstance(y, XlError):
        return y
    if op == "+":
        return x + y
    if op == "-":
        return x - y
    if op == "*":
        return x * y
    if op == "/":
        return DIV0 if y == 0 else x / y
    try:
        out = x**y
    except (ZeroDivisionError, OverflowError):
        return NUM
    return out if isinstance(out, float) else NUM


# ----------------------------------------------------------------------------------- evaluator

FAILED = object()  # marker for a formula cell the evaluator could not compute


class _Eval:
    def __init__(self, cells: dict[str, dict[tuple[int, int], Any]]) -> None:
        self.cells = cells  # sheet -> (row, col) -> value; formulas appear once computed
        self.formulas: dict[str, set[tuple[int, int]]] = {}

    # -- references
    def _cell(self, sheet: str, row: int, col: int) -> Scalar:
        if sheet not in self.cells:
            return REF
        key = (row, col)
        if key in self.formulas.get(sheet, ()):
            if key not in self.cells[sheet]:
                raise UnsupportedFormula("circular reference")
            v = self.cells[sheet][key]
            if v is FAILED:
                raise UnsupportedFormula("depends on a formula that cannot be computed")
            return cast(Scalar, v)
        v = self.cells[sheet].get(key)
        if v is FAILED:
            raise UnsupportedFormula("depends on a cell value the evaluator cannot read")
        return cast(Scalar, v)

    def _range(self, sheet: str, r1: int, c1: int, r2: int, c2: int) -> _Range | XlError:
        if sheet not in self.cells:
            return REF
        known = set(self.cells[sheet]) | self.formulas.get(sheet, set())
        area = (r2 - r1 + 1) * (c2 - c1 + 1)
        coords: Iterator[tuple[int, int]]
        if area <= len(known):
            coords = ((r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1))
        else:
            coords = iter(sorted(known))
        out = _Range()
        for r, c in coords:
            if r1 <= r <= r2 and c1 <= c <= c2 and (r, c) in known:
                v = self._cell(sheet, r, c)
                if v is not None:
                    out.append(v)
        return out

    def scalar(self, node: Node) -> Scalar:
        v = self.ev(node)
        if isinstance(v, _Range):
            raise UnsupportedFormula("a range where one value is expected")
        return v

    def ev(self, node: Node) -> Scalar | _Range:
        kind = node[0]
        if kind in ("num", "str", "bool"):
            return cast(Scalar, node[1])
        if kind == "ref":
            _, sheet, r1, c1, r2, c2 = node
            if (r1, c1) == (r2, c2):
                return self._cell(sheet, r1, c1)
            return self._range(sheet, r1, c1, r2, c2)
        if kind == "neg":
            n = _num(self.scalar(node[1]))
            return n if isinstance(n, XlError) else -n
        if kind == "pct":
            n = _num(self.scalar(node[1]))
            return n if isinstance(n, XlError) else n / 100
        if kind == "bin":
            op = node[1]
            a, b = self.scalar(node[2]), self.scalar(node[3])
            if op in ("=", "<>", "<", ">", "<=", ">="):
                return _compare(op, a, b)
            if op == "&":
                ta, tb = _text(a), _text(b)
                if isinstance(ta, XlError):
                    return ta
                return tb if isinstance(tb, XlError) else ta + tb
            return _arith(op, a, b)
        if kind == "call":
            fn = _FUNCS.get(node[1])
            if fn is None:
                raise UnsupportedFormula(f"function {node[1]}")
            return fn(self, node[2])
        raise UnsupportedFormula(f"node {kind}")


# -- functions: each takes (evaluator, arg nodes) and returns a value


def _args_numbers(ev: _Eval, args: list[Node]) -> list[float] | XlError:
    """SUM/MAX/MIN arguments: ranges and refs count numbers only; direct values are coerced."""
    out: list[float] = []
    for a in args:
        if a[0] == "ref":
            v = ev.ev(a)
            if isinstance(v, XlError):
                return v
            items = v if isinstance(v, _Range) else [v]
            for item in items:
                if isinstance(item, XlError):
                    return item
                if isinstance(item, float):
                    out.append(item)
        else:
            n = _num(ev.scalar(a))
            if isinstance(n, XlError):
                return n
            out.append(n)
    return out


def _f_sum(ev: _Eval, args: list[Node]) -> Scalar:
    nums = _args_numbers(ev, args)
    return nums if isinstance(nums, XlError) else float(sum(nums))


def _f_max(ev: _Eval, args: list[Node]) -> Scalar:
    nums = _args_numbers(ev, args)
    return nums if isinstance(nums, XlError) else (max(nums) if nums else 0.0)


def _f_min(ev: _Eval, args: list[Node]) -> Scalar:
    nums = _args_numbers(ev, args)
    return nums if isinstance(nums, XlError) else (min(nums) if nums else 0.0)


def _arity(name: str, args: list[Node], low: int, high: int) -> None:
    if not low <= len(args) <= high:
        raise UnsupportedFormula(f"{name} takes {low}-{high} arguments")


def _f_if(ev: _Eval, args: list[Node]) -> Scalar:
    _arity("IF", args, 2, 3)
    cond = _truth(ev.scalar(args[0]))
    if isinstance(cond, XlError):
        return cond
    if cond:
        return ev.scalar(args[1])
    return ev.scalar(args[2]) if len(args) == 3 else False


def _f_iferror(ev: _Eval, args: list[Node]) -> Scalar:
    _arity("IFERROR", args, 2, 2)
    v = ev.scalar(args[0])
    return ev.scalar(args[1]) if isinstance(v, XlError) else v


def _f_isnumber(ev: _Eval, args: list[Node]) -> Scalar:
    _arity("ISNUMBER", args, 1, 1)
    v = ev.scalar(args[0])
    return isinstance(v, float)


def _logic(ev: _Eval, args: list[Node], combine: Callable[[list[bool]], bool]) -> Scalar:
    seen: list[bool] = []
    for a in args:
        v = ev.ev(a)
        if isinstance(v, XlError):
            return v
        items = v if isinstance(v, _Range) else [v]
        for item in items:
            if isinstance(item, XlError):
                return item
            if a[0] == "ref":  # references skip text and empty cells
                if isinstance(item, (bool, float)):
                    seen.append(bool(item))
                continue
            t = _truth(item)
            if isinstance(t, XlError):
                return t
            seen.append(t)
    return combine(seen) if seen else VALUE


def _f_and(ev: _Eval, args: list[Node]) -> Scalar:
    return _logic(ev, args, all)


def _f_or(ev: _Eval, args: list[Node]) -> Scalar:
    return _logic(ev, args, any)


def _f_n(ev: _Eval, args: list[Node]) -> Scalar:
    _arity("N", args, 1, 1)
    v = ev.scalar(args[0])
    if isinstance(v, XlError):
        return v
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    return v if isinstance(v, float) else 0.0


def _f_abs(ev: _Eval, args: list[Node]) -> Scalar:
    _arity("ABS", args, 1, 1)
    n = _num(ev.scalar(args[0]))
    return n if isinstance(n, XlError) else abs(n)


_FUNCS: dict[str, Callable[[_Eval, list[Node]], Scalar]] = {
    "IF": _f_if,
    "IFERROR": _f_iferror,
    "ISNUMBER": _f_isnumber,
    "AND": _f_and,
    "OR": _f_or,
    "SUM": _f_sum,
    "MAX": _f_max,
    "MIN": _f_min,
    "N": _f_n,
    "ABS": _f_abs,
}


# ------------------------------------------------------------------------------- the workbook


@dataclass
class Evaluation:
    """Results per ``(sheet title, "B4")``; ``failed`` maps a formula cell to why it has none."""

    values: dict[tuple[str, str], Scalar] = field(default_factory=dict)
    failed: dict[tuple[str, str], str] = field(default_factory=dict)


Key = tuple[str, int, int]


def _deps(node: Node, formulas: dict[str, set[tuple[int, int]]]) -> Iterator[Key]:
    kind = node[0]
    if kind == "ref":
        _, sheet, r1, c1, r2, c2 = node
        known = formulas.get(sheet, set())
        if (r2 - r1 + 1) * (c2 - c1 + 1) <= len(known):
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    if (r, c) in known:
                        yield sheet, r, c
        else:
            for r, c in known:
                if r1 <= r <= r2 and c1 <= c <= c2:
                    yield sheet, r, c
    elif kind in ("neg", "pct"):
        yield from _deps(node[1], formulas)
    elif kind == "bin":
        yield from _deps(node[2], formulas)
        yield from _deps(node[3], formulas)
    elif kind == "call":
        for a in node[2]:
            yield from _deps(a, formulas)


def evaluate_workbook(wb: Workbook) -> Evaluation:
    """Compute every formula cell of ``wb`` in memory (the workbook is not changed)."""
    cells: dict[str, dict[tuple[int, int], Any]] = {}
    formula_text: dict[Key, str] = {}
    result = Evaluation()
    for ws in wb.worksheets:
        store: dict[tuple[int, int], Any] = {}
        for row in ws.iter_rows():
            for c in row:
                if c.value is None:
                    continue
                if c.data_type == "f" and isinstance(c.value, str):
                    formula_text[(ws.title, c.row, c.column)] = c.value
                    continue
                try:
                    if c.data_type == "f":
                        raise UnsupportedFormula("array or data-table formula")
                    store[(c.row, c.column)] = _raw(c.value)
                except UnsupportedFormula as exc:
                    store[(c.row, c.column)] = FAILED
                    result.failed[(ws.title, c.coordinate)] = str(exc)
        cells[ws.title] = store
    ev = _Eval(cells)
    for sheet, r, c in formula_text:
        ev.formulas.setdefault(sheet, set()).add((r, c))

    trees: dict[Key, Node | str] = {}
    for key, text in formula_text.items():
        try:
            trees[key] = parse_formula(text, key[0])
        except UnsupportedFormula as exc:
            trees[key] = str(exc)

    def deps_of(key: Key) -> Iterator[Key]:
        tree = trees[key]
        return iter(()) if isinstance(tree, str) else _deps(tree, ev.formulas)

    done: set[Key] = set()
    for start in formula_text:
        if start in done:
            continue
        entered = {start}
        stack: list[tuple[Key, Iterator[Key]]] = [(start, deps_of(start))]
        while stack:
            key, it = stack[-1]
            nxt = next((d for d in it if d not in done and d not in entered), None)
            if nxt is not None:
                entered.add(nxt)
                stack.append((nxt, deps_of(nxt)))
                continue
            stack.pop()
            _compute(ev, key, trees[key], result)
            done.add(key)
    return result


def _compute(ev: _Eval, key: Key, tree: Node | str, result: Evaluation) -> None:
    sheet, r, c = key
    coord = f"{get_column_letter(c)}{r}"
    try:
        if isinstance(tree, str):
            raise UnsupportedFormula(tree)
        v = ev.scalar(tree)
    except UnsupportedFormula as exc:
        ev.cells[sheet][(r, c)] = FAILED
        result.failed[(sheet, coord)] = str(exc)
        return
    out: Scalar = 0.0 if v is None else v  # a formula that points at an empty cell shows 0
    ev.cells[sheet][(r, c)] = out
    result.values[(sheet, coord)] = out


# ---------------------------------------------------------------------------------- the writer

_FORMULA_CELL = re.compile(
    r'<c r="([A-Z]+[0-9]+)"((?: [A-Za-z:]+="[^"]*")*)><f>(.*?)</f><v ?/></c>'
)
_SHEET_FILE = re.compile(r"xl/worksheets/sheet(\d+)\.xml")


def _number(v: float) -> str:
    return str(int(v)) if v == int(v) and abs(v) < 1e15 else repr(v)


def _cell_xml(coord: str, attrs: str, formula: str, v: Scalar) -> str:
    attrs = re.sub(r' t="[^"]*"', "", attrs)
    if isinstance(v, bool):
        return f'<c r="{coord}"{attrs} t="b"><f>{formula}</f><v>{int(v)}</v></c>'
    if isinstance(v, XlError):
        return f'<c r="{coord}"{attrs} t="e"><f>{formula}</f><v>{escape(v.code)}</v></c>'
    if isinstance(v, str):
        return f'<c r="{coord}"{attrs} t="str"><f>{formula}</f><v>{escape(v)}</v></c>'
    if v is None:
        raise UnsupportedFormula(f"no result for {coord}")
    return f'<c r="{coord}"{attrs}><f>{formula}</f><v>{_number(v)}</v></c>'


def embed_cached_values(xlsx: bytes, wb: Workbook, evaluation: Evaluation) -> bytes:
    """Rewrite the saved ``xlsx`` so each computed formula cell carries its result in ``<v>``."""
    titles = [ws.title for ws in wb.worksheets]
    src = zipfile.ZipFile(io.BytesIO(xlsx))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            m = _SHEET_FILE.fullmatch(item.filename)
            if m is not None and 1 <= int(m.group(1)) <= len(titles):
                title = titles[int(m.group(1)) - 1]

                def swap(cm: re.Match[str], title: str = title) -> str:
                    coord = cm.group(1)
                    if (title, coord) not in evaluation.values:
                        return cm.group(0)
                    return _cell_xml(
                        coord, cm.group(2), cm.group(3), evaluation.values[(title, coord)]
                    )

                data = _FORMULA_CELL.sub(swap, data.decode("utf-8")).encode("utf-8")
            dst.writestr(item, data)
    return out.getvalue()


def with_cached_values(wb: Workbook, xlsx: bytes, *, strict: bool = False) -> bytes:
    """``xlsx`` (the saved ``wb``) with cached results; never raises unless ``strict``.

    A formula that cannot be computed is logged and keeps an empty ``<v>`` (never a 0). In
    ``strict`` mode (tests) it raises ``UnsupportedFormula`` instead.
    """
    try:
        evaluation = evaluate_workbook(wb)
        if evaluation.failed:
            detail = "; ".join(f"{s}!{c}: {w}" for (s, c), w in sorted(evaluation.failed.items()))
            if strict:
                raise UnsupportedFormula(detail)
            logger.warning(
                "export: %d formula(s) have no cached value: %s",
                len(evaluation.failed),
                detail[:500],
            )
        return embed_cached_values(xlsx, wb, evaluation)
    except UnsupportedFormula:
        raise
    except Exception:
        if strict:
            raise
        logger.exception("export: cached values skipped, the file is saved without them")
        return xlsx
