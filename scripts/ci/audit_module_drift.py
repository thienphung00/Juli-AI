#!/usr/bin/env python3
"""Nightly audit: MODULE.md public symbols vs Python AST."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    REPO_ROOT,
    VALIDATION_DIR,
    parse_architecture_map,
    parse_module_md_public_symbols,
    module_public_symbols_from_code,
    utc_now_iso,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()

    modules = parse_architecture_map()
    drift_entries: list[dict] = []
    for module_path, info in modules.items():
        if info.tier >= 3:
            continue
        module_md = REPO_ROOT / module_path / "MODULE.md"
        documented = parse_module_md_public_symbols(module_md)
        actual = module_public_symbols_from_code(module_path)
        missing_in_doc = sorted(actual - documented)
        orphan_in_doc = sorted(documented - actual)
        if missing_in_doc or orphan_in_doc:
            drift_entries.append(
                {
                    "module": module_path,
                    "tier": info.tier,
                    "missingInModuleMd": missing_in_doc,
                    "orphanInModuleMd": orphan_in_doc,
                }
            )

    payload = {
        "id": f"audit-drift-{args.date}",
        "timestamp": utc_now_iso(),
        "driftCount": len(drift_entries),
        "entries": drift_entries,
        "severity": "CRITICAL" if drift_entries else "OK",
    }
    out = VALIDATION_DIR / f"audit-drift-{args.date}.json"
    write_json(out, payload)
    print(f"wrote {out} ({len(drift_entries)} modules with drift)")
    return 1 if drift_entries else 0


if __name__ == "__main__":
    raise SystemExit(main())
