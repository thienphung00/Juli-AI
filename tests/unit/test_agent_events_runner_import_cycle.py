"""Proves the `events`/`runner` import cycle is structurally eliminated —
not merely worked around — by relocating `WorkflowRunStatus`/`StopReason`/
`STOP_REASON_TO_STATUS` to `services/agent/status.py` (#1139, AGT-W3A).

**History.** #1125 (`events/payloads.py`) needed `StopReason`/
`WorkflowRunStatus` for event payloads and imported them from
`services/agent/runner/status.py` — the only module that had them at the
time. Importing *any* submodule of `runner` forces Python to execute
`runner/__init__.py` first. If that `__init__.py` ever eagerly imported
`runner.core` (which imports `services.agent.events` right back), the
result was a genuine cycle: `events -> runner.status -> runner/__init__ ->
runner.core -> events`, caught mid-load and raised as an `ImportError`
naming a "partially initialized module". #1119's fix was a PEP 562 lazy
`__getattr__` in `runner/__init__.py` deferring the `core`/`tool_executor`
imports until first attribute access — a workaround that left `events`
still depending on `runner` for vocabulary it doesn't own.

#1139 relocates that vocabulary to `services/agent/status.py`, a leaf
module with zero intra-package dependents that both `runner` and `events`
import directly. `events` no longer imports anything from `runner`, so
nothing `runner/__init__.py` does — eager or lazy — can affect `events`'s
load order. The lazy `__getattr__` is deleted; `WorkflowRunner` is now an
ordinary eager package-level export.

Every subprocess scenario below runs in a **fresh interpreter** (mirroring
`test_celery_agent_broker_boot_assertion.py`'s pattern) so `sys.modules`
starts empty and the import order asserted is the *only* thing that has
happened by the time each process's assertion runs — this repo's single,
already-import-polluted pytest session would hide a reintroduced cycle
otherwise, since many other modules already import both packages by the
time any one test runs.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
EVENTS_PACKAGE_DIR = BACKEND_SRC / "juli_backend" / "services" / "agent" / "events"


def _run_in_subprocess(code: str) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND_SRC)
    return subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestBothImportOrdersSucceedEagerlyInAFreshInterpreter:
    """AC: eagerly importing `events` and `runner`, in both orders, in a
    fresh interpreter, must succeed. The original failure signature was
    `ImportError: cannot import name 'AssistantTextEvent' from partially
    initialized module` — if the cycle ever reappears (e.g. someone
    reintroduces an eager `runner/__init__.py -> runner.core -> events`
    edge while `events` still imported from `runner`), one of these two
    orders raises exactly that shape of `ImportError` and this test fails
    with it in `stderr`.
    """

    def test_events_first_then_runner(self):
        result = _run_in_subprocess(
            "import juli_backend.services.agent.events as events\n"
            "import juli_backend.services.agent.runner as runner\n"
            "print(runner.WorkflowRunner.__name__)\n"
            "print(runner.RunResult.__name__)\n"
            "print(events.EventSink.__name__)\n"
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "WorkflowRunner" in result.stdout
        assert "RunResult" in result.stdout
        assert "EventSink" in result.stdout

    def test_runner_first_then_events(self):
        result = _run_in_subprocess(
            "import juli_backend.services.agent.runner as runner\n"
            "import juli_backend.services.agent.events as events\n"
            "print(runner.WorkflowRunner.__name__)\n"
            "print(runner.RunResult.__name__)\n"
            "print(events.EventSink.__name__)\n"
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "WorkflowRunner" in result.stdout
        assert "RunResult" in result.stdout
        assert "EventSink" in result.stdout

    def test_status_submodule_first_then_events_then_runner(self):
        """The specific edge that made the cycle possible in the first
        place: importing `services.agent.status` directly (as
        `events/payloads.py` does) must not force `runner/__init__.py` to
        execute at all — `status.py` no longer lives inside `runner/`."""
        result = _run_in_subprocess(
            "import sys\n"
            "import juli_backend.services.agent.status\n"
            "runner_pkg_loaded = 'juli_backend.services.agent.runner' in sys.modules\n"
            "print(f'runner_pkg_loaded={runner_pkg_loaded}')\n"
            "import juli_backend.services.agent.events as events\n"
            "import juli_backend.services.agent.runner as runner\n"
            "print(runner.WorkflowRunner.__name__)\n"
            "print(events.EventSink.__name__)\n"
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "runner_pkg_loaded=False" in result.stdout
        assert "WorkflowRunner" in result.stdout
        assert "EventSink" in result.stdout


class TestWorkflowRunnerExportIsEagerNotLazy:
    """AC: the PEP 562 `__getattr__` workaround is deleted — `runner.core`
    (and `runner.tool_executor`) are real, ordinary imports that execute as
    part of `runner/__init__.py`, not deferred until first attribute
    access."""

    def test_core_and_tool_executor_are_in_sys_modules_immediately(self):
        result = _run_in_subprocess(
            "import sys\n"
            "import juli_backend.services.agent.runner\n"
            "core_loaded = 'juli_backend.services.agent.runner.core' in sys.modules\n"
            "tool_executor_loaded = "
            "'juli_backend.services.agent.runner.tool_executor' in sys.modules\n"
            "print(f'core_loaded={core_loaded}')\n"
            "print(f'tool_executor_loaded={tool_executor_loaded}')\n"
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "core_loaded=True" in result.stdout
        assert "tool_executor_loaded=True" in result.stdout

    def test_tool_executor_exports_resolve_as_package_attributes_in_either_order(self):
        """Regression cover for the one assertion lost when
        `test_agent_runner_lazy_import.py` was deleted (found in review of #1139).

        The three `tool_executor` names must resolve off the `runner` *package*,
        not merely off `runner.tool_executor`. Under the old lazy `__getattr__`
        that resolution was the entire point of the workaround; with the
        workaround deleted it has to hold eagerly instead — and in both import
        orders, since events-first is the order that used to cycle.

        `test_core_and_tool_executor_are_in_sys_modules_immediately` proves the
        submodules load, which is a weaker claim: a submodule can be in
        `sys.modules` while the package never re-exports its names.
        """
        events_mod = "juli_backend.services.agent.events.payloads"
        runner_mod = "juli_backend.services.agent.runner"
        names = ("ProductToolExecutor", "ToolExecutor", "ToolExecutionError")

        for first, second in ((events_mod, runner_mod), (runner_mod, events_mod)):
            result = _run_in_subprocess(
                f"import {first}\n"
                f"import {second}\n"
                f"import {runner_mod} as runner\n"
                f"for name in {names!r}:\n"
                "    print(f'{name}={getattr(runner, name).__name__}')\n"
            )
            assert result.returncode == 0, (
                f"import order {first} -> {second} failed: "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
            for name in names:
                assert f"{name}={name}" in result.stdout, (
                    f"{name} did not resolve as a `runner` package attribute in "
                    f"import order {first} -> {second}: stdout={result.stdout!r}"
                )

    def test_runner_init_has_no_module_getattr(self):
        import juli_backend.services.agent.runner as runner

        assert "__getattr__" not in vars(runner), (
            "runner/__init__.py must not define a module-level __getattr__ — "
            "the PEP 562 lazy-export workaround was deleted by #1139"
        )

    def test_unknown_attribute_still_raises_attribute_error(self):
        import juli_backend.services.agent.runner as runner

        with pytest.raises(AttributeError):
            runner.NotARealExport


_RUNNER_MODULE = "juli_backend.services.agent.runner"


def _is_runner_module(dotted: str) -> bool:
    """True for the runner package itself and anything beneath it — but not for a
    sibling that merely shares the prefix (`...agent.runner_utils`)."""
    return dotted == _RUNNER_MODULE or dotted.startswith(_RUNNER_MODULE + ".")


def _containing_package(path: Path) -> str:
    """Dotted name of the package a file lives in — the base a `level=1` relative
    import resolves against. That is the containing directory either way: for
    `pkg/__init__.py` it is `pkg` (the package the file defines), and for
    `pkg/mod.py` it is also `pkg` (the module's parent)."""
    return ".".join(path.parent.relative_to(BACKEND_SRC).parts)


def _imported_module_paths(node: ast.AST, path: Path) -> list[str]:
    """Every absolute dotted module path an import statement can reach.

    Three forms have to be resolved, not just the obvious one — a guard that
    only understands `from juli_backend.services.agent.runner.x import y` is
    trivially, and silently, bypassed by the other two:

    - `import a.b.c`                    -> the dotted names directly
    - `from a.b import c`               -> `a.b` *and* `a.b.c`, since `c` may be
                                           a submodule rather than an attribute
    - `from ..runner import c`          -> resolved against the containing
                                           package, since `node.module` is a
                                           bare `"runner"` with `level=2`
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []

    if node.level:
        parts = _containing_package(path).split(".")
        base_parts = parts[: len(parts) - (node.level - 1)]
        base = ".".join(base_parts)
        target = f"{base}.{node.module}" if node.module else base
    else:
        target = node.module or ""

    if not target:
        return []
    # `from X import name` binds X.name when `name` is a submodule, so both the
    # package and each imported name have to be checked.
    return [target] + [f"{target}.{alias.name}" for alias in node.names]


class TestEventsPackageImportsNothingFromRunner:
    """AC: `events` no longer imports anything from `runner` — statically
    verified by walking every `.py` file's AST under `services/agent/events/`
    rather than trusting prose, so a reintroduced `from
    juli_backend.services.agent.runner...` import anywhere in that package
    trips this test."""

    def test_no_file_under_events_imports_from_runner(self):
        assert EVENTS_PACKAGE_DIR.is_dir(), f"events package not found at {EVENTS_PACKAGE_DIR}"

        offending: list[str] = []
        for path in sorted(EVENTS_PACKAGE_DIR.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                for target in _imported_module_paths(node, path):
                    if _is_runner_module(target):
                        offending.append(f"{path}: {ast.unparse(node)}  -> {target}")

        assert not offending, (
            "services/agent/events/ must not import from services/agent/runner/ "
            f"(the events contract must not depend on the runner implementation): {offending}"
        )

    @pytest.mark.parametrize(
        ("statement", "trips"),
        [
            # The obvious form.
            ("from juli_backend.services.agent.runner.core import WorkflowRunner", True),
            ("from juli_backend.services.agent.runner import core", True),
            ("import juli_backend.services.agent.runner.core", True),
            ("import juli_backend.services.agent.runner as r", True),
            # Importing the subpackage *by name* — `node.module` is only
            # `...services.agent` here, so a guard reading `node.module` alone
            # never sees `runner` and waves this straight through.
            ("from juli_backend.services.agent import runner", True),
            # Relative forms — `node.module` is a bare `"runner"` with level=2,
            # which does not start with the absolute prefix at all.
            ("from ..runner import core", True),
            ("from ..runner.core import WorkflowRunner", True),
            ("from .. import runner", True),
            # Must NOT trip: the neutral status module this slice created, in
            # every form, or a sibling that merely shares the name prefix.
            ("from juli_backend.services.agent.status import StopReason", False),
            ("from juli_backend.services.agent import status", False),
            ("from ..status import StopReason", False),
            ("import juli_backend.services.agent.runner_utils", False),
        ],
    )
    def test_guard_resolves_every_form_of_import(self, statement: str, trips: bool):
        """The guard is only worth having if it cannot be sidestepped by writing
        the same import a different way. Each form below is resolved to the
        absolute module paths it can actually reach, and checked.

        The `False` rows matter as much as the `True` ones: a guard that trips on
        everything would pass the `True` rows while making the package unusable,
        and `runner_utils` pins that prefix matching respects module boundaries.
        """
        node = ast.parse(statement).body[0]
        targets = _imported_module_paths(node, EVENTS_PACKAGE_DIR / "synthetic_module.py")
        assert any(_is_runner_module(t) for t in targets) is trips, (
            f"{statement!r} resolved to {targets}"
        )
