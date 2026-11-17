"""Fast-track pipeline v2 tools (pipeline-eval baseline 2026-11-16): shared state,
gate validity, owner-command lint and the public-repo PR scrub. No network, no database."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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


def test_a_batch_registered_before_any_commit_is_not_merged(repo):
    """2026-11-17: a batch registered at the tip was marked merged once it moved ahead."""
    tip = _git(repo, "rev-parse", "main")
    _git(repo, "branch", "fresh", "main")
    b = {"head": tip, "base": tip, "status": "building"}
    assert not state.batch_landed("fresh", b, tip)
    _git(repo, "checkout", "-q", "fresh")
    (repo / "work.txt").write_text("built\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "work")
    assert not state.batch_landed("fresh", b, tip)
    assert b["head"] == _git(repo, "rev-parse", "fresh")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge fresh", "fresh")
    assert state.batch_landed("fresh", b, _git(repo, "rev-parse", "main"))


xdist_trial = _load("xdist_trial", REPO / "fasttrack" / "bin" / "xdist_trial.py")


def _junit(path: Path, cases: dict[str, str], seconds: float) -> Path:
    body = {"passed": "", "failed": "<failure message='x'/>", "skipped": "<skipped/>"}
    rows = "".join(
        f"<testcase classname='{c.split('::')[0]}' name='{c.split('::')[1]}'>{body[o]}</testcase>"
        for c, o in cases.items()
    )
    path.write_text(
        f"<testsuites><testsuite name='pytest' tests='{len(cases)}' time='{seconds}'>"
        f"{rows}</testsuite></testsuites>"
    )
    return path


def test_xdist_trial_is_ok_only_with_same_tests_same_outcomes_and_faster(tmp_path):
    serial = {"t.a::one": "passed", "t.a::two": "skipped", "t.b::three": "passed"}
    s1 = _junit(tmp_path / "s1.xml", dict(list(serial.items())[:2]), 50)
    s2 = _junit(tmp_path / "s2.xml", dict(list(serial.items())[2:]), 70)
    good = _junit(tmp_path / "x.xml", serial, 30)
    rec = tmp_path / "trial.jsonl"
    args = ["compare", "--serial", str(s1), str(s2), "--record", str(rec), "--tree", "T1"]
    assert xdist_trial.main([*args, "--xdist", str(good)]) == 0
    r = json.loads(rec.read_text().splitlines()[-1])
    assert r["ok"] and r["serial_seconds"] == 70 and r["serial_runner_seconds"] == 120

    flaky = _junit(tmp_path / "f.xml", {**serial, "t.b::three": "failed"}, 30)
    assert xdist_trial.main([*args, "--xdist", str(flaky), "--strict"]) == 1
    r = json.loads(rec.read_text().splitlines()[-1])
    assert r["xdist_only_failures"] == ["t.b::three"] and not r["ok"]

    dropped = _junit(tmp_path / "d.xml", dict(list(serial.items())[:2]), 30)
    xdist_trial.main([*args, "--xdist", str(dropped)])
    assert json.loads(rec.read_text().splitlines()[-1])["missing_in_xdist"] == ["t.b::three"]

    slower = _junit(tmp_path / "w.xml", serial, 90)
    xdist_trial.main([*args, "--xdist", str(slower)])
    r = json.loads(rec.read_text().splitlines()[-1])
    assert not r["faster"] and not r["ok"]


def test_xdist_count_catches_a_silent_drop(tmp_path):
    x = _junit(tmp_path / "x.xml", {"t.a::one": "passed", "t.a::two": "passed"}, 1)
    assert xdist_trial.main(["count", str(x), "--expect", "2"]) == 0
    assert xdist_trial.main(["count", str(x), "--expect", "3"]) == 1


def test_xdist_trial_completes_after_three_consecutive_ok_trees(tmp_path):
    rec = tmp_path / "trial.jsonl"
    rows = [("T1", True), ("T2", False), ("T3", True), ("T4", True)]
    rec.write_text(
        "".join(
            json.dumps({"at": f"2026-11-2{i}", "where": "local", "tree": t, "ok": ok}) + "\n"
            for i, (t, ok) in enumerate(rows)
        )
    )
    assert xdist_trial.main(["summary", str(rec)]) == 1  # T2 broke the streak: 2 of 3
    with rec.open("a") as f:
        f.write(json.dumps({"at": "2026-11-29", "where": "local", "tree": "T5", "ok": True}) + "\n")
    assert xdist_trial.main(["summary", str(rec)]) == 0


def test_the_xdist_trial_never_blocks_a_deploy():
    wf = yaml.safe_load((REPO / ".github/workflows/fasttrack-deploy.yml").read_text())
    jobs = wf["jobs"]
    for trial in ("backend-unit-xdist-trial", "xdist-trial-compare"):
        assert jobs[trial]["continue-on-error"] is True, trial
        for job in ("backup", "deploy"):
            assert trial not in jobs[job]["needs"], (trial, job)


def test_pr_checks_run_the_deploy_gates_commands_without_secrets():
    text = (REPO / ".github/workflows/fasttrack-pr.yml").read_text()
    pr = yaml.safe_load(text)
    deploy = yaml.safe_load((REPO / ".github/workflows/fasttrack-deploy.yml").read_text())
    assert pr[True]["pull_request"]["branches"] == ["fasttrack/**"]  # YAML 1.1 reads `on` as True
    assert "secrets." not in text and pr["permissions"] == {"contents": "read"}

    def runs(job: dict) -> list[str]:
        return [
            s["run"].replace(" \\\n", "\n").split("--junitxml")[0].strip()
            for s in job["steps"]
            if "run" in s
        ]

    for job in ("frontend", "static"):
        assert runs(pr["jobs"][job]) == runs(deploy["jobs"][job]), job
    pr_unit, dep_unit = runs(pr["jobs"]["backend-unit"]), runs(deploy["jobs"]["backend-unit"])
    assert pr_unit == dep_unit
    assert pr["jobs"]["backend-unit"]["strategy"] == deploy["jobs"]["backend-unit"]["strategy"]
    # Phase 2: the database check runs here too, same commands, shards and Postgres service.
    for key in ("strategy", "services", "env"):
        assert pr["jobs"]["check"][key] == deploy["jobs"]["check"][key], key
    assert runs(pr["jobs"]["check"]) == runs(deploy["jobs"]["check"])
    check_env = pr["jobs"]["check"]["steps"][-1]["env"]
    assert check_env["SINCE"] == "origin/main" and check_env["JULI_TEST_DATABASE_DISPOSABLE"] == "1"


def test_the_pr_gate_record_exists_only_when_all_five_gate_jobs_pass():
    pr = yaml.safe_load((REPO / ".github/workflows/fasttrack-pr.yml").read_text())
    gate = pr["jobs"]["gate"]
    assert sorted(gate["needs"]) == sorted(["heads", "frontend", "backend-unit", "static", "check"])
    assert "if" not in gate  # implicit success(): a failed or skipped gate job means no record
    upload = gate["steps"][-1]
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["with"]["name"] == gate_status.ARTIFACT_PREFIX + "${{ env.TREE }}"
    record = next(s["run"] for s in gate["steps"] if s.get("name") == "Record the tested tree")
    assert "git rev-parse 'HEAD^{tree}'" in record
    assert "migration_heads.py heads" in pr["jobs"]["heads"]["steps"][-1]["run"]


def _fake_github(artifacts: list[dict], runs: dict[int, dict]):
    calls: list[str] = []

    def get(path: str):
        calls.append(path)
        if "/actions/artifacts?" in path:
            return {"artifacts": artifacts}
        return runs[int(path.rsplit("/", 1)[1])]

    return get, calls


def _art(run_id: int, *, fork: bool = False, expired: bool = False) -> dict:
    return {
        "expired": expired,
        "workflow_run": {"id": run_id, "repository_id": 1, "head_repository_id": 2 if fork else 1},
    }


def _run(run_id: int, **over) -> dict:
    run = {
        "id": run_id,
        "path": gate_status.PR_WORKFLOW,
        "event": "pull_request",
        "conclusion": "success",
        "pull_requests": [{"number": 7}],
        "html_url": f"https://example.invalid/runs/{run_id}",
        "updated_at": "2026-11-17T00:00:00Z",
    }
    run.update(over)
    return run


def test_a_passing_pr_run_for_the_tree_makes_the_gate_valid():
    get, calls = _fake_github([_art(11)], {11: _run(11)})
    ok, detail = gate_status.ci_gate("t" * 40, get, "o/r")
    assert ok and "run 11" in detail and "#7" in detail
    assert (
        calls[0]
        == f"/repos/o/r/actions/artifacts?name={gate_status.ARTIFACT_PREFIX}{'t' * 40}&per_page=20"
    )


@pytest.mark.parametrize(
    ("art", "run", "why"),
    [
        (_art(12, fork=True), _run(12), "fork"),
        (_art(13, expired=True), _run(13), "expired"),
        (_art(14), _run(14, conclusion="failure"), "concluded failure"),
        (_art(15), _run(15, path=".github/workflows/other.yml"), "is not"),
        (_art(16), _run(16, event="push"), "is not"),
    ],
)
def test_a_pr_run_from_a_fork_or_another_workflow_or_red_never_counts(art, run, why):
    get, _ = _fake_github([art], {run["id"]: run})
    ok, detail = gate_status.ci_gate("t" * 40, get, "o/r")
    assert not ok and why in detail


def test_no_pr_run_for_the_tree_is_missing_not_valid():
    get, _ = _fake_github([], {})
    ok, detail = gate_status.ci_gate("t" * 40, get, "o/r")
    assert not ok and detail.startswith("MISSING")
