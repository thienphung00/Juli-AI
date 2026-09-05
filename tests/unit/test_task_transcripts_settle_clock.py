"""#1582: ``settle_clock`` must not ``NameError`` on a never-reset fresh import,
and a scan that raises must not be reported the same way as a scan that
completed and genuinely found nothing (ADR-093 discipline).

``task_transcripts._settle_clock`` was declared ``global`` and read inside
``settle_clock()`` but carried no module-level definition at all. Every test
elsewhere in this repo resets the clock in an autouse fixture before touching
it, and that reset call is what creates the module attribute — which is
exactly why the bug was invisible to this repo's own suite. The first unpinned
read in a process that never calls ``reset_settle_clock()`` first — the exact
shape of ``generate_status_records.py`` in CI, which imports this module fresh
and reads the clock once per run — raised ``NameError`` every single time.

Once that scan crashes, the second question is what the caller reports. The
one production consumer, ``capture_providers.run_metrics``, already caught the
raise and named it in ``gaps[]`` — but the top-level per-field *reading* still
cited the generic "no transcript was found" text, collapsing "this could not
be checked" into "the answer is empty". Those are different states and must
not share a reason.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
TASK_TRANSCRIPTS_PATH = CI_DIR / "task_transcripts.py"

_MODULE_SLOT = itertools.count()


def _fresh_task_transcripts_module() -> Any:
    """Load a brand-new ``task_transcripts`` module instance.

    A distinct module name per call, never registered under the shared
    ``task_transcripts`` alias: this must be a module nothing else in the test
    session has touched, so a *different* test's autouse
    ``reset_settle_clock()`` call on the shared import cannot leak an
    assignment into this one. That leak is exactly why every other test in
    this repo never sees the defect.
    """
    name = f"_juli_fresh_task_transcripts_{next(_MODULE_SLOT)}"
    spec = importlib.util.spec_from_file_location(name, TASK_TRANSCRIPTS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_settle_clock_does_not_raise_on_a_never_reset_fresh_import() -> None:
    """The ordering every other test in the repo never exercises.

    Every existing caller resets the clock in an autouse fixture before
    touching it. A freshly loaded module that has never called
    ``reset_settle_clock()`` is the only way to see the accessor's real,
    un-primed state — the same state ``generate_status_records.py`` starts
    from on every real CI run.
    """
    fresh = _fresh_task_transcripts_module()
    value = fresh.settle_clock()
    assert isinstance(value, float)
    # Latches, per the accessor's own contract: a second unpinned read agrees.
    assert fresh.settle_clock() == value


def test_settle_clock_still_accepts_an_explicit_now_before_ever_latching() -> None:
    """A caller-supplied instant must work even before the module has latched.

    Guards against a fix that only patches the ``None`` branch and leaves the
    early-return for an explicit ``now`` untouched by accident.
    """
    fresh = _fresh_task_transcripts_module()
    assert fresh.settle_clock(now=1.0) == 1.0


# ---------------------------------------------------------------------------
# run_metrics: a scan that raises must not read as a clean empty answer
# ---------------------------------------------------------------------------


def _load_run_metrics_seam():
    if str(CI_DIR) not in sys.path:
        sys.path.insert(0, str(CI_DIR))
    import capture_providers
    import task_transcripts
    from capture_providers import run_metrics

    return capture_providers, run_metrics, task_transcripts


_seam, run_metrics, task_transcripts = _load_run_metrics_seam()
CaptureContext = _seam.CaptureContext

ISSUE = 1582


@pytest.fixture(autouse=True)
def _unlatch_settle_clock():
    """Keep the shared ``task_transcripts`` import's clock unlatched around
    each test in this section, matching the house pattern in
    ``test_run_metrics_provider.py``.
    """
    task_transcripts.reset_settle_clock()
    yield
    task_transcripts.reset_settle_clock()


def _context() -> Any:
    review = {"issueId": ISSUE, "status": "PASS"}
    return CaptureContext(
        issue=ISSUE,
        review=review,
        validation={"issueId": ISSUE, "status": "PASS"},
        review_bytes=json.dumps(review).encode(),
        validation_bytes=b"{}",
    )


def test_a_raising_scanner_is_reported_unavailable_never_as_a_clean_empty_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash mid-scan must not read the same as "genuinely nothing found".

    ``read_task_dir`` raising (the settle-clock bug did exactly this,
    unconditionally, in production) is already caught by ``run_metrics`` and
    named in ``gaps[]`` — but the per-field reading must say so too, not fall
    back to the text reserved for a scan that completed and found nothing.
    """
    repo_root = tmp_path / "checkout" / "Juli-AI-v2"
    repo_root.mkdir(parents=True)
    base = tmp_path / "tempbase"
    slug = task_transcripts.project_slug(repo_root)
    tasks = base / "claude-501" / slug / "session-under-test" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "agent-one.output").write_text('{"type": "user"}\n', encoding="utf-8")

    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise NameError("name '_settle_clock' is not defined")

    monkeypatch.setattr(task_transcripts, "read_task_dir", _raise)

    block = run_metrics.capture(
        _context(), repo_root=repo_root, temp_bases=(str(base),), environ={}, claims=None
    )

    assert block["status"] == "not-measured"
    for field in ("tokenUsage", "toolInvocationCount", "executionDurationMs"):
        measurement = block[field]
        assert measurement["available"] is False, field
        assert "value" not in measurement, field
        # The load-bearing distinction: the reason must name the crash, not
        # restate the generic "nothing was found" text reserved for a scan
        # that completed and genuinely found nothing (ADR-093).
        assert measurement["reason"] != run_metrics.NO_TRANSCRIPT_REASON, field
        assert "raised" in measurement["reason"], field

    assert any(gap["reason"] == "task-dir-unreadable" for gap in block["gaps"])
    assert any("NameError" in gap.get("detail", "") for gap in block["gaps"])
    # The generic "not found" gap must not also fire beside the real one — that
    # would be the exact collapse this fix removes, just moved into gaps[].
    assert not any(
        gap["reason"] in ("no-transcript-for-issue", "no-persisted-task-transcripts")
        for gap in block["gaps"]
    )


