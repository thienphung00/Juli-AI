"""Deterministic upstream fingerprints for workflow prompt cache staleness gates."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Callable

EXECUTION_MD = "EXECUTION.md"
GITHUB_ISSUE_PATH_RE = re.compile(r"^GitHub issue #(\d+)$")


def git_blob_hash(content: bytes) -> str:
    """Git object hash for a blob (matches ``git hash-object``)."""
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def github_issue_body_hash(body: str) -> str:
    """First 16 hex chars of SHA-256 over ``gh issue view`` body text."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def extract_execution_slice(content: str, slice_id: str) -> str:
    """Return the ``##`` section of EXECUTION.md that contains ``slice_id``."""
    lines = content.splitlines(keepends=True)
    marker = re.compile(rf"\*\*{re.escape(slice_id)}\*\*")
    slice_line = next((index for index, line in enumerate(lines) if marker.search(line)), None)
    if slice_line is None:
        return content

    section_start = 0
    for index in range(slice_line, -1, -1):
        if lines[index].startswith("## "):
            section_start = index
            break

    section_end = len(lines)
    for index in range(section_start + 1, len(lines)):
        if lines[index].startswith("## "):
            section_end = index
            break

    return "".join(lines[section_start:section_end])


def execution_content_for_fingerprint(
    repo_root: Path,
    slice_id: str | None,
) -> bytes:
    path = repo_root / EXECUTION_MD
    if not path.exists():
        raise FileNotFoundError(f"{EXECUTION_MD} not found under {repo_root}")
    text = path.read_text(encoding="utf-8")
    if slice_id:
        text = extract_execution_slice(text, slice_id)
    return text.encode("utf-8")


def repo_file_blob_hash(repo_root: Path, relative_path: str) -> str:
    path = repo_root / relative_path
    if not path.exists():
        raise FileNotFoundError(f"Upstream file missing: {relative_path}")
    return git_blob_hash(path.read_bytes())


def default_fetch_github_issue_body(issue_id: int, repo_root: Path) -> str:
    try:
        output = subprocess.check_output(
            ["gh", "issue", "view", str(issue_id), "--json", "body", "-q", ".body"],
            cwd=repo_root,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or str(exc)).strip()
        raise RuntimeError(f"gh issue view #{issue_id} failed: {detail}") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("gh CLI not found; required for GitHub issue fingerprints") from exc
    return output


def default_fetch_github_issue_labels(issue_id: int, repo_root: Path) -> list[str]:
    """Return GitHub issue label names via ``gh`` (empty list if none)."""
    try:
        output = subprocess.check_output(
            [
                "gh",
                "issue",
                "view",
                str(issue_id),
                "--json",
                "labels",
                "-q",
                "[.labels[].name]",
            ],
            cwd=repo_root,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or str(exc)).strip()
        raise RuntimeError(f"gh issue view #{issue_id} labels failed: {detail}") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("gh CLI not found; required for GitHub issue labels") from exc
    names = json.loads(output or "[]")
    if not isinstance(names, list):
        raise RuntimeError(f"unexpected labels payload for #{issue_id}: {names!r}")
    return [str(name) for name in names]


IssueBodyFetcher = Callable[[int], str]


def fingerprint_for_path(
    path: str,
    *,
    repo_root: Path,
    slice_id: str | None = None,
    issue_body_fetcher: IssueBodyFetcher,
) -> str:
    issue_match = GITHUB_ISSUE_PATH_RE.match(path)
    if issue_match:
        body = issue_body_fetcher(int(issue_match.group(1)))
        return github_issue_body_hash(body)
    if path == EXECUTION_MD:
        return git_blob_hash(execution_content_for_fingerprint(repo_root, slice_id))
    return repo_file_blob_hash(repo_root, path)


def build_parent_upstream_fingerprints(
    *,
    parent_issue_id: int,
    handoff_path: str,
    slice_id: str | None,
    repo_root: Path,
    issue_body_fetcher: IssueBodyFetcher,
) -> list[dict[str, str]]:
    entries = [
        {"path": f"GitHub issue #{parent_issue_id}", "source": "github_issue"},
        {"path": handoff_path, "source": "repo_file"},
        {"path": EXECUTION_MD, "source": "execution_slice" if slice_id else "repo_file"},
    ]
    return [
        {
            "path": entry["path"],
            "fingerprint": fingerprint_for_path(
                entry["path"],
                repo_root=repo_root,
                slice_id=slice_id if entry["path"] == EXECUTION_MD else None,
                issue_body_fetcher=issue_body_fetcher,
            ),
        }
        for entry in entries
    ]


def build_child_upstream_fingerprints(
    *,
    issue_id: int,
    scope_alignment_path: str,
    repo_root: Path,
    issue_body_fetcher: IssueBodyFetcher,
) -> list[dict[str, str]]:
    return [
        {
            "path": f"GitHub issue #{issue_id}",
            "fingerprint": fingerprint_for_path(
                f"GitHub issue #{issue_id}",
                repo_root=repo_root,
                issue_body_fetcher=issue_body_fetcher,
            ),
        },
        {
            "path": scope_alignment_path,
            "fingerprint": fingerprint_for_path(
                scope_alignment_path,
                repo_root=repo_root,
                issue_body_fetcher=issue_body_fetcher,
            ),
        },
    ]


def compare_fingerprints(
    cached: list[dict[str, str]],
    live: list[dict[str, str]],
) -> list[dict[str, str]]:
    live_by_path = {entry["path"]: entry["fingerprint"] for entry in live}
    mismatches: list[dict[str, str]] = []
    for entry in cached:
        path = entry["path"]
        expected = entry["fingerprint"]
        actual = live_by_path.get(path)
        if actual is None:
            mismatches.append(
                {
                    "path": path,
                    "expected": expected,
                    "actual": None,
                    "reason": "missing live fingerprint",
                }
            )
            continue
        if actual != expected:
            mismatches.append(
                {
                    "path": path,
                    "expected": expected,
                    "actual": actual,
                    "reason": "fingerprint mismatch",
                }
            )
    return mismatches


def fingerprints_to_json(entries: list[dict[str, str]]) -> str:
    return json.dumps(entries, indent=2)
