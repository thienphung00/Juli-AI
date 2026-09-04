"""#1444 (HE-B/P-EVAL-10): a run narrower than CI's cannot be reported as full coverage.

487 of 541 pytest invocations in the corpus are narrower than the ``pytest tests/``
CI actually runs. Narrow runs during the loop are correct and stay allowed — the
defect is a narrow run *reported as* full coverage, which is how #943/#948 shipped
schema drift past a green CI.

Every test here plants a lie and asserts the provider catches it. A happy-path-only
test would be an instance of the defect class this slice exists to close: the
vacuous pass.

**Unit of measurement: the invocation, not the command.** 76 corpus commands chain
2-5 pytest runs, and a chain whose first run is broad and second narrow cannot
honestly be scored as one selector — the broad head would launder the narrow tail.
``test_subsuming_selector_is_not_flagged`` plants exactly that lie.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"


def _load_seam():
    """Import the capture seam, which lives outside any importable package root.

    Done inside a function deliberately: hoisting the ``sys.path`` insert above
    module-level imports needs two ``# noqa: E402`` suppressions, and the repo's
    debt ratchet counts suppression identities. Paying two units of tracked debt
    for import cosmetics is a bad trade.
    """
    if str(CI_DIR) not in sys.path:
        sys.path.insert(0, str(CI_DIR))
    import capture_providers
    from capture_providers import command_scope

    return capture_providers, command_scope


_seam, command_scope = _load_seam()

CaptureContext = _seam.CaptureContext
CaptureProviderError = _seam.CaptureProviderError
capture_run_block = _seam.capture_run_block
discover_providers = _seam.discover_providers
provider_sandbox = _seam.provider_sandbox

# A stand-in for .github/workflows/pr.yml carrying the two shapes the real file
# uses: a literal block scalar with backslash continuations, and a folded scalar.
FAKE_WORKFLOW = """\
jobs:
  lint:
    steps:
      - name: Ruff
        run: ruff check backend/src/juli_backend tests scripts
  typecheck:
    steps:
      - name: Mypy
        run: mypy backend/src/juli_backend --ignore-missing-imports
  test:
    steps:
      # A comment naming pytest tests/everything must not be read as a command.
      - name: Pytest with coverage (PR-safe Tests)
        run: |
          python -X faulthandler -m pytest tests/ -v --tb=short \\
            -m "not live and not demo_contract and not migration_heavy and not phase_scaffold" \\
            --cov=juli_backend --cov-fail-under=80
  live:
    steps:
      - name: Live TikTok sandbox pytest
        run: python -m pytest tests/ -v --tb=short -m live
  smoke:
    steps:
      - name: Bounded integration runtime smoke
        run: >-
          timeout 5m python -m pytest
          tests/integration/test_material_deployed_webhook_handoff.py
          -q --tb=short -m "not live and not migration_heavy"
"""

FAKE_PYTEST_INI = "[pytest]\ntestpaths = tests\n"


@pytest.fixture
def planted_ci(tmp_path, monkeypatch):
    """Point the provider at a planted pr.yml + pytest.ini instead of the repo's."""
    workflow = tmp_path / "pr.yml"
    workflow.write_text(FAKE_WORKFLOW, encoding="utf-8")
    ini = tmp_path / "pytest.ini"
    ini.write_text(FAKE_PYTEST_INI, encoding="utf-8")
    monkeypatch.setattr(command_scope, "CI_WORKFLOW_PATH", workflow)
    monkeypatch.setattr(command_scope, "PYTEST_INI_PATH", ini)
    return workflow


def _context(*commands: str, in_validation: tuple[str, ...] = ()) -> CaptureContext:
    """A context whose review/validation bodies cite ``commands``."""
    review = {
        "id": "review-issue-1444",
        "issue": 1444,
        "status": "PASS",
        "redGreenRefactorEvidence": [
            {
                "cycle": 1,
                "commands": [{"command": c, "exitCode": 0} for c in commands],
            }
        ],
    }
    validation = {
        "id": "validation-issue-1444",
        "issue": 1444,
        "status": "PASS",
        "checks": [
            {"name": "tests_pass", "status": "PASS", "details": {"command": c}}
            for c in in_validation
        ],
    }
    return CaptureContext(
        issue=1444,
        review=review,
        validation=validation,
        review_bytes=b"{}",
        validation_bytes=b"{}",
    )


