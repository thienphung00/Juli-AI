#!/usr/bin/env python3
"""Emit root requirements.txt from backend/pyproject.toml runtime dependencies."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


def main() -> int:
    pyproject = Path(__file__).resolve().parents[1] / "backend" / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    deps = data.get("project", {}).get("dependencies", [])
    if not deps:
        print("error: no [project].dependencies in pyproject.toml", file=sys.stderr)
        return 1
    out = Path(__file__).resolve().parents[1] / "requirements.txt"
    out.write_text("\n".join(deps) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(deps)} packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
