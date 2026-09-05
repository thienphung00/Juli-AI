"""Tests for the evidence assembler (#1458, HE-B/P-EVAL-8).

The verification pipeline of #1434 consumes an ``evidence.json`` that nothing
produced. This module tests the thing that produces it: one document per run,
merging junit XML, coverage XML, gate results, the environment fingerprint and
the execution trace — each tagged with the source it came from.

Every test here plants a lie and asserts it is caught. A happy path alone would
re-create the defect the epic exists to end: a green that means "did not look".
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"


def _load_seam():
    """Import the assembler, which lives outside any importable package root.

    Done inside a function deliberately: hoisting the ``sys.path`` insert above
    the module-level imports needs an E402 suppression comment, and the repo's
    debt ratchet counts suppression identities. Paying a unit of tracked debt for
    import cosmetics is a bad trade.
    """
    if str(CI_DIR) not in sys.path:
        sys.path.insert(0, str(CI_DIR))
    import assemble_evidence

    return assemble_evidence


ae = _load_seam()

# --------------------------------------------------------------------------
# Fixtures — the four file-backed sources, written as a runner would emit them.
# --------------------------------------------------------------------------

JUNIT_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="0" failures="1" skipped="0" tests="3" time="1.250">
    <testcase classname="tests.unit.test_a" name="test_ok" time="0.100"/>
    <testcase classname="tests.unit.test_a" name="test_skipped" time="0.000">
      <skipped message="nope"/>
    </testcase>
    <testcase classname="tests.unit.test_a" name="test_bad" time="1.150">
      <failure message="assert 1 == 2">boom</failure>
    </testcase>
  </testsuite>
</testsuites>
"""

COVERAGE_XML = """<?xml version="1.0" ?>
<coverage version="7.6.1" line-rate="0.8125" lines-covered="130" lines-valid="160"
          branch-rate="0.5" branches-covered="10" branches-valid="20" timestamp="1756000000">
  <packages/>
</coverage>
"""

GATE_RESULTS = {
    "gates": [
        {"name": "check_adr", "result": "PASS", "exitCode": 0, "durationMs": 41},
        {"name": "check_done_md", "result": "FAIL", "exitCode": 1, "durationMs": 55},
    ]
}

TRACE_LINES = [
    {
        "command": ["python", "-m", "pytest", "-q"],
        "exitCode": 1,
        "startedAt": "2026-09-02T10:00:00Z",
        "durationMs": 1250,
    },
    {
        "command": ["ruff", "check", "."],
        "exitCode": 0,
        "startedAt": "2026-09-02T10:00:02Z",
        "durationMs": 310,
    },
]

FINGERPRINT = {
    "python": "3.12.4",
    "juliBackendResolvedFrom": "/repo/backend/src/juli_backend/__init__.py",
    "baseDistanceCommits": 3,
}


def _fingerprint() -> dict[str, object]:
    """Stand-in for capture_providers.environment.fingerprint()."""
    return dict(FINGERPRINT)


def _source_paths(root: Path) -> dict[str, Path]:
    return {
        "junit": root / "junit.xml",
        "coverage": root / "coverage.xml",
        "gateResults": root / "gate-results.json",
        "trace": root / "trace.jsonl",
    }


def _write_sources(root: Path) -> dict[str, Path]:
    """Write the four file-backed sources as a runner would, return their paths."""
    paths = _source_paths(root)
    paths["junit"].write_text(JUNIT_XML, encoding="utf-8")
    paths["coverage"].write_text(COVERAGE_XML, encoding="utf-8")
    paths["gateResults"].write_text(json.dumps(GATE_RESULTS), encoding="utf-8")
    paths["trace"].write_text(
        "\n".join(json.dumps(line) for line in TRACE_LINES) + "\n", encoding="utf-8"
    )
    return paths


def _assemble(root: Path, *, claims: dict | None = None, write: bool = True, **overrides) -> dict:
    """Assemble against ``root``. ``write=False`` keeps a planted lie on disk."""
    paths = _write_sources(root) if write else _source_paths(root)
    kwargs: dict[str, object] = {
        "issue": 1458,
        "junit_xml": paths["junit"],
        "coverage_xml": paths["coverage"],
        "gate_results": paths["gateResults"],
        "trace": paths["trace"],
        "fingerprint": _fingerprint,
        "repo_root": root,
        "claims": claims,
    }
    kwargs.update(overrides)
    return ae.assemble_evidence(**kwargs)


