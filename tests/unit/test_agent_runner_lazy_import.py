"""Pins `services/agent/runner/__init__.py`'s lazy `WorkflowRunner`/`RunResult`/
`ProductToolExecutor` export (issue #1119, ADR-073 decision 1 — Review
follow-up).

**Why this file exists.** `events/payloads.py` (#1125) imports
`juli_backend.services.agent.runner.status` — a genuine dependency (event
payloads carry `StopReason`/`WorkflowRunStatus`). Importing *any* submodule
of `services.agent.runner` forces Python to execute this package's
`__init__.py` first. If `__init__.py` eagerly imported `core.py` (which
imports `juli_backend.services.agent.events` right back), that would be a
real import cycle: `events -> runner.status -> runner/__init__ ->
runner.core -> events`, caught mid-load and raising an `ImportError` naming
a "partially initialized module". Review reproduced exactly that by
re-adding an eager `from .core import RunResult, WorkflowRunner` to
`__init__.py`. The fix (`__init__.py`'s `__getattr__`, PEP 562) defers
importing `core`/`tool_executor` until something actually reads
`runner.WorkflowRunner` off the package — by which point `__init__.py` has
already finished executing, so the cycle cannot occur.

Nothing pinned that mechanism before this file: the general "package import
crashes" symptom Review's mutation produced isn't proof the *lazy* pattern
is what's protecting against it specifically — a future "tidy up that
`__getattr__`" edit that reverts to an eager import would only be caught the
next time someone imports `events` before `runner` in a fresh process, which
does not reliably happen inside this repo's single, already-import-polluted
pytest session (many other modules already import both packages by the time
any one test runs, so the cycle can go unnoticed in-process). Every test
below therefore runs in a **fresh subprocess** — mirroring
`test_celery_agent_broker_boot_assertion.py`'s pattern for #1129's own
fail-closed boot assertion — so `sys.modules` starts empty and the import
order asserted is the *only* thing that has happened by the time each
process's assertion runs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"


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


class TestBothImportOrdersSucceedInAFreshInterpreter:
    """AC (Review follow-up): `WorkflowRunner`/`RunResult` resolve through
    the package root regardless of which of the two mutually-dependent
    packages (`events`, `runner`) a caller happens to import first."""

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

    def test_runner_status_submodule_first_then_events(self):
        """The specific edge that made the cycle possible in the first
        place: importing `runner.status` directly (as `events/payloads.py`
        does) executes `runner/__init__.py` before anything about `events`
        has loaded."""
        result = _run_in_subprocess(
            "import juli_backend.services.agent.runner.status\n"
            "import juli_backend.services.agent.events as events\n"
            "import juli_backend.services.agent.runner as runner\n"
            "print(runner.WorkflowRunner.__name__)\n"
            "print(events.EventSink.__name__)\n"
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "WorkflowRunner" in result.stdout
        assert "EventSink" in result.stdout

    def test_tool_executor_exports_resolve_in_either_order(self):
        result = _run_in_subprocess(
            "import juli_backend.services.agent.events as events\n"
            "import juli_backend.services.agent.runner as runner\n"
            "print(runner.ProductToolExecutor.__name__)\n"
            "print(runner.ToolExecutor.__name__)\n"
            "print(runner.ToolExecutionError.__name__)\n"
            "print(events.EventSink.__name__)\n"
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "ProductToolExecutor" in result.stdout
        assert "ToolExecutor" in result.stdout
        assert "ToolExecutionError" in result.stdout


class TestImportingThePackageDoesNotEagerlyImportCoreOrToolExecutor:
    """AC (Review follow-up): pin the *mechanism*, not just the outcome.

    Importing `juli_backend.services.agent.runner` alone (touching no
    attribute) must leave `runner.core`/`runner.tool_executor` absent from
    `sys.modules` — the direct, mechanical fact that makes the cycle
    unreachable. A future edit that swaps `__getattr__` back for an eager
    `from .core import ...` fails this test immediately, independent of
    whether that particular process import order happens to also trigger
    the `events` cycle.
    """

    def test_core_and_tool_executor_are_not_imported_by_bare_package_import(self):
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
        assert "core_loaded=False" in result.stdout
        assert "tool_executor_loaded=False" in result.stdout

    def test_accessing_workflow_runner_lazily_loads_core_afterwards(self):
        """The flip side: the attribute really does resolve (it isn't just
        permanently missing) — accessing it triggers exactly the deferred
        import, after package init has already completed."""
        result = _run_in_subprocess(
            "import sys\n"
            "import juli_backend.services.agent.runner as runner\n"
            "before = 'juli_backend.services.agent.runner.core' in sys.modules\n"
            "runner.WorkflowRunner\n"
            "after = 'juli_backend.services.agent.runner.core' in sys.modules\n"
            "print(f'before={before} after={after}')\n"
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "before=False after=True" in result.stdout

    def test_unknown_attribute_raises_attribute_error_not_a_silent_none(self):
        result = _run_in_subprocess(
            "import juli_backend.services.agent.runner as runner\nrunner.NotARealExport\n"
        )
        assert result.returncode != 0
        assert "AttributeError" in result.stderr
