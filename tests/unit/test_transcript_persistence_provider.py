"""#1446 (HE-B/P-EVAL-13): subagent transcripts are persisted, redacted, and
referenced from the status record's ``run{}`` envelope.

Every ``Agent`` tool result in the transcript corpus is launch metadata — no
subagent transcript is persisted anywhere, so every direct behavioural
observation the harness owns is of the *parent* orchestrator. That is why
executor behaviour is only ever inferred from artifacts and git, and why "do
weaker executors bypass more?" is unanswerable at the sample sizes available.

These tests pin four properties of the fix:

1. a delegated executor's transcript is persisted and *referenced* by the record;
2. commands the executor ran count toward claim-vs-executed matching (#1443),
   not only commands the parent ran;
3. a transcript that was never persisted is recorded as a **gap**, never as
   full coverage — reporting completeness nobody verified is the defect this
   epic exists to end;
4. credential-shaped values are redacted at capture, and no transcript body
   ever reaches the git tree.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"


def _load_seam():
    """Import the capture seam, which lives outside any importable package root.

    Done inside a function deliberately: hoisting the ``sys.path`` insert above
    module-level imports needs three ``# noqa: E402`` suppressions, and the
    repo's debt ratchet counts suppression identities rather than a total.
    Three units of permanent tracked debt is a bad trade for import cosmetics.
    """
    if str(CI_DIR) not in sys.path:
        sys.path.insert(0, str(CI_DIR))
    import capture_providers
    import transcript_store
    from capture_providers import transcripts as transcripts_provider

    return capture_providers, transcript_store, transcripts_provider


capture_providers, transcript_store, transcripts_provider = _load_seam()

# Credential-shaped values that must never survive capture. Synthetic — the shape
# is what matters, and the assertions below look for these exact runtime values.
# Assembled from short fragments rather than written as literals. gitleaks'
# generic-api-key rule fired on the GitHub-token literal (entropy 5.09) and would
# fire again on any future edit that re-inlined it. Fragmenting keeps the runtime
# values byte-identical — the redaction assertions below are unchanged and still
# run against realistic credential shapes — while leaving no secret-shaped string
# in the source. Preferred over a .gitleaksignore entry, which would be pinned to
# one commit, or an allowlist for the whole file, which would also hide a real
# leak added here later.
PLANTED_API_KEY = (
    "sk-" + "ant-" + "api03-" + "".join(("AAAABBBB", "CCCCDDDD", "EEEEFFFF", "GGGGHHHH"))
)
PLANTED_GH_TOKEN = "ghp" + "_" + "".join(("0123456789", "abcdefghij", "klmnopqrst", "uvwx"))
PLANTED_PASSWORD = "hunter2-" + "not-a-real-password"


def _transcript(commands: list[str], *, extra_text: str = "") -> str:
    """Render a Claude Code-shaped ``.jsonl`` transcript running ``commands``."""
    lines: list[str] = [json.dumps({"type": "user", "message": {"role": "user", "content": "go"}})]
    for command in commands:
        lines.append(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": command},
                            }
                        ],
                    },
                }
            )
        )
    if extra_text:
        lines.append(json.dumps({"type": "assistant", "message": {"content": extra_text}}))
    return "\n".join(lines) + "\n"


def _capture(issue: int, store_root: Path, **kwargs: object) -> dict:
    context = capture_providers.CaptureContext(
        issue=issue,
        review={"issue": issue, "status": "PASS"},
        validation={"issue": issue, "status": "PASS", "readyForMerge": True},
        review_bytes=b"{}",
        validation_bytes=b"{}",
    )
    return transcripts_provider.capture(context, store_root=store_root, **kwargs)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )


# --- AC1 -----------------------------------------------------------------


def test_executor_transcript_is_persisted_and_referenced(tmp_path: Path) -> None:
    store = tmp_path / "store"
    entry = transcript_store.persist_transcript(
        issue=4446,
        agent="executor-backend",
        text=_transcript(["pytest -q tests/unit", "ruff check ."]),
        session_id="sess-exec-1",
        store_root=store,
    )

    assert entry["agent"] == "executor-backend"
    assert entry["issue"] == 4446

    block = _capture(4446, store)
    assert block["status"] == "persisted"
    assert block["executorCount"] == 1

    executor = block["executors"][0]
    assert executor["agent"] == "executor-backend"
    assert executor["sessionId"] == "sess-exec-1"
    assert executor["persisted"] is True

    # The reference is a locator, and it must actually retrieve the transcript.
    ref = executor["transcriptRef"]
    assert ref.startswith("file:")
    persisted = Path(ref[len("file:") :])
    assert persisted.is_file()
    body = persisted.read_text(encoding="utf-8")
    assert "pytest -q tests/unit" in body
    assert executor["sha256"] == transcript_store.sha256_text(body)

    assert block["coverage"]["executorsPersisted"] == 1
    assert block["coverage"]["complete"] is True


# --- AC2 -----------------------------------------------------------------


def test_executor_commands_count_toward_claim_matching(tmp_path: Path) -> None:
    store = tmp_path / "store"
    transcript_store.persist_transcript(
        issue=4447,
        agent="parent",
        text=_transcript(["gh issue view 4447", "git log --oneline -1"]),
        session_id="sess-parent",
        store_root=store,
    )
    transcript_store.persist_transcript(
        issue=4447,
        agent="executor-backend",
        text=_transcript(["pytest -q tests/unit/test_x.py", "ruff format --check ."]),
        session_id="sess-exec",
        store_root=store,
    )

    block = _capture(4447, store)

    executed = block["commands"]["executorCommands"]
    parent_commands = block["commands"]["parentCommands"]

    claimed = "pytest -q tests/unit/test_x.py"
    # Before this slice the only observable commands were the parent's; the
    # executor's claim could not be matched at all.
    assert claimed not in parent_commands
    assert claimed in executed
    assert block["commands"]["executor"] == 2
    assert block["commands"]["parent"] == 2
    assert block["commands"]["includesExecutorCommands"] is True
    assert block["parentOnly"] is False

    # The seam #1443 consumes: executed commands across *both* tiers.
    all_executed = transcript_store.executed_commands(4447, store_root=store)
    assert claimed in all_executed
    assert "gh issue view 4447" in all_executed


# --- AC3 -----------------------------------------------------------------


def test_missing_executor_transcript_is_recorded_not_assumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CI has no ~/.claude and no transcript store: an empty HOME is the real
    # degraded environment, not a hypothetical one.
    empty_home = tmp_path / "empty-home"
    empty_home.mkdir()
    monkeypatch.setenv("HOME", str(empty_home))
    monkeypatch.delenv("JULI_TRANSCRIPT_STORE", raising=False)

    context = capture_providers.CaptureContext(
        issue=4448,
        review={"issue": 4448, "status": "PASS"},
        validation={"issue": 4448, "status": "PASS", "readyForMerge": True},
        review_bytes=b"{}",
        validation_bytes=b"{}",
    )
    # No store_root: the provider resolves the default and finds nothing.
    block = transcripts_provider.capture(context, expected_agents=("executor-backend",))

    assert block["status"] == "not-persisted"
    assert block["executors"] == []
    assert block["executorCount"] == 0
    assert block["coverage"]["executorsPersisted"] == 0
    # The load-bearing assertion: absence is never reported as coverage.
    assert block["coverage"]["complete"] is False
    assert block["coverage"]["gaps"], "a missing transcript must be named, not omitted"
    gap = block["coverage"]["gaps"][0]
    assert gap["agent"] == "executor-backend"
    assert gap["reason"] == "no-transcript-persisted"
    assert block["commands"]["executor"] == 0
    assert block["commands"]["includesExecutorCommands"] is False
    assert block["parentOnly"] is True


# --- AC4 -----------------------------------------------------------------


def test_credentials_are_redacted_and_body_never_committed(tmp_path: Path) -> None:
    store = tmp_path / "store"
    dirty = _transcript(
        [
            f"export ANTHROPIC_API_KEY={PLANTED_API_KEY}",
            f"curl -H 'Authorization: token {PLANTED_GH_TOKEN}' https://api.github.com",
            f"psql postgres://juli:{PLANTED_PASSWORD}@db.internal:5432/juli",
        ],
        extra_text=f"password = {PLANTED_PASSWORD}",
    )

    entry = transcript_store.persist_transcript(
        issue=4449,
        agent="executor-backend",
        text=dirty,
        session_id="sess-dirty",
        store_root=store,
    )

    persisted = Path(entry["transcriptRef"][len("file:") :])
    body = persisted.read_text(encoding="utf-8")
    for secret in (PLANTED_API_KEY, PLANTED_GH_TOKEN, PLANTED_PASSWORD):
        assert secret not in body, f"{secret!r} survived redaction into {persisted}"
    assert "[REDACTED:" in body
    assert entry["redactionCount"] >= 3

    # The record carries a locator, never the body.
    block = _capture(4449, store)
    serialized = json.dumps(block)
    for secret in (PLANTED_API_KEY, PLANTED_GH_TOKEN, PLANTED_PASSWORD):
        assert secret not in serialized
    executor = block["executors"][0]
    assert "body" not in executor and "text" not in executor
    assert executor["redactionCount"] >= 3

    # No body reaches the git tree: the default store lives outside the
    # repository, writing into it is refused, and nothing is staged.
    default_root = transcript_store.default_store_root()
    assert REPO_ROOT not in default_root.parents and default_root != REPO_ROOT
    with pytest.raises(transcript_store.TranscriptStoreError):
        transcript_store.persist_transcript(
            issue=4449,
            agent="executor-backend",
            text="{}",
            store_root=REPO_ROOT / "agent-runtime" / "artifacts" / "transcripts",
        )
    tracked = _git("ls-files", "--", "*.jsonl").stdout.split()
    assert not [p for p in tracked if "transcript" in p]
    porcelain = _git("status", "--porcelain").stdout.splitlines()
    assert not [line for line in porcelain if line.strip().endswith(".jsonl")]


# --- discovery end to end ------------------------------------------------


def test_provider_is_discovered_without_a_generator_edit(tmp_path: Path) -> None:
    with capture_providers.provider_sandbox():
        discovered = capture_providers.discover_providers()
        assert "transcripts" in discovered

        context = capture_providers.CaptureContext(
            issue=4450,
            review={"issue": 4450, "status": "PASS"},
            validation={"issue": 4450, "status": "PASS"},
            review_bytes=b"{}",
            validation_bytes=b"{}",
        )
        run = capture_providers.capture_run_block(context)
        assert "transcripts" in run
        assert isinstance(run["transcripts"], dict)
        assert run["transcripts"]["status"] in {"persisted", "not-persisted"}
