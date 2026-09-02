"""#1441 (HE-B/P-EVAL-6): run metrics are measured, not typed.

Three executors independently reported that ``tokenUsage`` and
``executionDurationMs`` are unobtainable from an executor process, and the
slice was set aside on their word. They were wrong. Subagent transcripts *are*
persisted, at ``<session-temp>/tasks/<agentId>.output`` — the one location the
harness's transcript discovery never looks in. That is precisely where a metric
must come from: a place the agent being measured cannot write.

Every test here plants a lie and asserts the provider catches it. A
happy-path-only suite would be an instance of the defect class this slice
exists to close.

Two lies are load-bearing and worth naming:

**The duplicate-usage lie.** A single assistant message is written to the
transcript once per content block, each copy carrying the *same* ``usage``
object. Summing rows rather than messages overcounts by roughly 2x — measured
on a real transcript, 201 usage rows for 91 distinct message ids, turning
10,588,988 real tokens into 22,563,409. A naive implementation passes every
other test in this file and reports a confident, wrong number.
``test_metrics_are_read_from_the_persisted_transcript`` plants exactly that.

**The zero lie.** With no transcript there is nothing to report, and the only
honest shape carries *no* ``value`` key at all — so a consumer that skips the
``available`` check gets a ``KeyError`` rather than a plausible number. A zero
is exactly as unsourceable as 1,800,000 and is the more convincing of the two.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"


def _load_seam():
    """Import the capture seam, which lives outside any importable package root.

    Done inside a function deliberately: hoisting the ``sys.path`` insert above
    module-level imports needs ``# noqa: E402`` suppressions, and the repo's
    debt ratchet counts suppression identities. Paying tracked debt for import
    cosmetics is a bad trade.
    """
    if str(CI_DIR) not in sys.path:
        sys.path.insert(0, str(CI_DIR))
    import capture_providers
    import task_transcripts
    from capture_providers import run_metrics

    return capture_providers, run_metrics, task_transcripts


_seam, run_metrics, task_transcripts = _load_seam()

CaptureContext = _seam.CaptureContext
capture_run_block = _seam.capture_run_block
discover_providers = _seam.discover_providers
provider_sandbox = _seam.provider_sandbox

ISSUE = 1441
BRANCH = f"feature/issue-{ISSUE}-measured-run-metrics"
FOREIGN_BRANCH = "feature/issue-9999-someone-elses-work"


# ---------------------------------------------------------------------------
# Fake transcript construction — the real on-disk shape, built by hand.
# ---------------------------------------------------------------------------


def _assistant(
    *,
    message_id: str,
    agent_id: str,
    branch: str,
    timestamp: str,
    usage: dict[str, int],
    tools: tuple[str, ...] = (),
    worktree: str | None = None,
) -> dict:
    content: list[dict] = [{"type": "text", "text": "..."}]
    # tool_use ids are unique per invocation on disk, which is what lets the
    # provider dedupe a message repeated across rows without losing a call.
    tool_input = {"command": f"ls /repo/.worktrees/{worktree}"} if worktree else {}
    content += [
        {
            "type": "tool_use",
            "name": name,
            "id": f"tu_{message_id}_{index}_{name}",
            "input": dict(tool_input),
        }
        for index, name in enumerate(tools)
    ]
    return {
        "type": "assistant",
        "agentId": agent_id,
        "sessionId": "session-under-test",
        "gitBranch": branch,
        "isSidechain": True,
        "timestamp": timestamp,
        "message": {"id": message_id, "role": "assistant", "content": content, "usage": usage},
    }


def _usage(inp: int, out: int, cache_creation: int, cache_read: int) -> dict[str, int]:
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
    }


def _split_across_blocks(record: dict, copies: int) -> list[dict]:
    """One assistant message written ``copies`` times, usage repeated verbatim.

    This is the real on-disk shape, not a contrivance: the transcript writes a
    row per content block and each row carries the whole message's usage.
    """
    return [json.loads(json.dumps(record)) for _ in range(copies)]


_SLOT = itertools.count()


def _write_tasks(
    tmp_path: Path, files: dict[str, list[dict] | str], *, in_flight: bool = False
) -> tuple[Path, Path]:
    """Lay out ``<base>/claude-<uid>/<slug>/<session>/tasks/<agent>.output``.

    Returns ``(base, repo_root)``. The real directory layout is built so
    discovery is exercised end to end rather than handed the answer. Each call
    gets a fresh base, so a test that captures twice cannot have the second
    reading contaminated by the first one's files.
    """
    repo_root = tmp_path / "checkout" / "Juli-AI-v2"
    repo_root.mkdir(parents=True, exist_ok=True)
    base = tmp_path / f"tempbase-{next(_SLOT)}"
    slug = task_transcripts.project_slug(repo_root)
    tasks = base / "claude-501" / slug / "session-under-test" / "tasks"
    tasks.mkdir(parents=True)
    for name, body in files.items():
        if isinstance(body, str):
            (tasks / name).write_text(body, encoding="utf-8")
        else:
            (tasks / name).write_text(
                "\n".join(json.dumps(record) for record in body) + "\n", encoding="utf-8"
            )
    if not in_flight:
        # Backdate, so these read as finished runs. A freshly written file is by
        # definition still in flight, and every test that wants a *measurement*
        # needs a settled one.
        for path in tasks.glob("*.output"):
            os.utime(path, (0, 0))
    return base, repo_root


def _context(review: dict | None = None) -> CaptureContext:
    review = review or {"issueId": ISSUE, "status": "PASS"}
    return CaptureContext(
        issue=ISSUE,
        review=review,
        validation={"issueId": ISSUE, "status": "PASS"},
        review_bytes=json.dumps(review).encode(),
        validation_bytes=b"{}",
    )


def _capture(tmp_path: Path, files, *, claims: dict | None = None) -> dict:
    base, repo_root = _write_tasks(tmp_path, files)
    return run_metrics.capture(
        _context(),
        repo_root=repo_root,
        temp_bases=(str(base),),
        environ={},
        claims=claims,
    )


# ---------------------------------------------------------------------------


def test_metrics_are_read_from_the_persisted_transcript(tmp_path: Path) -> None:
    """Token usage, tool count and duration come off disk; usage is per message.

    The lie: the same assistant message appears three times, once per content
    block, each copy carrying the full usage. An implementation that sums rows
    reports 3x the truth and looks entirely plausible doing it.
    """
    first = _assistant(
        message_id="msg_a",
        agent_id="agent-one",
        branch=BRANCH,
        timestamp="2026-09-02T01:00:00.000Z",
        usage=_usage(10, 20, 300, 4000),
        tools=("Bash", "Edit"),
        worktree=f"w3-{ISSUE}",
    )
    second = _assistant(
        message_id="msg_b",
        agent_id="agent-one",
        branch=BRANCH,
        timestamp="2026-09-02T01:00:30.000Z",
        usage=_usage(1, 2, 3, 4),
        tools=("Bash",),
        worktree=f"w3-{ISSUE}",
    )
    records = _split_across_blocks(first, 3) + _split_across_blocks(second, 2)

    block = _capture(tmp_path, {"agent-one.output": records})

    assert block["status"] == "measured"
    tokens = block["tokenUsage"]
    assert tokens["available"] is True
    assert tokens["observedFrom"] == "task-transcript"

    # Per message, not per row. Summing rows would give 3x + 2x of this.
    assert tokens["value"] == {
        "input": 11,
        "output": 22,
        "cacheCreation": 303,
        "cacheRead": 4004,
        "total": 4340,
    }

    # tool_use blocks are counted per row as written — but the message dedup
    # must not silently swallow them either, so assert the exact figure.
    assert block["toolInvocationCount"]["available"] is True
    assert block["toolInvocationCount"]["value"] == 3
    assert block["toolsUsed"] == [
        {"toolName": "Bash", "count": 2},
        {"toolName": "Edit", "count": 1},
    ]

    assert block["executionDurationMs"]["available"] is True
    assert block["executionDurationMs"]["value"] == 30_000

    assert block["source"]["kind"] == "task-transcript"
    assert block["agents"][0]["agentId"] == "agent-one"
    # A locator, never the body.
    assert block["agents"][0]["transcriptRef"].endswith("agent-one.output")


def test_the_assigned_executor_domain_travels_with_the_metrics(tmp_path: Path) -> None:
    """The domain is read from the artifact, and its absence is not invented."""
    records = [
        _assistant(
            message_id="m",
            agent_id="agent-one",
            branch=BRANCH,
            timestamp="2026-09-02T01:00:00.000Z",
            usage=_usage(1, 1, 1, 1),
            tools=("Bash",),
            worktree=f"w3-{ISSUE}",
        )
    ]

    block = _capture(
        tmp_path,
        {"agent-one.output": records},
        claims={"executorDomain": "backend", "issueId": ISSUE},
    )
    assert block["executorDomain"] == "backend"
    assert block["executorDomainSource"] == "implementation-artifact"

    # The lie: no domain anywhere. It must read as unknown, never as a guess.
    blank = _capture(tmp_path, {"agent-one.output": records}, claims={})
    assert blank["executorDomain"] is None
    assert blank["executorDomainSource"] == "unknown"


def test_measured_wins_and_disagreement_is_preserved(tmp_path: Path) -> None:
    """A self-reported figure loses to the measurement and is kept beside it."""
    records = [
        _assistant(
            message_id="msg_a",
            agent_id="agent-one",
            branch=BRANCH,
            timestamp="2026-09-02T01:00:00.000Z",
            usage=_usage(100, 200, 300, 400),
            tools=("Bash",),
            worktree=f"w3-{ISSUE}",
        ),
        _assistant(
            message_id="msg_b",
            agent_id="agent-one",
            branch=BRANCH,
            timestamp="2026-09-02T01:01:00.000Z",
            usage=_usage(0, 0, 0, 0),
            tools=("Bash", "Read"),
            worktree=f"w3-{ISSUE}",
        ),
    ]
    claims = {
        "executorDomain": "backend",
        "tokenUsage": {"input": 1, "output": 2, "total": 1_800_000},
        "toolInvocationCount": 42,
        "executionDurationMs": 900_000,
    }

    block = _capture(tmp_path, {"agent-one.output": records}, claims=claims)

    assert block["tokenUsage"]["value"]["total"] == 1000
    assert block["toolInvocationCount"]["value"] == 3
    assert block["executionDurationMs"]["value"] == 60_000

    by_field = {entry["field"]: entry for entry in block["disagreements"]}
    assert by_field["tokenUsage.total"]["claimed"] == 1_800_000
    assert by_field["tokenUsage.total"]["observed"] == 1000
    assert by_field["tokenUsage.total"]["resolution"] == "observed"
    assert by_field["toolInvocationCount"]["claimed"] == 42
    assert by_field["executionDurationMs"]["claimed"] == 900_000
    assert by_field["executionDurationMs"]["observed"] == 60_000

    # An agreeing claim produces no entry, so a non-empty list always means
    # something. The lie here would be a provider that lists every field.
    agreeing = _capture(
        tmp_path,
        {"agent-one.output": records},
        claims={"tokenUsage": {"total": 1000}, "toolInvocationCount": 3},
    )
    assert [entry["field"] for entry in agreeing["disagreements"]] == []


def test_absent_transcript_records_unavailable_not_zero(tmp_path: Path) -> None:
    """CI has no session temp dir. That state must be loud, and must not be 0.

    Simulates the CI shape exactly: the temp base exists but holds no session
    at all. The block must carry no ``value`` key, so a consumer that skips the
    ``available`` check crashes rather than reading an invented number.
    """
    repo_root = tmp_path / "checkout" / "Juli-AI-v2"
    repo_root.mkdir(parents=True)
    empty_base = tmp_path / "no-such-temp-base"

    block = run_metrics.capture(
        _context(),
        repo_root=repo_root,
        temp_bases=(str(empty_base),),
        environ={},
        claims=None,
    )

    assert block["status"] == "not-measured"
    for field in ("tokenUsage", "toolInvocationCount", "executionDurationMs"):
        measurement = block[field]
        assert measurement["available"] is False, field
        assert "value" not in measurement, field
        assert measurement["reason"]
        # The whole point: the absent path must be a KeyError, never a zero.
        with pytest.raises(KeyError):
            measurement["value"]

    assert block["agents"] == []
    assert block["gaps"], "an unmeasured run must name why it is unmeasured"

    # A number anywhere under a metric field would be the lie this test exists
    # for: the unmeasured block must carry no numeric reading at all.
    for field in ("tokenUsage", "toolInvocationCount", "executionDurationMs"):
        for key, value in block[field].items():
            assert not isinstance(value, (int, float)) or isinstance(value, bool), (field, key)


def test_a_foreign_issues_transcript_is_not_counted(tmp_path: Path) -> None:
    """Another issue's agent in the same session must not inflate this record."""
    mine = _assistant(
        message_id="msg_mine",
        agent_id="agent-mine",
        branch=BRANCH,
        timestamp="2026-09-02T01:00:00.000Z",
        usage=_usage(1, 1, 1, 1),
        tools=("Bash",),
        worktree=f"w3-{ISSUE}",
    )
    theirs = _assistant(
        message_id="msg_theirs",
        agent_id="agent-theirs",
        branch=FOREIGN_BRANCH,
        timestamp="2026-09-02T01:00:00.000Z",
        usage=_usage(1_000_000, 1_000_000, 1_000_000, 1_000_000),
        tools=("Bash", "Bash", "Bash"),
        worktree="w3-9999",
    )

    block = _capture(
        tmp_path,
        {"agent-mine.output": [mine], "agent-theirs.output": [theirs]},
    )

    assert [agent["agentId"] for agent in block["agents"]] == ["agent-mine"]
    assert block["tokenUsage"]["value"]["total"] == 4
    assert block["toolInvocationCount"]["value"] == 1