# --------------------------------------------------------------------------
# AC1 — five sources, each tagged with where it came from.
# --------------------------------------------------------------------------


def test_all_five_sources_present_and_tagged(tmp_path: Path) -> None:
    """All five sources land, each carrying its own provenance tag.

    Then two lies are planted in the assembled document and the verifier the
    assembler itself runs must catch both: a section whose provenance tag was
    stripped, and a section mislabelled as another source's kind. Without the
    second check "tagged" would mean "carries a tag", not "carries the right
    one", and any source could impersonate any other.
    """
    document = _assemble(tmp_path)

    assert set(document["sources"]) == set(ae.REQUIRED_SOURCES)
    assert set(ae.REQUIRED_SOURCES) == {
        "junit",
        "coverage",
        "gateResults",
        "environment",
        "trace",
    }

    for name in ae.REQUIRED_SOURCES:
        tag = document["sources"][name]["source"]
        assert tag["kind"] == ae.SOURCE_KINDS[name], name
        # Runner-observed only: nothing in this document is a value an agent typed.
        assert tag["observedBy"] == "runner", name

    # The four file-backed sources are pinned to the exact bytes read, so the
    # document cannot describe a different file than the one it cites.
    for name in ("junit", "coverage", "gateResults", "trace"):
        tag = document["sources"][name]["source"]
        assert tag["bytes"] > 0, name
        assert len(tag["sha256"]) == 64, name

    # The content actually made it in, not just the tags.
    assert document["sources"]["junit"]["totals"]["tests"] == 3
    assert document["sources"]["junit"]["totals"]["failures"] == 1
    assert document["sources"]["coverage"]["linesCovered"] == 130
    assert [g["name"] for g in document["sources"]["gateResults"]["gates"]] == [
        "check_adr",
        "check_done_md",
    ]
    assert document["sources"]["environment"]["fingerprint"] == FINGERPRINT
    assert len(document["sources"]["trace"]["events"]) == 2

    # A document the assembler produced verifies.
    ae.verify_evidence_document(document)

    # Lie 1: strip a section's provenance tag. An untagged section is a fact
    # with no source, which is exactly the thing this document exists to stop.
    untagged = json.loads(json.dumps(document))
    del untagged["sources"]["coverage"]["source"]
    with pytest.raises(ae.EvidenceAssemblyError) as untagged_err:
        ae.verify_evidence_document(untagged)
    assert untagged_err.value.source == "coverage"

    # Lie 2: relabel the trace as if it were the junit results.
    mislabelled = json.loads(json.dumps(document))
    mislabelled["sources"]["trace"]["source"]["kind"] = ae.SOURCE_KINDS["junit"]
    with pytest.raises(ae.EvidenceAssemblyError) as mislabelled_err:
        ae.verify_evidence_document(mislabelled)
    assert mislabelled_err.value.source == "trace"

    # Lie 3: claim a runner observation for a value that was typed.
    forged = json.loads(json.dumps(document))
    forged["sources"]["gateResults"]["source"]["observedBy"] = "executor"
    with pytest.raises(ae.EvidenceAssemblyError) as forged_err:
        ae.verify_evidence_document(forged)
    assert forged_err.value.source == "gateResults"


# --------------------------------------------------------------------------
# AC2 — an absent or unparseable source fails closed, naming the source.
# --------------------------------------------------------------------------


