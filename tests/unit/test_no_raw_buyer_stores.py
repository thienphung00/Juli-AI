"""No new raw webhook store and no exception text in a ``last_error`` column (D16).

Owner decision D16 (ADR-116 §4, fast track D76) filters buyer data in memory
before any persistence. ``tests/unit/test_nda_buyer_data_sinks.py`` proves each
sink that exists today; this file stops the two shapes that leaked from coming
back in a new one:

1. **A webhook's ``data`` stored as received** -- ``payload=event.data``,
   ``row.payload = event.data``, ``payload_json=json.dumps(event.data)`` or a
   ``raw_body`` / ``payload`` built straight from ``.data``. A stored payload goes
   through ``sanitize_raw_payload`` / ``allowlist_payload`` first.
2. **An exception's text in a ``last_error`` column** -- ``repr(exc)``, ``{exc!r}``,
   ``str(exc)`` or ``f"{exc}"`` assigned to (or passed as) ``last_error``. A
   message can echo a vendor body, a rejected input value or bound SQL values;
   ``core.privacy.error_label`` is the shape to store.

AST, not grep, as in ``test_users_phone_is_never_fabricated.py``: the modules that
fixed these leaks document the old expression in comments and docstrings, and a
regex cannot tell the warning from the offence. Each detector is also run on a
synthetic offender, so a detector that stopped matching fails here too.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend/src/juli_backend"

#: Keyword / attribute names that persist a payload.
STORE_NAMES = frozenset({"payload", "payload_json", "raw_body"})
#: Names that hold an exception in the error-recording code paths. ``error`` is not
#: one: ``services/order_costs/store.py`` takes ``error: str`` -- an already-built
#: label -- and interpolates it; ``repr(error)`` is still caught by name-free ``repr``.
EXCEPTION_NAMES = frozenset({"exc", "err", "e", "exception"})


def _backend_sources() -> list[Path]:
    return sorted(p for p in BACKEND.rglob("*.py") if "migrations" not in p.parts)


def _is_raw_data(node: ast.AST) -> bool:
    """``x.data``, ``x.data or {}``, or ``json.dumps(x.data, ...)``."""
    if isinstance(node, ast.Attribute) and node.attr == "data":
        return True
    if isinstance(node, ast.BoolOp):
        return any(_is_raw_data(value) for value in node.values)
    if isinstance(node, ast.Call) and node.args:
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        return name in {"dumps", "dict"} and _is_raw_data(node.args[0])
    return False


def _is_exception_text(node: ast.AST) -> bool:
    """``repr(exc)``, ``str(exc)``, an f-string with ``{exc}`` / ``{exc!r}``, sliced or not."""
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            if child.func.id == "repr":
                return True
            if child.func.id == "str" and child.args and _names_exception(child.args[0]):
                return True
        if isinstance(child, ast.FormattedValue):
            if child.conversion == ord("r") or _names_exception(child.value):
                return True
    return False


def _names_exception(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id in EXCEPTION_NAMES


def raw_store_offences(tree: ast.AST) -> list[int]:
    """Line numbers storing a webhook's ``data`` as received."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg in STORE_NAMES and _is_raw_data(node.value):
            lines.append(node.value.lineno)
        if isinstance(node, ast.Assign) and _is_raw_data(node.value):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr in STORE_NAMES:
                    lines.append(node.lineno)
    return sorted(lines)


def last_error_offences(tree: ast.AST) -> list[int]:
    """Line numbers writing exception text into a ``last_error`` column."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.keyword)
            and node.arg == "last_error"
            and _is_exception_text(node.value)
        ):
            lines.append(node.value.lineno)
        if isinstance(node, ast.Assign) and _is_exception_text(node.value):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr == "last_error":
                    lines.append(node.lineno)
    return sorted(lines)


def _offences(detector) -> list[str]:
    found: list[str] = []
    for path in _backend_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found.extend(f"{path.relative_to(BACKEND)}:{line}" for line in detector(tree))
    return found


SYNTHETIC = """
async def handler(event, repo, row, state_repo, exc, error):
    await repo.record_if_new(payload_json=json.dumps(event.data, sort_keys=True))
    await repo.insert(raw_body=event.data or {})
    row.payload = event.data
    await state_repo.update(shop_id, last_error=repr(exc))
    await state_repo.update(shop_id, last_error=f"scoring: {exc!r}")
    row.last_error = str(exc)[:200]
    row.last_error = f"failed: {exc}"
"""

CLEAN = """
async def handler(event, repo, row, state_repo, exc, error):
    payload = await sanitize_raw_payload(session, shop_id, payload=delivered)
    await repo.record_if_new(payload_json=json.dumps(payload, sort_keys=True))
    await state_repo.update(shop_id, last_error=error_label(exc))
    row.last_error = f"scoring: {error_label(exc)}"
    row.last_error = f"{read}: {error}"[:200]
    row.last_error = None
"""


def test_the_detectors_catch_every_synthetic_offence_and_nothing_clean() -> None:
    tree = ast.parse(SYNTHETIC)
    assert raw_store_offences(tree) == [3, 4, 5]
    assert last_error_offences(tree) == [6, 7, 8, 9]
    clean = ast.parse(CLEAN)
    assert raw_store_offences(clean) == []
    assert last_error_offences(clean) == []


def test_no_webhook_data_is_stored_as_received() -> None:
    offences = _offences(raw_store_offences)
    assert offences == [], (
        f"{offences} store a webhook's `data` as received. Reduce it with "
        "`services.privacy.raw_payload.sanitize_raw_payload` (or `allowlist_payload` "
        "with a reviewed spec) first -- D16, ADR-116 §4."
    )


def test_no_exception_text_reaches_a_last_error_column() -> None:
    offences = _offences(last_error_offences)
    assert offences == [], (
        f"{offences} write exception text into `last_error`. Store "
        "`juli_backend.core.privacy.error_label(exc)` (class and vendor code) -- D16."
    )
