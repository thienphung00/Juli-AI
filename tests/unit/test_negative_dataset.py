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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from eval.curate_negatives import (  # noqa: E402
    classify_artifact_ref,
    classify_fix_commit,
    classify_pytest_invocation,
    classify_status_record_validation,
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

    # Commits are retrievable only in a complete clone. CI checks this repo out
    # shallow for every job that runs pytest (pr.yml:423 and 15 more), so demand
    # full resolution where the history is there and a definite MISSING_SOURCE
    # where it is not — never a shrug in either direction.
    complete_history = resolver.history_is_complete()
    commit_rows = [
        (row, res)
        for row, res in zip(ROWS, resolutions, strict=True)
        if row["provenance"]["kind"] == "git_commit"
    ]
    assert commit_rows
    expected = Resolution.RESOLVED if complete_history else Resolution.MISSING_SOURCE
    off = [row["record_id"] for row, res in commit_rows if res is not expected]
    assert off == [], (complete_history, off[:5])
    assert all(repo_backed(row["provenance"]) for row, _ in commit_rows + tracked_rows)

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