def test_the_worktree_path_attributes_an_agent_the_branch_cannot(tmp_path: Path) -> None:
    """The branch is the session's, not the agent's — measured on a live run.

    Six concurrent executors all recorded ``gitBranch: main`` while working in
    separate ``.worktrees/`` checkouts. Branch alone attributes none of them, so
    the tree an agent actually wrote to is the second signal.

    The lie planted here is the neighbour: an agent on the same ``main``, in
    ``w3-9999``, whose tokens must not land in this issue's total.
    """
    mine = _assistant(
        message_id="msg_mine",
        agent_id="agent-mine",
        branch="main",
        timestamp="2026-09-02T01:00:00.000Z",
        usage=_usage(1, 1, 1, 1),
        tools=("Bash",),
        worktree=f"w3-{ISSUE}",
    )
    neighbour = _assistant(
        message_id="msg_neighbour",
        agent_id="agent-neighbour",
        branch="main",
        timestamp="2026-09-02T01:00:00.000Z",
        usage=_usage(500_000, 500_000, 500_000, 500_000),
        tools=("Bash",),
        worktree="w3-9999",
    )
    # A worktree whose name merely *contains* the digits must not match either:
    # w3-14410 is a different issue, and a substring test would swallow it.
    lookalike = _assistant(
        message_id="msg_lookalike",
        agent_id="agent-lookalike",
        branch="main",
        timestamp="2026-09-02T01:00:00.000Z",
        usage=_usage(999, 999, 999, 999),
        tools=("Bash",),
        worktree=f"w3-{ISSUE}0",
    )

    block = _capture(
        tmp_path,
        {
            "agent-mine.output": [mine],
            "agent-neighbour.output": [neighbour],
            "agent-lookalike.output": [lookalike],
        },
    )

    assert [agent["agentId"] for agent in block["agents"]] == ["agent-mine"]
    assert block["agents"][0]["attributedBy"] == "worktreePath"
    assert block["tokenUsage"]["value"]["total"] == 4


