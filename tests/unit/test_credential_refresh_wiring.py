"""Wiring tests for #1232 (AGT-W4A-WIRE, ADR-081 decisions 1/6/9):

- the beat schedule entry (celery_app.py's beat_schedule)
- the credentials task_routes entry + the systemd -Q flag, in the same commit
- the static assertion that refresh_merchant_tokens has zero call sites
  outside core/security/tiktok_oauth.py and this slice's beat/lazy code
  (ADR-081 decision 4: "the three direct call sites stop using them and go
  through the resolver instead")

Cycle-logic tests (scan window, isolation, summary counts) live in
test_credential_refresh_beat.py, not here.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend/src/juli_backend"
WORKER_UNIT = REPO_ROOT / "infra/systemd/juli-celery-worker.service"

#: Files allowed to actually CALL `.refresh_merchant_tokens(...)`. Only the
#: thin-wrapper's own definition today -- ADR-081 decision 4 deletes every
#: direct call site this slice owns (orchestrate.py x2,
#: targeted_fetch_executor.py) in favour of resolve_production_read_credential
#: / refresh_credential, so neither the beat nor the lazy layer actually
#: calls refresh_merchant_tokens either. Named as a relative-path allowlist,
#: matching check_import_boundaries.py's style (importer_file as a
#: repo-relative posix path).
_ALLOWED_REFRESH_MERCHANT_TOKENS_CALLERS = frozenset(
    {
        "backend/src/juli_backend/core/security/tiktok_oauth.py",
        "backend/src/juli_backend/workers/tasks/credential_refresh_beat.py",
        "backend/src/juli_backend/core/security/credential_resolver.py",
    }
)


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def _refresh_merchant_tokens_call_sites() -> list[str]:
    """Repo-relative paths of every file containing an AST `Call` node whose
    callee attribute is `refresh_merchant_tokens` -- e.g. `x.refresh_merchant_tokens(...)`
    for any `x`. AST-based (not textual grep) so a docstring or comment that
    merely *mentions* the name -- both orchestrate.py's and
    targeted_fetch_executor.py's module comments do, explaining the deletion
    -- never produces a false positive, mirroring
    agent-runtime/scripts/ci/check_import_boundaries.py's AST-walk style.
    """
    hits: list[str] = []
    for py_file in _iter_python_files(BACKEND_SRC):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "refresh_merchant_tokens"
            ):
                hits.append(py_file.resolve().relative_to(REPO_ROOT).as_posix())
                break
    return hits


def test_refresh_merchant_tokens_has_no_call_sites_outside_the_allowlist():
    call_sites = _refresh_merchant_tokens_call_sites()
    unexpected = sorted(set(call_sites) - _ALLOWED_REFRESH_MERCHANT_TOKENS_CALLERS)
    assert not unexpected, (
        f"refresh_merchant_tokens is called from {unexpected}, outside "
        "core/security/tiktok_oauth.py and this slice's beat/lazy code. ADR-081 "
        "decision 4 requires orchestrate.py / targeted_fetch_executor.py to go "
        "through resolve_production_read_credential instead."
    )


def test_orchestrate_and_targeted_fetch_executor_no_longer_call_refresh_merchant_tokens():
    """Names the two files ADR-081 decision 4 explicitly calls out, so a
    regression here fails with a file name instead of just "somewhere"."""
    call_sites = set(_refresh_merchant_tokens_call_sites())
    assert "backend/src/juli_backend/workers/services/polling/orchestrate.py" not in call_sites
    assert (
        "backend/src/juli_backend/services/cdp_speed/targeted_fetch_executor.py" not in call_sites
    )


def test_tiktok_oauth_service_still_defines_refresh_merchant_tokens():
    """The thin wrapper (ADR-081 decision 4: "refresh_tokens /
    refresh_merchant_tokens remain as thin wrappers so nothing outside this
    slice breaks") must still exist -- this pins that the static check above
    is discriminating "no call sites" from "the method vanished"."""
    source = (BACKEND_SRC / "core/security/tiktok_oauth.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    method_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    }
    assert "refresh_merchant_tokens" in method_names


class TestBeatScheduleEntry:
    def test_credential_refresh_beat_is_scheduled_every_30_minutes(self):
        from celery.schedules import crontab

        from juli_backend.workers.celery_app import celery_app

        entry = celery_app.conf.beat_schedule["credential-refresh-beat"]
        assert entry["task"] == "juli_backend.credential_refresh_beat"
        assert entry["schedule"] == crontab(minute="*/30")


class TestCredentialsQueueRoutingAndSystemdFlag:
    def test_task_routes_carries_the_credentials_entry(self):
        from juli_backend.workers.celery_app import celery_app

        routes = celery_app.conf.task_routes or {}
        assert routes.get("juli_backend.credential_refresh_beat") == {"queue": "credentials"}

    def test_systemd_unit_dash_q_flag_includes_credentials(self):
        text = WORKER_UNIT.read_text(encoding="utf-8")
        joined = re.sub(r"\\\s*\n\s*", " ", text)
        match = re.search(r"^ExecStart=.*$", joined, re.MULTILINE)
        assert match, "no ExecStart= line in the worker unit"
        q = re.search(r"(?:-Q|--queues)[=\s]+([A-Za-z0-9_,\-]+)", match.group(0))
        assert q, "no -Q flag in the worker unit ExecStart"
        consumed = {name.strip() for name in q.group(1).split(",") if name.strip()}
        assert "credentials" in consumed
        # #1205's own regression guard (test_celery_worker_consumes_routed_queues.py)
        # already proves every routed queue is consumed generically; this test only
        # pins that THIS slice's queue specifically made it into that set, in case a
        # future edit to that file's allowlist logic ever masked a gap.
        assert {"celery", "agent_runs", "credentials"} <= consumed
