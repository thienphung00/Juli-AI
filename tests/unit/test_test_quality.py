"""Test-quality detectors and diff-scoped mutation (#1463, HE-E/P-EVAL-20).

The defect class: a test that is green on day one, never went red, and cannot
notice the thing it was written for. ``check_implementation_tdd_evidence.py``
tests for a *key's presence*, so nothing anywhere fails on a test with no
assertion.

**Every test here plants a lie and asserts it is caught.** A happy-path-only
suite would itself be an instance of the defect class this slice exists to
close, which is why each detector test carries a matching negative — a
well-formed construct that must *not* be flagged. A detector that flags
everything is as useless as one that flags nothing, and only the pair of
assertions distinguishes them.

The two load-bearing discrimination tests:

* ``test_fingerprints_match_ratchet_identity_format`` feeds detector output to
  the *real* ``eval.ratchets`` comparison. It fails if the fingerprint needs any
  transformation to be consumed, which is the whole point of reusing #1462's
  mechanism instead of building a parallel one.
* ``test_mutation_scope_is_diff_bounded_and_whole_repo_fails`` drives real
  ``git`` in a temp repository. It fails if the scope is inferred from anything
  other than the diff, and it plants the bad-base lie explicitly.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from eval import quality_detectors as qd
from eval.ratchets import Identity, MeasurementError, baseline_from, check, measure

REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# helpers — synthetic corpora on disk, scanned by the real detectors
#
# Nothing here monkeypatches a detector. A faked scan would only prove the
# reporting layer, not that the reporting layer is fed a real reading.
# --------------------------------------------------------------------------


def _write(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return path


def _symbols(findings, rule_code: str | None = None) -> set[str]:
    return {f.symbol for f in findings if rule_code is None or f.rule_code.startswith(rule_code)}


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(root),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        },
    )
    return result.stdout


# --------------------------------------------------------------------------
# layer 1 — AST detectors
# --------------------------------------------------------------------------


def test_planted_bad_tests_caught_good_test_untouched(tmp_path: Path) -> None:
    """The planted vacuous tests are flagged; the adjacent honest one is not.

    The negative half is the load-bearing half. ``test_real_behaviour`` sits in
    the same file, uses the same fixtures and the same mock, and differs only in
    that it can actually fail — so a detector that flags it has learned "looks
    like a test" rather than "cannot notice a defect".
    """
    _write(
        tmp_path,
        "tests/test_planted.py",
        '''
        from unittest.mock import Mock


        def test_zero_assertion_smoke():
            """Runs the code and notices nothing."""
            client = Mock()
            client.fetch(shop_id=7)


        def test_trivially_true():
            result = compute(7)
            assert True


        def test_self_comparison():
            result = compute(7)
            assert result == result


        def test_real_behaviour():
            client = Mock()
            client.fetch.return_value = {"total": 3}
            result = summarise(client, shop_id=7)
            assert result["total"] == 3
            client.fetch.assert_called_once_with(shop_id=7)
        ''',
    )

    findings = qd.scan_tree(tmp_path, roots=("tests",))

    assert _symbols(findings, qd.RULE_ZERO_ASSERTION) == {"test_zero_assertion_smoke"}
    assert _symbols(findings, qd.RULE_TRIVIAL_ASSERTION) == {
        "test_trivially_true",
        "test_self_comparison",
    }
    # The lie a permissive detector would tell: that the honest test is fine
    # *because nothing was flagged at all*. Assert the specific negative.
    assert "test_real_behaviour" not in _symbols(findings)


def test_assertion_bearing_helper_is_not_a_zero_assertion_test(tmp_path: Path) -> None:
    """A test whose only assertion is inside a same-file helper is not vacuous.

    This is the false positive that would make the detector unusable on this
    repo: ``_assert_envelope(response)`` is the dominant assertion style in
    ``tests/unit/test_api.py``. The planted lie is the *second* function, which
    calls a same-file helper that asserts nothing and must still be caught.
    """
    _write(
        tmp_path,
        "tests/test_helpers.py",
        """
        def _assert_envelope(response):
            assert response["status"] == "ok"


        def _log_envelope(response):
            print(response["status"])


        def test_delegates_to_asserting_helper():
            _assert_envelope(fetch())


        def test_delegates_to_silent_helper():
            _log_envelope(fetch())
        """,
    )

    findings = qd.scan_tree(tmp_path, roots=("tests",))
    flagged = _symbols(findings, qd.RULE_ZERO_ASSERTION)

    assert flagged == {"test_delegates_to_silent_helper"}


def test_weak_and_mock_return_classes_are_ratchet_not_blocking(tmp_path: Path) -> None:
    """``asserts_mock_return`` and ``weak_assertions_only`` never block.

    Both have legitimate uses and their false-positive rate on this repo is
    unmeasured, so promoting either to blocking is the failure this asserts
    against. The lie planted is the promotion itself: if a future edit adds
    either class to ``BLOCKING_CLASSES``, this fails.
    """
    _write(
        tmp_path,
        "tests/test_weak.py",
        """
        from unittest.mock import Mock


        def test_only_truthiness():
            result = summarise(shop_id=7)
            assert result is not None


        def test_asserts_what_it_injected():
            client = Mock()
            client.fetch.return_value = {"total": 3}
            assert client.fetch() == {"total": 3}


        def test_checks_a_real_value():
            result = summarise(shop_id=7)
            assert result["total"] == 3
        """,
    )

    findings = qd.scan_tree(tmp_path, roots=("tests",))

    assert _symbols(findings, qd.RULE_WEAK_ASSERTIONS_ONLY) == {"test_only_truthiness"}
    assert _symbols(findings, qd.RULE_ASSERTS_MOCK_RETURN) == {"test_asserts_what_it_injected"}
    assert "test_checks_a_real_value" not in _symbols(findings)

    assert qd.RULE_ASSERTS_MOCK_RETURN not in qd.BLOCKING_CLASSES
    assert qd.RULE_WEAK_ASSERTIONS_ONLY not in qd.BLOCKING_CLASSES
    assert qd.RULE_ZERO_ASSERTION in qd.BLOCKING_CLASSES
    assert qd.enforcement(qd.RULE_ASSERTS_MOCK_RETURN) == qd.ENFORCEMENT_RATCHET
    assert qd.enforcement(qd.RULE_ZERO_ASSERTION) == qd.ENFORCEMENT_BLOCKING


def test_mock_only_test_is_flagged_and_a_seam_test_is_not(tmp_path: Path) -> None:
    """A test that exercises only mocks proves routing, not behaviour.

    The negative is the case the class must never eat: a test that *uses* a mock
    as a collaborator but calls a real symbol under test.
    """
    _write(
        tmp_path,
        "tests/test_mocks.py",
        """
        from unittest.mock import MagicMock, Mock

        from juli_backend.services.scoring import score_shop


        def test_wires_two_mocks_together():
            repo = Mock()
            client = MagicMock()
            repo.load(client.fetch())
            repo.load.assert_called_once()


        def test_scores_with_a_mocked_repo():
            repo = Mock()
            repo.load.return_value = [1, 2, 3]
            assert score_shop(repo) == 2
        """,
    )

    findings = qd.scan_tree(tmp_path, roots=("tests",))

    assert _symbols(findings, qd.RULE_MOCK_ONLY) == {"test_wires_two_mocks_together"}
    assert "test_scores_with_a_mocked_repo" not in _symbols(findings, qd.RULE_MOCK_ONLY)


def test_unparseable_test_file_fails_closed(tmp_path: Path) -> None:
    """A file the scanner cannot read is never silently counted as clean."""
    _write(tmp_path, "tests/test_broken.py", "def test_x(:\n")

    with pytest.raises(MeasurementError):
        qd.scan_tree(tmp_path, roots=("tests",))


# --------------------------------------------------------------------------
# ratchet identity format
# --------------------------------------------------------------------------


def test_fingerprints_match_ratchet_identity_format(tmp_path: Path) -> None:
    """Fingerprints are consumed by the real ratchet with no transformation.

    Three planted lies, in order of how badly each would mislead:

    1. A fingerprint that needs reshaping to be parsed — asserted against by
       round-tripping through ``Identity.parse`` on the raw ``key()`` string.
    2. A baseline that passes because it is empty — asserted against by
       requiring the clean tree to actually produce identities.
    3. A newly added zero-assertion test slipping through — asserted against by
       requiring ``check`` to fail with ``new_identity`` on the mutated tree.
    """
    _write(
        tmp_path,
        "tests/test_corpus.py",
        """
        def test_vacuous():
            compute(1)


        def test_sound():
            assert compute(1) == 2
        """,
    )

    findings = qd.scan_tree(tmp_path, roots=("tests",))
    assert findings, "an empty reading would make every later assertion vacuous"

    for finding in findings:
        key = finding.identity().key()
        assert key.count("\t") == 3, f"identity key is not a 4-field record: {key!r}"
        assert Identity.parse(key) == finding.identity()

    # The real mechanism, not a re-implementation of it: `eval.ratchets.measure`
    # is handed this module's measurers and produces a genuine Measurement.
    measurers = qd.ratchet_measurers()
    before = measure(tmp_path, classes=list(measurers), measurers=measurers)
    assert not before.errors, before.errors
    baseline = baseline_from(before)
    assert check(baseline, before).ok

    zero_class = baseline["classes"][qd.debt_class_for(qd.RULE_ZERO_ASSERTION)]
    assert zero_class["occurrences"], "the clean baseline froze an empty set"

    # Plant the regression: one more zero-assertion test.
    _write(
        tmp_path,
        "tests/test_corpus.py",
        """
        def test_vacuous():
            compute(1)


        def test_newly_vacuous():
            compute(2)


        def test_sound():
            assert compute(1) == 2
        """,
    )

    after = measure(tmp_path, classes=list(measurers), measurers=measurers)
    result = check(baseline, after)

    assert not result.ok
    offenders = {v.identity.symbol for v in result.violations if v.identity is not None}
    assert "test_newly_vacuous" in offenders
    assert {v.kind for v in result.violations} == {"new_identity"}


def test_departed_finding_is_a_fix_not_a_failure(tmp_path: Path) -> None:
    """Fixing a vacuous test passes and is recorded as a departure, not debt."""
    _write(tmp_path, "tests/test_corpus.py", "def test_vacuous():\n    compute(1)\n")
    measurers = qd.ratchet_measurers()
    baseline = baseline_from(measure(tmp_path, classes=list(measurers), measurers=measurers))

    _write(tmp_path, "tests/test_corpus.py", "def test_vacuous():\n    assert compute(1) == 2\n")
    result = check(baseline, measure(tmp_path, classes=list(measurers), measurers=measurers))

    assert result.ok
    assert [i.symbol for i in result.departed] == ["test_vacuous"]


# --------------------------------------------------------------------------
# layer 2 — diff-scoped mutation
# --------------------------------------------------------------------------


def _mutation_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    # An empty root commit, so the test can name a base that is a genuine
    # ancestor of HEAD and against which every file in the tree "changed".
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    for name in ("alpha", "beta", "gamma", "delta", "epsilon"):
        _write(root, f"src/{name}.py", f"def {name}(n):\n    return n\n")
    _write(root, "tests/test_all.py", "def test_smoke():\n    assert True\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def test_mutation_scope_is_diff_bounded_and_whole_repo_fails(tmp_path: Path) -> None:
    """Mutation covers exactly the changed source files, and a bad base fails.

    The lie planted second is the expensive one: a diff base that resolves to
    the empty tree returns every file in the repository, which would silently
    turn a per-PR gate into a repo-wide run that exhausts the budget. That is
    not a large job to be throttled — it is a wrong base, and it fails.
    """
    root = _mutation_repo(tmp_path)
    base = _git(root, "rev-parse", "HEAD").strip()

    _git(root, "checkout", "-q", "-b", "feature")
    for name in ("alpha", "beta", "gamma"):
        _write(root, f"src/{name}.py", f"def {name}(n):\n    return n + 1\n")
    _write(root, "tests/test_all.py", "def test_smoke():\n    assert True\n    assert 1 == 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "three files")

    changed = qd.changed_python_sources(root, base=base, head="HEAD")

    assert changed == ("src/alpha.py", "src/beta.py", "src/gamma.py")
    # Test files are not mutated: mutating a test proves nothing about the
    # test's power to detect a defect in the source.
    assert not any(p.startswith("tests/") for p in changed)

    # Lie 2: a base every file "changed" against — the empty root commit, which
    # is what a branch cut from the wrong ref degrades into. It is a real
    # ancestor, the diff is well-formed and git is perfectly happy; only the
    # scope check can tell that the comparison point is meaningless.
    empty_root = _git(root, "rev-list", "--max-parents=0", "HEAD").strip()
    with pytest.raises(qd.BadDiffBaseError) as excinfo:
        qd.changed_python_sources(root, base=empty_root, head="HEAD")
    assert "whole repository" in str(excinfo.value)
    assert "5 source files" in str(excinfo.value)

    # Lie 2b: a base that does not resolve at all is the same defect, reported
    # in the same vocabulary rather than as an infrastructure error.
    with pytest.raises(qd.BadDiffBaseError) as unresolved:
        qd.changed_python_sources(root, base="no-such-ref", head="HEAD")
    assert "diff base" in str(unresolved.value)

    # Lie 3: a hand-supplied changed-file set covering the whole repo, which
    # would bypass the git check entirely.
    with pytest.raises(qd.BadDiffBaseError):
        qd.plan_mutations(root, changed_paths=qd.all_python_sources(root))


def test_mutation_run_reports_killed_and_survived_against_real_pytest(tmp_path: Path) -> None:
    """A real pytest run kills the mutant the test can see and not the one it cannot.

    The planted lie is the surviving mutant: ``threshold`` is never exercised at
    its boundary, so changing the constant cannot be noticed. If every mutant
    were reported killed, the runner is not really running the tests.
    """
    root = tmp_path / "repo"
    _write(
        root,
        "src/classify.py",
        """
        def classify(n):
            if n > 10:
                return "big"
            return "small"
        """,
    )
    # A second, unchanged source file, so the changed set is a genuine subset of
    # the inventory and the run is not leaning on the degenerate single-file case.
    _write(root, "src/untouched.py", "def untouched(n):\n    return n * 2\n")
    _write(
        root,
        "tests/test_classify.py",
        """
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

        from src.classify import classify


        def test_big():
            assert classify(20) == "big"
        """,
    )

    outcome = qd.run_mutations(
        root,
        changed_paths=("src/classify.py",),
        test_paths=("tests/test_classify.py",),
        max_mutants=6,
    )

    assert outcome.total > 0
    assert outcome.killed > 0, "no mutant died — the runner is not running the tests"
    assert outcome.survived > 0, "every mutant died — the runner is not applying them"
    assert 0.0 < outcome.score < 1.0
    assert outcome.killed + outcome.survived + outcome.errored == outcome.total
    assert {m.path for m in outcome.surviving} == {"src/classify.py"}


def test_configured_plugins_actually_register_under_disabled_autoload(tmp_path: Path) -> None:
    """The named plugins must be *module* paths, or every mutant reports ``errored``.

    ``run_mutations`` sets ``PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`` for speed and then
    re-adds what the corpus needs with ``-p``. ``-p pytest_asyncio`` imports a
    package whose ``__init__`` registers no hooks: ``asyncio_mode`` stays an
    unknown ini option, every async fixture errors at setup, and the campaign
    reports 0 killed / 0 survived / N errored — a zero-denominator score of 0.0
    that looks like a result and is not one. Measured on this repository the
    difference was 40/40 errored versus 29 killed / 10 survived.

    The lie planted is a corpus shaped like this repository's — an ``asyncio_mode
    = auto`` ini plus an autouse async fixture in ``conftest.py`` — which the
    synthetic single-file repo in the mutation-run test above never exercises.
    That is why that test stayed green while the runner could not score anything.
    """
    (tmp_path / "pytest.ini").write_text("[pytest]\nasyncio_mode = auto\n", encoding="utf-8")
    _write(
        tmp_path,
        "conftest.py",
        """
        import pytest


        @pytest.fixture(autouse=True)
        async def _autouse_async_fixture():
            yield
        """,
    )
    _write(tmp_path, "tests/test_async.py", "def test_ok():\n    assert True\n")

    env = {
        **os.environ,
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    plugin_args: list[str] = ["-p", "no:cacheprovider"]
    for plugin in qd.MUTATION_PYTEST_PLUGINS:
        plugin_args += ["-p", plugin]

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *plugin_args, "tests/test_async.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )

    # Exit 0 is the only outcome that proves the plugin registered. An errored
    # setup exits 1 with "no plugin or hook that handled it", which the runner
    # would bucket as `errored` for every single mutant.
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Unknown config option: asyncio_mode" not in (result.stdout + result.stderr), (
        "asyncio_mode was not recognised, so the plugin named in "
        "MUTATION_PYTEST_PLUGINS did not actually register its ini options"
    )


def test_mutation_score_min_is_unenforced(tmp_path: Path) -> None:
    """A low score does not fail until a distribution from real diffs exists.

    On a small diff the score swings hard on a handful of mutants, so enforcing
    a floor now would gate on noise. The lie planted is a 0.0 score, which a
    naive floor would reject.
    """
    assert qd.MUTATION_SCORE_MIN is None
    assert qd.mutation_gate_enforced() is False

    outcome = qd.MutationOutcome(
        files=("src/alpha.py",),
        killed=0,
        survived=9,
        errored=0,
        surviving=(),
        mutants_considered=9,
    )
    assert outcome.score == 0.0
    assert qd.mutation_verdict(outcome) == qd.VERDICT_UNENFORCED


# --------------------------------------------------------------------------
# no composite score
# --------------------------------------------------------------------------


def test_no_composite_score_is_emitted(tmp_path: Path) -> None:
    """Every sub-metric stands alone; nothing rolls them into one number.

    A composite is the easiest thing here to game — one dimension can be walked
    up to mask another falling. Two lies are planted: a report doctored to carry
    a composite key (the guard must raise), and a change to one detector that
    must leave every other sub-metric byte-identical.
    """
    _write(
        tmp_path,
        "tests/test_corpus.py",
        """
        def test_vacuous():
            compute(1)


        def test_sound():
            assert compute(1) == 2
        """,
    )

    report = qd.build_report(tmp_path, roots=("tests",))

    assert set(report["detectors"]) == set(qd.RULE_CODES)
    for name, entry in report["detectors"].items():
        assert entry["enforcement"] in (qd.ENFORCEMENT_BLOCKING, qd.ENFORCEMENT_RATCHET)
        assert isinstance(entry["count"], int), name
    qd.assert_no_composite(report)

    # Lie 1: a doctored report carrying a rolled-up number.
    doctored = dict(report)
    doctored["overall_score"] = 0.93
    with pytest.raises(qd.CompositeScoreError):
        qd.assert_no_composite(doctored)

    nested = dict(report)
    nested["detectors"] = dict(report["detectors"])
    nested["detectors"]["composite"] = {"count": 1}
    with pytest.raises(qd.CompositeScoreError):
        qd.assert_no_composite(nested)

    # Lie 2: moving one dimension must not move any other. Add weak-assertion
    # debt and assert the zero-assertion sub-metric is untouched.
    _write(
        tmp_path,
        "tests/test_more.py",
        "def test_weak():\n    result = compute(1)\n    assert result\n",
    )
    after = qd.build_report(tmp_path, roots=("tests",))

    assert after["detectors"][qd.RULE_WEAK_ASSERTIONS_ONLY]["count"] == 1
    for rule in qd.RULE_CODES:
        if rule == qd.RULE_WEAK_ASSERTIONS_ONLY:
            continue
        assert after["detectors"][rule] == report["detectors"][rule], rule


def test_reconciliation_reproduces_from_the_tree_it_describes() -> None:
    """The recorded reading is re-derived here, not taken on trust.

    The lie this exists to catch is the one the reconciliation itself would be
    most likely to tell: a number typed into a constant beside a confident note.
    A self-consistent dict proves nothing, so this re-runs the real scan and
    requires the committed figure to match it exactly. If a later change adds or
    fixes a zero-assertion test, this fails and the constant is updated in the
    same commit — which is the point, because that is a change in the thing
    being measured.
    """
    reconciliation = qd.RECONCILIATION

    assert reconciliation["reported"] == qd.REPORTED_ZERO_ASSERTION_TESTS
    assert reconciliation["reportedCorpus"] == qd.REPORTED_TEST_FUNCTIONS
    assert reconciliation["delta"] == reconciliation["measured"] - reconciliation["reported"]

    scan = qd.scan_corpus(REPO_ROOT, roots=qd.TEST_ROOTS)
    counts = qd.counts_by_rule(scan.findings)

    assert counts[qd.RULE_ZERO_ASSERTION] == reconciliation["measured"], (
        "the committed reconciliation no longer reproduces from this tree; "
        "re-run `python -m eval.quality_detectors scan` and update it"
    )
    # The corpus total is the reconciliation's *denominator*, not its claim. It
    # moves whenever any slice anywhere lands a test -- three concurrent peers did
    # so while this branch was open (4389 -> 4390 -> 4401 -> 4406), and CI tests the
    # merge result, so an exact pin here turns an unrelated peer's merge into a red
    # build without ever having caught a wrong number. The committed figure is still
    # held to a tolerance, so a grossly wrong denominator (a typo, or a reading taken
    # over the wrong roots) still fails; what is no longer asserted is that no one
    # else added a test.
    assert (
        abs(scan.test_functions - reconciliation["measuredCorpus"]) <= 0.02 * scan.test_functions
    ), (
        f"recorded corpus {reconciliation['measuredCorpus']} is more than 2% from the "
        f"live reading {scan.test_functions}; re-run "
        "`python -m eval.quality_detectors scan` and update the reconciliation"
    )

    # Fail-closed matters most on the real corpus: an exception swallowed into
    # "0 findings" would report the repository as clean, which is exactly the
    # lie this slice exists to stop. Every class must be present, even at zero.
    assert set(counts) == set(qd.RULE_CODES)
    for finding in scan.findings:
        assert Identity.parse(finding.identity().key()) == finding.identity()

    # The decomposition must actually decompose: each layer subtracts one kind
    # of evidence, so the counts are monotonically non-increasing and end on the
    # headline. A layer table that does not narrow is a post-hoc story.
    layers = list(reconciliation["layers"].values())
    assert layers == sorted(layers, reverse=True)
    assert layers[-1] == reconciliation["measured"]
    assert reconciliation["priorFigureLayer"] in reconciliation["layers"]

    # And the reconciliation's actual claim: at the layer the prior measurement
    # was taken, the two readings agree once corpus growth is accounted for.
    prior_layer = reconciliation["layers"][reconciliation["priorFigureLayer"]]
    # Scaled from the *live* corpus, not the committed one, so the claim is
    # re-tested against the tree as it actually is on every run.
    scaled = qd.REPORTED_ZERO_ASSERTION_TESTS * (
        scan.test_functions / reconciliation["reportedCorpus"]
    )
    assert abs(prior_layer - scaled) < 5, (
        "the prior ~97 figure no longer reconciles at the layer it was taken; "
        "neither number may be assumed correct until it does"
    )

    # #1535: the three assertions below are the ones whose absence let this
    # constant ship wrong. Before them the test checked only that the layers
    # narrowed and that the LAST one matched -- so five of the six were
    # unfalsifiable, and every figure in the prose note had no oracle at all.
    # Two of the three figures recorded with the layers in #1503 were already
    # wrong on the day they were written (the tree measured 4429 functions and
    # 443 modules against a recorded 4406 and 441) and survived because only the
    # figure a test checks was ever right.

    # AC1 (#1535): the final layer must be the headline as a SET, not merely as a
    # count. Two equal counts over different tests would be a coincidence dressed
    # as an explanation, and a count-only check cannot tell the two apart.
    identities = qd.reconciliation_identities(REPO_ROOT, roots=qd.TEST_ROOTS)
    zero_assertion_ids = {
        (f.path, f.symbol) for f in scan.findings if f.rule_code == qd.RULE_ZERO_ASSERTION
    }
    assert identities[qd.RECONCILIATION_LAYER_ORDER[-1]] == zero_assertion_ids, (
        "the last layer and the detector's own zero_assertion findings agree on "
        "count but not on which tests they are"
    )


def test_reconciliation_layers_are_derived_and_every_one_matches_the_committed_value() -> None:
    """AC2 (#1535). Every layer is recomputed, not just the last one.

    Before this existed the guard checked only that the layers narrowed and that
    the final one equalled the headline, so five of the six were unfalsifiable:
    any set of counts consistent with monotonicity would pass. A committed layer
    can never legitimately differ from the computed one -- the decomposition is
    arithmetic over the corpus, not a judgement -- so it is derived here and
    required to agree exactly.
    """
    derived = qd.reconciliation_layers(REPO_ROOT, roots=qd.TEST_ROOTS)

    assert derived == qd.RECONCILIATION_LAYERS, (
        "the committed layer decomposition no longer reproduces from this tree; "
        f"derived {derived}, committed {qd.RECONCILIATION_LAYERS} -- re-run "
        "`python -m eval.quality_detectors scan` and update both together"
    )
    assert list(derived) == list(qd.RECONCILIATION_LAYER_ORDER)
    counts = list(derived.values())
    assert counts == sorted(counts, reverse=True)


def test_reconciliation_note_states_no_stale_corpus_layer_or_ratio_figure() -> None:
    """AC3 (#1535). Every figure the prose states must be the current one.

    The note is prose, so nothing read it, so this branch's first commit shipped
    three stale numbers inside it: a scaled ratio still computed from the
    superseded corpus, a rate belonging to the previous layer values, and a gap
    quoted between two pre-fix figures. Review caught them by hand. A module
    whose subject is numbers that do not reproduce must not itself state numbers
    that do not reproduce.
    """
    reconciliation = qd.RECONCILIATION
    note = reconciliation["note"]
    layers_by_name = reconciliation["layers"]
    prior_layer = layers_by_name[reconciliation["priorFigureLayer"]]

    then_rate = 100 * qd.REPORTED_ZERO_ASSERTION_TESTS / qd.REPORTED_TEST_FUNCTIONS
    now_rate = 100 * prior_layer / qd.MEASURED_TEST_FUNCTIONS
    scaled_to_corpus = int(
        qd.REPORTED_ZERO_ASSERTION_TESTS * qd.MEASURED_TEST_FUNCTIONS / qd.REPORTED_TEST_FUNCTIONS
    )
    helper_credited = (
        layers_by_name["and_no_unittest_self_assert"]
        - layers_by_name["and_no_same_file_asserting_helper"]
    )
    raise_credited = (
        layers_by_name["and_no_same_file_asserting_helper"]
        - layers_by_name["and_no_raise_assertionerror"]
    )

    for figure in (
        f"Measured here: {qd.MEASURED_ZERO_ASSERTION_TESTS} zero-assertion tests",
        f"corpus of {qd.MEASURED_TEST_FUNCTIONS:,} test functions",
        f"({qd.MEASURED_TEST_MODULES} test modules)",
        f"layer reads {prior_layer} today",
        f"{qd.REPORTED_ZERO_ASSERTION_TESTS} * {qd.MEASURED_TEST_FUNCTIONS}/"
        f"{qd.REPORTED_TEST_FUNCTIONS} = {scaled_to_corpus}",
        f"({then_rate:.2f}% then, {now_rate:.2f}% now)",
        f"gap between {prior_layer} and {qd.MEASURED_ZERO_ASSERTION_TESTS} "
        f"is {helper_credited} tests",
        f"plus {raise_credited} that raise AssertionError",
    ):
        assert figure in note, (
            f"the reconciliation note no longer states {figure!r}; a figure in the "
            "prose has gone stale against the constants beside it"
        )

    # The module count is a denominator like the corpus, so it gets the same
    # tolerance rather than an exact pin -- an unrelated peer adding a test file
    # must not turn this red.
    scan = qd.scan_corpus(REPO_ROOT, roots=qd.TEST_ROOTS)
    assert abs(scan.files - qd.MEASURED_TEST_MODULES) <= 0.02 * scan.files, (
        f"recorded module count {qd.MEASURED_TEST_MODULES} is more than 2% from "
        f"the live reading {scan.files}"
    )


def test_this_slice_adds_no_debt_to_the_thing_it_measures() -> None:
    """The detector's own tests must not be instances of what it detects.

    The self-referential failure: a slice about vacuous tests shipping vacuous
    tests. There is no honest way to ratchet a class your own change adds to.
    """
    findings = qd.scan_file(REPO_ROOT, Path(__file__))

    assert findings == (), [f.identity().key() for f in findings]