def test_the_session_branch_never_outranks_a_contradicting_workspace(tmp_path: Path) -> None:
    """An agent on this issue's session branch, working someone else's tree.

    This inverts an earlier version of this test, which asserted ``gitBranch``
    was "the stronger claim". It is the weaker one, and asserting otherwise
    encoded the defect as an expectation.
    """
    interloper = _assistant(
        message_id="m",
        agent_id="agent-elsewhere",
        branch=BRANCH,
        timestamp="2026-09-02T01:00:00.000Z",
        usage=_usage(9_000_000, 0, 0, 0),
        tools=("Bash",),
        worktree="w3-1497",
    )
    block = _capture(tmp_path, {"agent-elsewhere.output": [interloper]})
    assert block["agents"] == []
    assert block["status"] == "not-measured"
    assert "value" not in block["tokenUsage"]


def test_prose_mentioning_the_issue_does_not_attribute_an_agent(tmp_path: Path) -> None:
    """A neighbour that only *talks* about this issue has done none of its work.

    The lie: the issue number all over the transcript text, and no tool call
    that ever touched the tree. A text match would credit it.
    """
    gossip = {
        "type": "assistant",
        "agentId": "agent-gossip",
        "sessionId": "session-under-test",
        "gitBranch": "main",
        "timestamp": "2026-09-02T01:00:00.000Z",
        "message": {
            "id": "msg_gossip",
            "content": [{"type": "text", "text": f"issue-{ISSUE} and .worktrees/w3-{ISSUE}"}],
            "usage": _usage(777_777, 0, 0, 0),
        },
    }
    block = _capture(tmp_path, {"agent-gossip.output": [gossip]})

    assert block["agents"] == []
    assert block["status"] == "not-measured"
    assert "value" not in block["tokenUsage"]


