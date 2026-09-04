"""Harness reproducibility pinning for sibling workflow-cache runs."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKILL_SUFFIX = "/SKILL.md"

#: Spec prefix selecting the fork point between HEAD and an integration base.
MERGE_BASE_PREFIX = "merge-base:"

#: Placeholder resolved to this run's actual integration base ref at check
#: time. Meaningful only as the final path segment of a `merge-base:` spec's
#: base ref (e.g. `merge-base:origin/BASE_REF`) -- see
#: `substitute_base_ref_token`.
BASE_REF_TOKEN = "BASE_REF"

#: Anchor spellings that resolve to the checked-out branch's own tip. Pinning to
#: any of these makes the gate compare a branch against itself: it goes red the
#: moment the branch has one commit, and it never once looks at the harness. See
#: ``resolve_bootstrap_anchor`` for why this is rejected rather than tolerated.
_SELF_REFERENTIAL_EXACT = frozenset({"HEAD", "@"})
_SELF_REFERENTIAL_PREFIXES = ("HEAD~", "HEAD^", "HEAD@{", "@~", "@^", "@{")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_self_referential_anchor(spec: str) -> bool:
    """True when ``spec`` re-resolves to whatever branch happens to be checked out.

    The pin exists to answer "has the harness changed since this run started".
    An anchor that tracks the branch tip cannot answer it — the two sides of the
    comparison move together.
    """
    candidate = (spec or "").strip().upper()
    if candidate in _SELF_REFERENTIAL_EXACT:
        return True
    return candidate.startswith(_SELF_REFERENTIAL_PREFIXES)


def current_branch_names(repo_root: Path) -> frozenset[str]:
    """Every spelling of the branch currently checked out, or empty when detached.

    Pinning to the branch you are standing on is the same defect as pinning to
    ``HEAD``, spelled differently: the anchor tracks the tip it is meant to
    measure against. The string guard cannot see it, so resolve it.
    """
    try:
        name = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return frozenset()
    if not name or name == "HEAD":  # detached: no branch name to collide with
        return frozenset()
    return frozenset({name, f"refs/heads/{name}", f"heads/{name}"})


def reject_self_referential_ref(ref: str, spec: str, repo_root: Path) -> None:
    """Raise when ``ref`` resolves to the checked-out branch's own tip.

    Applied to the whole spec *and*, after the prefix is stripped, to the base
    ref of a ``merge-base:`` spec. Checking only the whole spec leaves
    ``merge-base:HEAD`` accepted, which is the original defect wearing the new
    syntax: ``git merge-base HEAD HEAD`` is HEAD.
    """
    if is_self_referential_anchor(ref):
        raise RuntimeError(
            f"bootstrap pin spec {spec!r} is symbolic: it re-resolves at check time to "
            "the checked-out branch's own tip, so the gate would compare the branch against "
            "itself and could never detect harness drift. Use 'merge-base:<base-ref>' "
            "(recommended) or an explicit commit SHA."
        )
    if ref in current_branch_names(repo_root):
        raise RuntimeError(
            f"bootstrap pin spec {spec!r} names the checked-out branch {ref!r}, so it "
            "resolves to that branch's own tip and moves with every commit. The gate would "
            "compare the branch against itself and could never detect harness drift. Use "
            "'merge-base:<base-ref>' against an integration base instead."
        )


def resolve_base_ref_token() -> tuple[str, str | None]:
    """This run's actual integration base ref, or a documented default.

    #1608: `classify-tier` in pr.yml sets CI tier `issue` exactly when
    `github.base_ref` matches `feature/*-wave` -- an issue-tier run's real base
    is that wave, not `main`, and the wave can carry harness commits `main`
    does not yet have. Anchoring to a hardcoded `origin/main` reported those
    landed, reviewed wave commits as drift on every subsequent issue-tier PR
    (PR #1561's live failure: the wave had landed #1529's
    `status-record.schema.json` change, a watched `sourcePaths` entry, before
    `main` did).

    `test`/`full-regression`, the two base-anchored jobs, set the `BASE_REF`
    job env from `github.base_ref` -- the same value `validate-gates` and
    `policy-checks` already read to fetch and diff against the real base,
    rather than a branch name hardcoded into this file. At main tier
    `github.base_ref` *is* `main`, so this one dynamic form is correct at both
    tiers without a conditional.

    Falls back to GitHub Actions' own `GITHUB_BASE_REF` (set natively for
    `pull_request` events) when `BASE_REF` is unset, and only then degrades to
    `"main"` -- correct for a main-tier run or a branch cut locally from
    `main`, wrong for a branch whose real base is a wave. The degradation is
    recorded, never silent, matching the shallow-checkout fallback below.
    """
    for var in ("BASE_REF", "GITHUB_BASE_REF"):
        value = (os.environ.get(var) or "").strip()
        if value:
            return value, None
    return (
        "main",
        "BASE_REF/GITHUB_BASE_REF not set in the environment; the anchor's "
        f"{BASE_REF_TOKEN!r} token defaulted to 'main'. Correct for a "
        "main-tier run or a branch cut from main; wrong for a branch whose "
        "real integration base is a wave -- wire BASE_REF (github.base_ref) "
        "into the environment this gate runs in to fix that case.",
    )


def substitute_base_ref_token(base_ref: str) -> tuple[str, str | None]:
    """Replace a trailing ``BASE_REF`` path segment with this run's real base.

    Matches ``BASE_REF`` as a whole path segment (``BASE_REF`` or
    ``.../BASE_REF``), not as a substring, so a real ref that merely contains
    those letters is never silently rewritten. A base ref with no such segment
    is returned unchanged -- the token is opt-in: an explicit ref or SHA still
    works exactly as before.
    """
    segments = base_ref.split("/")
    if segments[-1] != BASE_REF_TOKEN:
        return base_ref, None
    resolved, note = resolve_base_ref_token()
    segments[-1] = resolved
    return "/".join(segments), note


def git_rev_parse(ref: str, repo_root: Path) -> str:
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", ref],
            cwd=repo_root,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or str(exc)).strip()
        raise RuntimeError(f"git rev-parse {ref!r} failed: {detail}") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("git CLI not found; required for bootstrap pinning") from exc
    return output.strip()


def git_merge_base(left: str, right: str, repo_root: Path) -> str:
    try:
        output = subprocess.check_output(
            ["git", "merge-base", left, right],
            cwd=repo_root,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or str(exc)).strip()
        raise RuntimeError(f"git merge-base {left!r} {right!r} failed: {detail}") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("git CLI not found; required for bootstrap pinning") from exc
    return output.strip()


def resolve_bootstrap_anchor_with_note(spec: str, repo_root: Path) -> tuple[str, str | None]:
    """Resolve a pin spec to the commit the harness was bootstrapped from.

    Accepted forms:

    ``merge-base:<base-ref>``
        The fork point between ``HEAD`` and ``<base-ref>``. This is the correct
        anchor for issue work: it is fixed for the life of the branch, so the
        branch's own commits cannot move it, and it is unaffected by unrelated
        traffic landing on the base after the fork. ``<base-ref>`` may end in
        the literal segment ``BASE_REF`` (e.g. ``origin/BASE_REF``), which is
        substituted for this run's actual base ref before resolution -- see
        ``substitute_base_ref_token``. A hardcoded base ref is wrong at issue
        tier, where the real base is a wave branch, not ``main`` (#1608).
    ``<ref>`` or ``<sha>``
        Any ref or explicit SHA that is not tied to the checked-out branch.

    Rejected: symbolic self-references (``HEAD``, ``@``, ``HEAD~1``, …), the
    checked-out branch's own name, and both of those as the base of a
    ``merge-base:`` spec. Failing closed here is the point — the previous behaviour silently accepted ``HEAD``
    and produced a gate that could only pass on a branch that had done no work.

    Returns ``(sha, degradation_note)``. The note is non-``None`` when the fork
    point could not be computed and the base ref was used directly: shallow
    checkouts have no common ancestor to find, and ``actions/checkout`` is
    shallow by default. Degrading is right here — the substantive half of the
    gate is the content diff, which still runs — but it is recorded rather than
    hidden, because an anchor that quietly means something else is how a gate
    stops measuring. The one thing never done is falling back to ``HEAD``.
    """
    candidate = (spec or "").strip()
    if not candidate:
        raise RuntimeError(
            "bootstrap pin spec is empty; set workflow_prompt_cache.bootstrap.pinBranch"
        )
    reject_self_referential_ref(candidate, candidate, repo_root)
    if not candidate.startswith(MERGE_BASE_PREFIX):
        return git_rev_parse(candidate, repo_root), None

    base_ref = candidate[len(MERGE_BASE_PREFIX) :].strip()
    if not base_ref:
        raise RuntimeError(f"bootstrap pin spec {candidate!r} names no base ref")
    # #1608: substitute a trailing BASE_REF token for this run's actual base
    # ref *before* the self-reference screen below, so the screen applies to
    # what will really be resolved -- not to the unsubstituted template.
    base_ref, token_note = substitute_base_ref_token(base_ref)
    # The base of a merge-base spec is a ref in its own right and gets the same
    # scrutiny: `merge-base:HEAD` resolves to HEAD and would restore the defect.
    reject_self_referential_ref(base_ref, candidate, repo_root)
    # Resolve the base first: if it is missing the anchor is unknowable, and a
    # gate with no anchor must be red, not lenient.
    base_sha = git_rev_parse(base_ref, repo_root)
    try:
        return git_merge_base("HEAD", base_ref, repo_root), token_note
    except RuntimeError:
        shallow_note = (
            f"no merge base between HEAD and {base_ref!r} (shallow checkout or unrelated "
            f"histories); anchored to {base_ref!r} itself at {base_sha[:12]}"
        )
        note = f"{token_note}; {shallow_note}" if token_note else shallow_note
        return base_sha, note


def resolve_bootstrap_anchor(spec: str, repo_root: Path) -> str:
    """The resolved anchor SHA. See :func:`resolve_bootstrap_anchor_with_note`."""
    sha, _ = resolve_bootstrap_anchor_with_note(spec, repo_root)
    return sha


def git_path_exists_at_commit(commit_sha: str, relative_path: str, repo_root: Path) -> bool:
    try:
        subprocess.check_output(
            ["git", "cat-file", "-e", f"{commit_sha}:{relative_path}"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def list_repo_paths_at_commit(
    commit_sha: str,
    source_paths: list[str],
    repo_root: Path,
) -> list[str]:
    paths: set[str] = set()
    for source_path in source_paths:
        normalized = source_path.strip("/")
        if not normalized:
            continue
        try:
            output = subprocess.check_output(
                ["git", "ls-tree", "-r", "--name-only", commit_sha, "--", normalized],
                cwd=repo_root,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or str(exc)).strip()
            raise RuntimeError(
                f"git ls-tree at {commit_sha} for {normalized!r} failed: {detail}"
            ) from exc
        for line in output.splitlines():
            entry = line.strip()
            if entry:
                paths.add(entry)
    return sorted(paths)


def enumerate_bootstrap_skill_paths(
    commit_sha: str,
    source_paths: list[str],
    repo_root: Path,
) -> list[str]:
    """Skill paths available from bootstrap source dirs at a pinned commit."""
    skill_paths = [
        path
        for path in list_repo_paths_at_commit(commit_sha, source_paths, repo_root)
        if path.endswith("SKILL.md")
    ]
    return sorted(skill_paths)


def diff_harness_paths_since(
    pinned_sha: str,
    source_paths: list[str],
    repo_root: Path,
) -> list[str]:
    """Bootstrap-source paths that differ between the pin and the tree in use.

    This is what the gate actually measures. Anchoring alone is not enough: a
    stable anchor plus an identity check would pass unconditionally, because the
    branch's own harness edits never move the fork point. So compare *content*.

    The comparison runs pin → working tree, not pin → HEAD, deliberately. The
    harness a run reads is the one on disk; an uncommitted edit to a skill is
    exactly as much drift as a committed one, and is the form drift usually takes
    while a run is still in flight. Untracked additions count too — a run can
    load a skill file that did not exist at the pin.
    """
    normalized = [path.strip("/") for path in source_paths if path and path.strip("/")]
    if not normalized:
        return []

    drifted: set[str] = set()
    for args in (
        ["diff", "--name-only", pinned_sha, "--", *normalized],
        ["ls-files", "--others", "--exclude-standard", "--", *normalized],
    ):
        try:
            output = subprocess.check_output(
                ["git", *args],
                cwd=repo_root,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or str(exc)).strip()
            raise RuntimeError(f"git {args[0]} for bootstrap drift failed: {detail}") from exc
        except FileNotFoundError as exc:
            raise RuntimeError("git CLI not found; required for bootstrap pinning") from exc
        for line in output.splitlines():
            entry = line.strip()
            if entry:
                drifted.add(entry)
    return sorted(drifted)


def extract_harness_skill_paths(child_cache: dict[str, Any]) -> list[str]:
    harness = child_cache.get("harnessUtility") or {}
    skills = harness.get("skills") or []
    paths: list[str] = []
    for entry in skills:
        if isinstance(entry, dict):
            path = entry.get("path")
            if isinstance(path, str) and path.strip():
                paths.append(path.strip())
    return sorted(paths)


def normalize_skill_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def skill_path_exists_at_commit(
    commit_sha: str,
    skill_path: str,
    repo_root: Path,
) -> bool:
    relative = normalize_skill_path(skill_path)
    return git_path_exists_at_commit(commit_sha, relative, repo_root)


def bootstrap_ref_from_git(
    branch: str,
    repo_root: Path,
    *,
    copied_at: str | None = None,
) -> dict[str, str]:
    """Record the pin: the anchor spec as written, and the SHA it resolved to.

    ``branch`` keeps its name for the callers and the parent-cache schema, but it
    now holds an anchor *spec* — ``merge-base:origin/main``, a ref, or a SHA. The
    immutable half of the pin remains ``commitSha``.
    """
    commit_sha = resolve_bootstrap_anchor(branch, repo_root)
    return {
        "branch": branch,
        "commitSha": commit_sha,
        "copiedAt": copied_at or utc_now_iso(),
    }


def validate_bootstrap_ref(
    parent_cache: dict[str, Any],
    child_cache: dict[str, Any],
    *,
    bootstrap_config: dict[str, Any],
    repo_root: Path,
) -> tuple[bool, str, dict[str, Any]]:
    bootstrap_ref = parent_cache.get("bootstrapRef")
    details: dict[str, Any] = {
        "bootstrapRef": bootstrap_ref,
        "harnessSkillPaths": extract_harness_skill_paths(child_cache),
    }

    if not isinstance(bootstrap_ref, dict):
        return False, "Parent cache missing bootstrapRef", details

    branch = bootstrap_ref.get("branch")
    commit_sha = bootstrap_ref.get("commitSha")
    copied_at = bootstrap_ref.get("copiedAt")
    missing = [
        field
        for field, value in (
            ("branch", branch),
            ("commitSha", commit_sha),
            ("copiedAt", copied_at),
        )
        if not isinstance(value, str) or not value.strip()
    ]
    if missing:
        return False, f"bootstrapRef missing fields: {', '.join(missing)}", details

    branch = branch.strip()
    commit_sha = commit_sha.strip()
    source_paths = bootstrap_config.get("sourcePaths") or []
    if not source_paths:
        return False, "workflow_prompt_cache.bootstrap.sourcePaths is empty in config", details

    try:
        resolved_anchor, anchor_note = resolve_bootstrap_anchor_with_note(branch, repo_root)
    except RuntimeError as exc:
        return False, str(exc), details

    details["resolvedAnchorSha"] = resolved_anchor
    details["pinnedCommitSha"] = commit_sha
    details["anchorDegraded"] = anchor_note is not None
    if anchor_note:
        details["anchorDegradationReason"] = anchor_note

    if resolved_anchor != commit_sha:
        return (
            False,
            (
                f"Bootstrap anchor {branch!r} now resolves to {resolved_anchor[:12]}, "
                f"not the pinned bootstrapRef.commitSha ({commit_sha[:12]}). "
                "The run's fork point moved (rebase or base merge), so the harness "
                "underneath it is no longer the one it bootstrapped from. Re-pin "
                "deliberately with an Architect note, or re-fork from the pinned SHA."
            ),
            details,
        )

    harness_paths = extract_harness_skill_paths(child_cache)
    details["harnessSkillPaths"] = harness_paths

    missing_at_pin: list[str] = []
    for skill_path in harness_paths:
        if not skill_path_exists_at_commit(commit_sha, skill_path, repo_root):
            missing_at_pin.append(skill_path)

    if missing_at_pin:
        return (
            False,
            (
                "harnessUtility skill paths missing at pinned bootstrapRef.commitSha: "
                + ", ".join(missing_at_pin)
            ),
            details,
        )

    try:
        drifted = diff_harness_paths_since(commit_sha, source_paths, repo_root)
    except RuntimeError as exc:
        return False, str(exc), details

    details["driftedHarnessPaths"] = drifted
    details["watchedSourcePaths"] = list(source_paths)

    if drifted:
        shown = ", ".join(drifted[:10])
        overflow = "" if len(drifted) <= 10 else f" (+{len(drifted) - 10} more)"
        return (
            False,
            (
                f"Harness drift since pinned bootstrapRef.commitSha ({commit_sha[:12]}): "
                f"{shown}{overflow}. The bootstrap source changed under this run, so its "
                "context is not the context the pin describes. Land the harness change on "
                "its own, then re-pin with an Architect note."
            ),
            details,
        )

    try:
        bootstrap_index = enumerate_bootstrap_skill_paths(commit_sha, source_paths, repo_root)
    except RuntimeError as exc:
        return False, str(exc), details

    details["bootstrapSkillIndex"] = bootstrap_index
    details["bootstrapSkillIndexSha"] = commit_sha

    return (
        True,
        (
            f"Bootstrap pinned to {commit_sha[:12]} via {branch}; "
            f"{len(harness_paths)} harnessUtility skill path(s) verified; "
            f"no drift across {len(source_paths)} bootstrap source path(s)"
            + (f" [degraded anchor: {anchor_note}]" if anchor_note else "")
        ),
        details,
    )
