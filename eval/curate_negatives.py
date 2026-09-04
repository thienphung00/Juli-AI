"""#1456 (HE-C/P-EVAL-14) — derive labelled negatives from the caches that already exist.

The corpus grades this harness on 290 status records of which four ever failed
validation.  Nothing else in it is labelled bad, so sensitivity has had no
denominator to be measured against.  The negatives were never missing — they were
never *adjudicated*.  Seven mechanical rules read the three caches we already
keep and label at record level:

===========================  ==================================================
population                    the rule that labels it
===========================  ==================================================
subagent_success_claims       a completed task-notification claiming success,
                              contradicted by the parent within 5 replies
artifact_refs                 an ``artifactRef`` naming a path in no commit on
                              any branch
pytest_invocations            a pytest run narrower than the one CI runs
gate_result_claims            a PASS/FAIL claim about a checkable command with
                              no invocation of it in the prior 40 events
review_validation_pairs       review PASS recorded over validation FAIL
fix_commits                   a ``fix:`` commit naming an issue an earlier
                              commit already named
validation_outcomes           validation status FAIL
===========================  ==================================================

Three things this module is careful about.

**Provenance, not assertion.** Every row cites the transcript file and line, the
status record and JSON pointer, or the commit — with a SHA-256 of the bytes read.
A label is disputed by re-running its derivation, never by argument.

**The positive class stays.** Each population keeps the members no rule labelled.
#1457 measured the false-positive floor at 0 against a clean arm; without the
same denominator here there is nothing to compare that against.

**The prior counts are inputs.** The seven numbers in issue #1456 came from an
earlier analysis whose regexes were not recorded. Where this derivation lands
elsewhere the manifest carries the difference and its cause — see
``eval/datasets/negative_dataset.manifest.json``. Reconciling a divergence away
would destroy the only evidence that the two derivations differ.

Run it with ``python -m eval.curate_negatives``. It reads ~241 MB of transcript
cache, so it runs on a developer machine and commits its output; the tests read
that output. Stdlib only — CI installs ``./backend[dev] -c backend/constraints.txt``
and nothing more.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from eval.negative_dataset import (
    DEFAULT_TRANSCRIPT_ROOT,
    LABEL_RULES,
    POSITIVE_DERIVATION_RULE,
    PRIOR_MEASUREMENTS,
    REPO_ROOT,
    assign_temporal_split,
    canonical_sha256,
    sha256_text,
    write_dataset,
)

STATUS_DIR = REPO_ROOT / "agent-runtime" / "artifacts" / "status"
VALIDATE_GATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"

EXCERPT_LIMIT = 200

# --------------------------------------------------------------------------- #
# rule 3 — pytest scope
# --------------------------------------------------------------------------- #

#: What CI actually runs: `pytest tests/` over the whole tree
#: (.github/workflows/release.yml:85, .github/workflows/pr.yml:460). An agent run
#: that names anything narrower has tested less than the oracle will.
CI_EQUIVALENT_TARGETS = frozenset({"tests", "tests/", "./tests", "./tests/"})

#: `python [-flags] -m pytest`, or a bare `pytest` at the head of a command
#: segment. The lazy `[^\s;&|]+` run is what lets `python -X faulthandler -m
#: pytest` match without swallowing a following `&& pytest`.
PYTEST_INVOCATION = re.compile(
    r"(?:(?<![\w./-])python[0-9.]*[ \t]+(?:[^\s;&|]+[ \t]+)*?-m[ \t]+pytest\b)"
    r"|(?:(?:^|[;&|(]|\n)[ \t]*(?:timeout[ \t]+\S+[ \t]+)?pytest\b)"
)

#: Options that take a separate value, skipped with their argument so the value
#: is never mistaken for a test path. `-m` is a marker selector and is treated as
#: neutral: CI uses markers too (`-m "not live"`), so a marker alone is not narrower.
_PYTEST_VALUE_OPTIONS = frozenset(
    {"-m", "--tb", "-p", "-n", "--maxfail", "--timeout", "-o", "--deselect", "--ignore", "-c"}
)
_SHELL_BREAKS = frozenset({"|", "||", "&&", ";", ">", ">>", "2>&1", "<"})


def find_pytest_invocations(command: str) -> list[str]:
    """Return the argument tail of each pytest invocation in a shell command."""
    return [command[match.end() :] for match in PYTEST_INVOCATION.finditer(command)]


def pytest_scope_is_narrower(tail: str) -> bool:
    """True when this invocation selects less than CI's `pytest tests/`."""
    segment = tail.split("\n", 1)[0]
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()

    positional: list[str] = []
    selector = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _SHELL_BREAKS:
            break
        if token == "-k":
            selector = True
            index += 2
            continue
        if token.startswith("-k") and len(token) > 2:
            selector = True
            index += 1
            continue
        if token in _PYTEST_VALUE_OPTIONS:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        positional.append(token)
        index += 1

    if selector:
        return True
    if not positional:
        # Bare `pytest` runs pytest.ini's testpaths = tests, i.e. exactly CI's scope.
        return False
    return not set(positional) <= CI_EQUIVALENT_TARGETS


