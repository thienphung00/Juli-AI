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


def test_a_claim_moves_only_from_its_holder_with_an_approval(repo):
    claim = ["claim-migration", "134", "--name", "t5", "--branch", "b2"]
    assert state.main([*claim, "--session", "s1"]) == 0
    assert state.main([*claim, "--session", "s2", "--transfer-from", "s1"]) == 1  # no approval
    assert (
        state.main([*claim, "--session", "s2", "--transfer-from", "s3", "--approved-by", "owner"])
        == 1  # s3 does not hold it
    )
    with state.locked_state(write=False) as st:
        assert st["migrations"]["134"]["session"] == "s1"
    assert (
        state.main(
            [*claim, "--session", "s2", "--transfer-from", "s1", "--approved-by", "owner #6"]
        )
        == 0
    )
    with state.locked_state(write=False) as st:
        m = st["migrations"]["134"]
        assert (m["session"], m["transferred_from"], m["approved_by"]) == ("s2", "s1", "owner #6")
    last = json.loads((Path(state.state_dir()) / "events.jsonl").read_text().splitlines()[-1])
    assert last["kind"] == "claim-migration-transfer" and last["from_session"] == "s1"


def test_a_migration_past_claimed_never_moves(repo):
    claim = ["claim-migration", "135", "--name", "x", "--branch", "b"]
    assert state.main([*claim, "--session", "s1"]) == 0
    assert state.main(["migration", "135", "--status", "live"]) == 0
    moved = [*claim, "--session", "s2", "--transfer-from", "s1", "--approved-by", "owner"]
    assert state.main(moved) == 1
    with state.locked_state(write=False) as st:
        assert st["migrations"]["135"]["session"] == "s1"


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


def test_the_xdist_trial_is_over_xdist_gates_locally_and_ci_stays_serial():
    # Owner 2026-11-18: trial ended. predeploy.sh gates with xdist by default; CI keeps the
    # 4 serial shards and carries no xdist job.
    jobs = yaml.safe_load((REPO / ".github/workflows/fasttrack-deploy.yml").read_text())["jobs"]
    assert not [j for j in jobs if "xdist" in j]
    predeploy = (REPO / "fasttrack" / "predeploy.sh").read_text()
    assert 'XDIST="${JULI_GATE_XDIST:-1}"' in predeploy


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


# ---- W48 pipeline fixes (pipeline-eval 2026-W47) ------------------------------------------

brief_rules = _load("brief_rules", REPO / "fasttrack" / "bin" / "brief_rules.py")


def _st_main(*args: str) -> int:
    return state.main(list(args))


def _read_state(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "state" / "STATE.json").read_text())


def test_an_owner_decision_reaches_every_other_session_once(repo, tmp_path, capsys):
    _st_main("session", "s1", "--role", "r")
    _st_main("session", "s2", "--role", "r")
    assert _st_main("decide", "--session", "s1", "no writes to the shop cover") == 0
    capsys.readouterr()
    _st_main("check", "--session", "s2", "--no-refresh")
    first = capsys.readouterr().out
    _st_main("check", "--session", "s2", "--no-refresh")
    second = capsys.readouterr().out
    _st_main("check", "--session", "s1", "--no-refresh")
    own = capsys.readouterr().out
    assert "OWNER DECISION #1" in first and "no writes to the shop cover" in first
    assert "OWNER DECISION" not in second
    assert "OWNER DECISION" not in own


def test_handover_moves_open_batches_and_claims_and_needs_an_approval(repo, tmp_path):
    st = _base_state(repo)
    st["sessions"] = {"old": {"role": "x"}}
    st["batches"] = {
        "fasttrack/b1": {"session": "old", "status": "building"},
        "fasttrack/b0": {"session": "old", "status": "merged"},
    }
    st["migrations"] = {
        "140": {"session": "old", "status": "claimed"},
        "139": {"session": "old", "status": "live"},
    }
    moved = state.handover(st, "old", "new", "owner 2026-11-23")
    assert st["batches"]["fasttrack/b1"]["session"] == "new"
    assert st["batches"]["fasttrack/b0"]["session"] == "old"
    assert st["migrations"]["140"]["session"] == "new"
    assert st["migrations"]["139"]["session"] == "old"
    assert st["sessions"]["old"]["role"].startswith("inactive")
    assert moved == ["batch fasttrack/b1", "migration 140"]
    with pytest.raises(SystemExit) as exc:
        _st_main("handover", "--from", "old", "--to", "new")
    assert exc.value.code == 2  # --approved-by is required


