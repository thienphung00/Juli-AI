"""Detect scenarios captured against a prompt that is no longer in production.

#1311 AC7: "A scenario whose `prompt_sha256` does not match the current
production prompt is detectable by a command, and the command is documented."

Why this exists. A scenario is a recording of what the agent *did* under a
particular prompt. Bump the prompt and the recording still replays perfectly —
same events, same pacing, green tests — while no longer showing what the agent
would do today. Nothing fails. That silence is the whole problem: the demo
quietly becomes fiction, and the suite keeps saying it is fine.

Recording `prompt_sha256` at capture time is what makes the drift *visible*;
this command is what makes it *checkable*. Recording alone is not the criterion.

The hash is taken from `composer.prompt_sha256()` — the same function the runner
calls when it stamps a run — rather than re-hashing the prompt here. Two
independent hash implementations would drift, and the one that drifts silently
is the one that decides whether a scenario is stale.

Usage:

    python -m juli_backend.services.agent.golden_scenarios.staleness
    python -m juli_backend.services.agent.golden_scenarios.staleness --json
    python -m juli_backend.services.agent.golden_scenarios.staleness path/to/scenarios

Exit codes: 0 every scenario matches the current production prompt; 1 at least
one is stale; 2 the scan could not be performed (bad path, unreadable scenario).
A non-zero exit is what lets CI or a pre-release check use this without anyone
reading the output.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from juli_backend.services.agent.prompts.composer import (
    UnknownWorkflowKeyError,
    production_version,
    prompt_sha256,
)

# .../backend/src/juli_backend/services/agent/golden_scenarios/staleness.py
# parents: 0 golden_scenarios, 1 agent, 2 services, 3 juli_backend, 4 src,
# 5 backend, 6 repo root.
DEFAULT_SCENARIO_DIR = (
    Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "golden_scenarios"
)


@dataclass(frozen=True)
class ScenarioStaleness:
    path: Path
    scenario_id: str
    workflow_key: str
    recorded_sha256: str
    current_sha256: str | None
    error: str | None = None

    @property
    def is_stale(self) -> bool:
        """An unresolvable workflow_key counts as stale, not as passing.

        A scenario naming a workflow that no longer has a prompt binding cannot
        be compared against production — and "cannot be compared" must never
        read as "matches". Treating it as current would let a renamed workflow
        silently retire the check for every scenario under it.
        """
        if self.current_sha256 is None:
            return True
        return self.recorded_sha256 != self.current_sha256


def _current_sha256(workflow_key: str) -> str:
    """The production prompt hash for a workflow, via the runner's own producer."""
    return prompt_sha256(workflow_key, production_version(workflow_key))


def check_scenarios(scenario_dir: Path) -> list[ScenarioStaleness]:
    """Every scenario under `scenario_dir`, with its recorded and current hashes.

    Raises FileNotFoundError when the directory is missing and ValueError when a
    file is unreadable or lacks the fields — a scan that silently returns an
    empty list would report "nothing stale" for a broken directory, which is the
    failure this command exists to prevent.
    """
    if not scenario_dir.is_dir():
        raise FileNotFoundError(f"scenario directory not found: {scenario_dir}")

    results: list[ScenarioStaleness] = []
    for path in sorted(scenario_dir.glob("*.json")):
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} is not readable JSON: {exc}") from exc

        try:
            workflow_key = data["workflow_key"]
            recorded = data["prompt_sha256"]
            scenario_id = data["scenario_id"]
        except KeyError as exc:
            raise ValueError(f"{path} is missing required field {exc}") from exc

        try:
            current: str | None = _current_sha256(workflow_key)
            error: str | None = None
        except UnknownWorkflowKeyError as exc:
            current, error = None, str(exc)

        results.append(
            ScenarioStaleness(
                path=path,
                scenario_id=scenario_id,
                workflow_key=workflow_key,
                recorded_sha256=recorded,
                current_sha256=current,
                error=error,
            )
        )
    return results


def _render_text(results: list[ScenarioStaleness]) -> str:
    if not results:
        return "no scenarios found"
    lines = []
    for r in results:
        mark = "STALE  " if r.is_stale else "current"
        lines.append(f"{mark} {r.scenario_id}  ({r.path.name})")
        if r.error:
            lines.append(f"        {r.error}")
        elif r.is_stale:
            lines.append(f"        recorded {r.recorded_sha256[:16]}…")
            lines.append(f"        current  {r.current_sha256[:16]}…")
    stale = [r for r in results if r.is_stale]
    lines.append("")
    lines.append(
        f"{len(stale)} of {len(results)} scenario(s) stale."
        + (
            "  Re-capture them, or accept that the demo shows behaviour the "
            "current prompt no longer produces."
            if stale
            else ""
        )
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="golden-scenario-staleness",
        description=(
            "Report golden scenarios whose prompt_sha256 no longer matches the "
            "current production prompt (#1311 AC7)."
        ),
    )
    parser.add_argument(
        "scenario_dir",
        nargs="?",
        default=str(DEFAULT_SCENARIO_DIR),
        help=f"directory of scenario JSON files (default: {DEFAULT_SCENARIO_DIR})",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    try:
        results = check_scenarios(Path(args.scenario_dir))
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "scenario_id": r.scenario_id,
                        "path": str(r.path),
                        "workflow_key": r.workflow_key,
                        "recorded_sha256": r.recorded_sha256,
                        "current_sha256": r.current_sha256,
                        "error": r.error,
                        "stale": r.is_stale,
                    }
                    for r in results
                ],
                indent=2,
            )
        )
    else:
        print(_render_text(results))

    return 1 if any(r.is_stale for r in results) else 0


if __name__ == "__main__":  # pragma: no cover - thin CLI entry
    raise SystemExit(main())
