"""Archive-on-emit for the five gitignored ADR-003 artifact body directories (#2067).

The incident these tests stand against: a worktree cleanup on 2026-09-21 removed
21 worktrees on the premise that "a worktree is a checkout, not history; removing
it with the branch intact loses nothing". That premise is true in most repos and
false in this one, because `.gitignore` keeps `reviews/`, `implementations/`,
`intent-reviews/`, `validation/` and `optimization/` as files that exist ONLY
inside the worktree that produced them. Five committed status records (#1701,
#1748, #1977, #1540, #1608) now cite `local-only:` bodies that exist nowhere, and
99 of the 111 `local-only:` records on `main` were already orphaned before that
cleanup.

`test_archived_body_survives_real_worktree_removal` is the load-bearing one: it
builds a real git repo, adds a real linked worktree, emits a body through the
real writer, runs a real `git worktree remove --force`, and asserts the body is
still readable. Delete the `archive_body` call in `common.write_json` and it goes
red with exactly the incident's signature.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
GIT_SCRIPTS_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "git"


def _seam():
    """Import the archive seam lazily (keeps E402 suppressions out of this file)."""
    for path in (CI_DIR, GIT_SCRIPTS_DIR):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    import artifact_archive
    import check_worktree_artifacts_archived
    import common

    return artifact_archive, common, check_worktree_artifacts_archived


def _git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout


def _init_repo(root: Path) -> None:
    """A real git repo carrying this repo's artifact .gitignore policy."""
    root.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", "-b", "main", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "test", cwd=root)
    (root / ".gitignore").write_text(
        "\n".join(
            f"agent-runtime/artifacts/{name}/**/*.json"
            for name in (
                "reviews",
                "implementations",
                "intent-reviews",
                "validation",
                "optimization",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    status = root / "agent-runtime" / "artifacts" / "status"
    status.mkdir(parents=True, exist_ok=True)
    (status / ".keep").write_text("", encoding="utf-8")
    _git("add", "-A", cwd=root)
    _git("commit", "-qm", "init", cwd=root)


def _body_path(root: Path, issue: int) -> Path:
    return root / "agent-runtime" / "artifacts" / "reviews" / f"review-issue-{issue}.json"


def _payload(issue: int, summary: str = "reviewed") -> dict:
    return {"id": f"review-issue-{issue}", "issue": issue, "summary": summary}


# ---------------------------------------------------------------------------
# The property: emitting a body archives it outside the worktree.
# ---------------------------------------------------------------------------


def test_write_json_archives_a_review_body(tmp_path, monkeypatch):
    artifact_archive, common, _ = _seam()
    archive = tmp_path / "archive"
    monkeypatch.setenv(artifact_archive.ARCHIVE_DIR_ENV, str(archive))

    body = _body_path(tmp_path / "repo", 2067)
    common.write_json(body, _payload(2067))

    digest = hashlib.sha256(body.read_bytes()).hexdigest()
    archived = archive / "reviews" / f"review-issue-2067.{digest[:12]}.json"
    assert archived.is_file(), f"no durable copy at {archived}"
    assert json.loads(archived.read_text(encoding="utf-8")) == _payload(2067)


@pytest.mark.parametrize(
    "body_dir",
    ["reviews", "implementations", "intent-reviews", "validation", "optimization"],
)
def test_every_policy_local_body_directory_is_archived(tmp_path, monkeypatch, body_dir):
    """All five gitignored directories, not just the one the fix was written for."""
    artifact_archive, common, _ = _seam()
    archive = tmp_path / "archive"
    monkeypatch.setenv(artifact_archive.ARCHIVE_DIR_ENV, str(archive))

    body = tmp_path / "repo" / "agent-runtime" / "artifacts" / body_dir / "thing-issue-7.json"
    common.write_json(body, {"issue": 7})

    assert list((archive / body_dir).glob("thing-issue-7.*.json"))


def test_tracked_and_unrelated_artifacts_are_not_archived(tmp_path, monkeypatch):
    """status/ is tracked and already durable; audits and caches are not bodies."""
    artifact_archive, common, _ = _seam()
    archive = tmp_path / "archive"
    monkeypatch.setenv(artifact_archive.ARCHIVE_DIR_ENV, str(archive))

    artifacts = tmp_path / "repo" / "agent-runtime" / "artifacts"
    common.write_json(artifacts / "status" / "issue-2067.json", {"issue": 2067})
    common.write_json(artifacts / "waves" / "wave-1.json", {"wave": 1})
    common.write_json(tmp_path / "repo" / "somewhere" / "else.json", {"x": 1})

    assert not archive.exists(), "archive should hold bodies only, nothing else"


def test_distinct_versions_of_one_body_are_both_kept(tmp_path, monkeypatch):
    """A re-review must not overwrite the evidence the first review stood on."""
    artifact_archive, common, _ = _seam()
    archive = tmp_path / "archive"
    monkeypatch.setenv(artifact_archive.ARCHIVE_DIR_ENV, str(archive))

    body = _body_path(tmp_path / "repo", 2067)
    common.write_json(body, _payload(2067, "first pass"))
    common.write_json(body, _payload(2067, "second pass"))

    archived = sorted((archive / "reviews").glob("review-issue-2067.*.json"))
    assert len(archived) == 2
    summaries = {json.loads(p.read_text(encoding="utf-8"))["summary"] for p in archived}
    assert summaries == {"first pass", "second pass"}


def test_re_emitting_identical_content_is_idempotent(tmp_path, monkeypatch):
    artifact_archive, common, _ = _seam()
    archive = tmp_path / "archive"
    monkeypatch.setenv(artifact_archive.ARCHIVE_DIR_ENV, str(archive))

    body = _body_path(tmp_path / "repo", 2067)
    common.write_json(body, _payload(2067))
    common.write_json(body, _payload(2067))

    assert len(list((archive / "reviews").glob("review-issue-2067.*.json"))) == 1


def test_unarchivable_body_fails_loudly_at_emit_time(tmp_path, monkeypatch):
    """A body that cannot be archived must break the write, not warn under it.

    Emit time is the only moment the body is still reproducible. Swallowing the
    error here is what produces a green log and an empty archive -- the exact
    shape of the 2026-09-21 loss, discovered weeks later.
    """
    artifact_archive, common, _ = _seam()
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setenv(artifact_archive.ARCHIVE_DIR_ENV, str(blocker))

    with pytest.raises(artifact_archive.ArtifactArchiveError):
        common.write_json(_body_path(tmp_path / "repo", 2067), _payload(2067))


# ---------------------------------------------------------------------------
# The incident itself, reproduced against real git.
# ---------------------------------------------------------------------------


def test_archive_default_location_is_shared_by_every_worktree(tmp_path):
    """The default archive sits under the COMMON git dir, not the worktree's own.

    `git worktree remove` deletes `.git/worktrees/<name>`; anything archived
    there would die with the worktree it was meant to outlive.
    """
    artifact_archive, _, _ = _seam()
    main = tmp_path / "main"
    _init_repo(main)
    linked = tmp_path / "wt"
    _git("worktree", "add", "-q", "-b", "slice", str(linked), cwd=main)

    from_main = artifact_archive.archive_root(main)
    from_linked = artifact_archive.archive_root(linked)

    assert from_main == from_linked
    assert from_linked.resolve() == (main / ".git" / "artifact-archive").resolve()
    assert "worktrees" not in from_linked.parts


def test_archived_body_survives_real_worktree_removal(tmp_path):
    """The whole point: remove the worktree, keep the evidence.

    This is the 2026-09-21 incident replayed end to end -- gitignored body,
    linked worktree, `git worktree remove`. It fails if the archive step is
    removed from `common.write_json`.
    """
    artifact_archive, common, _ = _seam()
    main = tmp_path / "main"
    _init_repo(main)
    linked = tmp_path / "wt"
    _git("worktree", "add", "-q", "-b", "slice", str(linked), cwd=main)

    body = _body_path(linked, 1701)
    common.write_json(body, _payload(1701, "evidence that must outlive the worktree"))
    digest = hashlib.sha256(body.read_bytes()).hexdigest()

    # The body really is invisible to git -- this is why `git fsck` could not
    # recover the five lost records.
    assert _git("check-ignore", "-q", str(body.relative_to(linked)), cwd=linked) == ""

    _git("worktree", "remove", "--force", str(linked), cwd=main)
    assert not body.exists(), "precondition: worktree removal really did delete the body"

    archived = artifact_archive.archived_copy_path(
        artifact_archive.body_relative_path(body), digest, artifact_archive.archive_root(main)
    )
    assert archived.is_file(), (
        "the emitted body exists nowhere after worktree removal — this is the "
        "data-loss failure mode #2067 exists to close"
    )
    assert json.loads(archived.read_text(encoding="utf-8"))["summary"] == (
        "evidence that must outlive the worktree"
    )


# ---------------------------------------------------------------------------
# The backstop: pre-removal guard.
# ---------------------------------------------------------------------------


def test_guard_fails_on_a_worktree_holding_an_unarchived_body(tmp_path):
    _, _, guard = _seam()
    main = tmp_path / "main"
    _init_repo(main)

    body = _body_path(main, 1748)
    body.parent.mkdir(parents=True, exist_ok=True)
    body.write_text(json.dumps(_payload(1748)), encoding="utf-8")  # written behind the writer

    at_risk = guard.unarchived_bodies(main)
    assert [p.name for p in at_risk] == ["review-issue-1748.json"]
    assert guard.main(["--worktree", str(main)]) == 1


def test_guard_passes_once_the_body_is_archived(tmp_path):
    artifact_archive, _, guard = _seam()
    main = tmp_path / "main"
    _init_repo(main)

    body = _body_path(main, 1748)
    body.parent.mkdir(parents=True, exist_ok=True)
    body.write_text(json.dumps(_payload(1748)), encoding="utf-8")
    artifact_archive.archive_body(body)

    assert guard.unarchived_bodies(main) == []
    assert guard.main(["--worktree", str(main)]) == 0


def test_guard_repairs_with_archive_flag(tmp_path):
    _, _, guard = _seam()
    main = tmp_path / "main"
    _init_repo(main)

    body = _body_path(main, 1977)
    body.parent.mkdir(parents=True, exist_ok=True)
    body.write_text(json.dumps(_payload(1977)), encoding="utf-8")

    assert guard.main(["--worktree", str(main), "--archive"]) == 1
    assert guard.unarchived_bodies(main) == []
    assert guard.main(["--worktree", str(main)]) == 0


def test_guard_sees_bodies_git_status_collapses_into_one_directory_line(tmp_path):
    """`git status` reports a wholly-ignored directory as one `dir/` entry.

    A guard that only looked at the literal status lines would count that as one
    path and miss every file under it -- the same invisibility that made the
    directories easy to overlook in the first place.
    """
    _, _, guard = _seam()
    main = tmp_path / "main"
    _init_repo(main)

    for issue in (1540, 1608, 1701):
        body = _body_path(main, issue)
        body.parent.mkdir(parents=True, exist_ok=True)
        body.write_text(json.dumps(_payload(issue)), encoding="utf-8")

    assert len(guard.unarchived_bodies(main)) == 3


# ---------------------------------------------------------------------------
# Policy list must not drift from the resolver's or from .gitignore.
# ---------------------------------------------------------------------------


def test_body_dir_names_match_the_ref_resolver_and_real_gitignore():
    artifact_archive, _, _ = _seam()
    import artifact_ref_resolution

    from_resolver = {
        d.removeprefix("agent-runtime/artifacts/").rstrip("/")
        for d in artifact_ref_resolution.POLICY_LOCAL_BODY_DIRS
    }
    assert set(artifact_archive.BODY_DIR_NAMES) == from_resolver

    for name in artifact_archive.BODY_DIR_NAMES:
        probe = f"agent-runtime/artifacts/{name}/probe-issue-1.json"
        proc = subprocess.run(
            ["git", "check-ignore", "-q", probe],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"{probe} is not gitignored on the real tree"