def test_only_one_full_suite_holds_the_lock(repo, tmp_path, capsys):
    assert _st_main("suite-lock", "acquire", "--session", "s1", "--what", "predeploy full") == 0
    assert _st_main("suite-lock", "acquire", "--session", "s2") == 1
    assert "already running: s1" in capsys.readouterr().err
    assert _st_main("suite-lock", "release", "--session", "s2") == 1
    _st_main("session", "s2", "--role", "r")
    capsys.readouterr()
    _st_main("check", "--session", "s2", "--no-refresh")
    assert "full test suite running: s1" in capsys.readouterr().out
    assert _st_main("suite-lock", "release", "--session", "s1") == 0
    assert _read_state(tmp_path)["suite_lock"] is None
    assert _st_main("suite-lock", "acquire", "--session", "s2") == 0


def test_a_stale_suite_lock_can_be_taken(repo):
    st = _base_state(repo)
    st["suite_lock"] = {"session": "s1", "what": "x", "at": "2020-01-01T00:00:00Z"}
    assert state.suite_lock(st, "acquire", "s2", "y") is None
    assert st["suite_lock"]["session"] == "s2"


def test_check_says_to_rotate_a_session_past_six_hours(repo):
    st = _base_state(repo)
    st["sessions"] = {
        "s1": {"started_at": "2020-01-01T00:00:00Z"},
        "s2": {"started_at": state.now()},
    }
    _, adv_old = state.blockers(st, "s1", None)
    _, adv_new = state.blockers(st, "s2", None)
    assert any("write the handoff" in a for a in adv_old)
    assert not any("write the handoff" in a for a in adv_new)


def test_session_fresh_resets_the_start(repo, tmp_path):
    _st_main("session", "s1", "--role", "r")
    st = json.loads((tmp_path / "state" / "STATE.json").read_text())
    st["sessions"]["s1"]["started_at"] = "2020-01-01T00:00:00Z"
    (tmp_path / "state" / "STATE.json").write_text(json.dumps(st))
    _st_main("session", "s1")
    assert _read_state(tmp_path)["sessions"]["s1"]["started_at"] == "2020-01-01T00:00:00Z"
    _st_main("session", "s1", "--fresh")
    assert _read_state(tmp_path)["sessions"]["s1"]["started_at"] != "2020-01-01T00:00:00Z"


def _note(d: Path, name: str, kind: str, desc: str) -> None:
    (d / f"{name}.md").write_text(
        f'---\nname: {name}\ndescription: "{desc}"\nmetadata:\n  type: {kind}\n---\n\n{desc}\n'
    )


def test_brief_rules_picks_matching_notes_and_flags_platform_and_library(
    tmp_path, monkeypatch, capsys
):
    mem = tmp_path / "mem"
    mem.mkdir()
    _note(
        mem,
        "fix-all-staleness",
        "feedback",
        "Connector staleness gaps are fixed together, never one dataset",
    )
    _note(mem, "ratchet", "feedback", "pytest tests without assert break the test quality ratchet")
    _note(mem, "who-i-am", "user", "Connector staleness owner profile")
    _note(mem, "lunch", "project", "Lunch menu planning for the team offsite")
    brief = tmp_path / "brief.md"
    brief.write_text("Fix Connector staleness for the Shopee voucher reader; bump the react chart.")
    monkeypatch.setenv("JULI_FASTTRACK_STATE_DIR", str(tmp_path / "nostate"))
    assert brief_rules.main([str(brief), "--memory-dir", str(mem), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    names = [n["name"] for n in out["notes"]]
    assert names == ["fix-all-staleness"]  # user notes and unrelated notes never match
    assert {"shopee", "connector", "voucher", "reader"} <= set(out["platform"])
    assert out["library"] == ["react"]


def test_brief_rules_includes_owner_decisions_that_match_the_brief(tmp_path, monkeypatch, capsys):
    sd = tmp_path / "state"
    sd.mkdir()
    (sd / "STATE.json").write_text(
        json.dumps(
            {
                "decisions": [
                    {
                        "id": 1,
                        "text": "voucher reader keeps the per-line promo fields",
                        "by": "s1",
                        "at": "t",
                    },
                    {"id": 2, "text": "landing page colour stays blue", "by": "s1", "at": "t"},
                ]
            }
        )
    )
    monkeypatch.setenv("JULI_FASTTRACK_STATE_DIR", str(sd))
    brief = tmp_path / "brief.md"
    brief.write_text("Change the voucher reader promo mapping.")
    brief_rules.main([str(brief), "--memory-dir", str(tmp_path / "none"), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert [d["id"] for d in out["decisions"]] == [1]
    assert out["library"] == []


def test_the_brief_template_and_pipeline_carry_the_w48_rows_and_rules():
    brief = (REPO / "fasttrack" / "contracts" / "EXECUTOR-BRIEF.md").read_text()
    for row in ("| R1… |", "| PLATFORM |", "| LIB |", "brief_rules.py"):
        assert row in brief
    pipe = (REPO / "fasttrack" / "PIPELINE.md").read_text()
    for rule in (
        "Grill exit checklist",
        "state.py decide",
        "state.py handover",
        "suite-lock",
        "~6 h of work",
    ):
        assert rule in pipe