def _by_verdict(block: dict, verdict: str) -> list[dict]:
    return [i for i in block["invocations"] if i["verdict"] == verdict]


# --------------------------------------------------------------------------- #
# AC1
# --------------------------------------------------------------------------- #


def test_narrower_selector_is_flagged(planted_ci):
    """The lie: `pytest tests/unit` reported green, while CI runs `pytest tests/`.

    tests/unit skips tests/integration entirely — the exact gap that let the
    products.revenue (#943) and inventory_items.velocity (#948) schema drift
    reach main behind a green tick.
    """
    block = command_scope.capture(
        _context("PYTHONPATH=$PWD/backend/src python -m pytest tests/unit -q")
    )

    assert block["unit"] == "invocation"
    narrower = _by_verdict(block, "narrower_than_CI")
    assert len(narrower) == 1, block["invocations"]
    entry = narrower[0]

    # Both selectors are named — the record must not merely say "narrow".
    assert entry["citedSelector"] == "tests/unit"
    assert entry["ciSelector"] == "tests"
    assert entry["tool"] == "pytest"
    assert "paths_not_subsuming" in entry["reasons"]

    # And the top-level roll-up carries it, so a reader of the record cannot
    # miss it by not walking `invocations`.
    assert block["narrowerCount"] == 1
    assert block["narrowerThanCI"][0]["citedSelector"] == "tests/unit"

    # The lie is caught, not laundered: this must never read as full coverage.
    assert _by_verdict(block, "subsumes_CI") == []


def test_narrowing_is_found_in_the_validation_body_too(planted_ci):
    """A command cited only under validation.checks[].details must still be scored."""
    block = command_scope.capture(_context(in_validation=("python -m pytest tests/unit -q",)))

    assert block["invocationsScored"] == 1
    assert _by_verdict(block, "narrower_than_CI")[0]["citedSelector"] == "tests/unit"


# --------------------------------------------------------------------------- #
# AC2
# --------------------------------------------------------------------------- #


def test_subsuming_selector_is_not_flagged(planted_ci):
    """A genuine CI-equivalent run is clean — and a broad head cannot launder a narrow tail.

    The planted lie is the chained command: `pytest tests/ && pytest tests/unit/test_x.py`.
    Scored per *command* its first run reaches CI scope and the whole thing passes.
    Scored per *invocation* — the unit this provider declares — the narrow tail is
    still reported. 76 commands in the corpus have this shape.
    """
    ci_equivalent = (
        "python -X faulthandler -m pytest tests/ -v --tb=short "
        '-m "not live and not demo_contract and not migration_heavy and not phase_scaffold"'
    )

    clean = command_scope.capture(_context(ci_equivalent))
    assert clean["narrowerCount"] == 0
    assert len(_by_verdict(clean, "subsumes_CI")) == 1
    assert clean["narrowerThanCI"] == []

    chained = command_scope.capture(
        _context(f"{ci_equivalent} && python -m pytest tests/unit/test_x.py -q")
    )
    assert chained["commandsCited"] == 1
    assert chained["invocationsScored"] == 2, "the chain must not be scored as one selector"
    assert chained["narrowerCount"] == 1
    assert _by_verdict(chained, "subsumes_CI")[0]["citedSelector"] == "tests"
    tail = _by_verdict(chained, "narrower_than_CI")[0]
    assert tail["citedSelector"] == "tests/unit/test_x.py"
    assert tail["ciSelector"] == "tests"


