#!/usr/bin/env python3
"""Resolve status-record ``artifactRef``/``sha256`` pairs against git history (#1445).

#670 recorded an integrity chain and never built the store it points into. Its schema
still says the verbose review/validation bodies *"move to CI artifact retention with
sha256 integrity references recorded here"*, while ``pr.yml`` records that no such
upload step exists or can: the five artifact body directories are gitignored, so nothing
reaches the runner to upload. The consequence is measurable -- 240 of the 538
``artifactRef``/``sha256`` pairs in the committed corpus name a path that exists in no
commit on any branch, and none of the records above issue 660 resolve at all. Those
``sha256`` fields fingerprint files stored nowhere.

This module answers one question honestly: *does this ref resolve, and does what it
resolves to hash to what the record claims?* It returns a status per ref and never
guesses. The caller decides what to do with each status -- ``check_artifact_retention_guard``
fails a ``gateVersion: 2`` record on a broken ref but only MARKS a ``gateVersion: 1``
record, because the historical bodies exist on no machine and rewriting history to
invent them is out of scope (Architect lock: no backfill).

**Shallow checkouts.** CI checks this repo out shallow for the retention-guard job
(a bare ``actions/checkout`` with no ``fetch-depth``), so history before the graft is
simply absent. "This path is in no commit" is then unknowable, and answering
UNRESOLVABLE would be a verdict the data does not support. Every ref in a shallow
checkout is reported ``INDETERMINATE`` with the reason printed, never a wrong verdict.

Stdlib only, like every other module under ``agent-runtime/scripts/ci/``.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

GIT_HISTORY_SCHEME = "git-history:"

#: #1497. ``git-history:`` asserts retrievability from history. For the five
#: artifact body directories that assertion can never be true: ``.gitignore``
#: forbids committing them BY POLICY (ADR-003, "emit is not commit"), so a
#: ``git-history:`` ref to one is a claim the repository is structurally unable
#: to satisfy -- which made every ``gateVersion: 2`` record unpassable the moment
#: #1445 started checking. ``local-only:`` is the honest claim for those bodies:
#: *this file existed on the machine that ran the loop, this is its sha256, and
#: it is not retrievable from here by policy.* It is deliberately a WEAKER claim,
#: and it is admissible only for the paths policy really does forbid committing
#: -- see ``POLICY_LOCAL_BODY_DIRS``. Anywhere else it is an unsupported scheme,
#: so it cannot be used to launder a dangling ``git-history:`` ref into a pass.
LOCAL_ONLY_SCHEME = "local-only:"

#: The repo-relative directory prefixes whose contents ``.gitignore`` keeps out
#: of every commit (the five verbose artifact body dirs of ADR-052's #670 P1
#: Option A amendment). Kept in step with ``.gitignore``; the corpus test
#: ``test_no_committed_status_record_claims_git_history_for_a_gitignored_body``
#: cross-checks this list against ``git check-ignore`` on the real tree.
POLICY_LOCAL_BODY_DIRS = (
    "agent-runtime/artifacts/reviews/",
    "agent-runtime/artifacts/implementations/",
    "agent-runtime/artifacts/intent-reviews/",
    "agent-runtime/artifacts/validation/",
    "agent-runtime/artifacts/optimization/",
)

#: The ref resolves and the content it resolves to hashes to the recorded sha256.
MATCH = "MATCH"
#: The ref names a path that exists in no commit on any branch.
UNRESOLVABLE = "UNRESOLVABLE"
#: The path exists in history, but no version of it hashes to the recorded sha256.
HASH_MISMATCH = "HASH_MISMATCH"
#: The ref is not in a form this resolver can follow (e.g. #670's never-built
#: "CI run artifact URL fragment").
UNSUPPORTED_SCHEME = "UNSUPPORTED_SCHEME"
#: Resolution could not be attempted here -- shallow checkout, or no git repository.
#: Explicitly *not* a verdict about the ref.
INDETERMINATE = "INDETERMINATE"
#: #1497: the ref names a body inside a policy-local directory and says so with
#: the ``local-only:`` scheme. Known-unretrievable BY DESIGN, not an integrity
#: failure -- the record never claimed it could be read back. Answered without
#: consulting git at all, because it is a statement about policy rather than
#: about this checkout's history (so it survives CI's shallow checkout).
POLICY_LOCAL = "POLICY_LOCAL"

#: Statuses that are a positive finding of a broken integrity claim. ``POLICY_LOCAL``
#: is deliberately absent: nothing is broken about a ref that correctly declares
#: its target unretrievable.
FAILING_STATUSES = frozenset({UNRESOLVABLE, HASH_MISMATCH, UNSUPPORTED_SCHEME})

#: The two blocks of a status record that carry an artifactRef/sha256 pair.
REF_FIELDS = ("review", "validation")


@dataclass(frozen=True)
class RefResolution:
    """One ref, one verdict, one human-readable reason. ``detail`` always names
    the ref, so a failing guard message points at the exact thing that is wrong."""

    field: str
    ref: str
    status: str
    detail: str

    @property
    def resolved(self) -> bool:
        return self.status == MATCH

    @property
    def is_failure(self) -> bool:
        return self.status in FAILING_STATUSES


@dataclass(frozen=True)
class RefIndex:
    """Every path reachable from any ref, mapped to the blob shas it has held.

    Built from ``git rev-list --all --objects``, which walks objects rather than
    diffs -- so unlike ``git log --name-only`` it cannot miss a file that only ever
    entered history through a merge commit.

    ``available=False`` means the index could not be built at all (shallow checkout,
    or not a git repository); ``reason`` says which, and every ref then resolves to
    ``INDETERMINATE``.
    """

    available: bool
    reason: str
    paths: dict[str, frozenset[str]] = field(default_factory=dict)


_INDEX_CACHE: dict[str, RefIndex] = {}


def _git(repo_root: Path, *args: str, text: bool = True) -> subprocess.CompletedProcess:
    # Fixed argv, no shell: nothing here is interpolated from record content.
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=text,
        check=False,
    )


def is_shallow_repository(repo_root: Path) -> bool:
    """True when history before a graft point is absent from this checkout."""
    proc = _git(repo_root, "rev-parse", "--is-shallow-repository")
    if proc.returncode != 0:
        return False
    return proc.stdout.strip() == "true"


def build_ref_index(repo_root: Path) -> RefIndex:
    """Build the path -> blob-sha index for ``repo_root`` (uncached)."""
    probe = _git(repo_root, "rev-parse", "--is-shallow-repository")
    if probe.returncode != 0:
        return RefIndex(
            available=False,
            reason=(
                f"no readable git repository at {repo_root} "
                f"({probe.stderr.strip() or 'git rev-parse failed'}), so artifactRef "
                "resolution was not attempted"
            ),
        )
    if probe.stdout.strip() == "true":
        return RefIndex(
            available=False,
            reason=(
                "this is a shallow checkout (git rev-parse --is-shallow-repository is "
                "true); history before the graft is absent, so a ref missing here may "
                "still exist upstream and absence cannot be asserted"
            ),
        )

    proc = _git(repo_root, "rev-list", "--all", "--objects")
    if proc.returncode != 0:
        return RefIndex(
            available=False,
            reason=(
                "git rev-list --all --objects failed in "
                f"{repo_root}: {proc.stderr.strip() or 'unknown error'}"
            ),
        )

    collected: dict[str, set[str]] = {}
    for line in proc.stdout.splitlines():
        sha, _, path = line.partition(" ")
        if not path:
            continue  # a commit or tag object: no path component
        collected.setdefault(path, set()).add(sha)
    return RefIndex(
        available=True,
        reason="",
        paths={path: frozenset(shas) for path, shas in collected.items()},
    )


def get_ref_index(repo_root: Path) -> RefIndex:
    """Cached ``build_ref_index``. The walk costs about half a second; a guard run
    resolves two refs and a corpus sweep resolves hundreds, so build it once."""
    key = str(Path(repo_root).resolve())
    cached = _INDEX_CACHE.get(key)
    if cached is None:
        cached = build_ref_index(Path(repo_root))
        _INDEX_CACHE[key] = cached
    return cached


def reset_ref_index_cache() -> None:
    """Drop the cache -- for a caller that mutates a repository between reads."""
    _INDEX_CACHE.clear()


def is_policy_local_path(path: str) -> bool:
    """True when ``path`` lies inside one of the five gitignored body directories,
    i.e. when policy forbids it ever reaching a commit."""
    normalised = (path or "").strip().lstrip("./")
    return any(normalised.startswith(prefix) for prefix in POLICY_LOCAL_BODY_DIRS)


def policy_local_ref(path: str) -> str:
    """Build the honest ref for a body policy forbids committing (#1497)."""
    return f"{LOCAL_ONLY_SCHEME}{path}"


def _resolve_local_only(field_name: str, ref: str, expected: str) -> RefResolution:
    path = ref[len(LOCAL_ONLY_SCHEME) :].strip()
    if not path:
        return RefResolution(
            field_name,
            ref,
            UNSUPPORTED_SCHEME,
            f"{field_name}.artifactRef {ref!r} carries the {LOCAL_ONLY_SCHEME} scheme "
            "with an empty path",
        )
    if not is_policy_local_path(path):
        # The laundering guard. `local-only:` excuses a ref from resolution, so it
        # must only ever be reachable for the paths policy genuinely forbids
        # committing -- otherwise any dangling `git-history:` ref could be
        # relabelled into a pass and #1445 would be worth nothing.
        return RefResolution(
            field_name,
            ref,
            UNSUPPORTED_SCHEME,
            (
                f"{field_name}.artifactRef names {path} with the {LOCAL_ONLY_SCHEME} "
                "scheme, but that path is not inside any of the gitignored artifact "
                f"body directories ({', '.join(POLICY_LOCAL_BODY_DIRS)}) — nothing "
                "stops it being committed, so it may not claim to be unretrievable "
                "by policy"
            ),
        )
    return RefResolution(
        field_name,
        ref,
        POLICY_LOCAL,
        (
            f"{field_name}.artifactRef names {path}, a body .gitignore forbids "
            "committing (ADR-003: emit is not commit) — the record claims only that "
            f"it existed locally with sha256 {expected[:12]}…, not that it can be read "
            "back here; unretrievable by policy, not an integrity failure"
        ),
    )


def resolve_ref(
    field_name: str, ref: str, expected_sha256: str, *, repo_root: Path
) -> RefResolution:
    """Resolve one ``artifactRef`` and check it against its recorded ``sha256``."""
    ref = (ref or "").strip()
    expected = (expected_sha256 or "").strip().lower()

    if ref.startswith(LOCAL_ONLY_SCHEME):
        # Answered before any git call: policy, not history, decides this one.
        return _resolve_local_only(field_name, ref, expected)

    if not ref.startswith(GIT_HISTORY_SCHEME):
        return RefResolution(
            field_name,
            ref,
            UNSUPPORTED_SCHEME,
            (
                f"{field_name}.artifactRef {ref!r} uses no scheme this guard can follow "
                f"(expected {GIT_HISTORY_SCHEME}<repo-relative-path> for a committed "
                f"path, or {LOCAL_ONLY_SCHEME}<repo-relative-path> for a body policy "
                "forbids committing) — #670's promised CI artifact-retention store was "
                "never built, so such a ref points at nothing that can be read back"
            ),
        )

    path = ref[len(GIT_HISTORY_SCHEME) :].strip()
    if not path:
        return RefResolution(
            field_name,
            ref,
            UNSUPPORTED_SCHEME,
            f"{field_name}.artifactRef {ref!r} carries the {GIT_HISTORY_SCHEME} scheme "
            "with an empty path",
        )

    index = get_ref_index(Path(repo_root))
    if not index.available:
        return RefResolution(
            field_name,
            ref,
            INDETERMINATE,
            f"{field_name}.artifactRef {path} was not resolved: {index.reason}",
        )

    blobs = index.paths.get(path)
    if not blobs:
        return RefResolution(
            field_name,
            ref,
            UNRESOLVABLE,
            (
                f"{field_name}.artifactRef names {path}, which exists in no commit on "
                f"any branch — the recorded sha256 {expected} fingerprints a file that "
                "is stored nowhere"
            ),
        )

    for blob in sorted(blobs):
        content = _git(repo_root, "cat-file", "blob", blob, text=False)
        if content.returncode != 0:
            continue
        if hashlib.sha256(content.stdout).hexdigest() == expected:
            return RefResolution(
                field_name,
                ref,
                MATCH,
                (
                    f"{field_name}.artifactRef resolves to {path} at blob {blob[:12]} "
                    f"and its content matches the recorded sha256 {expected[:12]}…"
                ),
            )

    return RefResolution(
        field_name,
        ref,
        HASH_MISMATCH,
        (
            f"{field_name}.artifactRef resolves to {path} ({len(blobs)} version(s) in "
            f"history) but none of them matches the recorded sha256 {expected} — the "
            "integrity claim is false"
        ),
    )


def resolve_record_refs(payload: dict, *, repo_root: Path) -> list[RefResolution]:
    """Resolve the review and validation refs of one status record."""
    resolutions: list[RefResolution] = []
    for name in REF_FIELDS:
        block = payload.get(name)
        if not isinstance(block, dict):
            continue
        resolutions.append(
            resolve_ref(
                name,
                str(block.get("artifactRef", "")),
                str(block.get("sha256", "")),
                repo_root=repo_root,
            )
        )
    return resolutions