def test_missing_source_fails_closed(tmp_path: Path) -> None:
    """Absent, unparseable, wrong-shape and unavailable-provider all fail closed.

    Each planted lie must raise naming the offending source. A document with a
    silently missing section would make the absence of evidence
    indistinguishable from evidence of absence.
    """
    # Lie 1: the file is simply not there.
    for name, kwarg in (
        ("junit", "junit_xml"),
        ("coverage", "coverage_xml"),
        ("gateResults", "gate_results"),
        ("trace", "trace"),
    ):
        root = tmp_path / f"absent-{name}"
        root.mkdir()
        with pytest.raises(ae.EvidenceAssemblyError) as err:
            _assemble(root, **{kwarg: root / "does-not-exist"})
        assert err.value.source == name
        assert name in str(err.value)

    # Lie 2: the file exists but is truncated mid-element.
    root = tmp_path / "truncated"
    root.mkdir()
    paths = _write_sources(root)
    paths["junit"].write_text("<testsuites><testsuite tests=", encoding="utf-8")
    with pytest.raises(ae.EvidenceAssemblyError) as truncated:
        _assemble(root, write=False)
    assert truncated.value.source == "junit"

    # Lie 3: the file parses but is the wrong document — a coverage report
    # handed in as junit results. Valid XML, wrong facts.
    root = tmp_path / "wrong-root"
    root.mkdir()
    _write_sources(root)
    (root / "junit.xml").write_text(COVERAGE_XML, encoding="utf-8")
    with pytest.raises(ae.EvidenceAssemblyError) as wrong_root:
        _assemble(root, write=False)
    assert wrong_root.value.source == "junit"

    # Lie 4: a gate result reporting a verdict but no exit code. A verdict
    # without an exit code is prose, and prose is what this epic replaces.
    root = tmp_path / "gate-without-exit-code"
    root.mkdir()
    paths = _write_sources(root)
    paths["gateResults"].write_text(
        json.dumps({"gates": [{"name": "check_adr", "result": "PASS"}]}), encoding="utf-8"
    )
    with pytest.raises(ae.EvidenceAssemblyError) as no_exit:
        _assemble(root, write=False)
    assert no_exit.value.source == "gateResults"

    # Lie 4b: a gate with an exit code but no verdict. Found by running the
    # assembler against real gate output: the validate gates print a verdict
    # line whose name is not the script's name, so a plausible-looking harvester
    # yields exitCode 0 and result null for every gate. pr.yml's own comment
    # says the verdict line — not the exit code — is what separates "the gate
    # answered" from "the gate could not", so a null verdict is not a PASS.
    root = tmp_path / "gate-without-verdict"
    root.mkdir()
    paths = _write_sources(root)
    paths["gateResults"].write_text(
        json.dumps({"gates": [{"name": "check_adr", "result": None, "exitCode": 0}]}),
        encoding="utf-8",
    )
    with pytest.raises(ae.EvidenceAssemblyError) as no_verdict:
        _assemble(root, write=False)
    assert no_verdict.value.source == "gateResults"

    # Lie 5: a trace line with no observed duration.
    root = tmp_path / "trace-without-duration"
    root.mkdir()
    paths = _write_sources(root)
    paths["trace"].write_text(
        json.dumps({"command": ["pytest"], "exitCode": 0}) + "\n", encoding="utf-8"
    )
    with pytest.raises(ae.EvidenceAssemblyError) as no_duration:
        _assemble(root, write=False)
    assert no_duration.value.source == "trace"

    # Lie 6: an empty trace. Zero observed commands is not a run.
    root = tmp_path / "empty-trace"
    root.mkdir()
    paths = _write_sources(root)
    paths["trace"].write_text("", encoding="utf-8")
    with pytest.raises(ae.EvidenceAssemblyError) as empty:
        _assemble(root, write=False)
    assert empty.value.source == "trace"

    # Lie 7: the environment fingerprint provider is unavailable. It is a
    # source like any other, so its absence fails the same way rather than
    # yielding a document with four sections and no complaint.
    def _explode() -> dict[str, object]:
        raise ModuleNotFoundError("no module named 'capture_providers.environment'")

    root = tmp_path / "no-fingerprint"
    root.mkdir()
    with pytest.raises(ae.EvidenceAssemblyError) as no_env:
        _assemble(root, fingerprint=_explode)
    assert no_env.value.source == "environment"

    # And the failures above produced no document at all — not a partial one.
    assert not (tmp_path / "evidence.json").exists()


# --------------------------------------------------------------------------
# AC3 — observed wins, and the disagreement is preserved.
# --------------------------------------------------------------------------


