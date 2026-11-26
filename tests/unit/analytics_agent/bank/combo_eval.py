"""One generated combination: run it, judge it against the oracle and the gap rules, and keep
the records the bank pins (`combo_record.json`):

- per gap rule, the combinations it explains (count + hash): a fix or a regression inside a
  rule's footprint changes the hash, so the record must be updated in the same change;
- per mismatch case, its CURRENT outcome bucket (owner 26/11: pinned, not xfail-by-default).

Record after a change (one process, ~2 min for the gate, ~35 min for the full product):

    PYTHONPATH=backend/src:. python -m tests.unit.analytics_agent.bank.combo_eval --gate
    PYTHONPATH=backend/src:. python -m tests.unit.analytics_agent.bank.combo_eval --full
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.unit.analytics_agent.bank import combos, runner
from tests.unit.analytics_agent.bank.cached import CachedCardEngine, CachedData

RECORD_FILE = Path(__file__).parent / "combo_record.json"


@dataclass
class Verdict:
    status: str  # pass | gap | fail | mismatch
    rules: list[str] = field(default_factory=list)
    unexplained: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    bucket: str | None = None


def judge(case: dict[str, Any], out: Any, problems: list[str]) -> Verdict:
    if case["family"] == "mismatch":
        return Verdict("mismatch", bucket=combos.bucket(case, out), problems=problems)
    rules = [g for g in combos.GAP_RULES if g.applies(case)]
    if not problems:
        return Verdict("pass")
    unexplained = []
    used: set[str] = set()
    for p in problems:
        crash = bool(re.search(combos.CRASH, p))
        hit = [g for g in rules if g.matches(p) and (not crash or g.explains != combos.ANY)]
        used.update(g.name for g in hit)
        if not hit:
            unexplained.append(p)
    if unexplained:
        return Verdict("fail", sorted(used), unexplained, problems)
    return Verdict("gap", sorted(used), [], problems)


def case_of(cid: str) -> dict[str, Any]:
    if cid.startswith("data."):
        _, p, s, m, o = cid.split(".", 4)
        return combos.data_case(p, s, m, o)
    return _others()[cid]


_OTHER_CACHE: dict[str, dict[str, Any]] = {}


def _others() -> dict[str, dict[str, Any]]:
    if not _OTHER_CACHE:
        _OTHER_CACHE.update({c["id"]: c for c in combos.other_families()})
    return _OTHER_CACHE


def ids(full: bool) -> list[str]:
    data = (
        [f"data.{p.id}.{s.id}.{m}.{o}" for p in combos.D.PERIODS for s in combos.D.SCOPES
         for m in combos.D.metric_ids() for o in combos.D.OUTPUTS]
        if full
        else [f"data.{p}.{s}.{m}.{o}" for p, s, m, o in combos.covering_rows()]
    )  # fmt: skip
    return [*data, *_others()]


async def run_one(factory: Any, shop_id: Any, case: dict[str, Any]) -> tuple[Any, list[str]]:
    data, engine = CachedData(factory, shop_id), CachedCardEngine(factory, shop_id)
    out = await runner.ask(factory, data, shop_id, case, engine=engine)
    return out, await runner.check(out, case, factory, shop_id)


def footprint_hash(found: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(found)).encode()).hexdigest()[:16]


def summarise(verdicts: dict[str, Verdict]) -> dict[str, Any]:
    rules: dict[str, list[str]] = {g.name: [] for g in combos.GAP_RULES}
    for cid, v in verdicts.items():
        for r in v.rules:
            rules[r].append(cid)
    return {
        "combinations": len(verdicts),
        "passed": sum(1 for v in verdicts.values() if v.status == "pass"),
        "gap": sum(1 for v in verdicts.values() if v.status == "gap"),
        "failed": sorted(c for c, v in verdicts.items() if v.status == "fail"),
        "rules": {r: {"count": len(c), "hash": footprint_hash(c)} for r, c in rules.items()},
        "mismatch": {c: v.bucket for c, v in sorted(verdicts.items()) if v.bucket},
    }


async def _record(full: bool, path: Path, shop_id: Any) -> dict[str, Any]:
    from tests.unit.analytics_agent.bank.world import sqlite_factory

    verdicts: dict[str, Verdict] = {}
    t0 = time.monotonic()
    async with sqlite_factory(path) as factory:
        for n, cid in enumerate(ids(full), 1):
            case = case_of(cid)
            out, problems = await run_one(factory, shop_id, case)
            verdicts[cid] = judge(case, out, problems)
            if n % 5000 == 0:
                print(n, f"{time.monotonic() - t0:.0f}s", flush=True)
    summary = summarise(verdicts)
    summary["seconds"] = round(time.monotonic() - t0)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--gate", action="store_true")
    g.add_argument("--full", action="store_true")
    args = ap.parse_args()
    from tests.unit.analytics_agent.bank.world import build_sqlite

    path = Path(tempfile.mkdtemp()) / "shop.sqlite"
    summary = asyncio.run(_record(args.full, path, build_sqlite(path)))
    rec = json.loads(RECORD_FILE.read_text(encoding="utf-8")) if RECORD_FILE.exists() else {}
    rec["full" if args.full else "gate"] = summary
    RECORD_FILE.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(
        f"{summary['combinations']} combinations: {summary['passed']} pass, {summary['gap']} "
        f"known gap, {len(summary['failed'])} unexplained, {summary['seconds']}s"
    )


if __name__ == "__main__":
    main()
