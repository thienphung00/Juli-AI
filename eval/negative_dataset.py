"""#1456 (HE-C/P-EVAL-14) — schema, provenance resolution and temporal split.

This module holds everything that reads or checks the emitted dataset.  It
deliberately knows nothing about *deriving* it: the seven derivation rules live
in :mod:`eval.curate_negatives`, which imports this module and not the reverse.
That seam is what lets ``tests/unit/test_negative_dataset.py`` verify the
committed dataset in CI, where the 241 MB transcript cache the derivation reads
does not exist.

Provenance is the whole point of the slice.  A label here can be *disputed by
re-running its derivation* rather than by argument, so every row cites the file
and line, the JSON pointer, or the commit it came from, together with a SHA-256
of exactly the bytes that were read.  A source that is present and no longer
hashes to the recorded digest is a hard failure, never a shrug:
:class:`Resolution` keeps "source absent on this machine" and "source present
and disagrees" as distinct outcomes precisely so the second can never be
laundered into the first.

Stdlib only.  CI installs ``./backend[dev] -c backend/constraints.txt`` and
nothing else; #1457 lost a CI run to a ``jsonschema`` import that worked locally.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = REPO_ROOT / "eval" / "datasets" / "negative_dataset.jsonl"
MANIFEST_PATH = REPO_ROOT / "eval" / "datasets" / "negative_dataset.manifest.json"

#: Where the Claude Code transcript cache lives on a developer machine. Absent in CI.
DEFAULT_TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects" / "-Users-macos-Juli-AI-v2"

POSITIVE_DERIVATION_RULE = "no_rule_matched"

#: label -> the derivation rule that is allowed to assign it. One rule, one label:
#: a label that two rules can assign cannot be disputed by re-running "the" rule.
LABEL_RULES: dict[str, str] = {
    "claim_false": "subagent_success_claim_contradicted_within_5_replies",
    "evidence_unretrievable": "artifact_ref_in_no_commit_on_any_branch",
    "scope_overstated": "pytest_invocation_narrower_than_ci",
    "unbacked_claim": "gate_result_claim_without_run_in_prior_40_events",
    "verdict_contradiction": "review_pass_over_validation_fail",
    "rework_signal": "fix_commit_naming_an_earlier_issue",
    "true_negative": "validation_status_fail",
}
NEGATIVE_LABELS = frozenset(LABEL_RULES)
DERIVATION_RULES = frozenset(LABEL_RULES.values()) | {POSITIVE_DERIVATION_RULE}

PROVENANCE_KINDS = frozenset({"transcript_line", "status_record", "git_commit"})
#: Kinds whose source ships inside the repository, so they must resolve in CI too.
REPO_BACKED_KINDS = frozenset({"status_record", "git_commit"})

PROVENANCE_FIELDS: dict[str, tuple[tuple[str, type], ...]] = {
    "transcript_line": (("file", str), ("line", int), ("sha256", str)),
    "status_record": (("file", str), ("pointer", str), ("sha256", str)),
    "git_commit": (("commit", str), ("sha256", str)),
}


@dataclass(frozen=True)
class PriorMeasurement:
    """One row of the seven-row table in issue #1456 — an input to reproduce, not a truth."""

    negative: int
    total: int
    label: str
    description: str


#: The seven prior measurements, frozen verbatim from the issue body. These are
#: NOT ground truth; a derivation that lands elsewhere is a finding, and the
#: manifest must carry the cause. See ``reconciliation_errors``.
PRIOR_MEASUREMENTS: dict[str, PriorMeasurement] = {
    "subagent_success_claims": PriorMeasurement(
        88,
        351,
        "claim_false",
        "Subagent success claims contradicted by the parent within 5 replies",
    ),
    "artifact_refs": PriorMeasurement(
        240, 538, "evidence_unretrievable", "artifactRef naming a path in no commit on any branch"
    ),
    "pytest_invocations": PriorMeasurement(
        487, 541, "scope_overstated", "pytest invocations narrower than CI's"
    ),
    "gate_result_claims": PriorMeasurement(
        88, 239, "unbacked_claim", "Gate-result claims with no matching run in the prior 40 events"
    ),
    "review_validation_pairs": PriorMeasurement(
        2, 2, "verdict_contradiction", "Review PASS over validation FAIL, same issue"
    ),
    "fix_commits": PriorMeasurement(
        46, 229, "rework_signal", "fix: commits naming an earlier issue"
    ),
    "validation_outcomes": PriorMeasurement(4, 270, "true_negative", "Validation FAILs"),
}

SPLITS = frozenset({"train", "holdout"})