def test_ruff_and_mypy_scope_is_compared_against_their_own_ci_lanes(planted_ci):
    """The lie: `ruff check backend` presented as the lint gate CI runs.

    CI lints backend/src/juli_backend *plus* tests and scripts. A cited run over
    backend alone leaves both other trees unlinted.
    """
    block = command_scope.capture(
        _context(
            "ruff check backend",
            "ruff check backend/src/juli_backend tests scripts",
            "mypy backend/src/juli_backend --ignore-missing-imports",
        )
    )

    verdicts = {i["citedSelector"]: i["verdict"] for i in block["invocations"]}
    assert verdicts["backend"] == "narrower_than_CI"
    assert verdicts["backend/src/juli_backend tests scripts"] == "subsumes_CI"
    assert verdicts["backend/src/juli_backend"] == "subsumes_CI"


def test_command_with_no_ci_counterpart_is_recorded_not_silently_dropped(planted_ci):
    """The lie: `ruff format --check` counted as satisfying `ruff check`.

    They are different subcommands. Neither may be silently discarded, or the
    record's counts stop reconciling with what was actually run.
    """
    block = command_scope.capture(_context("ruff format --check backend"))

    no_ref = _by_verdict(block, "no_ci_reference")
    assert len(no_ref) == 1
    assert no_ref[0]["tool"] == "ruff format"
    assert block["narrowerCount"] == 0
    assert _by_verdict(block, "subsumes_CI") == []


# --------------------------------------------------------------------------- #
# AC3
# --------------------------------------------------------------------------- #


def test_marker_deselection_is_recorded(planted_ci):
    """The lie: an extra `-m "not slow"` over identical paths, presented as equivalent.

    Paths match CI exactly, so a path-only comparison passes it. The extra
    deselection is real narrowing and must be named, not silently folded in.
    """
    block = command_scope.capture(
        _context(
            "python -m pytest tests/ -v "
            '-m "not live and not demo_contract and not migration_heavy '
            'and not phase_scaffold and not slow"'
        )
    )

    entry = _by_verdict(block, "narrower_than_CI")[0]
    assert entry["citedSelector"] == "tests"
    assert entry["ciSelector"] == "tests"
    assert "paths_not_subsuming" not in entry["reasons"]
    assert "extra_deselected_markers" in entry["reasons"]
    assert entry["extraDeselectedMarkers"] == ["slow"]
    assert entry["citedDeselectedMarkers"] == [
        "demo_contract",
        "live",
        "migration_heavy",
        "phase_scaffold",
        "slow",
    ]
    assert entry["ciDeselectedMarkers"] == [
        "demo_contract",
        "live",
        "migration_heavy",
        "phase_scaffold",
    ]


def test_deselection_matching_ci_exactly_is_recorded_but_not_flagged(planted_ci):
    """CI's own deselect expression is not narrowing — but it is still recorded."""
    block = command_scope.capture(
        _context(
            "python -m pytest tests/ "
            '-m "not live and not demo_contract and not migration_heavy and not phase_scaffold"'
        )
    )

    entry = _by_verdict(block, "subsumes_CI")[0]
    assert entry["citedDeselectedMarkers"] == [
        "demo_contract",
        "live",
        "migration_heavy",
        "phase_scaffold",
    ]
    assert entry["extraDeselectedMarkers"] == []


def test_positive_marker_and_keyword_filters_narrow(planted_ci):
    """The lie: `-m live` / `-k contract` over `tests/` passed off as the full suite.

    Paths are identical to CI's; the selection is a fraction of it.
    """
    block = command_scope.capture(
        _context("python -m pytest tests/ -m live", 'python -m pytest tests/ -k "contract"')
    )

    reasons = [set(i["reasons"]) for i in block["invocations"]]
    assert {"positive_marker_selection"} <= reasons[0]
    assert block["invocations"][0]["selectedMarkers"] == ["live"]
    assert {"keyword_filter"} <= reasons[1]
    assert block["narrowerCount"] == 2


# --------------------------------------------------------------------------- #
# AC4 — fail closed
# --------------------------------------------------------------------------- #


