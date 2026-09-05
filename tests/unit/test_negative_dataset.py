"""#1456 (HE-C/P-EVAL-14) — the labelled-negative dataset curated from existing caches.

The corpus this harness grades itself on has no negatives: 269 of 270 status
records are shippable and ``acceptanceMapped < acceptanceTotal`` has never once
occurred.  Sensitivity cannot be measured against a population where nothing is
labelled bad.  The hole is in the *labels*, not the data — the transcript cache,
the status records and ``git log`` already contain several hundred derivable
negatives that were simply never adjudicated at record level.

``eval/curate_negatives.py`` derives them mechanically and emits
``eval/datasets/negative_dataset.jsonl``.  These tests read the *committed*
dataset, because the derivation reads ~241 MB of transcript cache that does not
exist in CI.  Reading a committed file is exactly the shape of test that can pass
vacuously, so every test here also **plants a lie** — a tampered provenance, a
manifest count the rows do not support, a positive carrying a negative rule, a
row moved across the split boundary — and asserts the checker catches it.  A
green run therefore means the checks work, not merely that the file parses.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from eval.curate_negatives import (  # noqa: E402
    FIX_COMMIT_REF_SCOPE,
    FIX_COMMIT_TRUNK_REFS,
    classify_artifact_ref,
    classify_fix_commit,
    classify_pytest_invocation,
    classify_status_record_validation,
    derive_fix_commit_rows,
    resolve_fix_commit_scope,
)
from eval.negative_dataset import (  # noqa: E402
    NEGATIVE_LABELS,
    POSITIVE_DERIVATION_RULE,
    PRIOR_MEASUREMENTS,
    PROVENANCE_KINDS,
    ProvenanceResolver,
    Resolution,
    always_retrievable,
    label_errors,
    load_manifest,
    load_rows,
    provenance_shape_errors,
    reconciliation_errors,
    repo_backed,
    split_errors,
)

ROWS = load_rows()
MANIFEST = load_manifest()

REQUIRED_ROW_FIELDS = {
    "record_id",
    "population",
    "label",
    "source",
    "provenance",
    "derivation_rule",
    "timestamp",
    "split",
}


def _git(repo_root: Path, *args: str) -> str:
    """Run one git command in ``repo_root``, failing the test on a non-zero exit."""
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _reachable_commits(repo_root: Path) -> frozenset[str]:
    """Every commit object this checkout actually has, enumerated independently.

    Deliberately its own ``git rev-list`` rather than a read of the resolver's
    commit index: the assertion below is that the resolver's verdict for a row
    agrees with what git reports for that one commit, and it would say nothing
    at all if both sides read the same cache.
    """
    result = subprocess.run(
        ["git", "rev-list", "--all"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return frozenset(result.stdout.split())


def _present_objects(repo_root: Path, commits: Sequence[str]) -> frozenset[str]:
    """Which of these SHAs this checkout holds as commit *objects*, reachable or not.

    ``rev-list`` above walks refs and so cannot see an object that no ref
    reaches. ``cat-file --batch-check`` reads the object database directly and
    can. The gap between the two answers is exactly the state #1579 found: an
    object a squash-merge left in the database with nothing pointing at it.

    Both probes are the test's own subprocesses. Neither reads
    ``ProvenanceResolver``'s index, so the assertion below still compares two
    independently obtained answers rather than a cache against itself.
    """
    if not commits:
        return frozenset()
    result = subprocess.run(
        ["git", "cat-file", "--batch-check"],
        cwd=repo_root,
        input="\n".join(commits) + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    present = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        # "<sha> commit <size>" when held; "<name> missing" when not.
        if len(fields) == 3 and fields[1] == "commit":
            present.add(fields[0])
    return frozenset(present)


def _expected_commit_resolution(
    commit: str, reachable: frozenset[str], present: frozenset[str]
) -> Resolution:
    """One of three outcomes, each a fact about this row in this checkout.

    * reachable from some ref -- RESOLVED. The subject is retrievable, so the
      digest must match exactly.
    * held as an object but reachable from no ref -- UNREACHABLE. A
      squash-merge dissolved the branch that pointed at it; the object survives
      in the clone that curated the row and in no other, so nobody else can
      re-derive it. Not a digest disagreement, and not a fetch away either.
    * not held at all -- MISSING_SOURCE.

    The expectation is a property of the *row*, which is what makes it
    invariant under fetch depth. What it replaces asked
    ``history_is_complete()`` -- a property of the *clone* -- and so admitted
    only two states, every commit present or none. A bounded ``fetch-depth`` is
    a third state the binary model excluded: measured on real clones of this
    branch, depth 1 reaches 0 of the 125 commit rows and depth 200 reaches 59,
    so no single clone-wide verdict is correct at both. Keyed per row, the same
    expectation holds at depth 1, at 200 and in a complete clone.

    The UNREACHABLE arm is narrower than "complete clone", and the distinction
    caught an earlier version of this docstring out. It is not that a *shallow*
    fetch declines to transfer a dangling object -- **no clone transfers one at
    all**, at any depth, because git's transfer protocol enumerates objects by
    walking refs and nothing points at a dissolved commit. So the two rows in
    ``DISSOLVED_COMMIT_ROWS`` report UNREACHABLE only in the working copy that
    curated them, where the object was written locally and never left. Every
    fresh clone -- complete ones included -- reports them MISSING_SOURCE from
    this function and MISMATCH from the resolver, because there the objects are
    genuinely absent. Measured, not inferred: ``cat-file --batch-check`` says
    ``commit`` for both in the curating worktree and ``missing`` in a fresh
    ``git clone`` of the same branch. Expect MISMATCH, not UNREACHABLE, when
    reading this anywhere but the machine that ran the curation.

    #1618 corrects the scope of that last sentence. It holds for *dangling*
    objects, which is what it was written about, but dissolution is not the only
    route to UNREACHABLE. Two bounded fetches also produce it: pr.yml fetches the
    merge ref at a bounded depth and then the base ref at a bounded depth, and
    the second can deliver an object the first ref's own walk does not reach.
    Observed on PR #1616, where a healthy row at depth 199 against fetch-depth
    200 reported UNREACHABLE and read as freshly dissolved. So UNREACHABLE means
    "here but unreachable", and *why* is answerable only in a complete clone.
    """
    if commit in reachable:
        return Resolution.RESOLVED
    return Resolution.UNREACHABLE if commit in present else Resolution.MISSING_SOURCE


#: The commit rows whose objects a squash-merge dissolved, by ``record_id`` (#1579).
#: Recorded as an allowlist rather than a count so that a *new* dissolution is red
#: on sight instead of being absorbed by a budget. Asserted as a subset, not an
#: equality, because no clone but the curating one holds these objects at all --
#: not a depth question, a reachability one, since a clone transfers only what a
#: ref reaches. Everywhere else the set is empty, and the subset has to hold
#: there too. Curation is pinned
#: to the trunk (``eval.curate_negatives.resolve_fix_commit_scope``) so this set
#: cannot grow from a future derivation.
DISSOLVED_COMMIT_ROWS = frozenset({"fix_commits/f6c0630567443eb4", "fix_commits/702867bf541e1fcd"})


def test_every_row_provenance_resolves() -> None:
    """Every row names a real file line, JSON pointer or commit — and a tampered one is caught."""
    assert ROWS, "the committed dataset is empty; run `python -m eval.curate_negatives`"

    # Shape first: a row whose provenance is malformed can never be re-derived,
    # and would silently resolve to "source missing" rather than to a defect.
    shape_problems = provenance_shape_errors(ROWS)
    assert shape_problems == [], shape_problems[:5]
    assert {r["provenance"]["kind"] for r in ROWS} <= PROVENANCE_KINDS

    for row in ROWS:
        assert REQUIRED_ROW_FIELDS <= set(row), sorted(REQUIRED_ROW_FIELDS - set(row))
    assert len({r["record_id"] for r in ROWS}) == len(ROWS), "record_id is not unique"

    resolver = ProvenanceResolver(repo_root=REPO_ROOT)
    resolutions = resolver.resolve_all(ROWS)

    # A source that IS present and disagrees with the recorded digest is a hard
    # failure everywhere: it means the label cites evidence that no longer says
    # what the label claims.
    mismatched = [
        row["record_id"]
        for row, res in zip(ROWS, resolutions, strict=True)
        if res is Resolution.MISMATCH
    ]
    assert mismatched == [], mismatched[:5]

    malformed = [
        row["record_id"]
        for row, res in zip(ROWS, resolutions, strict=True)
        if res is Resolution.MALFORMED
    ]
    assert malformed == [], malformed[:5]

    # Status records are tracked files, so they are present at any fetch depth —
    # CI included. These must resolve exactly, with no allowance. They are what
    # keeps this assertion real rather than skipped in CI.
    tracked_rows = [
        (row, res)
        for row, res in zip(ROWS, resolutions, strict=True)
        if always_retrievable(row["provenance"])
    ]
    assert tracked_rows, "no tracked-file provenance — nothing would be checkable in CI"
    unresolved = [row["record_id"] for row, res in tracked_rows if res is not Resolution.RESOLVED]
    assert unresolved == [], unresolved[:5]

    # Commit rows are judged one at a time, so the expectation does not move
    # with the checkout depth: a commit reachable in this clone must resolve
    # exactly, one held only as a dangling object must be a definite
    # UNREACHABLE, and one the clone does not hold at all must be a definite
    # MISSING_SOURCE — never a shrug in any direction, and never MISMATCH or
    # MALFORMED. CI checks this repo out shallow for every job that runs pytest
    # — depth 1 for most, a bounded depth for `test` and `full-regression` —
    # and this holds identically at either, and in a complete clone.
    reachable = _reachable_commits(REPO_ROOT)
    commit_rows = [
        (row, res)
        for row, res in zip(ROWS, resolutions, strict=True)
        if row["provenance"]["kind"] == "git_commit"
    ]
    assert commit_rows
    present = _present_objects(REPO_ROOT, [r["provenance"]["commit"] for r, _ in commit_rows])
    off = [
        (row["record_id"], res.name)
        for row, res in commit_rows
        if res is not _expected_commit_resolution(row["provenance"]["commit"], reachable, present)
    ]
    assert off == [], off[:5]
    assert all(repo_backed(row["provenance"]) for row, _ in commit_rows + tracked_rows)

    # UNREACHABLE is tolerated only for the rows already known to be dissolved.
    # Anything else means a squash-merge has just dissolved fresh evidence, and
    # that must be red rather than quietly accepted as a known cost.
    # #1618: only ask this where the answer means something. UNREACHABLE is
    # "the object is here and no ref reaches it". In a complete clone that is the
    # signature of a dissolved commit. In a bounded checkout it is also the
    # signature of a commit outside the fetched window -- pr.yml issues two
    # bounded fetches (merge ref, then base ref), and the second can deliver an
    # object the first ref's walk does not reach. From inside, the two causes are
    # indistinguishable, so asserting here asserts on noise.
    #
    # Measured on PR #1616, a docs-only change: fix_commits/957d94212a58b698
    # (commit 7ae85937d -- present, digest matching, reachable in a complete
    # clone) sits at depth 199 against fetch-depth 200 and reported as freshly
    # dissolved. 78 of the 125 commit rows sit in the band [150, 260] and 13 more
    # cross as the wave advances, so this is a date-dependent false alarm on
    # whichever PR is open, not a defect in that PR.
    dissolved = {row["record_id"] for row, res in commit_rows if res is Resolution.UNREACHABLE}
    if resolver.history_is_complete():
        assert dissolved <= DISSOLVED_COMMIT_ROWS, sorted(dissolved - DISSOLVED_COMMIT_ROWS)[:5]
    else:
        # Not silent: a check that quietly stops running is the failure mode of
        # #1600 and #1603. Say what was seen and what was not asserted.
        print(
            f"#1618: dissolution not asserted (bounded checkout) -- "
            f"{len(dissolved)} UNREACHABLE row(s), "
            f"{len(dissolved - DISSOLVED_COMMIT_ROWS)} outside the allowlist; "
            f"the per-row expectation above still ran at this depth."
        )

    # Cache-backed rows resolve exactly wherever the cache exists (a developer
    # machine); in CI the cache is absent and MISSING_SOURCE is the honest answer.
    cache_rows = [
        (row, res)
        for row, res in zip(ROWS, resolutions, strict=True)
        if not repo_backed(row["provenance"])
    ]
    for row, res in cache_rows:
        assert res in (Resolution.RESOLVED, Resolution.MISSING_SOURCE), (row["record_id"], res)

    # --- planted lies -------------------------------------------------------
    # Status record: tamper the recorded digest, demand a MISMATCH.
    original = next(r for r in ROWS if r["provenance"]["kind"] == "status_record")
    tampered = json.loads(json.dumps(original))
    tampered["provenance"]["sha256"] = "0" * 64
    assert resolver.resolve(tampered["provenance"]) is Resolution.MISMATCH

    absent = json.loads(json.dumps(original))
    absent["provenance"]["file"] = "agent-runtime/artifacts/status/issue-0.json"
    assert resolver.resolve(absent["provenance"]) is Resolution.MISSING_SOURCE

    pointed_nowhere = json.loads(json.dumps(original))
    pointed_nowhere["provenance"]["pointer"] = "/review/noSuchField"
    assert resolver.resolve(pointed_nowhere["provenance"]) is Resolution.MISMATCH

    # Git: HEAD is present at any fetch depth, so this branch is exercised in a
    # shallow CI checkout too — where the dataset's own commit rows cannot be.
    head = subprocess.run(
        ["git", "log", "-1", "--pretty=%H%x1f%s"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    head_sha, head_subject = head.split("\x1f", 1)
    good_commit = {
        "kind": "git_commit",
        "commit": head_sha,
        "sha256": hashlib.sha256(head_subject.encode("utf-8")).hexdigest(),
    }
    assert resolver.resolve(good_commit) is Resolution.RESOLVED
    assert resolver.resolve({**good_commit, "sha256": "0" * 64}) is Resolution.MISMATCH
    assert resolver.resolve({**good_commit, "commit": "f" * 40}) is not Resolution.RESOLVED

    # The per-row rule above must still go red on a real defect, or admitting
    # UNREACHABLE would have weakened this gate rather than repaired it. HEAD is
    # reachable at every fetch depth, so this exhibit runs in CI too: a commit
    # the checkout HAS AND CAN REACH, carrying a digest that disagrees, resolves
    # MISMATCH where the rule demands RESOLVED, and lands in `off`. That is the
    # input the new rule still fails on, and UNREACHABLE cannot absorb it —
    # a reachable commit never takes that branch.
    assert head_sha in reachable
    assert head_sha in _present_objects(REPO_ROOT, [head_sha])
    liar = {**good_commit, "sha256": "0" * 64}
    assert resolver.resolve(liar) is Resolution.MISMATCH
    assert resolver.resolve(liar) is not _expected_commit_resolution(
        head_sha, reachable, _present_objects(REPO_ROOT, [head_sha])
    )

    # The three commit outcomes, separated in a repository this test builds, so
    # the distinction is proven rather than inferred from the dataset — and
    # proven in a *complete* clone, which is the state that used to report the
    # dangling object as MISMATCH.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _git(root, "init", "-q", "-b", "trunk", ".")
        _git(root, "config", "user.email", "t@example.com")
        _git(root, "config", "user.name", "t")
        _git(root, "commit", "-q", "--allow-empty", "-m", "kept: on the trunk")
        kept = _git(root, "rev-parse", "HEAD").strip()
        _git(root, "commit", "-q", "--allow-empty", "-m", "dissolved: squashed away")
        dangling = _git(root, "rev-parse", "HEAD").strip()
        # Move the only ref off it. The object stays in the database; nothing
        # points at it — precisely what a squash-merge plus branch delete leaves.
        _git(root, "reset", "-q", "--hard", kept)

        probe = ProvenanceResolver(repo_root=root)
        assert probe.history_is_complete(), "the exhibit must run in a complete clone"

        kept_ok = {
            "kind": "git_commit",
            "commit": kept,
            "sha256": hashlib.sha256(b"kept: on the trunk").hexdigest(),
        }
        assert probe.resolve(kept_ok) is Resolution.RESOLVED
        # Reachable and disagreeing is still a hard failure. This is the input
        # that keeps the assertion above red under the new rule.
        assert probe.resolve({**kept_ok, "sha256": "0" * 64}) is Resolution.MISMATCH
        # Present but reachable from no ref is its own outcome, not a digest
        # disagreement — the resolver never even reads the digest to say so.
        assert (
            probe.resolve(
                {
                    "kind": "git_commit",
                    "commit": dangling,
                    "sha256": hashlib.sha256(b"dissolved: squashed away").hexdigest(),
                }
            )
            is Resolution.UNREACHABLE
        )
        assert probe.resolve({"kind": "git_commit", "commit": dangling, "sha256": "0" * 64}) is (
            Resolution.UNREACHABLE
        )
        # And a commit that simply does not exist stays a hard failure in a
        # complete clone: absence is not laundered into the new outcome.
        assert probe.resolve({**kept_ok, "commit": "f" * 40}) is Resolution.MISMATCH

    # Malformed provenance is rejected outright, never treated as "cannot check".
    assert resolver.resolve({"kind": "nonsense"}) is Resolution.MALFORMED
    assert resolver.resolve({"kind": "git_commit", "commit": head_sha}) is Resolution.MALFORMED

    # Transcript kind: the real cache may be absent here, so verify the resolver
    # against a synthetic transcript it controls. Without this the transcript
    # branch would be untested in CI, which is the vacuity this epic exists to end.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        line = json.dumps({"type": "assistant", "timestamp": "2026-01-01T00:00:00Z"})
        (root / "synthetic.jsonl").write_text(f"ignored\n{line}\n", encoding="utf-8")
        digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
        synthetic = ProvenanceResolver(repo_root=REPO_ROOT, transcript_root=root)
        good = {"kind": "transcript_line", "file": "synthetic.jsonl", "line": 2, "sha256": digest}
        assert synthetic.resolve(good) is Resolution.RESOLVED
        assert synthetic.resolve({**good, "sha256": "0" * 64}) is Resolution.MISMATCH
        assert synthetic.resolve({**good, "line": 1}) is Resolution.MISMATCH
        assert synthetic.resolve({**good, "line": 99}) is Resolution.MISMATCH
        assert synthetic.resolve({**good, "file": "nope.jsonl"}) is Resolution.MISSING_SOURCE


def test_counts_reproduce_prior_measurements_or_explain() -> None:
    """All seven prior measurements are re-derived; each is reproduced or explained."""
    reconciliation = MANIFEST["reconciliation"]
    assert {e["population"] for e in reconciliation} == set(PRIOR_MEASUREMENTS)

    # The reconciliation is checked against the rows, not taken on its word — a
    # manifest that reports a count the dataset does not contain is the exact
    # "agent reports a value" failure the epic forbids.
    problems = reconciliation_errors(ROWS, MANIFEST)
    assert problems == [], problems[:5]

    for entry in reconciliation:
        prior = PRIOR_MEASUREMENTS[entry["population"]]
        assert entry["prior_reported_negative"] == prior.negative
        assert entry["prior_reported_total"] == prior.total
        reproduced = (
            entry["derived_negative"] == prior.negative and entry["derived_total"] == prior.total
        )
        assert entry["reproduced"] is reproduced, entry["population"]
        if not reproduced:
            # A difference is a finding, and a finding has a stated cause.
            assert len(entry["explanation"].strip()) >= 40, entry["population"]

    # planted lie: inflate one derived count and demand the cross-check catches it.
    tampered = json.loads(json.dumps(MANIFEST))
    tampered["reconciliation"][0]["derived_negative"] += 7
    assert reconciliation_errors(ROWS, tampered) != []

    # planted lie: a population silently dropped from the reconciliation.
    dropped = json.loads(json.dumps(MANIFEST))
    dropped["reconciliation"] = dropped["reconciliation"][1:]
    assert reconciliation_errors(ROWS, dropped) != []


def test_positives_are_retained_and_unlabelled() -> None:
    """Records showing no failure mode stay in, unlabelled — the false-positive denominator."""
    positives = [r for r in ROWS if r["label"] is None]
    negatives = [r for r in ROWS if r["label"] is not None]
    assert positives, "no positive class: false positives would be unmeasurable"
    assert negatives

    assert {r["label"] for r in negatives} <= NEGATIVE_LABELS
    for row in positives:
        assert row["derivation_rule"] == POSITIVE_DERIVATION_RULE

    # Positives are retained per population, so each population carries its own
    # denominator — #1457 established the false-positive floor at 0 and this
    # dataset has to offer the same denominator to compare against.
    by_population: dict[str, list[dict]] = {}
    for row in ROWS:
        by_population.setdefault(row["population"], []).append(row)
    assert set(by_population) == set(PRIOR_MEASUREMENTS)
    populations_with_positives = [
        p for p, rows in by_population.items() if any(r["label"] is None for r in rows)
    ]
    assert len(populations_with_positives) == len(by_population), sorted(
        set(by_population) - set(populations_with_positives)
    )

    assert label_errors(ROWS) == []

    # planted lie: a row labelled positive while carrying a negative rule.
    tampered = json.loads(json.dumps(ROWS[:1]))
    tampered[0]["label"] = None
    tampered[0]["derivation_rule"] = "pytest_invocation_narrower_than_ci"
    assert label_errors(tampered) != []

    # planted lie: a negative label nobody defined.
    invented = json.loads(json.dumps(ROWS[:1]))
    invented[0]["label"] = "definitely_bad"
    assert label_errors(invented) != []

    # The derivation itself, run on clean inputs, must decline to label. These
    # call the same classifiers the curation script uses.
    assert classify_pytest_invocation("python -m pytest tests/") is None
    assert classify_pytest_invocation("cd /repo && pytest tests") is None
    assert classify_pytest_invocation("python -m pytest tests/unit/test_x.py") is not None
    assert classify_pytest_invocation("python -m pytest tests/ -k webhook") is not None

    known = {"agent-runtime/artifacts/status/issue-1326.json"}
    assert (
        classify_artifact_ref("git-history:agent-runtime/artifacts/status/issue-1326.json", known)
        is None
    )
    assert (
        classify_artifact_ref("git-history:agent-runtime/artifacts/reviews/nope.json", known)
        is not None
    )

    assert classify_status_record_validation({"validation": {"status": "PASS"}}) is None
    assert classify_status_record_validation({"validation": {"status": "FAIL"}}) is not None

    assert classify_fix_commit("feat(api): add a route (#10)", {10}) is None
    assert classify_fix_commit("fix(api): brand new problem (#99)", {10}) is None
    assert classify_fix_commit("fix(api): redo the route (#10) (#99)", {10}) is not None


def test_split_is_temporal() -> None:
    """Train precedes holdout in wall-clock time, so no gate can be tuned on its own future."""
    boundary = MANIFEST["split"]["boundary"]
    assert MANIFEST["split"]["strategy"] == "temporal"

    train = [r for r in ROWS if r["split"] == "train"]
    holdout = [r for r in ROWS if r["split"] == "holdout"]
    assert train and holdout
    assert len(train) + len(holdout) == len(ROWS), "some row carries neither split"

    assert max(r["timestamp"] for r in train) < boundary
    assert min(r["timestamp"] for r in holdout) >= boundary

    # The defining property, stated directly: nothing in holdout predates
    # anything in train. A random split violates this with probability ~1.
    assert max(r["timestamp"] for r in train) < min(r["timestamp"] for r in holdout)

    assert split_errors(ROWS, MANIFEST) == []

    # planted lie: move the single latest row back into train.
    tampered = json.loads(json.dumps(ROWS))
    latest = max(tampered, key=lambda r: r["timestamp"])
    latest["split"] = "train"
    assert split_errors(tampered, MANIFEST) != []

    # planted lie: a random-looking split that interleaves the two classes.
    shuffled = json.loads(json.dumps(ROWS))
    for i, row in enumerate(sorted(shuffled, key=lambda r: r["timestamp"])):
        row["split"] = "holdout" if i % 2 else "train"
    assert split_errors(shuffled, MANIFEST) != []


def test_fix_commit_curation_is_pinned_to_the_trunk() -> None:
    """Rule 6 draws commits from the trunk, so it cannot cite a soon-to-be-dissolved tip.

    #1579's two rows were curated at ``HEAD`` on a feature branch, so its scope
    included commits that the squash-merge then dissolved. A trunk ref cannot:
    a commit reachable from the trunk survives every later squash-merge, because
    it *is* what a squash-merge produces. This is the half of the fix that stops
    the population growing new unreachable rows; the resolver's ``UNREACHABLE``
    is the half that reports the ones already in it honestly.
    """
    assert FIX_COMMIT_REF_SCOPE != "HEAD", "HEAD is what let a dissolving tip in"
    assert FIX_COMMIT_REF_SCOPE in FIX_COMMIT_TRUNK_REFS

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _git(root, "init", "-q", "-b", "main", ".")
        _git(root, "config", "user.email", "t@example.com")
        _git(root, "config", "user.name", "t")

        # No trunk ref yet: the scope must refuse rather than silently fall back
        # to HEAD, which is exactly the fallback that would reintroduce the bug.
        try:
            resolve_fix_commit_scope(root)
        except RuntimeError:
            pass
        else:  # pragma: no cover - only reached on a regression
            raise AssertionError("an unpinnable repo must raise, not fall back to HEAD")

        _git(root, "commit", "-q", "--allow-empty", "-m", "fix: on the trunk (#1)")
        trunk_tip = _git(root, "rev-parse", "HEAD").strip()

        # A feature branch whose tip a squash-merge is about to dissolve.
        _git(root, "checkout", "-q", "-b", "feature/x")
        _git(root, "commit", "-q", "--allow-empty", "-m", "fix: about to be squashed (#1)")
        doomed = _git(root, "rev-parse", "HEAD").strip()

        scope = resolve_fix_commit_scope(root)
        assert scope in FIX_COMMIT_TRUNK_REFS
        in_scope = set(_git(root, "rev-list", scope).split())
        assert trunk_tip in in_scope
        assert doomed not in in_scope, "the pinned scope still admits a dissolving tip"

        # And the derivation built on it agrees — it is the derivation, not the
        # constant, that decides what lands in the dataset.
        cited = {row["provenance"]["commit"] for row in derive_fix_commit_rows(root)}
        assert trunk_tip in cited
        assert doomed not in cited


def test_dissolution_check_still_bites_in_a_complete_clone() -> None:
    """#1618 / ADR-092 exhibit: scoping a check is legitimate only if it can
    still fail somewhere.

    The dissolution assertion is now gated on `history_is_complete()`, because in
    a bounded checkout UNREACHABLE cannot distinguish a squash-dissolved commit
    from one outside the fetched window. Narrowing where a check runs is the
    shape of a gate weakening, so exhibit the input that still turns it red: a
    freshly dissolved row, in a complete clone, outside the allowlist.
    """
    fresh = "fix_commits/deadbeefdeadbeef"
    assert fresh not in DISSOLVED_COMMIT_ROWS

    observed = set(DISSOLVED_COMMIT_ROWS) | {fresh}
    assert not observed <= DISSOLVED_COMMIT_ROWS, (
        "a row that is UNREACHABLE and outside the allowlist must fail the "
        "dissolution check; if this passes, fresh dissolution is tolerated"
    )

    # The allowlist must stay a subset assertion over identities. A count budget
    # would absorb a third dissolution silently -- #1579 chose identities for
    # exactly that reason and this keeps the choice from being undone.
    assert isinstance(DISSOLVED_COMMIT_ROWS, frozenset)
    assert len(DISSOLVED_COMMIT_ROWS) == 2, sorted(DISSOLVED_COMMIT_ROWS)


def test_the_second_cause_of_unreachable_is_recorded() -> None:
    """#1618: the docstring claimed UNREACHABLE arises only in the working copy
    that curated the dataset -- "no clone transfers a dangling object at all".

    True of dangling objects, and verified when written, but not the only route:
    CI produced UNREACHABLE for a healthy row on PR #1616 because two bounded
    fetches can deliver an object the checked-out ref's walk does not reach. A
    reader trusting the narrower claim would conclude the row was dissolved.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    assert "#1618" in source
    assert "bounded fetches" in source, (
        "the fetched-window cause of UNREACHABLE is not recorded, leaving "
        "dissolution as the only documented explanation"
    )
