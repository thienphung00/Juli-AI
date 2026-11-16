"""Fast-track pipeline v2 tools (pipeline-eval baseline 2026-11-16): shared state,
gate validity, owner-command lint and the public-repo PR scrub. No network, no database."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


state = _load("state", REPO / "fasttrack" / "state.py")
gate_status = _load("gate_status", REPO / "fasttrack" / "gate_status.py")
cmdlint = _load("cmdlint", REPO / "fasttrack" / "bin" / "cmdlint.py")
open_pr = _load("open_pr", REPO / "fasttrack" / "bin" / "open_pr.py")

MIG = state.MIGRATIONS_DIR


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A tiny git repo: main has migration 130; branch 'batch' adds 131 and 132."""
    r = tmp_path / "r"
    (r / MIG).mkdir(parents=True)
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / MIG / "130_businesses.py").write_text("x = 1\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    _git(r, "checkout", "-qb", "batch")
    (r / MIG / "131_reader_blocks.py").write_text("x = 1\n")
    (r / MIG / "132_w2a.py").write_text("x = 1\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "batch")
    monkeypatch.chdir(r)
    monkeypatch.setenv("JULI_FASTTRACK_STATE_DIR", str(tmp_path / "state"))
    return r


def _base_state(repo: Path) -> dict:
    st = state.empty_state()
    st["deploy_branch"]["tip"] = _git(repo, "rev-parse", "main")
    return st


def test_unclaimed_and_foreign_migrations_block(repo):
    st = _base_state(repo)
    st["migrations"]["131"] = {"session": "s1", "name": "reader_blocks", "status": "claimed"}
    block, _ = state.blockers(st, "s1", "batch")
    assert any("migration 132" in b and "not claimed" in b for b in block)
    assert not any("migration 131" in b for b in block)
    block_other, _ = state.blockers(st, "tiktok", "batch")
    assert any("claimed by s1" in b for b in block_other)


def test_branch_missing_the_tip_blocks(repo):
    st = _base_state(repo)
    _git(repo, "checkout", "-q", "main")
    (repo / "new.txt").write_text("tip moved\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "tip moves")
    st["deploy_branch"]["tip"] = _git(repo, "rev-parse", "main")
    st["migrations"].update({"131": {"session": "s1"}, "132": {"session": "s1"}})
    block, _ = state.blockers(st, "s1", "batch")
    assert any("does not contain the deploy tip" in b for b in block)


def test_pending_tag_blocks_and_failed_tag_is_reported(repo):
    st = _base_state(repo)
    st["tags"].append({"tag": "fasttrack-deploy-x", "sha": "a" * 40, "conclusion": "pending"})
    block, _ = state.blockers(st, "s1", None)
    assert any("has no result yet" in b for b in block)
    st["tags"][-1]["conclusion"] = "failure"
    block, adv = state.blockers(st, "s1", None)
    assert not block
    assert any("FAILED" in a and "prod is NOT" in a for a in adv)


def test_claim_migration_refuses_a_number_taken_by_another_session(repo):
    assert (
        state.main(
            ["claim-migration", "131", "--session", "s1", "--name", "a", "--branch", "batch"]
        )
        == 0
    )
    assert (
        state.main(
            ["claim-migration", "131", "--session", "tiktok", "--name", "b", "--branch", "x"]
        )
        == 1
    )
    with state.locked_state(write=False) as st:
        assert st["migrations"]["131"]["session"] == "s1"
    events = (Path(state.state_dir()) / "events.jsonl").read_text().splitlines()
    assert json.loads(events[-1])["kind"] == "claim-migration"


def test_ab_assignment_is_balanced_and_stable(repo):
    st = state.empty_state()
    arms = [state.ab_assign(st, "b1", f"s{i}", "coord") for i in range(6)]
    assert arms.count("A") == arms.count("B") == 3
    assert state.ab_assign(st, "b1", "s0", "coord") == arms[0]


def _job(state_dir: Path, tree: str, job: str, **over) -> None:
    rec = {
        "job": job,
        "status": "PASS",
        "rc": 0,
        "seconds": 1,
        "tests": 3,
        "mode": "full",
        "clean": 1,
        "contains_tip": 1,
        "tip": "t" * 40,
        "finished_at": "now",
    }
    rec.update(over)
    d = state_dir / "predeploy" / tree
    d.mkdir(parents=True, exist_ok=True)
    (d / f"job-{job}.json").write_text(json.dumps(rec))


def test_gate_valid_only_when_every_job_passed_clean_with_tip(tmp_path):
    tree = "f" * 40
    for j in gate_status.GATE_JOBS:
        _job(tmp_path, tree, j)
    ok, _ = gate_status.gate(tree, tmp_path)
    assert ok
    _job(tmp_path, tree, "check", contains_tip=0)
    ok, rows = gate_status.gate(tree, tmp_path)
    assert not ok
    assert "did not contain tip" in dict(rows)["check"]
    _job(tmp_path, tree, "check", mode="fast")
    assert not gate_status.gate(tree, tmp_path)[0]
    (tmp_path / "predeploy" / tree / "job-unit.json").unlink()
    _job(tmp_path, tree, "check")
    ok, rows = gate_status.gate(tree, tmp_path)
    assert not ok
    assert dict(rows)["unit"].startswith("MISSING")


@pytest.mark.parametrize(
    "cmd, rule",
    [
        ("psql -c 'select 1' --from YYYY-MM-DD", "placeholder"),
        ("systemctl restart juli-api-candidate-<port>", "angle-bracket"),
        ("git push origin $S:refs/heads/x", "zsh colon"),
        ("git push origin --tags", "pushes every tag"),
        ("cd /Users/macos/x\n./run.sh", "cd"),
        ("echo 'unterminated", "unbalanced"),
    ],
)
def test_cmdlint_flags_known_owner_command_failures(cmd, rule):
    assert any(rule in p for p in cmdlint.lint(cmd)), cmdlint.lint(cmd)


def test_cmdlint_passes_a_clean_command():
    cmd = (
        "cd /Users/macos/Juli-AI-v2/juli/.worktrees/b1"
        " && ./fasttrack/bin/pg-test.sh tests/integration/test_a.py"
    )
    assert cmdlint.lint(cmd) == []


def test_public_pr_scrub_blocks_private_data_and_allows_noreply():
    text = (
        "Fix for shop d73a240b-0000 owner a.b@gmail.com call 0912345678\n"
        "Co-Authored-By: C <noreply@anthropic.com>"
    )
    hits = open_pr.scan(text, ["d73a240b-0000"])
    kinds = {h.split(":")[0] for h in hits}
    assert {"email", "vn-phone", "scrub term"} <= kinds
    assert not any("anthropic" in h for h in hits)
    assert open_pr.scan("P100: Tổng quan header and period picker", []) == []