def test_observed_wins_and_disagreement_is_preserved(tmp_path: Path) -> None:
    """An agent's claim never overwrites an observation, and never disappears.

    The lies planted here are the ones actually found in the corpus: a round
    ``executionDurationMs``, a ``tokenUsage`` no process could have read, and
    test counts that flatter the run. The document must carry the observed
    value *and* keep the claim, because the disagreement is the eval label.
    """
    claims = {
        "issue": 1458,
        "testsRun": 42,
        "testsFailed": 0,
        "tokenUsage": 1_800_000,
        "executionDurationMs": 1_800_000,
    }
    document = _assemble(tmp_path, claims=claims)

    # Observed wins: the canonical numbers are junit's, not the artifact's.
    assert document["sources"]["junit"]["totals"]["tests"] == 3
    assert document["sources"]["junit"]["totals"]["failures"] == 1

    by_field = {d["field"]: d for d in document["disagreements"]}

    assert by_field["testsRun"]["claimed"] == 42
    assert by_field["testsRun"]["observed"] == 3
    assert by_field["testsRun"]["observedFrom"] == "junit"
    assert by_field["testsRun"]["resolution"] == "observed"

    assert by_field["testsFailed"]["claimed"] == 0
    assert by_field["testsFailed"]["observed"] == 1

    # executionDurationMs IS observable from the runner — the trace carries
    # per-command durations the runner measured — so the round number loses to
    # the sum of what was actually timed.
    assert document["metrics"]["executionDurationMs"]["available"] is True
    assert document["metrics"]["executionDurationMs"]["value"] == 1560
    assert by_field["executionDurationMs"]["claimed"] == 1_800_000
    assert by_field["executionDurationMs"]["observed"] == 1560

    # tokenUsage is NOT observable from the runner. It is recorded explicitly
    # unavailable — never 0, because a zero reads as a measurement.
    token = document["metrics"]["tokenUsage"]
    assert token["available"] is False
    assert "value" not in token
    assert token["reason"]
    assert by_field["tokenUsage"]["observed"] is None
    assert by_field["tokenUsage"]["observedFrom"] == "unavailable"
    assert by_field["tokenUsage"]["claimed"] == 1_800_000

    # An agreeing claim produces no disagreement, so the list means something.
    honest_root = tmp_path / "honest"
    honest_root.mkdir()
    honest = _assemble(honest_root, claims={"testsRun": 3, "testsFailed": 1})
    honest_fields = {d["field"] for d in honest["disagreements"]}
    assert "testsRun" not in honest_fields
    assert "testsFailed" not in honest_fields

    # Even a claimed *zero* for an unobservable field is a disagreement: zero is
    # as unsourceable as 1,800,000 and is the more convincing lie.
    zeroed = tmp_path / "zeroed"
    zeroed.mkdir()
    zero_doc = _assemble(zeroed, claims={"tokenUsage": 0})
    zero_fields = {d["field"]: d for d in zero_doc["disagreements"]}
    assert zero_fields["tokenUsage"]["claimed"] == 0
    assert zero_fields["tokenUsage"]["observed"] is None

    # No claims at all: no invented disagreements.
    quiet = tmp_path / "quiet"
    quiet.mkdir()
    assert _assemble(quiet, claims=None)["disagreements"] == []


# --------------------------------------------------------------------------
# Supporting guards.
# --------------------------------------------------------------------------


def test_unavailable_is_never_expressed_as_a_zero(tmp_path: Path) -> None:
    """No metric may be reported unavailable *and* carry a numeric value."""
    document = _assemble(tmp_path)
    for name, metric in document["metrics"].items():
        assert isinstance(metric["available"], bool), name
        if metric["available"]:
            assert "value" in metric and metric["observedFrom"], name
        else:
            assert "value" not in metric, name
            assert metric["reason"], name


def test_untimed_suite_is_unavailable_not_a_measured_zero(tmp_path: Path) -> None:
    """A junit report with no ``time=`` must not yield ``testSuiteDurationMs: 0``.

    Every other junit total fails closed on an absent attribute, but suite time
    was summed with ``or 0.0``, so a report carrying no timing was recorded
    ``{"available": true, "value": 0}`` — an unmeasured field wearing a
    measurement's clothes, which is the precise defect #1434 exists to end and
    which this module's own docstring promises not to commit.
    """
    timed = tmp_path / "timed"
    timed.mkdir()
    assert _assemble(timed)["metrics"]["testSuiteDurationMs"] == {
        "available": True,
        "value": 1250,
        "observedFrom": "junit.suiteTime",
    }

    untimed = tmp_path / "untimed"
    untimed.mkdir()
    paths = _write_sources(untimed)
    paths["junit"].write_text(
        '<testsuites><testsuite name="pytest" tests="3" failures="1" errors="0" '
        'skipped="0"><testcase classname="a" name="b"/></testsuite></testsuites>',
        encoding="utf-8",
    )
    metric = _assemble(untimed, write=False)["metrics"]["testSuiteDurationMs"]
    assert metric["available"] is False
    assert "value" not in metric
    assert metric["reason"]

    # One untimed suite poisons the total rather than silently understating it:
    # a sum over suites where one is missing is not a sum.
    mixed = tmp_path / "mixed"
    mixed.mkdir()
    paths = _write_sources(mixed)
    paths["junit"].write_text(
        "<testsuites>"
        '<testsuite name="a" tests="1" failures="0" errors="0" skipped="0" time="2.0">'
        '<testcase classname="a" name="x"/></testsuite>'
        '<testsuite name="b" tests="1" failures="0" errors="0" skipped="0">'
        '<testcase classname="b" name="y"/></testsuite>'
        "</testsuites>",
        encoding="utf-8",
    )
    assert _assemble(mixed, write=False)["metrics"]["testSuiteDurationMs"]["available"] is False


