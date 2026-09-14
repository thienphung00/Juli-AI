"""Guard (#1891): no test may set the database role from a `connect`-event listener.

`tests/unit/test_action_card_refresh_task_scope.py::_juli_app_engine_session_factory`
used to issue `SET ROLE juli_app` from `@event.listens_for(engine.sync_engine,
"connect")`. That statement runs inside the DBAPI's own implicit transaction, and
SQLAlchemy's reset-on-return issues a ROLLBACK when a connection goes back to the
pool -- which undoes it. Measured on this repo's own Postgres, 2026-09-10:

    session 1: current_user=juli_app
    session 2: current_user=macos
    session 3: current_user=macos

So only the FIRST session drawn from such a pool actually runs as `juli_app`; every
later one is silently the table owner, which is exempt from row-level security --
any assertion spanning more than one session from that factory proved nothing about
RLS. The fix (`tests/support/postgres.py`'s `juli_app_async_sessionmaker` /
`juli_app_sync_sessionmaker`) sets the role in the connection's own startup packet
(`server_settings`/`options`) instead, which survives a reset-on-return because it is
the connection's own default rather than a statement run against it.

This is deliberately a *static AST scan*, following the convention already
established by `test_agent_llm_sdk_containment.py` and
`test_demo_execution_import_boundary.py`: the property this guards must hold whether
or not the offending branch is ever exercised by a particular test run, and a
string-grep would false-positive on this very module's docstring (which says
"SET ROLE" and "connect" several times) -- `ast` sees code, not comments/docstrings.

Placed as its own module rather than folded into `test_test_quality.py`: that
module's detectors are driven by the separate `eval.quality_detectors` /
`eval.ratchets` machinery (diff-scoped mutation scoring, ratchet fingerprints) built
for a different class of defect (a test that never went red). This guard is a
simple, permanent, always-on repo-wide containment check with no ratchet or
diff-scoping involved -- the same shape as `test_agent_llm_sdk_containment.py`, which
is why it lives beside it rather than growing a new detector for a one-off pattern.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = REPO_ROOT / "tests"

# A sweep that silently discovers zero test files would pass vacuously. Kept well
# below the real count (500+ modules under tests/ as of this commit) so the test
# doesn't become a tripwire on ordinary repo growth/pruning.
MIN_PLAUSIBLE_TEST_FILE_COUNT = 100

_ROLE_PATTERN = "set role"

# The helpers this guard exists to protect -- named in the failure message so a
# future violation points straight at the fix, not just at the ban.
_SANCTIONED_HELPERS = (
    "tests.support.postgres.juli_app_async_sessionmaker",
    "tests.support.postgres.juli_app_sync_sessionmaker",
)


def _discover_test_files(*, root: Path = TESTS_ROOT) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _is_listens_for_call(node: ast.AST) -> bool:
    """`event.listens_for(...)` or a bare `listens_for(...)`, however imported."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "listens_for"
    if isinstance(func, ast.Name):
        return func.id == "listens_for"
    return False


def _is_listen_call(node: ast.AST) -> bool:
    """`event.listen(...)` or a bare `listen(...)`, however imported."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "listen"
    if isinstance(func, ast.Name):
        return func.id == "listen"
    return False


def _call_targets_connect_event(call: ast.Call) -> bool:
    """True if any positional argument to the registration call is the string
    literal `"connect"` -- the event name is always a plain string in every
    shape SQLAlchemy's `event` API accepts (positional, never keyword-only)."""
    return any(isinstance(arg, ast.Constant) and arg.value == "connect" for arg in call.args)


def _sets_role_in_body(handler: ast.AST) -> bool:
    """Whether `handler`'s source text (as reconstructed by `ast.unparse`) contains
    a `SET ROLE` statement anywhere -- including inside an f-string, which
    `ast.unparse` renders back into `f'SET ROLE {x}'` text rather than leaving it
    as an opaque `JoinedStr` node.
    """
    try:
        source = ast.unparse(handler)
    except (ValueError, TypeError):
        return False
    return _ROLE_PATTERN in source.lower()


def _find_function_by_name(tree: ast.Module, name: str) -> ast.AST | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    return None


def _connect_role_violations(py_file: Path) -> list[str]:
    """Return a list of human-readable violation descriptions for `py_file`, empty
    if the file registers no role-setting `connect`-event listener.
    """
    source = py_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(py_file))
    violations: list[str] = []

    for node in ast.walk(tree):
        # Decorator form: `@event.listens_for(engine, "connect")` on the handler
        # function itself.
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for decorator in node.decorator_list:
                if _is_listens_for_call(decorator) and _call_targets_connect_event(decorator):
                    if _sets_role_in_body(node):
                        violations.append(
                            f"{node.lineno}: @event.listens_for(..., 'connect') handler "
                            f"'{node.name}' issues SET ROLE"
                        )

        # Direct-call form: `event.listen(engine, "connect", handler)`.
        if _is_listen_call(node) and _call_targets_connect_event(node):
            handler_arg = node.args[-1] if node.args else None
            handler_node: ast.AST | None = None
            if isinstance(handler_arg, ast.Name):
                handler_node = _find_function_by_name(tree, handler_arg.id)
            elif isinstance(handler_arg, ast.Lambda):
                handler_node = handler_arg
            if handler_node is not None and _sets_role_in_body(handler_node):
                violations.append(
                    f"{node.lineno}: event.listen(..., 'connect', ...) handler issues SET ROLE"
                )

    return violations