def classify_pytest_invocation(command: str) -> str | None:
    """Label a shell command that runs pytest, or None when its scope matches CI's."""
    tails = find_pytest_invocations(command)
    if not tails:
        return None
    if any(pytest_scope_is_narrower(tail) for tail in tails):
        return "scope_overstated"
    return None


# --------------------------------------------------------------------------- #
# rule 2 — artifactRef retrievability
# --------------------------------------------------------------------------- #


def artifact_ref_path(ref: str) -> str:
    """Strip the `git-history:` scheme prefix an artifactRef carries."""
    return ref.split(":", 1)[1] if ":" in ref else ref


def classify_artifact_ref(ref: str, known_paths: Iterable[str]) -> str | None:
    """Label an artifactRef whose path appears in no commit on any branch."""
    paths = known_paths if isinstance(known_paths, (set, frozenset)) else set(known_paths)
    return None if artifact_ref_path(ref) in paths else "evidence_unretrievable"


# --------------------------------------------------------------------------- #
# rules 5 and 7 — status record verdicts
# --------------------------------------------------------------------------- #


def classify_status_record_validation(record: Mapping[str, Any]) -> str | None:
    """Label a status record whose validation gate returned FAIL."""
    status = (record.get("validation") or {}).get("status")
    return "true_negative" if status == "FAIL" else None


def classify_review_validation_pair(record: Mapping[str, Any]) -> str | None:
    """Label a record carrying a review PASS over a validation FAIL for the same issue."""
    review = (record.get("review") or {}).get("status")
    validation = (record.get("validation") or {}).get("status")
    return "verdict_contradiction" if review == "PASS" and validation == "FAIL" else None


# --------------------------------------------------------------------------- #
# rule 6 — rework signal in git
# --------------------------------------------------------------------------- #

FIX_SUBJECT = re.compile(r"^fix(\([^)]*\))?!?:")
#: The trailing `(#N)` is the squash-merge PR number, not an issue the fix names.
#: Counting it would mark every conventional fix commit as rework.
TRAILING_PR_REF = re.compile(r"\s*\(#\d+\)\s*$")
ISSUE_REF = re.compile(r"#(\d+)")


def classify_fix_commit(subject: str, seen_issues: Iterable[int]) -> str | None:
    """Label a `fix:` commit naming an issue some earlier commit already named."""
    if not FIX_SUBJECT.match(subject):
        return None
    named = {int(n) for n in ISSUE_REF.findall(TRAILING_PR_REF.sub("", subject))}
    earlier = seen_issues if isinstance(seen_issues, (set, frozenset)) else set(seen_issues)
    return "rework_signal" if named & earlier else None


# --------------------------------------------------------------------------- #
# rules 1 and 4 — transcript claims
# --------------------------------------------------------------------------- #

TASK_NOTIFICATION = re.compile(r"<task-notification>.*?</task-notification>", re.S)
COMPLETED_STATUS = "<status>completed</status>"

SUCCESS_CLAIM = re.compile(
    r"(?i)(all (?:tests|checks|gates) (?:pass|passing|passed|green)"
    r"|tests? pass(?:ing|ed|es)?|exit code:? 0|\bPASS\b|✅|\bgreen\b"
    r"|\bcomplete[d]?\b|\bsuccess(?:ful|fully)?\b|\bdone\b)"
)