def test_a_shared_session_branch_does_not_attribute_every_concurrent_agent(
    tmp_path: Path,
) -> None:
    """The #1508 defect, in the exact shape it was reproduced in.

    ``gitBranch`` is a *session-wide* field, not the agent's. Measured on the
    live store while this slice was under review: five concurrent agents all
    recording BOTH ``main`` and ``feature/issue-1441-measured-run-metrics``,
    because one tree in the session moved onto that branch and the field
    flipped for everyone at once. Attributing on it summed a peer reviewer and
    three unrelated executors into this issue's total — 34,200,395 reported
    against 10,134,878 real, a 3.3x fabrication that grew in real time.

    The genuine executor is identifiable *only* by the tree it worked in. Two
    of the impostors here carry this test file's own fixture worktrees, which
    is how the reviewer's transcript acquired them: it read this file.
    """
    session_branch = BRANCH
    agents = {
        # The real executor: the only one that worked in this issue's tree.
        "agent-executor.output": [
            _assistant(
                message_id="m-exec",
                agent_id="agent-executor",
                branch=session_branch,
                timestamp="2026-09-02T01:00:00.000Z",
                usage=_usage(4, 6, 10, 80),
                tools=("Bash",),
                worktree=f"w3-{ISSUE}",
            )
        ],
        # A peer reviewer that merely read this file — hence the fixture names.
        "agent-reviewer.output": [
            _assistant(
                message_id="m-rev",
                agent_id="agent-reviewer",
                branch=session_branch,
                timestamp="2026-09-02T01:00:00.000Z",
                usage=_usage(5_000_000, 0, 0, 0),
                tools=("Bash",),
                worktree="w3-1463",
            )
        ],
        # Two unrelated concurrent executors on their own slices.
        "agent-peer-1497.output": [
            _assistant(
                message_id="m-1497",
                agent_id="agent-peer-1497",
                branch=session_branch,
                timestamp="2026-09-02T01:00:00.000Z",
                usage=_usage(6_000_000, 0, 0, 0),
                tools=("Bash",),
                worktree="w3-1497",
            )
        ],
        "agent-peer-1498.output": [
            _assistant(
                message_id="m-1498",
                agent_id="agent-peer-1498",
                branch=session_branch,
                timestamp="2026-09-02T01:00:00.000Z",
                usage=_usage(6_200_000, 0, 0, 0),
                tools=("Bash",),
                worktree="w3-1498",
            )
        ],
    }

    block = _capture(tmp_path, agents)

    assert [agent["agentId"] for agent in block["agents"]] == ["agent-executor"]
    assert block["agents"][0]["attributedBy"] == "worktreePath"
    assert block["tokenUsage"]["value"]["total"] == 100
    # The fabricated headline the defect produced must be nowhere in the block.
    assert block["tokenUsage"]["value"]["total"] != 17_200_100