def _scan_for_violations(*, root: Path = TESTS_ROOT) -> dict[Path, list[str]]:
    violations: dict[Path, list[str]] = {}
    for py_file in _discover_test_files(root=root):
        found = _connect_role_violations(py_file)
        if found:
            violations[py_file] = found
    return violations


def test_sweep_discovers_a_plausible_number_of_test_files() -> None:
    """Guards against the sweep silently finding zero (or near-zero) files -- a scan
    over an empty or wrong directory would pass every containment assertion
    vacuously.
    """
    discovered = _discover_test_files()
    assert len(discovered) >= MIN_PLAUSIBLE_TEST_FILE_COUNT, (
        f"expected to discover at least {MIN_PLAUSIBLE_TEST_FILE_COUNT} test files "
        f"under {TESTS_ROOT}, only found {len(discovered)} -- is TESTS_ROOT wrong, "
        "or did the sweep silently fail to walk the tree?"
    )


def test_no_test_sets_the_database_role_from_a_connect_event_listener() -> None:
    """The real repo-wide check (AC2, #1891): no test in `tests/` sets the database
    role via a `connect`-event listener. Use `tests/support/postgres.py`'s
    `juli_app_async_sessionmaker` / `juli_app_sync_sessionmaker` instead -- both set
    the role in the connection's startup packet, which survives the pool's
    reset-on-return.
    """
    violations = _scan_for_violations()

    assert not violations, (
        "found a connect-event role-setting listener -- this pattern only holds "
        "for the FIRST session drawn from the pool (#1891). Use "
        f"{_SANCTIONED_HELPERS} from tests/support/postgres.py instead. "
        f"Offending module(s): "
        f"{ {str(f.relative_to(REPO_ROOT)): v for f, v in violations.items()} }"
    )


def _write_module(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_scan_detects_a_synthetic_decorator_form_violation(tmp_path: Path) -> None:
    """Proves the guard is not vacuous for the decorator form -- the exact shape
    `_juli_app_engine_session_factory` used before this issue's fix.
    """
    offending = tmp_path / "test_synthetic_decorator.py"
    _write_module(
        offending,
        (
            "from sqlalchemy import event\n\n"
            "def make(engine):\n"
            "    @event.listens_for(engine.sync_engine, 'connect')\n"
            "    def _set_role(dbapi_connection, connection_record):\n"
            "        cursor = dbapi_connection.cursor()\n"
            "        cursor.execute(f'SET ROLE {ROLE}')\n"
            "        cursor.close()\n"
        ),
    )

    violations = _scan_for_violations(root=tmp_path)

    assert offending in violations, f"expected {offending} to be flagged, got {violations}"
    assert "SET ROLE" in violations[offending][0]


def test_scan_detects_a_synthetic_direct_call_form_violation(tmp_path: Path) -> None:
    """Proves the guard also catches the `event.listen(engine, "connect", handler)`
    direct-call form, not only the decorator form.
    """
    offending = tmp_path / "test_synthetic_direct_call.py"
    _write_module(
        offending,
        (
            "from sqlalchemy import event\n\n"
            "def _set_role(dbapi_connection, connection_record):\n"
            "    cursor = dbapi_connection.cursor()\n"
            "    cursor.execute('SET ROLE juli_app')\n"
            "    cursor.close()\n\n"
            "def make(engine):\n"
            "    event.listen(engine.sync_engine, 'connect', _set_role)\n"
        ),
    )

    violations = _scan_for_violations(root=tmp_path)

    assert offending in violations, f"expected {offending} to be flagged, got {violations}"


def test_a_connect_listener_that_does_not_set_role_is_not_flagged(tmp_path: Path) -> None:
    """The negative: proves the guard is precise, not a blanket ban on every
    `connect`-event listener -- only the role-setting shape is forbidden.
    """
    benign = tmp_path / "test_synthetic_benign_connect_listener.py"
    _write_module(
        benign,
        (
            "from sqlalchemy import event\n\n"
            "def make(engine):\n"
            "    connect_count = []\n\n"
            "    @event.listens_for(engine.sync_engine, 'connect')\n"
            "    def _count_connect(dbapi_connection, connection_record):\n"
            "        connect_count.append(1)\n\n"
            "    return connect_count\n"
        ),
    )

    violations = _scan_for_violations(root=tmp_path)

    assert not violations, f"expected no violations for a benign connect listener, got {violations}"


def test_a_non_connect_event_listener_that_sets_role_is_not_flagged(tmp_path: Path) -> None:
    """A second negative: a `SET ROLE` inside a handler for a *different* event
    (e.g. `before_cursor_execute`, used elsewhere in this repo for query counting)
    must not be flagged -- the defect this guards against is specific to `connect`,
    where the pool's reset-on-return undoes the statement.
    """
    benign = tmp_path / "test_synthetic_other_event_role_set.py"
    _write_module(
        benign,
        (
            "from sqlalchemy import event\n\n"
            "def make(engine):\n"
            "    @event.listens_for(engine.sync_engine, 'before_cursor_execute')\n"
            "    def _set_role(conn, cursor, statement, parameters, context, executemany):\n"
            "        cursor.execute('SET ROLE juli_app')\n"
            "\n"
        ),
    )

    violations = _scan_for_violations(root=tmp_path)

    assert not violations, f"expected no violations for a non-connect event, got {violations}"
