#!/usr/bin/env python3
"""PreToolUse gate: no writes from a checkout that will mislead you.

Companion to ``.claude/hooks/executor_cache_gate.py``. That gate enforces *who* may edit
product code; this one enforces *where from*.

The failure it prevents is not a bad edit — it is a correct edit applied to the wrong
tree. On 2026-08-11 the primary working directory was found 90 commits and 8.5 days
behind ``origin/main`` with two worktrees abandoned at the repo root. Every agent that
started there read stale source and believed it, and the resulting rework was invisible
because each individual change was locally sound.

Prompt discipline had already failed at this: ``.cursor/rules/git-baseline.mdc`` has
described the correct worktree lifecycle since #666, and the drift happened anyway. So
the check runs as a gate rather than as advice.

Behaviour
---------
* Delegates every judgement to ``agent-runtime/scripts/git/checkout_preflight.py`` — one
  implementation, usable by hand, by CI, and by this hook.
* Blocks (exit 2) only on ``FAIL`` findings in ``BLOCKING_CHECKS``. ``WARN``-level drift
  (dirty tree, worktree count) never blocks a write.
* **No network.** Staleness is measured against the local ``origin/main`` ref.
* Verdicts are cached briefly per checkout so the common case costs one file read.
* **Fails open** on any internal error. A broken gate must not brick the edit loop —
  the same contract the executor cache gate follows.

Escape hatch: ``JULI_SKIP_CHECKOUT_PREFLIGHT=1``. Deliberately trivial to set and
deliberately visible in the transcript when it is.

Protocol: PreToolUse JSON on stdin; exit 0 allows, exit 2 blocks with stderr fed back to
the agent.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
ENGINE_REL = Path("agent-runtime/scripts/git/checkout_preflight.py")
CACHE_TTL_SECONDS = 120


def load_engine(repo: Path):
    """Import the preflight engine from the repo being edited, not from a fixed path."""
    spec = importlib.util.spec_from_file_location("checkout_preflight", repo / ENGINE_REL)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: @dataclass resolves annotations via sys.modules[cls.__module__],
    # which raises AttributeError if the module is absent. Skipping this made the gate
    # throw during import and silently fail open — a gate that cannot fail is not a gate.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def cache_path(repo: Path, branch: str) -> Path:
    key = hashlib.sha256(f"{repo}\n{branch}".encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"juli-checkout-preflight-{key}.json"


def cached_verdict(path: Path) -> str | None:
    try:
        blob = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - blob.get("ts", 0) > CACHE_TTL_SECONDS:
        return None
    return blob.get("message")


def store_verdict(path: Path, message: str) -> None:
    try:
        path.write_text(json.dumps({"ts": time.time(), "message": message}))
    except OSError:
        pass


def build_message(repo: Path, branch: str, blocking: list) -> str:
    lines = [
        f"Checkout preflight: blocked a write from {repo} [{branch}].",
        "",
        "This checkout will give you wrong answers. Fix it before editing:",
        "",
    ]
    for f in blocking:
        lines.append(f"  * {f.check} — {f.headline}")
        if f.detail:
            lines.append(f"      {f.detail}")
        if f.remedy:
            lines.append(f"      fix: {f.remedy}")
        lines.append("")
    lines += [
        "Full report:",
        "    python agent-runtime/scripts/git/checkout_preflight.py --fetch",
        "",
        "Task work belongs in its own worktree cut from current main:",
        "    git fetch origin",
        "    git worktree add .worktrees/<task> -b feature/<desc> origin/main",
        "",
        "Override for this session only (and say why): JULI_SKIP_CHECKOUT_PREFLIGHT=1",
    ]
    return "\n".join(lines)


def main() -> int:
    if os.environ.get("JULI_SKIP_CHECKOUT_PREFLIGHT") == "1":
        return 0

    payload = json.load(sys.stdin)
    if payload.get("tool_name") not in WRITE_TOOLS:
        return 0

    raw_path = (payload.get("tool_input") or {}).get("file_path")
    if not raw_path:
        return 0

    cwd = Path(payload.get("cwd") or ".").resolve()
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if top.returncode != 0:
        return 0
    repo = Path(top.stdout.strip()).resolve()

    # Edits outside this repo are not ours to police.
    try:
        Path(raw_path).resolve().relative_to(repo)
    except ValueError:
        return 0

    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()

    cache = cache_path(repo, branch)
    hit = cached_verdict(cache)
    if hit is not None:
        if hit == "":
            return 0
        print(hit, file=sys.stderr)
        return 2

    engine = load_engine(repo)
    if engine is None:
        return 0  # engine absent (old branch, partial checkout) — fail open

    findings = engine.run_checks(repo, fetch=False, quick=True)
    blocking = [
        f for f in findings if f.severity == engine.FAIL and f.check in engine.BLOCKING_CHECKS
    ]
    if not blocking:
        store_verdict(cache, "")
        return 0

    message = build_message(repo, branch, blocking)
    store_verdict(cache, message)
    print(message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — a broken gate must not block all edits
        sys.exit(0)
