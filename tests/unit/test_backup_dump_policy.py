"""P62-A (D72.1): fewer full pg_dumps of production.

Pins the three halves of the policy without a database or SSH:

- safe-alembic-upgrade.sh dumps only when a migration is pending (driven with a
  fake helper / pg_dump / alembic next to a copy of the script);
- the fast-track deploy workflow runs its `backup` job only on force_backup and
  only after every gate passed (P62-C: a migration is dumped once, by
  safe-alembic-upgrade.sh), and a SKIPPED backup still lets deploy run while a
  FAILED one does not (the `if` expressions are evaluated against simulated job
  results);
- infra/scripts/backup-database.sh (shared by that job and the daily
  juli-db-backup.timer) verifies before naming the dump and rotates old ones.
- both dumps leave out the rows of public.processed_events (P62-C).
"""

from __future__ import annotations

import ast
import fnmatch
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"
SYSTEMD_DIR = REPO_ROOT / "infra/systemd"
DEPLOY_YML = REPO_ROOT / ".github/workflows/fasttrack-deploy.yml"
MIGRATIONS_DIR = REPO_ROOT / "backend/src/juli_backend/database/migrations/versions"
BACKUP_GLOB = "juli-pre-migrate-*.dump"  # safe_alembic_helpers.find_latest_backup

BASH = shutil.which("bash") or "/bin/bash"


def _load_migration_heads() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_heads", SCRIPTS_DIR / "migration_heads.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mh = _load_migration_heads()


# --------------------------------------------------------------------------- heads


def _write_rev(directory: Path, name: str, rev: str, down: str) -> None:
    (directory / f"{name}.py").write_text(
        f'"""m"""\nrevision: str = "{rev}"\ndown_revision: str | None = {down}\n',
        encoding="utf-8",
    )


def test_heads_of_the_real_migrations_match_alembic():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR.parent))
    alembic_heads = sorted(ScriptDirectory.from_config(cfg).get_heads())
    assert mh.script_heads(MIGRATIONS_DIR) == alembic_heads
    assert len(alembic_heads) == 1


def test_heads_handles_branches_merges_and_plain_assignments(tmp_path: Path):
    _write_rev(tmp_path, "001", "a", "None")
    _write_rev(tmp_path, "002", "b", '"a"')
    _write_rev(tmp_path, "003", "c", '"a"')
    assert mh.script_heads(tmp_path) == ["b", "c"]

    (tmp_path / "004.py").write_text('revision = "d"\ndown_revision = ("b", "c")\n')
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "helpers.py").write_text("X = 1\n")
    assert mh.script_heads(tmp_path) == ["d"]


def test_heads_refuses_a_missing_directory(tmp_path: Path):
    with pytest.raises(FileNotFoundError) as excinfo:
        mh.script_heads(tmp_path / "nope")
    assert "nope" in str(excinfo.value)


@pytest.mark.parametrize(
    ("heads", "prod", "force", "expected"),
    [
        (["h"], "h", False, False),
        (["h"], "  h\n", False, False),
        # P62-C: a pending or unreadable migration is safe-alembic's dump, not ours.
        (["h"], "g", False, False),
        (["h"], "", False, False),
        (["h", "i"], "h", False, False),
        ([], "h", False, False),
        (["h"], "h", True, True),
        (["h"], "g", True, True),
    ],
)
def test_decide_backup_runs_only_when_forced(heads, prod, force, expected):
    backup, reason = mh.decide_backup(heads, prod, force=force)
    assert backup is expected
    assert reason


def test_decide_reason_names_the_migration_state():
    assert "migration pending" in mh.decide_backup(["h"], "g", force=False)[1]
    assert "safe-alembic dumps" in mh.decide_backup(["h"], "", force=False)[1]
    forced = mh.decide_backup(["h"], "h", force=True)[1]
    assert forced.startswith("force_backup requested")
    assert "no new migration" in forced