def test_a_genuinely_empty_scan_still_reads_as_not_found_not_a_scan_error(
    tmp_path: Path,
) -> None:
    """The negative case for the metrics side: no crash happened here.

    Guards against a fix broad enough to report every "nothing measured" case
    as a scan error — the CI-common case (no session temp dir at all) must
    keep citing :data:`run_metrics.NO_TRANSCRIPT_REASON`, unmodified.
    """
    repo_root = tmp_path / "checkout" / "Juli-AI-v2"
    repo_root.mkdir(parents=True)
    empty_base = tmp_path / "no-such-temp-base"

    block = run_metrics.capture(
        _context(), repo_root=repo_root, temp_bases=(str(empty_base),), environ={}, claims=None
    )

    assert block["status"] == "not-measured"
    assert block["tokenUsage"]["reason"] == run_metrics.NO_TRANSCRIPT_REASON


# ---------------------------------------------------------------------------
# claim_vs_executed: the negative case — a genuinely fabricated citation must
# still fail. This fix must not blunt that signal.
# ---------------------------------------------------------------------------


def _load_claim_vs_executed():
    if str(CI_DIR) not in sys.path:
        sys.path.insert(0, str(CI_DIR))
    from capture_providers import claim_vs_executed

    return claim_vs_executed


claim_vs_executed = _load_claim_vs_executed()


def _cv_context() -> Any:
    review = {"issue": ISSUE, "status": "PASS"}
    validation = {"issue": ISSUE, "status": "PASS", "readyForMerge": True}
    return _seam.CaptureContext(
        issue=ISSUE,
        review=review,
        validation=validation,
        review_bytes=json.dumps(review).encode("utf-8"),
        validation_bytes=json.dumps(validation).encode("utf-8"),
    )


def test_a_genuinely_fabricated_citation_still_fails(tmp_path: Path) -> None:
    """The fix must not blunt the real signal — this must still be FAIL.

    The transcript shows one command actually invoked; the artifact cites a
    different one it never ran. Distinguishing "could not check" from "did not
    match" must never widen what counts as unverifiable.
    """
    transcripts = tmp_path / "projects" / "-repo"
    transcripts.mkdir(parents=True)
    (transcripts / "session.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "toolu_0",
                                    "name": "Bash",
                                    "input": {"command": "ruff check backend"},
                                }
                            ],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    artifact = {
        "issueId": ISSUE,
        "redGreenRefactorEvidence": [
            {
                "cycle": 1,
                "commands": [
                    {
                        "command": (
                            "PYTHONPATH=$PWD/backend/src python -m pytest "
                            "tests/unit/test_fabricated.py -q"
                        ),
                        "exitCode": 0,
                    }
                ],
            }
        ],
    }

    block = claim_vs_executed.capture(
        _cv_context(),
        implementation_artifact=artifact,
        transcript_dirs=[transcripts],
    )

    assert block["status"] == "FAIL", block
    assert block["recordPasses"] is False
    assert block["matchedCommandCount"] == 0
    assert block["unmatchedCommandCount"] == 1