def test_module_imports_only_stdlib_and_repo_siblings() -> None:
    """A third-party import here is a CI collection error, not a local failure.

    ``agent-runtime/scripts/ci/`` is stdlib-only; a peer slice shipped a
    ``jsonschema`` import that passed locally and died on CI collection. This
    shadows the usual offenders with raising stubs and re-imports the module in
    a clean interpreter, so the guard fails here rather than in CI.
    """
    source = (CI_DIR / "assemble_evidence.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed_siblings = {p.stem for p in CI_DIR.glob("*.py")} | {"capture_providers"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    third_party = imported - sys.stdlib_module_names - allowed_siblings - {"__future__"}
    assert third_party == set(), f"non-stdlib imports: {sorted(third_party)}"

    # Behavioural half: a raising stub in front of the usual offenders, so the
    # guard fails on an import that the AST scan above could not attribute.
    probe = (
        "import sys\n"
        "BANNED = {'jsonschema', 'yaml', 'pydantic', 'requests', 'httpx', 'dotenv'}\n"
        "class Raiser:\n"
        "    def find_module(self, name, path=None): return None\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in BANNED:\n"
        "            raise AssertionError('assemble_evidence imported ' + name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, Raiser())\n"
        f"sys.path.insert(0, {str(CI_DIR)!r})\n"
        "import assemble_evidence\n"
        "assert assemble_evidence.REQUIRED_SOURCES\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr


def test_runs_under_a_shallow_checkout_with_no_home_claude(tmp_path: Path) -> None:
    """CI checks out shallow and has no ``~/.claude``. Simulated, not assumed.

    The runner-observed commit must still be captured from a depth-1 clone, the
    shallowness must be recorded rather than inferred, and nothing may read the
    agent's home directory.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    env = {
        "HOME": str(tmp_path / "empty-home"),
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    (tmp_path / "empty-home").mkdir()
    assert not (Path(env["HOME"]) / ".claude").exists()

    def git(*args: str, cwd: Path) -> None:
        subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)

    git("init", "-q", "-b", "main", cwd=origin)
    (origin / "a.txt").write_text("one\n", encoding="utf-8")
    git("add", "a.txt", cwd=origin)
    git("commit", "-qm", "one", cwd=origin)
    (origin / "a.txt").write_text("two\n", encoding="utf-8")
    git("commit", "-qam", "two", cwd=origin)

    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{origin}", str(shallow)],
        env=env,
        check=True,
        capture_output=True,
    )

    document = _assemble(shallow, repo_root=shallow)
    commit = document["runner"]["commit"]
    assert commit["available"] is True
    assert len(commit["value"]) == 40
    assert document["runner"]["shallow"] is True

    # And a directory that is not a git checkout reports unavailable, not "".
    plain = tmp_path / "plain"
    plain.mkdir()
    plain_doc = _assemble(plain, repo_root=plain)
    assert plain_doc["runner"]["commit"]["available"] is False
    assert "value" not in plain_doc["runner"]["commit"]


def test_cli_writes_one_document_and_fails_closed(tmp_path: Path) -> None:
    """The CLI writes the document, and writes nothing at all when a source fails."""
    paths = _write_sources(tmp_path)
    out = tmp_path / "evidence.json"
    argv = [
        "--issue",
        "1458",
        "--junit",
        str(paths["junit"]),
        "--coverage",
        str(paths["coverage"]),
        "--gate-results",
        str(paths["gateResults"]),
        "--trace",
        str(paths["trace"]),
        "--repo-root",
        str(tmp_path),
        "--out",
        str(out),
    ]
    assert ae.main(argv, fingerprint=_fingerprint) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert set(document["sources"]) == set(ae.REQUIRED_SOURCES)

    # Planted lie: junit disappears between runs. The CLI must exit non-zero
    # and must not leave a stale or half-written document behind.
    paths["junit"].unlink()
    missing_out = tmp_path / "missing.json"
    argv[argv.index(str(out))] = str(missing_out)
    assert ae.main(argv, fingerprint=_fingerprint) == 1
    assert not missing_out.exists()