def test_unparseable_command_fails_closed(planted_ci):
    """The lie: garbage that would otherwise be skipped, leaving a vacuous 0 narrowings.

    A silently-dropped command is indistinguishable from a command that scored
    clean, which is precisely the "absence of evidence read as evidence of
    absence" failure the run{} envelope exists to close.
    """
    with pytest.raises(command_scope.UnparseableCommandError) as excinfo:
        command_scope.capture(_context('python -m pytest tests/ -k "unbalanced'))
    assert "unbalanced" in str(excinfo.value)

    # A non-string / empty citation is equally unparseable, never a quiet skip.
    for bad in ("", "   "):
        with pytest.raises(command_scope.UnparseableCommandError):
            command_scope.capture(_context(bad))

    bad_type = _context()
    bad_type.review["redGreenRefactorEvidence"][0]["commands"] = [{"command": 17, "exitCode": 0}]
    with pytest.raises(command_scope.UnparseableCommandError):
        command_scope.capture(bad_type)


def test_unparseable_command_aborts_the_whole_record(planted_ci):
    """Through the real registry the failure surfaces named, and no record is written."""
    with provider_sandbox():
        discover_providers()
        assert command_scope.PROVIDER_NAME == "commandScope"
        with pytest.raises(CaptureProviderError) as excinfo:
            capture_run_block(_context('pytest tests/ -k "oops'))
    assert excinfo.value.provider == "commandScope"


def test_missing_ci_workflow_fails_closed(tmp_path, monkeypatch):
    """No pr.yml means CI's selectors are unknown — that is a failure, not "no narrowing"."""
    monkeypatch.setattr(command_scope, "CI_WORKFLOW_PATH", tmp_path / "absent.yml")
    monkeypatch.setattr(command_scope, "PYTEST_INI_PATH", tmp_path / "absent.ini")
    with pytest.raises(command_scope.UnparseableCommandError):
        command_scope.capture(_context("pytest tests/"))


def test_ci_workflow_with_no_recognised_lane_fails_closed(tmp_path, monkeypatch):
    """A pr.yml the parser understands nothing in must not yield an empty reference set."""
    workflow = tmp_path / "pr.yml"
    workflow.write_text("jobs:\n  noop:\n    steps:\n      - run: echo hi\n", encoding="utf-8")
    monkeypatch.setattr(command_scope, "CI_WORKFLOW_PATH", workflow)
    monkeypatch.setattr(command_scope, "PYTEST_INI_PATH", tmp_path / "absent.ini")
    with pytest.raises(command_scope.UnparseableCommandError):
        command_scope.capture(_context("pytest tests/"))


# --------------------------------------------------------------------------- #
# The reference must come from the real workflow, not a hardcoded guess
# --------------------------------------------------------------------------- #


def test_ci_selectors_are_read_from_the_real_pr_yml():
    """The lie a hardcoded constant would tell: CI's scope frozen at authoring time.

    Read the workflow that actually runs. If someone narrows the PR-safe lane,
    this reference moves with it.
    """
    selectors = command_scope.ci_selectors()

    assert selectors["pytest"].paths == ("tests",)
    assert selectors["pytest"].deselected_markers == frozenset(
        {"live", "demo_contract", "migration_heavy", "phase_scaffold"}
    )
    # Widened by #1528: agent-runtime/scripts joined the lint perimeter. This
    # pin moves with pr.yml by design — it is the reference CI's scope is read
    # from, so it must track a widening as faithfully as a narrowing.
    assert selectors["ruff check"].paths == (
        "backend/src/juli_backend",
        "tests",
        "scripts",
        "agent-runtime/scripts",
    )
    assert selectors["mypy"].paths == ("backend/src/juli_backend",)

    # Provably sourced: the raw text is a substring of the committed workflow.
    workflow_text = command_scope.CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "not phase_scaffold" in workflow_text


def test_provider_conforms_to_the_capture_seam():
    """PROVIDER_NAME + capture(context), discovered without editing the writer."""
    with provider_sandbox():
        assert "commandScope" in discover_providers()
