"""`reconcile` moves every recorded figure together, or refuses (#1731).

The corpus constants and the prose note beside them are checked against each
other by test_test_quality.py, so a merge resolution here is eight coordinated
edits. Doing them by hand four times in one working day is what prompted this;
doing them *wrong* is worse than tedious, because both sides of the merge edit
the same paragraph and a textual splice of two such edits is how PR #1616
acquired an F401 that no conflict marker announced.
"""

from __future__ import annotations

import pathlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: A full corpus scan over ~4,800 test functions takes most of pytest's default
#: 30s timeout on its own, and tips over it when another scanning suite runs in
#: the same session. The work is genuinely that expensive; the default is what
#: is wrong for these three, not the scan. test_ratchets.py carries the same
#: standing flake risk for the same reason.
pytestmark = pytest.mark.timeout(180)


def _qd():
    sys.path.insert(0, str(REPO_ROOT))
    import eval.quality_detectors as qd

    return qd


@pytest.fixture(scope="module")
def reconciled():
    """One corpus scan for the whole module.

    `reconcile_source` scans every test root, which at ~4,800 functions costs
    most of pytest's 30s per-test timeout on its own. Three tests each paying
    that is three timeouts, so the work is done once and shared -- the same
    reason the scan is a standing flake risk in test_ratchets.py.
    """
    qd = _qd()
    source = pathlib.Path(qd.__file__).read_text(encoding="utf-8")
    rewritten, figures = qd.reconcile_source(REPO_ROOT, source)
    return qd, source, rewritten, figures


def test_reconcile_reports_the_live_figures_without_writing(reconciled) -> None:
    """A dry run must not touch the file it describes."""
    qd, source, _rewritten, figures = reconciled
    assert Path(qd.__file__).read_text(encoding="utf-8") == source, "dry run wrote to the module"
    assert figures["testFunctions"] > 0 and figures["testModules"] > 0
    assert figures["zeroAssertion"] == qd.MEASURED_ZERO_ASSERTION_TESTS


def test_the_rewritten_source_carries_every_figure_and_the_prose_agrees(reconciled) -> None:
    """Constants and prose move together, which is the whole point."""
    _qd_mod, _source, rewritten, figures = reconciled

    n, m = figures["testFunctions"], figures["testModules"]
    assert f"MEASURED_TEST_FUNCTIONS = {n}" in rewritten
    assert f"MEASURED_TEST_MODULES = {m}" in rewritten
    assert f"corpus of {n:,} test functions" in rewritten
    assert f"({m} test modules)" in rewritten
    assert f"({figures['thenRate']:.2f}% then, {figures['nowRate']:.2f}% now)" in rewritten


def test_it_refuses_rather_than_guessing_when_a_figure_is_not_where_it_expects(reconciled) -> None:
    """ADR-092 exhibit: a source it cannot re-derive confidently must fail.

    Silently skipping an edit it could not place would produce exactly the
    half-updated file the note test exists to catch -- constants moved, prose
    stale -- and would do it under a command whose name promises the opposite.
    """
    qd, source, _rewritten, _figures = reconciled
    # a hand-mangled source: the constant renamed, so its anchor is gone
    mangled = source.replace(
        f"MEASURED_TEST_FUNCTIONS = {qd.MEASURED_TEST_FUNCTIONS}",
        "MEASURED_TEST_FUNCTIONS = 1  # hand-edited",
    )

    with pytest.raises(qd.MeasurementError, match="Refusing to guess"):
        qd.reconcile_source(REPO_ROOT, mangled)