def test_several_attributed_agents_are_listed_and_never_summed(tmp_path: Path) -> None:
    """Two agents in one tree is ambiguous, and a sum would invent a run.

    Summing is only right if the agents *are* one run, and nothing on disk says
    they are. Adding them produces a total no single process ever spent, which
    is the fabrication this epic exists to end — so the headline goes
    unavailable and every candidate is listed with its own real figures.
    """
    shared = {
        "agent-a.output": [
            _assistant(
                message_id="m-a",
                agent_id="agent-a",
                branch="main",
                timestamp="2026-09-02T01:00:00.000Z",
                usage=_usage(1, 1, 1, 1),
                tools=("Bash",),
                worktree=f"w3-{ISSUE}",
            )
        ],
        "agent-b.output": [
            _assistant(
                message_id="m-b",
                agent_id="agent-b",
                branch="main",
                timestamp="2026-09-02T01:00:00.000Z",
                usage=_usage(2, 2, 2, 2),
                tools=("Bash",),
                worktree=f"w3-{ISSUE}",
            )
        ],
    }

    block = _capture(tmp_path, shared)

    assert block["status"] == "ambiguous"
    for field in ("tokenUsage", "toolInvocationCount", "executionDurationMs"):
        assert block[field]["available"] is False, field
        # The sum, 12, must not appear under any guise.
        assert "value" not in block[field], field
        assert "ambiguous" in block[field]["reason"]

    # Nothing is lost: both candidates keep their own measured figures.
    listed = {agent["agentId"]: agent["tokenUsage"]["total"] for agent in block["agents"]}
    assert listed == {"agent-a": 4, "agent-b": 8}
    assert any(gap["reason"] == "ambiguous-attribution" for gap in block["gaps"])


