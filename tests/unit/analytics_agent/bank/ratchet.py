"""The bank only grows: `ratchet.json` records every case id with a hash of what it asks and
expects, the case count and the passing count. `test_bank_ratchet.py` fails when a recorded
case is gone, when a case changed (a loosened expectation, a pass turned xfail) or was added
without the record being updated, or when the counts drop.

Update the record after adding or tightening cases (the diff of ratchet.json is the review):

    PYTHONPATH=backend/src:. python -m tests.unit.analytics_agent.bank.ratchet --update

Removing a case needs `--allow-remove <id>` (and the owner's OK in the PR)."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from tests.unit.analytics_agent.bank.runner import ADVISOR_FILE, BANK_DIR, CASES_FILE, load_cases

RATCHET_FILE = BANK_DIR / "ratchet.json"
#: keys that do not change what a case asks or expects
FREE_KEYS = ("note",)


def case_hash(case: dict[str, Any]) -> str:
    body = {k: v for k, v in case.items() if k not in FREE_KEYS}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def snapshot(path: Path = CASES_FILE) -> dict[str, Any]:
    cases = load_cases(path)
    return {
        "count": len(cases),
        "passing": sum(1 for c in cases if c.get("status", "pass") == "pass"),
        "cases": {c["id"]: case_hash(c) for c in cases},
    }


def record() -> dict[str, Any]:
    return dict(json.loads(RATCHET_FILE.read_text(encoding="utf-8")))


def update(allow_remove: list[str]) -> dict[str, Any]:
    old = record() if RATCHET_FILE.exists() else {}
    new = {"bank": snapshot(CASES_FILE), "advisor": snapshot(ADVISOR_FILE)}
    for part in ("bank", "advisor"):
        gone = set((old.get(part) or {}).get("cases", {})) - set(new[part]["cases"])
        refused = sorted(gone - set(allow_remove))
        if refused:
            raise SystemExit(f"{part}: cases removed without --allow-remove: {refused}")
    RATCHET_FILE.write_text(json.dumps(new, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return new


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--allow-remove", nargs="*", default=[])
    args = ap.parse_args()
    if args.update:
        new = update(args.allow_remove)
        print(f"bank {new['bank']['count']} cases ({new['bank']['passing']} passing), "
              f"advisor {new['advisor']['count']}")  # fmt: skip


if __name__ == "__main__":
    main()
