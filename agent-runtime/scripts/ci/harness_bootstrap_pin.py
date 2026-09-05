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
    # #1608: `origin/{name}` too -- a `merge-base:origin/BASE_REF` spec
    # substitutes the run's base ref into exactly that position, so a
    # substituted value that resolves to the checked-out branch's own remote
    # counterpart (e.g. after `git push -u` repoints this branch's own
    # upstream at itself, observed directly on the #1608 branch) must collide
    # here too, or it launders the self-referential defect through a spelling
    # this set didn't previously cover.
    return frozenset({name, f"refs/heads/{name}", f"heads/{name}", f"origin/{name}"})


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


def git_upstream_branch_name(repo_root: Path) -> str | None:
    """This branch's tracked upstream, as a bare branch name, or ``None``.

    ``None`` covers every case with no usable answer -- detached HEAD, no
    upstream configured, a bare ``git init`` with nothing tracked, or any
    other git error -- and never raises: this is one candidate in a fallback
    chain, not a required answer.
    """
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    if not output:
        return None
    # `--symbolic-full-name` on an upstream returns the remote-qualified form
    # (e.g. `origin/main`). Strip exactly the leading remote segment -- the
    # value this function returns must be a bare ref, the same shape
    # BASE_REF/GITHUB_BASE_REF already use, so `substitute_base_ref_token` can
    # drop it into `origin/BASE_REF`'s last segment without doubling the
    # `origin/` prefix.
    if "/" in output:
        return output.split("/", 1)[1]
    return output


def resolve_base_ref_token(repo_root: Path) -> tuple[str, str | None]:
    """This run's actual integration base ref, or a documented default.

    #1608: `classify-tier` in pr.yml sets CI tier `issue` exactly when
    `github.base_ref` matches `feature/*-wave` -- an issue-tier run's real base
    is that wave, not `main`, and the wave can carry harness commits `main`
    does not yet have. Anchoring to a hardcoded `origin/main` reported those
    landed, reviewed wave commits as drift on every subsequent issue-tier PR
    (PR #1561's live failure: the wave had landed #1529's
    `status-record.schema.json` change, a watched `sourcePaths` entry, before
    `main` did).

    Resolution order:

    1. **`BASE_REF`** -- the job env `test`/`full-regression` set from
       `github.base_ref`, the same value `validate-gates` and `policy-checks`
       already read. Authoritative: CI knows its own base and says so
       explicitly.
    2. **`GITHUB_BASE_REF`** -- GitHub Actions' own var, set natively for
       `pull_request` events, as a second line of defense if the job env is
       ever missing.
    3. **This branch's git upstream** (`@{u}`), screened for self-reference.
       Neither CI env var is set for a bare local run, and the harness's own
       primary local workflow is a worktree cut from a wave branch (this
       epic's own issue branches are created that way) -- defaulting straight
       to `main` there reproduces this issue's exact bug for every local
       `pytest` run, on the branch that fixes it, which is how it was found.
       `@{u}` is fixed by whoever created the branch, not chosen by the run
       that reads it -- the same "not self-settable" property `BASE_REF`
       has -- *unless* something has since repointed it, which a plain
       `git push -u` on the branch itself does (observed directly here:
       pushing this exact branch's PR repointed its own upstream at its own
       remote counterpart). Screened by the same self-referential-ref check
       every other anchor spelling goes through (see `current_branch_names`'s
       `origin/{name}` entry); a self-referential upstream is treated as no
       answer, not used.
    4. **`"main"`**, recorded as a degradation, never silent -- correct for a
       main-tier run, a branch cut locally from `main`, or a checkout with no
       upstream at all; wrong for a branch whose real base is a wave and none
       of the above resolved one.
    """
    for var in ("BASE_REF", "GITHUB_BASE_REF"):
        value = (os.environ.get(var) or "").strip()
        if value:
            # Defensive only: both pr.yml and GitHub Actions' own GITHUB_BASE_REF
            # supply a bare branch name for every trigger this gate runs under.
            # Stripping a `refs/heads/` prefix that isn't there is a no-op; not
            # stripping one that is there would build an invalid nested refspec
            # two calls downstream, in `git fetch`, far from this line.
            return value.removeprefix("refs/heads/"), None

    upstream = git_upstream_branch_name(repo_root)
    if upstream and not is_self_referential_anchor(upstream):
        if upstream not in current_branch_names(repo_root):
            return upstream, None

    return (
        "main",
        "BASE_REF/GITHUB_BASE_REF not set in the environment and git's own "
        "upstream-tracking ref did not resolve to a usable, non-self-referential "
        f"branch; the anchor's {BASE_REF_TOKEN!r} token defaulted to 'main'. "
        "Correct for a main-tier run or a branch cut from main; wrong for a "
        "branch whose real integration base is a wave -- wire BASE_REF "
        "(github.base_ref) into the environment this gate runs in, or point "
        "this branch's git upstream at its real base, to fix that case.",
    )