def test_a_still_running_agent_is_in_flight_and_not_measured(tmp_path: Path) -> None:
    """A live transcript has no final total, and reading one breaks idempotency.

    ``capture_run_block`` promises ``generate_status_records`` byte-idempotent
    output. A transcript still being appended to breaks that promise: two
    generations seconds apart disagree, which surfaced here as an intermittent
    failure of ``test_status_record_gate::test_migration_is_idempotent``.

    It is also wrong on its own terms. An agent that has not finished has not
    yet spent what it will spend, so any figure read from it is a lower bound
    reported as a measurement. In-flight is its own state.
    """
    records = [
        _assistant(
            message_id="m",
            agent_id="agent-live",
            branch="main",
            timestamp="2026-09-02T01:00:00.000Z",
            usage=_usage(1, 1, 1, 1),
            tools=("Bash",),
            worktree=f"w3-{ISSUE}",
        )
    ]
    base, repo_root = _write_tasks(tmp_path, {"agent-live.output": records}, in_flight=True)
    # The file was just written, so it is by definition still in flight.
    block = run_metrics.capture(
        _context(), repo_root=repo_root, temp_bases=(str(base),), environ={}, claims=None
    )

    assert block["agents"] == []
    assert block["status"] == "not-measured"
    assert "value" not in block["tokenUsage"]
    assert any(gap["reason"] == "in-flight-transcript" for gap in block["gaps"])

    # Two reads of a settled store must be byte-identical — the property the
    # status-record generator depends on.
    old = _write_tasks(tmp_path, {"agent-done.output": records})
    first = run_metrics.capture(
        _context(), repo_root=old[1], temp_bases=(str(old[0]),), environ={}, claims=None
    )
    second = run_metrics.capture(
        _context(), repo_root=old[1], temp_bases=(str(old[0]),), environ={}, claims=None
    )
    assert first == second
    assert first["status"] == "measured"
    assert first["tokenUsage"]["value"]["total"] == 4