def test_decide_cli_prints_github_output_lines(tmp_path: Path):
    _write_rev(tmp_path, "001", "a", "None")
    _write_rev(tmp_path, "002", "b", '"a"')
    script = SCRIPTS_DIR / "migration_heads.py"

    def run(*extra: str) -> list[str]:
        out = subprocess.run(
            [
                sys.executable,
                "-I",
                str(script),
                "decide",
                "--migrations-dir",
                str(tmp_path),
                *extra,
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return out.splitlines()

    same = run("--production-revision", "b")
    assert same[0] == "backup=false"
    assert same[1].startswith("reason=")
    assert run("--production-revision", "a")[0] == "backup=false"
    assert run("--production-revision", "b", "--force")[0] == "backup=true"


# ------------------------------------------------------------------------ workflow


@pytest.fixture(scope="module")
def deploy_wf() -> dict:
    return yaml.safe_load(DEPLOY_YML.read_text(encoding="utf-8"))


def _eval_if(expr: str, results: dict[str, str], outputs: dict[str, dict[str, str]]) -> bool:
    """Evaluate the subset of GitHub expression syntax the deploy `if`s use."""
    py = " ".join(expr.split())
    py = py.replace("!cancelled()", "True")
    py = re.sub(
        r"needs\.([\w-]+)\.result",
        lambda m: repr(results[m.group(1)]),
        py,
    )
    py = re.sub(
        r"needs\.([\w-]+)\.outputs\.(\w+)",
        lambda m: repr(outputs.get(m.group(1), {}).get(m.group(2), "")),
        py,
    )
    py = py.replace("&&", " and ").replace("||", " or ")
    return bool(_eval_node(ast.parse(py, mode="eval").body))


def _eval_node(node: ast.expr) -> object:
    """and / or / == over constants: all the deploy `if`s need, and nothing more."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(v) for v in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq):
        return _eval_node(node.left) == _eval_node(node.comparators[0])
    raise AssertionError(f"unsupported expression: {ast.dump(node)}")


def test_workflow_has_force_backup_dispatch_input(deploy_wf: dict):
    on = deploy_wf.get("on") or deploy_wf.get(True)
    force = on["workflow_dispatch"]["inputs"]["force_backup"]
    assert force["type"] == "boolean"
    assert force["default"] is False
    assert on["push"] == {"tags": ["fasttrack-deploy-*"]}


def test_plan_reads_production_revision_and_decides(deploy_wf: dict):
    plan = deploy_wf["jobs"]["plan"]
    assert plan["needs"] == "validate"
    assert set(plan["outputs"]) == {"backup", "reason"}
    steps = {s.get("id"): s for s in plan["steps"] if s.get("id")}
    prod = steps["prod"]
    assert prod["uses"].startswith("appleboy/ssh-action@")
    assert str(prod["with"]["capture_stdout"]).lower() == "true"
    assert "current-revision" in prod["with"]["script"]
    assert "pg_dump" not in prod["with"]["script"]
    decide = steps["decide"]
    run = decide["run"]
    assert "migration_heads.py decide" in run
    assert "*-force-backup" in run
    assert "FASTTRACK_FORCE_BACKUP" in decide["env"]["FORCE_VAR"]
    assert "inputs.force_backup" in decide["env"]["FORCE_INPUT"]
    assert "$GITHUB_OUTPUT" in run


GATES = {"check", "build", "frontend", "backend-unit", "static"}


def test_backup_runs_only_when_plan_says_so_and_uses_the_shared_script(deploy_wf: dict):
    backup = deploy_wf["jobs"]["backup"]
    assert set(backup["needs"]) == {"plan"} | GATES
    assert backup["environment"] == "production"
    text = yaml.safe_dump(backup)
    assert "infra/scripts/backup-database.sh" in text
    assert "BACKUP_LABEL" in text
    assert "releases/current" in text


def test_backup_waits_for_every_gate_and_a_forced_plan(deploy_wf: dict):
    """P62-C: no dump for a deploy whose tests fail (2026-10-26: 2 of 5 dumps were)."""
    expr = deploy_wf["jobs"]["backup"]["if"]
    ok = {"plan": "success", **{g: "success" for g in GATES}}
    assert _eval_if(expr, ok, {"plan": {"backup": "true"}}) is True
    assert _eval_if(expr, ok, {"plan": {"backup": "false"}}) is False
    for gate in GATES:
        for bad in ("failure", "skipped", "cancelled"):
            got = _eval_if(expr, {**ok, gate: bad}, {"plan": {"backup": "true"}})
            assert got is False, (gate, bad)


def test_check_no_longer_waits_for_a_backup(deploy_wf: dict):
    check = deploy_wf["jobs"]["check"]
    assert check["needs"] == "plan"
    assert "if" not in check


DEPLOY_NEEDS = {"plan", "backup"} | GATES


@pytest.mark.parametrize(
    ("plan", "plan_backup", "backup", "runs"),
    [
        ("success", "false", "skipped", True),  # not forced: skip counts as success
        ("success", "true", "success", True),  # forced: backup ran and passed
        ("success", "true", "failure", False),  # a failed backup stops the deploy
        ("success", "true", "cancelled", False),
        ("success", "true", "skipped", False),  # needed but skipped: never deploy
        ("failure", "", "skipped", False),  # could not decide: stop
        ("skipped", "", "skipped", False),  # validate failed
    ],
)
def test_deploy_treats_only_a_legitimately_skipped_backup_as_success(
    deploy_wf: dict, plan: str, plan_backup: str, backup: str, runs: bool
):
    deploy = deploy_wf["jobs"]["deploy"]
    results = {g: "success" for g in GATES} | {"plan": plan, "backup": backup}
    got = _eval_if(deploy["if"], results, {"plan": {"backup": plan_backup}})
    assert got is runs


def test_deploy_needs_every_gate_and_checks_each_result(deploy_wf: dict):
    deploy = deploy_wf["jobs"]["deploy"]
    assert set(deploy["needs"]) == DEPLOY_NEEDS
    all_ok = {job: "success" for job in DEPLOY_NEEDS}
    assert _eval_if(deploy["if"], all_ok, {}) is True
    for job in GATES:
        for bad in ("failure", "skipped", "cancelled"):
            results = {**all_ok, job: bad}
            assert _eval_if(deploy["if"], results, {}) is False, (job, bad)


def test_the_p55_gates_are_unchanged(deploy_wf: dict):
    jobs = deploy_wf["jobs"]
    for job in ("build", "frontend", "backend-unit", "static"):
        assert jobs[job]["needs"] == "validate", job
        assert "if" not in jobs[job], job


# ------------------------------------------------------- safe-alembic-upgrade.sh


FAKE_HELPER = textwrap.dedent(
    """\
    import json, os, sys
    cmd = sys.argv[1]
    log = os.environ.get("FAKE_LOG")
    if log:
        with open(log, "a") as fh:
            fh.write("helper " + cmd + "\\n")
    answers = {
        "estimate-db-bytes": "1000",
        "current-revision": os.environ.get("FAKE_FROM_REV", "h"),
        "head-revision": "h",
        "pending-revisions": os.environ.get("FAKE_PENDING", "[]"),
        "row-counts": json.dumps({"users": 1}),
        "verify-migration-privileges": json.dumps({"role": "owner"}),
        "migration-db-url": "postgresql://fake/db",
        "verify-token-decrypt": json.dumps({"decrypt": "ok"}),
    }
    if cmd == "verify-backup-size-floor":
        sys.exit(0)
    print(answers[cmd])
    """
)

FAKE_PG_DUMP = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    set -eu
    echo "pg_dump $*" >> "${FAKE_LOG}"
    [ -z "${FAKE_PG_DUMP_FAIL:-}" ] || exit 1
    out=""
    while [ $# -gt 0 ]; do
      if [ "$1" = "-f" ]; then out="$2"; shift; fi
      shift
    done
    head -c 2097152 /dev/zero > "${out}"
    """
)

FAKE_PG_RESTORE = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    set -eu
    echo "pg_restore $*" >> "${FAKE_LOG}"
    for t in ${FAKE_TOC_TABLES:-alembic_version users shops tiktok_credentials a b c d e f}; do
      echo "1; 0 1 TABLE DATA public ${t} owner"
    done
    """
)

FAKE_ALEMBIC = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    echo "alembic $*" >> "${FAKE_LOG}"
    """
)