def substitute_base_ref_token(base_ref: str, repo_root: Path) -> tuple[str, str | None]:
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
    resolved, note = resolve_base_ref_token(repo_root)
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


def identity_coincides_with_head_note(ref: str, resolved_sha: str, repo_root: Path) -> str | None:
    """A degradation note when ``resolved_sha`` is HEAD's own commit, else ``None``.

    ``reject_self_referential_ref`` screens by spelling: it enumerates the
    checked-out branch's known name forms (``current_branch_names``) and a
    fixed list of symbolic HEAD forms (``is_self_referential_anchor``).
    Neither enumerates SHAs, so a raw or abbreviated commit SHA that happens
    to equal HEAD's own commit passes both silently -- the exact
    self-referential defect ADR-092 exists to prevent, reached through a
    spelling nobody enumerated (#1611). Screening by resolved commit identity
    instead closes every spelling at once, including ones nobody has thought
    of yet: it does not matter whether the coincidence was spelled as a SHA,
    an abbreviated SHA, or (see below) an ordinary name.

    This degrades rather than raises, deliberately: a *named* base ref (e.g.
    ``main`` in ``merge-base:main``) resolves to this exact identity
    coincidence in the normal, correct case too -- immediately after a fresh
    fork, or after a fast-forward merge, before the branch has done any work
    of its own. Rejecting that would make the gate structurally unpassable at
    the moment it is first bootstrapped (exactly the failure mode #1540's
    fix exists to avoid). From here, a coincidental match at fork time and a
    self-referential value that keeps recomputing to HEAD on every future run
    are indistinguishable in a single call -- so this records the coincidence,
    non-silently, rather than guessing which one it is. A note that keeps
    appearing across runs, never once resolving to something behind HEAD, is
    the signal that something is wrong; a note that appears once at bootstrap
    and never again is the harmless, ordinary case.
    """
    head_sha = git_rev_parse("HEAD", repo_root)
    if resolved_sha != head_sha:
        return None
    return (
        f"ref {ref!r} currently resolves to HEAD's own commit ({head_sha[:12]}); the "
        "anchor and HEAD coincide right now. Expected immediately after a fresh fork "
        "or a fast-forward merge with no work yet on this branch -- harmless as long "
        "as it stops the moment real work lands. If this keeps appearing across runs "
        "of the same branch, the anchor is not a fixed historical point but is being "
        "resolved against HEAD dynamically, which is the self-referential defect "
        "(ADR-092) reached through a different spelling."
    )