def test_non_transcript_output_files_are_ignored(tmp_path: Path) -> None:
    """The tasks dir also holds plain-text tool output. It is not a transcript.

    Measured on a real session: 37 of 56 ``.output`` files parse as JSONL and
    19 are raw text. A provider that treats a text file as an empty transcript
    would report a phantom agent with zero tokens — a measured-looking zero.
    """
    real = _assistant(
        message_id="msg_a",
        agent_id="agent-one",
        branch=BRANCH,
        timestamp="2026-09-02T01:00:00.000Z",
        usage=_usage(5, 5, 5, 5),
        tools=("Bash",),
        worktree=f"w3-{ISSUE}",
    )
    block = _capture(
        tmp_path,
        {
            "agent-one.output": [real],
            "b9d29ydj4.output": "total 440\ndrwxr-xr-x 15 macos wheel 480 Sep 2 09:27 .\n",
            "empty.output": "",
        },
    )

    assert [agent["agentId"] for agent in block["agents"]] == ["agent-one"]
    assert block["tokenUsage"]["value"]["total"] == 20


def test_provider_never_raises_on_a_broken_store(tmp_path: Path) -> None:
    """A broken store is a gap, not an abort — a raise kills record generation."""
    repo_root = tmp_path / "checkout" / "Juli-AI-v2"
    repo_root.mkdir(parents=True)
    # The lie: a *file* where the temp base directory should be.
    broken = tmp_path / "not-a-directory"
    broken.write_text("nope", encoding="utf-8")

    block = run_metrics.capture(
        _context(), repo_root=repo_root, temp_bases=(str(broken),), environ={}
    )
    assert block["status"] == "not-measured"
    assert "value" not in block["tokenUsage"]


def test_provider_is_discovered_and_owns_the_metrics_block() -> None:
    """Discovery finds the module by directory listing, per the #1438 seam."""
    with provider_sandbox():
        names = discover_providers()
        assert run_metrics.PROVIDER_NAME == "metrics"
        assert "metrics" in names
        run = capture_run_block(_context())
        assert set(run["metrics"]) >= {
            "schemaVersion",
            "status",
            "tokenUsage",
            "toolInvocationCount",
            "executionDurationMs",
            "executorDomain",
        }


def test_project_slug_matches_the_real_on_disk_naming() -> None:
    """Discovery hinges on the slug; the real corpus fixes its exact form."""
    assert task_transcripts.project_slug("/Users/macos/Juli-AI-v2") == "-Users-macos-Juli-AI-v2"
    assert (
        task_transcripts.project_slug("/Users/macos/Juli-AI-v2/.claude")
        == "-Users-macos-Juli-AI-v2--claude"
    )
    # A worktree checkout must still resolve to its parent repository's slug,
    # which is where the session actually landed.
    candidates = task_transcripts.slug_candidates("/Users/macos/Juli-AI-v2/.worktrees/w3-1441")
    assert "-Users-macos-Juli-AI-v2" in candidates


def test_measures_this_repository_when_a_session_is_present() -> None:
    """Not a fixture: read the live store if this machine has one.

    Skipped where no session temp dir exists (CI), which is the honest outcome
    rather than a synthetic pass.
    """
    dirs = task_transcripts.discover_task_dirs(repo_root=REPO_ROOT, environ=dict(os.environ))
    if not dirs:
        pytest.skip("no persisted task transcripts on this machine")
    agents = task_transcripts.read_task_dir(dirs[0])
    assert agents, "a discovered tasks dir with no parseable agent is a discovery bug"
    for agent in agents:
        assert agent["tokenUsage"]["total"] >= 0
        assert re.fullmatch(r"[A-Za-z0-9._\-]+", agent["agentId"])