#: Deliberately excludes a bare "fails"/"failing": a parent narrating a red TDD
#: phase is not contradicting its subagent, and including it inflated the count
#: from 94 to 140 against a prior measurement of 88.
CONTRADICTION = re.compile(
    r"(?i)(\bdid ?n[o']?t\b|\bdoes ?n[o']?t\b|\bwas ?n[o']?t\b|\bis ?n[o']?t\b"
    r"|never (?:ran|existed|committed|happened)|\bno such\b|\bnot true\b|\bincorrect\b"
    r"|\bwrong\b|\bfalse\b|still fail|actually fail|does not exist|\bno commit\b"
    r"|contradict|overstat|\bvacuous\b|fake green|\bunverified\b)"
)

CONTRADICTION_WINDOW_REPLIES = 5
GATE_CLAIM_WINDOW_EVENTS = 40

VERDICT = re.compile(
    r"(?i)(\bPASS(?:ED|ES|ING)?\b|\bFAIL(?:ED|S|ING)?\b|\bgreen\b|\bclean\b"
    r"|exit code:? *[0-9]|✅|❌|\ball .{0,20}pass)"
)


def checkable_command_families(gate_dir: Path = VALIDATE_GATE_DIR) -> dict[str, re.Pattern[str]]:
    """Commands whose result an agent can claim and a transcript can corroborate.

    The 29 `agent-runtime/scripts/validate/` gates plus the five lint/test commands
    CI runs. The prior measurement's family list was not recorded, which is why the
    population size here differs from its 239 — see the manifest.
    """
    families: dict[str, re.Pattern[str]] = {
        "pytest": re.compile(r"\bpytest\b", re.I),
        "ruff": re.compile(r"\bruff\b", re.I),
        "mypy": re.compile(r"\bmypy\b", re.I),
        "pre-commit": re.compile(r"\bpre-commit\b", re.I),
        "import-linter": re.compile(r"\b(?:import-linter|lint-imports)\b", re.I),
    }
    for path in sorted(gate_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        families[path.stem] = re.compile(r"\b" + re.escape(path.stem) + r"\b", re.I)
    return families


# --------------------------------------------------------------------------- #
# transcript reading
# --------------------------------------------------------------------------- #


def _content_blocks(event: Mapping[str, Any]) -> list[dict[str, Any]]:
    message = event.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def _texts(event: Mapping[str, Any]) -> list[str]:
    return [
        block.get("text", "")
        for block in _content_blocks(event)
        if block.get("type") == "text" and isinstance(block.get("text"), str)
    ]


def _bash_commands(event: Mapping[str, Any]) -> list[str]:
    commands = []
    for block in _content_blocks(event):
        if block.get("type") == "tool_use" and block.get("name") == "Bash":
            command = (block.get("input") or {}).get("command")
            if isinstance(command, str):
                commands.append(command)
    return commands


def normalise_timestamp(raw: str | None) -> str | None:
    """UTC, second precision, `Z` suffix — so timestamps sort lexicographically."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_transcript(path: Path) -> list[dict[str, Any]]:
    """One streaming pass per transcript, keeping only what the rules need.

    The full parsed objects are dropped as we go: the cache is ~241 MB and holding
    it would cost well over a gigabyte for no benefit.
    """
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            stripped = line.rstrip("\n")
            if not stripped.strip():
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            events.append(
                {
                    "line": number,
                    "sha256": sha256_text(stripped),
                    "type": event.get("type"),
                    "timestamp": normalise_timestamp(event.get("timestamp")),
                    "texts": _texts(event),
                    "bash": _bash_commands(event),
                }
            )
    return events


def _excerpt(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:EXCERPT_LIMIT]


def _last_known_timestamp(events: Sequence[Mapping[str, Any]], index: int) -> str | None:
    """Nearest preceding timestamp — a handful of cache event kinds carry none."""
    for position in range(index, -1, -1):
        stamp = events[position].get("timestamp")
        if stamp:
            return stamp
    return None


# --------------------------------------------------------------------------- #
# row construction
# --------------------------------------------------------------------------- #


def _row(
    population: str,
    label: str | None,
    source: str,
    provenance: dict[str, Any],
    timestamp: str,
    evidence: str,
    discriminator: str,
) -> dict[str, Any]:
    rule = LABEL_RULES[label] if label else POSITIVE_DERIVATION_RULE
    identity = canonical_sha256([population, provenance, discriminator])[:16]
    return {
        "record_id": f"{population}/{identity}",
        "population": population,
        "label": label,
        "source": source,
        "provenance": provenance,
        "derivation_rule": rule,
        "timestamp": timestamp,
        "evidence": evidence,
    }


def derive_transcript_rows(
    transcript_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Rules 1, 3 and 4, all three of which need the same streaming pass."""
    claims: list[dict[str, Any]] = []
    pytest_rows: list[dict[str, Any]] = []
    gate_rows: list[dict[str, Any]] = []
    families = checkable_command_families()

    for path in sorted(transcript_root.glob("*.jsonl")):
        events = read_transcript(path)
        name = path.name

        for index, event in enumerate(events):
            timestamp = event["timestamp"] or _last_known_timestamp(events, index)
            if not timestamp:
                continue
            provenance = {
                "kind": "transcript_line",
                "file": name,
                "line": event["line"],
                "sha256": event["sha256"],
            }

            # -- rule 1: subagent success claim vs the parent's next 5 replies --
            if event["type"] == "user":
                for text in event["texts"]:
                    for ordinal, block in enumerate(TASK_NOTIFICATION.findall(text)):
                        if COMPLETED_STATUS not in block or not SUCCESS_CLAIM.search(block):
                            continue
                        contradicted = False
                        replies = 0
                        for later in events[index + 1 :]:
                            if later["type"] != "assistant":
                                continue
                            replies += 1
                            if replies > CONTRADICTION_WINDOW_REPLIES:
                                break
                            if any(CONTRADICTION.search(t) for t in later["texts"]):
                                contradicted = True
                                break
                        claims.append(
                            _row(
                                "subagent_success_claims",
                                "claim_false" if contradicted else None,
                                "transcript_cache",
                                provenance,
                                timestamp,
                                _excerpt(block),
                                f"notification:{ordinal}",
                            )
                        )

            # -- rule 3: pytest scope --------------------------------------
            for command_ordinal, command in enumerate(event["bash"]):
                for tail_ordinal, tail in enumerate(find_pytest_invocations(command)):
                    narrower = pytest_scope_is_narrower(tail)
                    pytest_rows.append(
                        _row(
                            "pytest_invocations",
                            "scope_overstated" if narrower else None,
                            "transcript_cache",
                            provenance,
                            timestamp,
                            _excerpt(command),
                            f"pytest:{command_ordinal}:{tail_ordinal}",
                        )
                    )

            # -- rule 4: a verdict claimed with no run behind it -------------
            if event["type"] != "assistant":
                continue
            window = events[max(0, index - GATE_CLAIM_WINDOW_EVENTS) : index]
            for text in event["texts"]:
                for line_ordinal, text_line in enumerate(text.splitlines()):
                    if not VERDICT.search(text_line):
                        continue
                    for family, pattern in families.items():
                        if not pattern.search(text_line):
                            continue
                        backed = any(
                            pattern.search(command)
                            for earlier in window
                            for command in earlier["bash"]
                        )
                        gate_rows.append(
                            _row(
                                "gate_result_claims",
                                None if backed else "unbacked_claim",
                                "transcript_cache",
                                provenance,
                                timestamp,
                                _excerpt(text_line),
                                f"claim:{line_ordinal}:{family}",
                            )
                        )

    return claims, pytest_rows, gate_rows


def paths_in_any_commit(repo_root: Path = REPO_ROOT) -> set[str]:
    """Every path named by any commit on any branch — the retrievability oracle."""
    result = subprocess.run(
        ["git", "log", "--all", "--pretty=format:", "--name-only"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _status_records(status_dir: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    for path in sorted(status_dir.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(document, dict):
            yield path.relative_to(REPO_ROOT).as_posix(), document


def derive_status_rows(
    status_dir: Path = STATUS_DIR,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Rules 2, 5 and 7, all over `agent-runtime/artifacts/status/`."""
    known = paths_in_any_commit()
    refs: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []

    for relative, record in _status_records(status_dir):
        timestamp = normalise_timestamp(record.get("timestamp"))
        if not timestamp:
            continue

        for section in ("review", "validation"):
            ref = (record.get(section) or {}).get("artifactRef")
            if not isinstance(ref, str) or not ref:
                continue
            refs.append(
                _row(
                    "artifact_refs",
                    classify_artifact_ref(ref, known),
                    "status_records",
                    {
                        "kind": "status_record",
                        "file": relative,
                        "pointer": f"/{section}/artifactRef",
                        "sha256": canonical_sha256(ref),
                    },
                    timestamp,
                    _excerpt(ref),
                    f"ref:{section}",
                )
            )

        review = (record.get("review") or {}).get("status")
        validation = (record.get("validation") or {}).get("status")

        if isinstance(review, str) and isinstance(validation, str):
            pairs.append(
                _row(
                    "review_validation_pairs",
                    classify_review_validation_pair(record),
                    "status_records",
                    {
                        "kind": "status_record",
                        "file": relative,
                        # The contradiction is a property of the whole record, so
                        # the whole record is what the digest covers.
                        "pointer": "/",
                        "sha256": canonical_sha256(record),
                    },
                    timestamp,
                    f"review={review} validation={validation}",
                    "pair",
                )
            )

        if isinstance(validation, str):
            outcomes.append(
                _row(
                    "validation_outcomes",
                    classify_status_record_validation(record),
                    "status_records",
                    {
                        "kind": "status_record",
                        "file": relative,
                        "pointer": "/validation/status",
                        "sha256": canonical_sha256(validation),
                    },
                    timestamp,
                    f"validation={validation}",
                    "validation",
                )
            )

    return refs, pairs, outcomes


#: Rule 6 walks the trunk, not `--all`, and that is a deliberate narrowing.
#: `--all` finds 226 fix commits here against the prior measurement's 229, but 101
#: of them live on branches that were squash-merged or never merged, so their SHAs
#: exist in one clone on one machine and nowhere else. A provenance row nobody
#: else can resolve cannot be disputed by re-running its derivation, which is the
#: whole point of the slice; it also made the count drift run to run as a
#: concurrent worktree committed.
#:
#: This was `HEAD` until #1579, which is narrow enough to exclude other people's
#: branches but not narrow enough to exclude *this* one: curating on a feature
#: branch put two of its own pre-squash tips into the dataset, and the squash-merge
#: then dissolved them, leaving rows nobody but that clone can resolve. A trunk ref
#: cannot do that — a commit reachable from the trunk survives every later
#: squash-merge, because a squashed commit is what the trunk is made of.
FIX_COMMIT_TRUNK_REFS = ("origin/main", "main")
FIX_COMMIT_REF_SCOPE = FIX_COMMIT_TRUNK_REFS[0]


def resolve_fix_commit_scope(repo_root: Path = REPO_ROOT) -> str:
    """The first trunk ref this checkout actually has, or a hard failure.

    There is deliberately no fallback to `HEAD`: a silent one would reinstate
    exactly the scope #1579 removed, and would do it precisely on the machines
    least likely to notice. A clone that cannot name the trunk cannot curate a
    durable citation, and saying so is the honest outcome.
    """
    for ref in FIX_COMMIT_TRUNK_REFS:
        probe = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode == 0 and probe.stdout.strip():
            return ref
    raise RuntimeError(
        "cannot pin fix-commit curation: none of "
        f"{', '.join(FIX_COMMIT_TRUNK_REFS)} resolves in {repo_root}. "
        "Fetch the trunk before curating; HEAD is not an acceptable substitute (#1579)."
    )


def derive_fix_commit_rows(repo_root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    """Rule 6 — a `fix:` commit naming an issue an earlier commit already named."""
    result = subprocess.run(
        ["git", "log", resolve_fix_commit_scope(repo_root), "--pretty=%H%x1f%aI%x1f%s"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    commits = []
    for line in result.stdout.splitlines():
        if line.count("\x1f") == 2:
            sha, authored, subject = line.split("\x1f")
            commits.append((sha, authored, subject))
    commits.sort(key=lambda item: item[1])

    seen: set[int] = set()
    rows: list[dict[str, Any]] = []
    for sha, authored, subject in commits:
        if FIX_SUBJECT.match(subject):
            timestamp = normalise_timestamp(authored)
            if timestamp:
                rows.append(
                    _row(
                        "fix_commits",
                        classify_fix_commit(subject, seen),
                        "git_log",
                        {
                            "kind": "git_commit",
                            "commit": sha,
                            "sha256": sha256_text(subject),
                        },
                        timestamp,
                        _excerpt(subject),
                        "fix",
                    )
                )
        # A commit's own refs only count as "earlier" for commits after it.
        seen |= {int(n) for n in ISSUE_REF.findall(subject)}
    return rows


# --------------------------------------------------------------------------- #
# reconciliation
# --------------------------------------------------------------------------- #

#: Why this derivation can legitimately land somewhere other than the prior
#: measurement. Stated per population, and only ever combined with the real
#: numbers below — never used to explain a difference away.
DIVERGENCE_CAUSES: dict[str, str] = {
    "subagent_success_claims": (
        "The prior measurement's success-claim and contradiction regexes were not recorded, so "
        "both are reconstructions here; the contradiction pattern deliberately excludes a bare "
        "'fails'/'failing', which a parent narrating a red TDD phase emits without contradicting "
        "anything (including it moved this count from 94 to 140)"
    ),
    "artifact_refs": (
        "The status corpus has grown since the prior measurement, and the artifact body "
        "directories are gitignored, so every ref added since is dangling by construction rather "
        "than by defect"
    ),
    "pytest_invocations": (
        "The unit differs. This population is one row per *invocation*, and 76 shell commands "
        "chain two to five pytest runs in one call; counting commands instead gives 549, which is "
        "within 8 of the prior 541 and strongly suggests the prior measurement counted commands. "
        "One row per invocation is the correct unit here because a chained command whose first run "
        "is broad and whose second is narrow cannot honestly be a single labelled record. The "
        "prior detection regex was also not recorded; this one counts `python [-flags] -m pytest` "
        "and a bare `pytest` at the head of a command segment, never crossing a newline, includes "
        "--collect-only runs, and treats a marker selector as neutral because CI uses markers too"
    ),
    "gate_result_claims": (
        "The prior measurement's list of checkable command families was not recorded; this one is "
        "the 29 agent-runtime/scripts/validate gates plus pytest, ruff, mypy, pre-commit and "
        "import-linter, which is very likely a narrower list than the original used"
    ),
    "review_validation_pairs": (
        "The prior denominator was 'surviving pairs' — the review/validation artifact bodies still "
        "on disk, of which only about 15 exist. This population is instead every status record "
        "carrying both verdicts, which is the larger and more durable denominator"
    ),
    "fix_commits": (
        "The ref scope is narrower on purpose, and the gap is the finding. `git log --all` "
        "reproduces the prior population closely — 226 fix commits against 229, 50 labelled "
        "against 46 — but 101 of those 226 cite SHAs reachable from no ref this repository will "
        "keep: squash-merged or abandoned feature branches whose commits exist in one clone on one "
        "machine. Two runs minutes apart disagreed as a concurrent worktree committed, so `--all` "
        "is not even deterministic here. Restricting to HEAD leaves 10/125. The 40 negatives that "
        "difference removes are the substantive result: most of the apparent rework signal lived "
        "on branches that no longer exist, so the prior 46/229 was measured over a ref set nobody "
        "can reconstruct. The trailing `(#N)` squash-merge PR reference is separately excluded "
        "from 'names an earlier issue', since counting it would mark nearly every conventional fix "
        "commit as rework"
    ),
    "validation_outcomes": (
        "The status corpus has grown since the prior measurement, so the denominator moved while "
        "the FAIL count did not"
    ),
}


def build_reconciliation(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[str, int] = defaultdict(int)
    negatives: dict[str, int] = defaultdict(int)
    for row in rows:
        totals[row["population"]] += 1
        if row["label"] is not None:
            negatives[row["population"]] += 1

    entries = []
    for population, prior in PRIOR_MEASUREMENTS.items():
        derived_negative = negatives[population]
        derived_total = totals[population]
        reproduced = derived_negative == prior.negative and derived_total == prior.total
        explanation = ""
        if not reproduced:
            explanation = (
                f"{DIVERGENCE_CAUSES[population]}. Derived {derived_negative}/{derived_total}; "
                f"prior reported {prior.negative}/{prior.total} "
                f"({derived_negative - prior.negative:+d} negatives, "
                f"{derived_total - prior.total:+d} population)."
            )
        entries.append(
            {
                "population": population,
                "label": prior.label,
                "description": prior.description,
                "derivation_rule": LABEL_RULES[prior.label],
                "prior_reported_negative": prior.negative,
                "prior_reported_total": prior.total,
                "derived_negative": derived_negative,
                "derived_total": derived_total,
                "reproduced": reproduced,
                "explanation": explanation,
            }
        )
    return entries


def curate(
    transcript_root: Path = DEFAULT_TRANSCRIPT_ROOT,
    holdout_fraction: float = 0.2,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    claims, pytest_rows, gate_rows = derive_transcript_rows(transcript_root)
    refs, pairs, outcomes = derive_status_rows()
    fixes = derive_fix_commit_rows()

    rows = claims + pytest_rows + gate_rows + refs + pairs + outcomes + fixes
    rows.sort(key=lambda row: (row["timestamp"], row["record_id"]))
    boundary = assign_temporal_split(rows, holdout_fraction=holdout_fraction)

    manifest = {
        "issue": 1456,
        "generator": "python -m eval.curate_negatives",
        "generated_from": {
            "transcript_root": str(transcript_root),
            "transcripts": len(sorted(transcript_root.glob("*.jsonl"))),
            "status_records": len(sorted(STATUS_DIR.glob("*.json"))),
            "repo_root": str(REPO_ROOT),
            # The ref actually walked, not the preferred one: a manifest that
            # names a scope the run did not use cannot be re-derived from.
            "fix_commit_ref_scope": resolve_fix_commit_scope(REPO_ROOT),
            "artifact_ref_oracle_scope": "--all",
            "scope_note": (
                "Commit provenance is drawn from the trunk so every cited SHA is durable and "
                "shared. It was HEAD until #1579, under which curating on a feature branch cited "
                "two of that branch's own pre-squash tips; the squash-merge then dissolved them. "
                "The artifactRef retrievability oracle deliberately uses --all instead: it is a "
                "set-membership test rather than a citation, and --all is the widest, most "
                "generous scope, so a ref dangling under it is dangling everywhere."
            ),
        },
        "rows": len(rows),
        "negatives": sum(1 for row in rows if row["label"] is not None),
        "positives": sum(1 for row in rows if row["label"] is None),
        "split": {
            "strategy": "temporal",
            "boundary": boundary,
            "holdout_fraction": holdout_fraction,
            "rationale": (
                "Rows are ordered by wall-clock time and cut once. Every train row strictly "
                "precedes every holdout row, so a gate tuned on train has seen nothing from the "
                "boundary instant onward. A random split would leak the future into training."
            ),
            "train": sum(1 for row in rows if row["split"] == "train"),
            "holdout": sum(1 for row in rows if row["split"] == "holdout"),
        },
        "reconciliation": build_reconciliation(rows),
    }
    return rows, manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--transcript-root", type=Path, default=DEFAULT_TRANSCRIPT_ROOT)
    parser.add_argument("--holdout-fraction", type=float, default=0.2)
    args = parser.parse_args(argv)

    if not args.transcript_root.exists():
        parser.error(f"transcript cache not found at {args.transcript_root}")

    rows, manifest = curate(args.transcript_root, args.holdout_fraction)
    write_dataset(rows, manifest)

    print(
        f"rows={manifest['rows']} negatives={manifest['negatives']} positives={manifest['positives']}"
    )
    print(
        f"split boundary={manifest['split']['boundary']} "
        f"train={manifest['split']['train']} holdout={manifest['split']['holdout']}"
    )
    print()
    print(f"{'population':<26} {'derived':>12} {'prior':>12}  reproduced")
    for entry in manifest["reconciliation"]:
        derived = f"{entry['derived_negative']}/{entry['derived_total']}"
        prior = f"{entry['prior_reported_negative']}/{entry['prior_reported_total']}"
        print(f"{entry['population']:<26} {derived:>12} {prior:>12}  {entry['reproduced']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
