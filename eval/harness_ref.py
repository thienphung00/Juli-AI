"""Resolve the replay harness from a protected ref the PR cannot edit (#1459).

Moving gate execution into CI accomplishes nothing if the gate source travels
with the branch under test: the PR would grade itself with its own copy of the
grader. This module draws the boundary. The harness -- replay code, canary
records, mutant corpus, measurement code -- resolves from ``HARNESS_REF``, the
resolved sha is recorded in the run record, and a PR whose diff touches the
harness path is refused before any evaluation runs.

The exit-code split
-------------------
Three values, never collapsed:

``0`` :data:`EXIT_OK`
    The harness was valid and the change under test passed.
``1`` :data:`EXIT_CHANGE_BAD`
    The harness was valid and the change under test is bad. This is a verdict.
``2`` :data:`EXIT_HARNESS_INVALID`
    No verdict was reached, because the grader could not be trusted: the PR
    edited it, ``HARNESS_REF`` did not resolve, the diff could not be computed,
    a canary passed, or the evaluation could not be launched.

Collapsing ``2`` into ``1`` recreates the original defect, where "the check
could not run" and "the work is bad" were indistinguishable -- and it does so in
the direction that hurts: a compromised harness would be reported as a bad PR,
and a *passing* compromised harness as a good one.

Fail closed, never fall back
----------------------------
Every unresolvable condition fails. The tempting behaviour -- "the protected ref
is unavailable, so use the copy that is already checked out" -- is the entire
vulnerability, because the copy on disk is the PR's copy. An unset
``HARNESS_REF`` is treated the same way: absence of configuration is the most
likely route by which this protection would quietly be lost, so it is not read
as permission to skip it.

Shallow checkouts
-----------------
``pr.yml`` checks this repo out shallow for most jobs, so the protected ref is
routinely *not* present locally and ``base...head`` is routinely unreachable.
That is detected explicitly rather than assumed away: the resolver can fetch the
ref on demand (``--allow-fetch``, the default), and when it still cannot resolve,
it fails with exit 2 and names shallowness in the reason so the remedy is
actionable.

Note the deliberate difference from ``agent-runtime/scripts/ci/artifact_ref_resolution``,
which answers INDETERMINATE under shallowness. There the question is "does this
path exist in history anywhere", and a truncated history genuinely cannot say.
Here the question is "can I grade with the protected harness *in this checkout*",
and under shallowness the honest answer is a definite no. Deferring would mean
grading with the branch copy, which is the one outcome this module exists to
prevent.

Stdlib only, like the rest of the harness.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

#: The environment variable naming the protected ref.
HARNESS_REF_ENV = "HARNESS_REF"

#: Repo-relative directory prefixes that constitute the harness. Everything the
#: evaluation uses to reach a verdict lives here: ``gate_scoring`` (measurement),
#: ``artifact_mutants`` and ``datasets``/``fixtures`` (the mutant corpus and
#: canary records), ``ratchets`` and ``baselines`` (the thresholds a verdict is
#: read against). A PR may not change any of it, because a PR that can change how
#: it is measured is not being measured.
#:
#: Scoped to ``eval/`` on purpose. ``agent-runtime/scripts/validate/`` holds the
#: gates that are *scored by* this harness, not the harness itself; freezing them
#: here would block the ordinary gate work this measurement exists to inform.
HARNESS_PATHS: tuple[str, ...] = ("eval/",)

# -- statuses ---------------------------------------------------------------

#: The ref resolved to a commit that carries the harness, and the PR left it alone.
RESOLVED = "RESOLVED"
#: No ref was configured. Fail closed: unconfigured is not unprotected.
UNSET = "UNSET"
#: The ref names nothing this checkout can reach, even after a fetch attempt.
UNRESOLVABLE = "UNRESOLVABLE"
#: The ref resolved, but no harness exists at that commit -- so "resolved" would
#: be a claim about a grader that is not there.
HARNESS_ABSENT = "HARNESS_ABSENT"
#: The PR's diff touches the harness path.
HARNESS_MODIFIED = "HARNESS_MODIFIED"
#: The diff could not be computed, so the harness cannot be shown untouched.
DIFF_UNAVAILABLE = "DIFF_UNAVAILABLE"

#: Every status other than :data:`RESOLVED` means no verdict may be issued.
VALID_STATUSES = frozenset({RESOLVED})

# -- exit codes -------------------------------------------------------------

EXIT_OK = 0
EXIT_CHANGE_BAD = 1
EXIT_HARNESS_INVALID = 2


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    # Fixed argv, no shell: refs come from configuration, never interpolated.
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def is_shallow_repository(repo_root: Path) -> bool:
    """True when history before a graft point is absent from this checkout."""
    proc = _git(repo_root, "rev-parse", "--is-shallow-repository")
    if proc.returncode != 0:
        return False
    return proc.stdout.strip() == "true"


def _normalise(path: str) -> str:
    """Collapse a repo-relative path to the directory it actually denotes.

    Resolves ``.`` and ``..`` textually so the prefix test below answers about
    the path a diff entry *denotes*, never about how it is spelled. Two spellings
    would otherwise decide the guard wrongly in opposite directions:
    ``eval/../backend/x.py`` starts with ``eval/`` but is a backend file, and
    ``backend/../eval/gate_scoring.py`` does not start with ``eval/`` but is the
    grader. An absolute path is not repo-relative, so it is never a harness path.
    """
    raw = (path or "").strip()
    if not raw or raw.startswith("/"):
        return ""
    parts: list[str] = []
    for segment in raw.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if parts:
                parts.pop()
            continue
        parts.append(segment)
    return "/".join(parts)


def is_harness_path(path: str) -> bool:
    """True when ``path`` denotes a file inside the harness."""
    normalised = _normalise(path)
    if not normalised:
        return False
    return any(normalised.startswith(prefix) for prefix in HARNESS_PATHS)


def harness_paths_touched(paths: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """The subset of ``paths`` that lies inside the harness, as given.

    Returns the caller's original spelling, so a failure message points at the
    exact diff entry rather than at a normalised form the reader would then have
    to map back to the diff themselves.
    """
    return tuple(path for path in paths if is_harness_path(path))


@dataclass(frozen=True)
class HarnessResolution:
    """One harness, one verdict, one reason.

    ``sha`` is ``None`` for every status except :data:`RESOLVED` -- there is no
    partially-resolved harness, and a caller that reads ``sha`` without checking
    ``is_valid`` gets ``None`` rather than a plausible-looking wrong commit.
    """

    ref: str
    status: str
    detail: str
    sha: str | None = None
    shallow: bool = False
    touched_harness_paths: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return self.status in VALID_STATUSES

    @property
    def exit_code(self) -> int:
        return EXIT_OK if self.is_valid else EXIT_HARNESS_INVALID


def _shallow_note(shallow: bool) -> str:
    if not shallow:
        return ""
    return (
        " This is a shallow checkout (git rev-parse --is-shallow-repository is true), "
        "which is how pr.yml checks the repo out for most jobs, so the object may exist "
        "upstream and simply not have been fetched; deepen the checkout or fetch the ref "
        "explicitly. It is still a failure here rather than a deferral: grading would "
        "otherwise proceed against the branch's own copy of the harness, which is exactly "
        "what the protected ref exists to prevent."
    )


def _rev_parse(repo_root: Path, ref: str) -> str | None:
    proc = _git(repo_root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _try_fetch(repo_root: Path, ref: str) -> None:
    """Best-effort fetch of a protected ref missing from a shallow checkout.

    Failure is not raised: the caller re-resolves afterwards and fails closed on
    the result, so a fetch that cannot run degrades to the same honest refusal.
    """
    _git(repo_root, "fetch", "--quiet", "--depth", "1", "origin", ref)


def _harness_exists_at(repo_root: Path, sha: str) -> bool:
    """True when at least one guarded path exists at ``sha``."""
    for prefix in HARNESS_PATHS:
        probe = _git(repo_root, "cat-file", "-e", f"{sha}:{prefix.rstrip('/')}")
        if probe.returncode == 0:
            return True
    return False


def changed_paths(repo_root: Path, base: str, head: str) -> tuple[list[str] | None, str]:
    """Paths changed between ``base`` and ``head``, or ``None`` with a reason.

    ``None`` is returned when the diff genuinely could not be computed. It is
    never conflated with an empty diff: an empty result that was never computed
    is not evidence that the harness was left alone, and treating it as such
    would reopen the hole under exactly the shallow checkouts CI uses.
    """
    proc = _git(repo_root, "diff", "--name-only", f"{base}...{head}")
    if proc.returncode != 0:
        # `A...B` needs a merge base; a two-dot diff still gives a truthful
        # answer about the endpoints when history is truncated.
        proc = _git(repo_root, "diff", "--name-only", base, head)
    if proc.returncode != 0:
        return None, (proc.stderr.strip() or "git diff failed")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()], ""


def resolve_harness(
    ref: str,
    *,
    repo_root: Path,
    base: str,
    head: str,
    allow_fetch: bool = True,
) -> HarnessResolution:
    """Resolve the harness from ``ref`` and confirm the PR did not touch it."""
    repo_root = Path(repo_root)
    ref = (ref or "").strip()
    shallow = is_shallow_repository(repo_root)

    if not ref:
        return HarnessResolution(
            ref="",
            status=UNSET,
            shallow=shallow,
            detail=(
                f"{HARNESS_REF_ENV} is not set, so there is no protected ref to resolve "
                "the harness from. This fails rather than falling back to the copy in "
                "the checkout: that copy belongs to the change under test, so using it "
                "would let the PR grade itself with its own grader."
            ),
        )

    sha = _rev_parse(repo_root, ref)
    if sha is None and allow_fetch:
        _try_fetch(repo_root, ref)
        sha = _rev_parse(repo_root, ref)
    if sha is None:
        return HarnessResolution(
            ref=ref,
            status=UNRESOLVABLE,
            shallow=shallow,
            detail=(
                f"{HARNESS_REF_ENV}={ref!r} does not resolve to a commit in this "
                "checkout, so the protected harness could not be obtained. No fallback "
                "to the branch's own copy is attempted -- that fallback is the whole "
                "vulnerability this check exists to close." + _shallow_note(shallow)
            ),
        )

    if not _harness_exists_at(repo_root, sha):
        return HarnessResolution(
            ref=ref,
            status=HARNESS_ABSENT,
            shallow=shallow,
            detail=(
                f"{HARNESS_REF_ENV}={ref!r} resolves to {sha[:12]}, but none of the "
                f"harness paths ({', '.join(HARNESS_PATHS)}) exist at that commit. A ref "
                "that resolves to a commit carrying no harness cannot grade anything; "
                "reporting it as resolved would mean silently grading with whatever copy "
                "is on disk."
            ),
        )

    paths, diff_error = changed_paths(repo_root, base, head)
    if paths is None:
        return HarnessResolution(
            ref=ref,
            status=DIFF_UNAVAILABLE,
            sha=None,
            shallow=shallow,
            detail=(
                f"the diff {base}...{head} could not be computed ({diff_error}), so the "
                "harness cannot be shown to be untouched by this change. An uncomputed "
                "diff is not an empty diff, and it is not evidence of innocence."
                + _shallow_note(shallow)
            ),
        )

    touched = harness_paths_touched(paths)
    if touched:
        return HarnessResolution(
            ref=ref,
            status=HARNESS_MODIFIED,
            sha=None,
            shallow=shallow,
            touched_harness_paths=touched,
            detail=(
                f"this change touches {len(touched)} harness path(s) -- "
                f"{', '.join(touched)} -- which the change under test may not edit. The "
                "harness computes the verdict, so a PR able to modify it grades itself. "
                "This is exit "
                f"{EXIT_HARNESS_INVALID} (harness invalid), deliberately distinct from "
                f"exit {EXIT_CHANGE_BAD} (the change is bad): no verdict was reached at "
                "all. Land harness changes on the protected ref, not through the PR "
                "being evaluated."
            ),
        )

    return HarnessResolution(
        ref=ref,
        status=RESOLVED,
        sha=sha,
        shallow=shallow,
        detail=(
            f"harness resolved from {ref!r} at {sha} and no harness path is touched by "
            f"{base}...{head}"
        ),
    )


def canary_exit_code(
    resolution: HarnessResolution, *, canary_exit_codes: list[int] | tuple[int, ...]
) -> int | None:
    """``2`` when any canary passed, else ``None``.

    A canary is a record engineered to fail. If the harness passes one, the
    harness has stopped discriminating, and every other result it produced in the
    same run is worthless -- including the passes. That is a harness failure, not
    a statement about the change under test.
    """
    if not resolution.is_valid:
        return EXIT_HARNESS_INVALID
    if any(code == 0 for code in canary_exit_codes):
        return EXIT_HARNESS_INVALID
    return None


def build_run_record(
    resolution: HarnessResolution,
    *,
    exit_code: int | None = None,
    base: str | None = None,
    head: str | None = None,
) -> dict:
    """The run record: which harness graded this run, and what it concluded.

    The sha is the load-bearing field. Without it, "the protected harness graded
    this" is a claim no reader can check after the fact, which is the
    self-assessment this slice replaces with evidence.
    """
    record = {
        "harnessRef": resolution.ref or None,
        "harnessSha": resolution.sha,
        "harnessStatus": resolution.status,
        "harnessValid": resolution.is_valid,
        "harnessPaths": list(HARNESS_PATHS),
        "touchedHarnessPaths": list(resolution.touched_harness_paths),
        "shallowCheckout": resolution.shallow,
        "detail": resolution.detail,
        "recordedAt": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    if exit_code is not None:
        record["exitCode"] = exit_code
    if base is not None:
        record["base"] = base
    if head is not None:
        record["head"] = head
    return record


def _run_evaluation(command: str, repo_root: Path) -> tuple[int, str]:
    """Run the change-under-test evaluation. Returns ``(exit_code, detail)``.

    A command that cannot be launched maps to :data:`EXIT_HARNESS_INVALID`, not
    to :data:`EXIT_CHANGE_BAD`. "The runner is broken" is not a finding about the
    PR, and charging it to the PR's account is the same conflation in miniature.
    """
    try:
        proc = subprocess.run(
            shlex.split(command),
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError) as exc:
        return EXIT_HARNESS_INVALID, f"the evaluation command could not be launched: {exc}"
    if proc.returncode == 0:
        return EXIT_OK, "the evaluation passed"
    return EXIT_CHANGE_BAD, f"the evaluation reported a failing change (exit {proc.returncode})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness-ref", default="", help=f"the protected ref ({HARNESS_REF_ENV})")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--run-record", default="")
    parser.add_argument("--eval-command", default="")
    parser.add_argument("--canary-exit-code", type=int, action="append", default=[])
    parser.add_argument("--no-fetch", action="store_true")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    resolution = resolve_harness(
        args.harness_ref,
        repo_root=repo_root,
        base=args.base,
        head=args.head,
        allow_fetch=not args.no_fetch,
    )

    exit_code = resolution.exit_code
    detail = resolution.detail

    if resolution.is_valid:
        canary = canary_exit_code(resolution, canary_exit_codes=args.canary_exit_code)
        if canary is not None:
            exit_code, detail = (
                canary,
                (
                    "a canary record passed. Canaries are engineered to fail, so a harness "
                    "that passes one has stopped discriminating and no result from this run "
                    "can be trusted."
                ),
            )
        elif args.eval_command:
            exit_code, detail = _run_evaluation(args.eval_command, repo_root)

    record = build_run_record(resolution, exit_code=exit_code, base=args.base, head=args.head)
    record["outcomeDetail"] = detail
    if args.run_record:
        path = Path(args.run_record)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2) + "\n")

    label = {
        EXIT_OK: "OK",
        EXIT_CHANGE_BAD: "CHANGE BAD",
        EXIT_HARNESS_INVALID: "HARNESS INVALID",
    }[exit_code]
    print(f"[{label}] exit={exit_code} status={resolution.status}")
    print(f"  harnessRef={resolution.ref or '<unset>'} harnessSha={resolution.sha or '<none>'}")
    print(f"  {detail}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
