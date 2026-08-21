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
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith("juli_backend.services.agent.runner"):
                        offending.append(f"{path}: from {node.module} import ...")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("juli_backend.services.agent.runner"):
                            offending.append(f"{path}: import {alias.name}")

        assert not offending, (
            "services/agent/events/ must not import from services/agent/runner/ "
            f"(the events contract must not depend on the runner implementation): {offending}"
        )
