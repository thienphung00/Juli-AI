"""The wave-manifest merge driver resolves a union and refuses anything else (#1731).

Every slice appends its own issue id to the wave manifest, so two concurrent
slices always conflict there and the resolution is always the sorted union. It
was done by hand at least six times in one working day, and a wrong resolution
silently drops a slice out of the wave -- the manifest is what `policy-checks`
reads to decide whether an issue belongs.

The driver must therefore be narrow: it owns the issues list and nothing else.
A disagreement about which wave the file describes is a real conflict, and
unioning it would paper over the question.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _driver():
    sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "git"))
    import merge_wave_manifest

    return merge_wave_manifest


def _manifest(issues: list[int], **overrides: object) -> dict:
    base = {
        "schemaVersion": "1.0.0",
        "artifactType": "wave_manifest",
        "waveId": "wave-harness-e-w5",
        "branch": "feature/harness-e-w5-wave",
        "issues": issues,
    }
    base.update(overrides)
    return base


def test_two_slices_each_appending_their_own_id_merge_to_the_union() -> None:
    """The case that actually happens, six times in one day."""
    merged = _driver().merge_manifests(
        _manifest([1436, 1459]),
        _manifest([1436, 1459, 1569]),
        _manifest([1436, 1459, 1734]),
    )

    assert merged is not None
    assert merged["issues"] == [1436, 1459, 1569, 1734]
    assert merged["waveId"] == "wave-harness-e-w5"


def test_a_disagreement_outside_the_issues_list_is_left_conflicted() -> None:
    """Two sides claiming different waves is a real question, not a union.

    Resolving it silently would merge one wave's manifest into another's and
    nothing downstream would notice.
    """
    merged = _driver().merge_manifests(
        _manifest([1]),
        _manifest([1, 2], waveId="wave-harness-e-w5"),
        _manifest([1, 3], waveId="wave-harness-e-w6"),
    )

    assert merged is None


def test_a_non_integer_id_is_left_conflicted() -> None:
    """Fail closed on anything the driver cannot vouch for."""
    assert _driver().merge_manifests(_manifest([1]), _manifest([1, 2]), _manifest([1, "3"])) is None


def test_a_missing_issues_list_is_left_conflicted() -> None:
    ours = _manifest([1])
    del ours["issues"]
    assert _driver().merge_manifests(_manifest([1]), ours, _manifest([1, 2])) is None


def test_the_driver_resolves_a_real_git_merge(tmp_path: Path) -> None:
    """End to end through git itself, not just the function.

    A driver that merges correctly in a unit test and is never invoked by git
    would leave the conflict exactly where it was.
    """
    import subprocess

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout

    rel = "agent-runtime/artifacts/waves/wave-harness-e-w5.json"
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "T")
    driver = REPO_ROOT / "agent-runtime" / "scripts" / "git" / "merge_wave_manifest.py"
    git("config", "merge.wave-manifest.driver", f"{sys.executable} {driver} %O %A %B")
    (tmp_path / ".gitattributes").write_text(f"{rel} merge=wave-manifest\n", encoding="utf-8")

    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)

    def write(issues: list[int]) -> None:
        path.write_text(json.dumps(_manifest(issues), indent=2) + "\n", encoding="utf-8")

    write([1436])
    git("add", "-A")
    git("commit", "-qm", "base", "--no-gpg-sign")

    git("checkout", "-qb", "slice-a")
    write([1436, 1569])
    git("commit", "-qam", "slice a", "--no-gpg-sign")

    git("checkout", "-q", "main")
    git("checkout", "-qb", "slice-b")
    write([1436, 1734])
    git("commit", "-qam", "slice b", "--no-gpg-sign")

    # Without the driver this is a textual conflict; with it, a clean merge.
    subprocess.run(
        ["git", "merge", "slice-a", "-m", "merge"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(path.read_text())["issues"] == [1436, 1569, 1734]
    assert "<<<<<<<" not in path.read_text()
