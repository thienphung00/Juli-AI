"""fasttrack/ci_shard.py: a sharded deploy gate runs exactly the tests an unsharded one runs."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "fasttrack" / "ci_shard.py"

_spec = importlib.util.spec_from_file_location("ci_shard", SCRIPT)
assert _spec and _spec.loader
ci_shard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci_shard)


def _unit_files() -> list[str]:
    return sorted(str(p.relative_to(REPO)) for p in (REPO / "tests" / "unit").rglob("test_*.py"))


def test_every_file_lands_in_exactly_one_shard(monkeypatch):
    monkeypatch.chdir(REPO)
    files = _unit_files()
    parts = ci_shard.shards(files, 4)
    flat = [f for part in parts for f in part]
    assert sorted(flat) == files
    assert len(flat) == len(set(flat))
    assert all(parts), "no shard may be empty for the real suite"


def test_shards_are_balanced_by_size(monkeypatch):
    monkeypatch.chdir(REPO)
    parts = ci_shard.shards(_unit_files(), 4)
    loads = [sum((REPO / f).stat().st_size for f in part) for part in parts]
    assert max(loads) <= 1.2 * min(loads)


def test_split_is_deterministic_and_drops_blanks_and_duplicates():
    paths = ["b.py", "a.py", "", "a.py", "c.py"]
    assert ci_shard.shards(paths, 2) == ci_shard.shards(list(reversed(paths)), 2)
    assert sorted(f for part in ci_shard.shards(paths, 2) for f in part) == ["a.py", "b.py", "c.py"]


def test_cli_prints_the_requested_shard_and_refuses_out_of_range(tmp_path):
    files = "\n".join(_unit_files()[:10])
    out = [
        subprocess.run(
            [sys.executable, str(SCRIPT), str(n), "3"],
            input=files,
            capture_output=True,
            text=True,
            cwd=REPO,
            check=True,
        ).stdout.split()
        for n in (1, 2, 3)
    ]
    assert sorted(f for part in out for f in part) == sorted(files.split())
    bad = subprocess.run(
        [sys.executable, str(SCRIPT), "4", "3"], input=files, capture_output=True, text=True
    )
    assert bad.returncode == 2