def _exe(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def fake_vps(tmp_path: Path) -> dict[str, Path]:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(SCRIPTS_DIR / "safe-alembic-upgrade.sh", scripts)
    shutil.copy2(SCRIPTS_DIR / "backup-database.sh", scripts)
    (scripts / "safe_alembic_helpers.py").write_text(FAKE_HELPER, encoding="utf-8")
    (scripts / "safe_alembic_compare.py").write_text("print('ok')\n", encoding="utf-8")
    (scripts / "safe-migrate-allowlist.txt").write_text("", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _exe(bin_dir / "pg_dump", FAKE_PG_DUMP)
    _exe(bin_dir / "pg_restore", FAKE_PG_RESTORE)
    release = tmp_path / "release"
    release.mkdir()
    (release / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    alembic = _exe(tmp_path / "alembic", FAKE_ALEMBIC)
    api_env = tmp_path / "api.env"
    api_env.write_text("DATABASE_URL=postgresql://fake/db\n", encoding="utf-8")
    return {
        "scripts": scripts,
        "bin": bin_dir,
        "release": release,
        "alembic": alembic,
        "api_env": api_env,
        "backups": tmp_path / "backups",
        "log": tmp_path / "calls.log",
    }


def _env(fake: dict[str, Path], **extra: str) -> dict[str, str]:
    env = {
        "PATH": f"{fake['bin']}:{os.environ.get('PATH', '')}",
        "HOME": str(fake["release"].parent),
        "RELEASE_DIR": str(fake["release"]),
        "API_ENV_FILE": str(fake["api_env"]),
        "BACKUP_DIR": str(fake["backups"]),
        "VENV_PYTHON": sys.executable,
        "HELPER_DIR": str(fake["scripts"]),
        "ALEMBIC_BIN": str(fake["alembic"]),
        "FAKE_LOG": str(fake["log"]),
        "TIKTOK_TOKEN_ENCRYPTION_KEY": "unused",
    }
    env.update(extra)
    return env


def _run(fake: dict[str, Path], script: str, **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, str(fake["scripts"] / script)],
        capture_output=True,
        text=True,
        env=_env(fake, **extra),
        check=False,
        timeout=60,
    )


def _calls(fake: dict[str, Path]) -> list[str]:
    log = fake["log"]
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_safe_upgrade_skips_the_dump_when_nothing_is_pending(fake_vps):
    result = _run(fake_vps, "safe-alembic-upgrade.sh", FAKE_PENDING="[]")
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "no pending migration — pre-migrate dump skipped" in out
    calls = _calls(fake_vps)
    assert not [c for c in calls if c.startswith("pg_dump")]
    assert "alembic upgrade head" in calls
    # The privilege gate and the post-checks still run.
    assert "helper verify-migration-privileges" in calls
    assert "helper verify-token-decrypt" in calls
    assert not list(fake_vps["backups"].glob("*.dump")) if fake_vps["backups"].exists() else True


def test_safe_upgrade_skip_path_ignores_disk_space(fake_vps):
    result = _run(fake_vps, "safe-alembic-upgrade.sh", FAKE_PENDING="[]", DISK_MARGIN_MB="99999999")
    assert result.returncode == 0, result.stdout + result.stderr


def test_safe_upgrade_dumps_before_a_pending_migration(fake_vps):
    result = _run(fake_vps, "safe-alembic-upgrade.sh", FAKE_PENDING='["abc"]')
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "pre-migrate dump skipped" not in out
    calls = _calls(fake_vps)
    dump_at = next(i for i, c in enumerate(calls) if c.startswith("pg_dump"))
    assert calls.index("alembic upgrade head") > dump_at
    assert "--exclude-table-data=public.processed_events" in calls[dump_at].split()
    assert len(list(fake_vps["backups"].glob(BACKUP_GLOB))) == 1


def test_safe_upgrade_unreadable_revision_still_dumps(fake_vps):
    # current-revision empty -> pending-revisions walks the whole history.
    result = _run(
        fake_vps, "safe-alembic-upgrade.sh", FAKE_FROM_REV="", FAKE_PENDING='["001","002"]'
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert any(c.startswith("pg_dump") for c in _calls(fake_vps))


def test_safe_upgrade_fails_closed_when_the_pending_dump_fails(fake_vps):
    result = _run(
        fake_vps, "safe-alembic-upgrade.sh", FAKE_PENDING='["abc"]', FAKE_PG_DUMP_FAIL="1"
    )
    out = result.stdout + result.stderr
    assert result.returncode != 0
    assert "pg_dump failed — aborting before alembic upgrade" in out
    assert "alembic upgrade head" not in _calls(fake_vps)


def test_safe_upgrade_fails_closed_on_disk_space_when_pending(fake_vps):
    result = _run(
        fake_vps, "safe-alembic-upgrade.sh", FAKE_PENDING='["abc"]', DISK_MARGIN_MB="99999999"
    )
    assert result.returncode != 0
    assert "insufficient disk space" in result.stdout + result.stderr
    assert "alembic upgrade head" not in _calls(fake_vps)


# ------------------------------------------------------------- backup-database.sh


def test_backup_database_writes_a_verified_labelled_dump_and_rotates(fake_vps):
    backups = fake_vps["backups"]
    backups.mkdir()
    old = backups / "juli-pre-migrate-20200101T000000Z.dump"
    old.write_bytes(b"x")
    (backups / f"{old.name}.sha256").write_text("x")
    recent = backups / "juli-pre-migrate-20991231T000000Z-daily.dump"
    recent.write_bytes(b"x")
    month_ago = time.time() - 30 * 86400
    os.utime(old, (month_ago, month_ago))

    result = _run(fake_vps, "backup-database.sh", BACKUP_LABEL="daily")
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "BACKUP OK" in out
    dumps = sorted(p.name for p in backups.glob(BACKUP_GLOB))
    new = [n for n in dumps if n != recent.name]
    assert len(new) == 1 and new[0].endswith("-daily.dump"), dumps
    assert fnmatch.fnmatch(new[0], BACKUP_GLOB)
    assert (backups / f"{new[0]}.sha256").is_file()
    assert not old.exists() and not (backups / f"{old.name}.sha256").exists()
    assert recent.exists()
    assert not list(backups.glob("*.partial*"))
    calls = _calls(fake_vps)
    dump_at = next(i for i, c in enumerate(calls) if c.startswith("pg_dump"))
    assert calls.index("helper verify-migration-privileges") < dump_at
    assert "--exclude-table-data=public.processed_events" in calls[dump_at].split()


def test_backup_database_keep_backups_caps_the_count(fake_vps):
    backups = fake_vps["backups"]
    backups.mkdir()
    for i in range(3):
        p = backups / f"juli-pre-migrate-2026010{i}T000000Z.dump"
        p.write_bytes(b"x")
        t = time.time() - (10 - i) * 3600
        os.utime(p, (t, t))
    result = _run(fake_vps, "backup-database.sh", BACKUP_LABEL="daily", KEEP_BACKUPS="2")
    assert result.returncode == 0, result.stdout + result.stderr
    names = sorted(p.name for p in backups.glob(BACKUP_GLOB))
    assert len(names) == 2
    assert any(n.endswith("-daily.dump") for n in names)


def test_backup_database_refuses_a_dump_missing_a_required_table(fake_vps):
    result = _run(
        fake_vps,
        "backup-database.sh",
        BACKUP_LABEL="daily",
        FAKE_TOC_TABLES="alembic_version users shops a b c d e f g h",
    )
    assert result.returncode != 0
    assert "no data for public.tiktok_credentials" in result.stderr
    backups = fake_vps["backups"]
    assert not list(backups.glob(BACKUP_GLOB))
    assert not list(backups.glob("*.partial*"))


def test_backup_database_refuses_a_thin_toc(fake_vps):
    result = _run(
        fake_vps,
        "backup-database.sh",
        BACKUP_LABEL="daily",
        FAKE_TOC_TABLES="alembic_version users shops tiktok_credentials",
    )
    assert result.returncode != 0
    assert "TABLE DATA entries" in result.stderr


def test_backup_database_refuses_a_failed_pg_dump(fake_vps):
    result = _run(fake_vps, "backup-database.sh", BACKUP_LABEL="daily", FAKE_PG_DUMP_FAIL="1")
    assert result.returncode != 0
    assert "pg_dump exited non-zero" in result.stderr
    assert not list(fake_vps["backups"].glob("*"))


def _seed_dump(backups: Path, name: str, age_hours: float) -> Path:
    backups.mkdir(exist_ok=True)
    path = backups / name
    path.write_bytes(b"x")
    t = time.time() - age_hours * 3600
    os.utime(path, (t, t))
    return path


def test_backup_database_cadence_guard_skips_a_recent_dump_without_db_contact(fake_vps):
    _seed_dump(fake_vps["backups"], "juli-pre-migrate-20261020T000000Z-daily.dump", 10)
    result = _run(
        fake_vps, "backup-database.sh", BACKUP_LABEL="daily", BACKUP_MIN_INTERVAL_HOURS="72"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "dump skipped" in result.stdout
    assert not _calls(fake_vps)  # no helper, no pg_dump: zero egress
    assert len(list(fake_vps["backups"].glob(BACKUP_GLOB))) == 1


def test_backup_database_cadence_guard_dumps_when_the_newest_is_old_enough(fake_vps):
    _seed_dump(fake_vps["backups"], "juli-pre-migrate-20261017T000000Z-daily.dump", 80)
    result = _run(
        fake_vps, "backup-database.sh", BACKUP_LABEL="daily", BACKUP_MIN_INTERVAL_HOURS="72"
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "BACKUP OK" in out
    assert re.search(r"DUMP_SIZE label=daily bytes=\d+ db_bytes=\d+", out)
    assert len(list(fake_vps["backups"].glob(BACKUP_GLOB))) == 2


def test_backup_database_default_has_no_cadence_guard(fake_vps):
    # The deploy workflow's backup job never sets it: a migration deploy always dumps.
    _seed_dump(fake_vps["backups"], "juli-pre-migrate-20261021T000000Z-daily.dump", 0.1)
    result = _run(fake_vps, "backup-database.sh", BACKUP_LABEL="fasttrack-abc1234")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(list(fake_vps["backups"].glob(BACKUP_GLOB))) == 2


def test_backup_database_refuses_a_bad_interval(fake_vps):
    result = _run(
        fake_vps, "backup-database.sh", BACKUP_LABEL="daily", BACKUP_MIN_INTERVAL_HOURS="3d"
    )
    assert result.returncode != 0
    assert "BACKUP_MIN_INTERVAL_HOURS" in result.stderr


@pytest.mark.parametrize("label", ["", "../etc", "a b", "x;rm"])
def test_backup_database_refuses_an_unsafe_label(fake_vps, label: str):
    result = _run(fake_vps, "backup-database.sh", BACKUP_LABEL=label or " ")
    assert result.returncode != 0
    assert "BACKUP_LABEL" in result.stderr
    assert not _calls(fake_vps)


# ------------------------------------------------------------------------ systemd


def test_daily_backup_units_are_consistent_with_the_restore_drill():
    service = (SYSTEMD_DIR / "juli-db-backup.service").read_text(encoding="utf-8")
    timer = (SYSTEMD_DIR / "juli-db-backup.timer").read_text(encoding="utf-8")
    drill = (SYSTEMD_DIR / "juli-restore-drill.service").read_text(encoding="utf-8")

    for section in ("[Unit]", "[Service]", "[Install]"):
        assert section in service
    assert "Type=oneshot" in service
    assert "ExecStart=/root/Juli-AI-v2/infra/scripts/backup-database.sh" in service
    assert "Environment=BACKUP_LABEL=daily" in service
    assert "Environment=BACKUP_MIN_INTERVAL_HOURS=72" in service

    def env_value(text: str, key: str) -> str:
        match = re.search(rf"^Environment={key}=(\S+)$", text, re.M)
        assert match, key
        return match.group(1)

    # Same release and the same directory the drill restores from.
    for key in ("RELEASE_DIR", "BACKUP_DIR"):
        assert env_value(service, key) == env_value(drill, key)

    assert "[Timer]" in timer
    assert "Unit=juli-db-backup.service" in timer
    assert re.search(r"^OnCalendar=\*-\*-\* \d\d:\d\d:\d\d UTC$", timer, re.M)
    assert "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer
    assert os.access(SCRIPTS_DIR / "backup-database.sh", os.X_OK)


def test_daily_dump_name_is_one_the_restore_drill_and_rotation_pick_up():
    script = (SCRIPTS_DIR / "backup-database.sh").read_text(encoding="utf-8")
    assert "juli-pre-migrate-${TS}-${BACKUP_LABEL}.dump" in script
    assert fnmatch.fnmatch("juli-pre-migrate-20261021T193000Z-daily.dump", BACKUP_GLOB)
    rotation = (SCRIPTS_DIR / "safe-alembic-upgrade.sh").read_text(encoding="utf-8")
    assert "'juli-pre-migrate-*.dump'" in rotation


def test_safe_upgrade_and_backup_job_logs_are_documented():
    readme = (REPO_ROOT / "fasttrack/README.md").read_text(encoding="utf-8")
    assert "force_backup" in readme
    assert "juli-db-backup.timer" in readme
    assert "BACKUP_MIN_INTERVAL_HOURS" in readme