def _compose_notes(*parts: str | None) -> str | None:
    joined = "; ".join(part for part in parts if part)
    return joined or None


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

    Rejected outright: symbolic self-references (``HEAD``, ``@``, ``HEAD~1``, …)
    and the checked-out branch's own name, both of those as the base of a
    ``merge-base:`` spec too. Failing closed here is the point — the previous
    behaviour silently accepted ``HEAD`` and produced a gate that could only
    pass on a branch that had done no work.

    Degraded, never silently accepted: a resolved anchor -- raw SHA,
    abbreviated SHA, or an ordinary named ref such as ``main`` -- that
    currently equals HEAD's own commit (#1611). ``current_branch_names`` and
    ``is_self_referential_ref`` enumerate *spellings*; a value that merely
    *coincides* with HEAD right now (e.g. a raw SHA that happens to equal it,
    or a fresh fork/fast-forward where the named base has not yet diverged)
    passes every spelling check and is indistinguishable, from here, from the
    same value being recomputed against HEAD on every future run -- which
    would be the self-referential defect wearing a different spelling. Both
    are recorded via a non-``None`` degradation note rather than one being
    silently accepted; see :func:`identity_coincides_with_head_note`.
    Rejecting outright here instead would make the gate structurally
    unpassable the moment it is first bootstrapped (fresh fork, or a
    fast-forward merge before any work lands) -- the same failure mode
    #1540's fix exists to avoid.

    Returns ``(sha, degradation_note)``. Besides the identity coincidence
    above, the note is non-``None`` when the fork point could not be computed
    and the base ref was used directly: shallow checkouts have no common
    ancestor to find, and ``actions/checkout`` is shallow by default.
    Degrading is right here — the substantive half of the gate is the content
    diff, which still runs — but it is recorded rather than hidden, because an
    anchor that quietly means something else is how a gate stops measuring.
    The one thing never done is falling back to ``HEAD``.
    """
    candidate = (spec or "").strip()
    if not candidate:
        raise RuntimeError(
            "bootstrap pin spec is empty; set workflow_prompt_cache.bootstrap.pinBranch"
        )
    reject_self_referential_ref(candidate, candidate, repo_root)
    if not candidate.startswith(MERGE_BASE_PREFIX):
        resolved = git_rev_parse(candidate, repo_root)
        # Spelling-based screening above cannot see a raw/abbreviated SHA that
        # happens to equal HEAD's own commit; record the resolved identity too.
        note = identity_coincides_with_head_note(candidate, resolved, repo_root)
        return resolved, note

    base_ref = candidate[len(MERGE_BASE_PREFIX) :].strip()
    if not base_ref:
        raise RuntimeError(f"bootstrap pin spec {candidate!r} names no base ref")
    # #1608: substitute a trailing BASE_REF token for this run's actual base
    # ref *before* the self-reference screen below, so the screen applies to
    # what will really be resolved -- not to the unsubstituted template.
    base_ref, token_note = substitute_base_ref_token(base_ref, repo_root)
    # The base of a merge-base spec is a ref in its own right and gets the same
    # scrutiny: `merge-base:HEAD` resolves to HEAD and would restore the defect.
    reject_self_referential_ref(base_ref, candidate, repo_root)
    # Resolve the base first: if it is missing the anchor is unknowable, and a
    # gate with no anchor must be red, not lenient.
    base_sha = git_rev_parse(base_ref, repo_root)
    try:
        merge_base_sha = git_merge_base("HEAD", base_ref, repo_root)
    except RuntimeError:
        shallow_note = (
            f"no merge base between HEAD and {base_ref!r} (shallow checkout or unrelated "
            f"histories); anchored to {base_ref!r} itself at {base_sha[:12]}"
        )
        # #1611: the base ref -- raw SHA, abbreviated SHA, or an ordinary name
        # that has not yet diverged -- can itself equal HEAD's own commit.
        # No name-spelling check enumerates that; screen the resolved
        # identity of what is actually being anchored to.
        identity_note = identity_coincides_with_head_note(base_ref, base_sha, repo_root)
        return base_sha, _compose_notes(token_note, shallow_note, identity_note)

    identity_note = identity_coincides_with_head_note(base_ref, merge_base_sha, repo_root)
    return merge_base_sha, _compose_notes(token_note, identity_note)


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