class Resolution(Enum):
    """Outcome of resolving one row's provenance against its source.

    ``MISSING_SOURCE`` and ``MISMATCH`` are kept apart on purpose. Collapsing them
    turns "I cannot check this here" into "this checks out", which is the vacuous
    pass this epic exists to end.
    """

    RESOLVED = "resolved"
    MISSING_SOURCE = "missing_source"
    MISMATCH = "mismatch"
    MALFORMED = "malformed"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_sha256(value: Any) -> str:
    """Digest of a JSON value under a canonical encoding, so key order cannot flip it."""
    return sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":")))


def repo_backed(provenance: Mapping[str, Any]) -> bool:
    """Whether the source ships inside the repository rather than in a local cache."""
    return provenance.get("kind") in REPO_BACKED_KINDS


def always_retrievable(provenance: Mapping[str, Any]) -> bool:
    """Whether the source is present in *any* checkout, shallow ones included.

    Status records are tracked files, so they are there whatever the fetch depth.
    Commits are not: CI checks out shallow, so git history is retrievable only
    where the clone is complete. This distinction is what keeps the CI assertion
    strict without making it wrong.
    """
    return provenance.get("kind") == "status_record"


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #


def load_rows(path: Path = DATASET_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_dataset(
    rows: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    dataset_path: Path = DATASET_PATH,
    manifest_path: Path = MANIFEST_PATH,
) -> None:
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    with dataset_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# provenance
# --------------------------------------------------------------------------- #


def provenance_shape_errors(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Structural problems that would make a row impossible to re-derive."""
    problems: list[str] = []
    for row in rows:
        rid = row.get("record_id", "<no record_id>")
        provenance = row.get("provenance")
        if not isinstance(provenance, dict):
            problems.append(f"{rid}: provenance is not an object")
            continue
        kind = provenance.get("kind")
        if kind not in PROVENANCE_KINDS:
            problems.append(f"{rid}: unknown provenance kind {kind!r}")
            continue
        for field, expected in PROVENANCE_FIELDS[kind]:
            value = provenance.get(field)
            if not isinstance(value, expected) or isinstance(value, bool):
                problems.append(f"{rid}: provenance.{field} is not a {expected.__name__}")
            elif expected is str and not value.strip():
                problems.append(f"{rid}: provenance.{field} is empty")
        digest = provenance.get("sha256")
        if isinstance(digest, str) and len(digest) != 64:
            problems.append(f"{rid}: provenance.sha256 is not a sha256 digest")
        if not isinstance(row.get("derivation_rule"), str):
            problems.append(f"{rid}: derivation_rule is missing")
    return problems


def _pointer_get(document: Any, pointer: str) -> Any:
    """Minimal RFC-6901 JSON pointer lookup. Raises KeyError when the path is absent."""
    if pointer in ("", "/"):
        return document
    node = document
    for raw in pointer.lstrip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(token)]
        elif isinstance(node, dict):
            node = node[token]
        else:
            raise KeyError(pointer)
    return node


class ProvenanceResolver:
    """Resolves each provenance kind against its real source, batching the expensive parts.

    Git history and transcript files are read once per resolver, not once per row:
    the dataset carries thousands of rows and a subprocess or a file open per row
    would put this well past pytest's 30 s budget.
    """

    def __init__(self, repo_root: Path = REPO_ROOT, transcript_root: Path | None = None) -> None:
        self.repo_root = Path(repo_root)
        self.transcript_root = (
            Path(transcript_root) if transcript_root is not None else DEFAULT_TRANSCRIPT_ROOT
        )
        self._commits: dict[str, str] | None = None
        self._shallow: bool | None = None
        self._transcript_cache: dict[str, dict[int, str]] = {}
        self._status_cache: dict[str, Any] = {}

    # -- git ---------------------------------------------------------------
    def history_is_complete(self) -> bool:
        """False in a shallow clone, where `git log --all` cannot see all history.

        This answers a question about the *clone*, and a checkout has three
        states, not two. Measured on real clones of this branch:

        * ``fetch-depth: 1`` -- shallow, 0 of the 125 git_commit rows reachable.
        * ``fetch-depth: 200`` -- still shallow (``--is-shallow-repository``
          stays true, so this predicate still returns False), yet 59 of the 125
          rows ARE reachable. A predicate that reports only "shallow" cannot
          describe this state, and any caller that reads it as "therefore no
          commit is retrievable" is wrong here. #1573 deepened `test` and
          `full-regression` to 200 so base-anchored gates resolve merge-base,
          and that is exactly the state they now run in.
        * ``fetch-depth: 0`` -- complete; this flips to True.

        Because of the middle state, do not use this to predict a per-row
        outcome. ``tests/unit/test_negative_dataset.py`` asks git whether it
        holds each individual commit instead, which is the only form stable
        across all three. This predicate remains the right question for the
        one thing it is asked below: whether a commit git does not have is
        genuinely *absent* (shallow) or a real defect (complete). Reporting an
        out-of-reach commit as a defect would be a false positive, and
        reporting an unretrievable one as resolved would be the vacuous pass
        this epic ends.
        """
        if self._shallow is None:
            result = subprocess.run(
                ["git", "rev-parse", "--is-shallow-repository"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
            self._shallow = result.stdout.strip() == "true" or result.returncode != 0
        return not self._shallow

    def _commit_index(self) -> dict[str, str]:
        if self._commits is None:
            result = subprocess.run(
                ["git", "log", "--all", "--pretty=%H%x1f%s"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
            index: dict[str, str] = {}
            for line in result.stdout.splitlines():
                if "\x1f" in line:
                    sha, subject = line.split("\x1f", 1)
                    index[sha] = subject
            self._commits = index
        return self._commits

    # -- status records -----------------------------------------------------
    def _status_document(self, relative: str) -> Any:
        if relative not in self._status_cache:
            path = self.repo_root / relative
            self._status_cache[relative] = (
                json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            )
        return self._status_cache[relative]

    # -- transcripts --------------------------------------------------------
    def _transcript_lines(self, name: str, wanted: Sequence[int]) -> dict[int, str] | None:
        path = self.transcript_root / name
        if not path.exists():
            return None
        cached = self._transcript_cache.setdefault(name, {})
        missing = [n for n in wanted if n not in cached]
        if missing:
            target = set(missing)
            with path.open(encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    if number in target:
                        cached[number] = line.rstrip("\n")
                        target.discard(number)
                        if not target:
                            break
        return cached

    # -- public -------------------------------------------------------------
    def resolve(self, provenance: Mapping[str, Any]) -> Resolution:
        kind = provenance.get("kind")
        if kind not in PROVENANCE_KINDS:
            return Resolution.MALFORMED
        for field, expected in PROVENANCE_FIELDS[kind]:
            if not isinstance(provenance.get(field), expected) or isinstance(
                provenance.get(field), bool
            ):
                return Resolution.MALFORMED
        digest = provenance["sha256"]

        if kind == "git_commit":
            subject = self._commit_index().get(provenance["commit"])
            if subject is None:
                # In a full clone a commit nobody has is a real defect; in a
                # shallow one it is simply out of reach. Never conflate the two.
                return (
                    Resolution.MISMATCH if self.history_is_complete() else Resolution.MISSING_SOURCE
                )
            return Resolution.RESOLVED if sha256_text(subject) == digest else Resolution.MISMATCH

        if kind == "status_record":
            document = self._status_document(provenance["file"])
            if document is None:
                return Resolution.MISSING_SOURCE
            try:
                value = _pointer_get(document, provenance["pointer"])
            except (KeyError, IndexError, ValueError):
                return Resolution.MISMATCH
            return Resolution.RESOLVED if canonical_sha256(value) == digest else Resolution.MISMATCH

        number = provenance["line"]
        lines = self._transcript_lines(provenance["file"], [number])
        if lines is None:
            return Resolution.MISSING_SOURCE
        line = lines.get(number)
        if line is None:
            return Resolution.MISMATCH
        return Resolution.RESOLVED if sha256_text(line) == digest else Resolution.MISMATCH

    def resolve_all(self, rows: Sequence[Mapping[str, Any]]) -> list[Resolution]:
        # Warm the per-file line caches in one streaming pass each, so a file is
        # opened once no matter how many rows cite it.
        wanted: dict[str, list[int]] = defaultdict(list)
        for row in rows:
            provenance = row.get("provenance")
            if isinstance(provenance, dict) and provenance.get("kind") == "transcript_line":
                name, number = provenance.get("file"), provenance.get("line")
                if isinstance(name, str) and isinstance(number, int):
                    wanted[name].append(number)
        for name, numbers in wanted.items():
            self._transcript_lines(name, numbers)
        return [self.resolve(row.get("provenance") or {}) for row in rows]


# --------------------------------------------------------------------------- #
# checkers — each is used by a test AND fed a planted lie by that same test
# --------------------------------------------------------------------------- #


def label_errors(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Label/rule agreement. A positive carrying a negative rule is the failure to catch."""
    problems: list[str] = []
    for row in rows:
        rid = row.get("record_id", "<no record_id>")
        label = row.get("label")
        rule = row.get("derivation_rule")
        if rule not in DERIVATION_RULES:
            problems.append(f"{rid}: unknown derivation_rule {rule!r}")
            continue
        if label is None:
            if rule != POSITIVE_DERIVATION_RULE:
                problems.append(f"{rid}: unlabelled row carries negative rule {rule!r}")
        elif label not in NEGATIVE_LABELS:
            problems.append(f"{rid}: unknown label {label!r}")
        elif LABEL_RULES[label] != rule:
            problems.append(f"{rid}: label {label!r} does not match rule {rule!r}")
    return problems


def reconciliation_errors(
    rows: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]
) -> list[str]:
    """The manifest's counts must be recomputable from the rows, not merely asserted."""
    problems: list[str] = []
    entries = manifest.get("reconciliation")
    if not isinstance(entries, list):
        return ["manifest has no reconciliation list"]

    reported = {e.get("population") for e in entries}
    for population in PRIOR_MEASUREMENTS:
        if population not in reported:
            problems.append(f"{population}: absent from the reconciliation")

    actual_total: dict[str, int] = defaultdict(int)
    actual_negative: dict[str, int] = defaultdict(int)
    for row in rows:
        population = row.get("population")
        actual_total[population] += 1
        if row.get("label") is not None:
            actual_negative[population] += 1

    for entry in entries:
        population = entry.get("population")
        if population not in PRIOR_MEASUREMENTS:
            problems.append(f"{population!r}: not one of the seven prior measurements")
            continue
        if entry.get("derived_total") != actual_total[population]:
            problems.append(
                f"{population}: derived_total {entry.get('derived_total')} "
                f"!= {actual_total[population]} rows"
            )
        if entry.get("derived_negative") != actual_negative[population]:
            problems.append(
                f"{population}: derived_negative {entry.get('derived_negative')} "
                f"!= {actual_negative[population]} labelled rows"
            )
        prior = PRIOR_MEASUREMENTS[population]
        reproduced = (
            entry.get("derived_negative") == prior.negative
            and entry.get("derived_total") == prior.total
        )
        if entry.get("reproduced") is not reproduced:
            problems.append(f"{population}: reproduced flag disagrees with the counts")
        if not reproduced and not str(entry.get("explanation", "")).strip():
            problems.append(f"{population}: differs from the prior measurement with no explanation")
    return problems


def split_errors(rows: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]) -> list[str]:
    """Temporal split: every train row strictly precedes every holdout row."""
    problems: list[str] = []
    split_meta = manifest.get("split") or {}
    boundary = split_meta.get("boundary")
    if split_meta.get("strategy") != "temporal":
        problems.append("split.strategy is not 'temporal'")
    if not isinstance(boundary, str) or not boundary:
        return problems + ["split.boundary is missing"]

    train: list[str] = []
    holdout: list[str] = []
    for row in rows:
        value = row.get("split")
        timestamp = row.get("timestamp")
        if value not in SPLITS:
            problems.append(f"{row.get('record_id')}: split {value!r} is not train/holdout")
            continue
        if not isinstance(timestamp, str) or not timestamp:
            problems.append(f"{row.get('record_id')}: no timestamp, so it cannot be split in time")
            continue
        (train if value == "train" else holdout).append(timestamp)

    if not train or not holdout:
        problems.append("the split has an empty side")
        return problems
    if max(train) >= boundary:
        problems.append(f"a train row at {max(train)} is at or past the boundary {boundary}")
    if min(holdout) < boundary:
        problems.append(f"a holdout row at {min(holdout)} predates the boundary {boundary}")
    if max(train) >= min(holdout):
        problems.append("train and holdout overlap in time — the split is not temporal")
    return problems


def assign_temporal_split(rows: Sequence[dict[str, Any]], holdout_fraction: float = 0.2) -> str:
    """Stamp ``split`` on every row and return the boundary timestamp.

    Ties are never straddled: every row sharing the boundary timestamp lands in
    holdout, so a gate tuned on train has seen nothing from the boundary instant
    onwards. Sorting is by (timestamp, record_id) so the boundary is deterministic.
    """
    ordered = sorted(rows, key=lambda r: (r["timestamp"], r["record_id"]))
    index = max(1, min(len(ordered) - 1, int(round(len(ordered) * (1.0 - holdout_fraction)))))
    boundary = ordered[index]["timestamp"]
    # Walk back over any tie so the boundary instant belongs wholly to holdout.
    while index > 1 and ordered[index - 1]["timestamp"] == boundary:
        index -= 1
    for position, row in enumerate(ordered):
        row["split"] = "train" if position < index else "holdout"
    return boundary
