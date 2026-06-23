#!/usr/bin/env python3
"""Build effective Agent Runtime behavior from agent-runtime.config.yml."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "agent-runtime.config.yml"
EXECUTOR_ALIASES = {
    "ui": "ui-ux",
    "ml": "machine-learning",
    "data": "data-platform",
}


class ConfigError(ValueError):
    """Raised when the harness config cannot produce a runtime definition."""


def parse_scalar(value: str) -> Any:
    stripped = value.strip()
    if stripped in {"true", "True"}:
        return True
    if stripped in {"false", "False"}:
        return False
    if stripped in {"[]", ""}:
        return [] if stripped == "[]" else ""
    if (
        (stripped.startswith('"') and stripped.endswith('"'))
        or (stripped.startswith("'") and stripped.endswith("'"))
    ):
        return stripped[1:-1]
    try:
        if "." in stripped:
            return float(stripped)
        return int(stripped)
    except ValueError:
        return stripped


def _next_container(lines: list[tuple[int, str]], index: int, indent: int) -> Any:
    for next_indent, next_text in lines[index + 1 :]:
        if next_indent <= indent:
            return {}
        return [] if next_text.startswith("- ") else {}
    return {}


def load_simple_yaml(path: Path) -> dict[str, Any]:
    """Parse the small YAML subset used by agent-runtime.config.yml.

    Supported syntax: nested mappings, string/number/bool scalars, and lists of
    scalars. This keeps runtime generation stdlib-only and reviewable.
    """

    logical_lines: list[tuple[int, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        logical_lines.append((indent, raw_line.strip()))

    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    for index, (indent, text) in enumerate(logical_lines):
        while indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if text.startswith("- "):
            if not isinstance(parent, list):
                raise ConfigError(f"list item without list parent at line: {text}")
            parent.append(parse_scalar(text[2:]))
            continue

        if ":" not in text:
            raise ConfigError(f"expected key/value mapping at line: {text}")
        key, raw_value = text.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not raw_value:
            container = _next_container(logical_lines, index, indent)
            parent[key] = container
            stack.append((indent, container))
        else:
            parent[key] = parse_scalar(raw_value)

    return root


def _require_mapping(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"config.{key} must be a mapping")
    return value


def _require_list(config: dict[str, Any], key: str) -> list[Any]:
    value = config.get(key)
    if not isinstance(value, list):
        raise ConfigError(f"config.{key} must be a list")
    return value


def validate_config(config: dict[str, Any]) -> None:
    required = {
        "version",
        "prompt",
        "model",
        "context",
        "routing",
        "executors",
        "skills",
        "tools",
        "agent_structure",
        "benchmark",
    }
    missing = sorted(required - config.keys())
    if missing:
        raise ConfigError(f"missing required config sections: {', '.join(missing)}")

    prompt = _require_mapping(config, "prompt")
    model = _require_mapping(config, "model")
    context = _require_mapping(config, "context")
    routing = _require_mapping(config, "routing")
    executors = _require_mapping(config, "executors")
    agent_structure = _require_mapping(config, "agent_structure")
    benchmark = _require_mapping(config, "benchmark")

    if not prompt.get("system_prompt"):
        raise ConfigError("prompt.system_prompt is required")
    if not model.get("primary") or not model.get("fallback"):
        raise ConfigError("model.primary and model.fallback are required")
    if int(context.get("budget_tokens", 0)) <= 0 or int(context.get("max_files", 0)) <= 0:
        raise ConfigError("context.budget_tokens and context.max_files must be positive")

    for key in ("backend_threshold", "ui_threshold", "data_threshold", "ml_threshold"):
        value = float(routing.get(key, -1))
        if value < 0 or value > 1:
            raise ConfigError(f"routing.{key} must be between 0 and 1")

    enabled = _require_list(executors, "enabled")
    if not enabled:
        raise ConfigError("executors.enabled must contain at least one executor")
    if agent_structure.get("mode") not in {
        "single_executor",
        "planner_executor",
        "planner_executor_reviewer",
    }:
        raise ConfigError("agent_structure.mode is invalid")
    if not isinstance(benchmark.get("enabled"), bool):
        raise ConfigError("benchmark.enabled must be boolean")


def normalize_executor_name(name: str) -> str:
    return EXECUTOR_ALIASES.get(name, name)


def build_effective_prompt(prompt_config: dict[str, Any]) -> str:
    selector = str(prompt_config["system_prompt"])
    variants = prompt_config.get("variants") or {}
    if not isinstance(variants, dict):
        raise ConfigError("prompt.variants must be a mapping when present")
    base_prompt = str(variants.get(selector, selector))
    additional = prompt_config.get("additional_instructions") or []
    if not isinstance(additional, list):
        raise ConfigError("prompt.additional_instructions must be a list")
    if additional:
        return base_prompt + "\n\n" + "\n".join(f"- {item}" for item in additional)
    return base_prompt


def build_runtime(config: dict[str, Any]) -> dict[str, Any]:
    validate_config(config)
    prompt = _require_mapping(config, "prompt")
    model = _require_mapping(config, "model")
    context = _require_mapping(config, "context")
    routing = _require_mapping(config, "routing")
    executors = _require_mapping(config, "executors")
    skills = _require_mapping(config, "skills")
    tools = _require_mapping(config, "tools")

    enabled_executors = [normalize_executor_name(str(item)) for item in executors["enabled"]]
    enabled_tools = [str(item) for item in tools.get("enabled", [])]
    disabled_tools = set(str(item) for item in tools.get("disabled", []))
    active_tools = [tool for tool in enabled_tools if tool not in disabled_tools]

    active_skills = {
        executor: [str(skill) for skill in skills.get(executor, [])]
        for executor in enabled_executors
    }
    routing_table = {
        "backend": {
            "threshold": float(routing["backend_threshold"]),
            "paths": routing.get("domain_mappings", {}).get("backend", []),
        },
        "ui-ux": {
            "threshold": float(routing["ui_threshold"]),
            "paths": routing.get("domain_mappings", {}).get("ui-ux", []),
        },
        "data-platform": {
            "threshold": float(routing["data_threshold"]),
            "paths": routing.get("domain_mappings", {}).get("data-platform", []),
        },
        "machine-learning": {
            "threshold": float(routing["ml_threshold"]),
            "paths": routing.get("domain_mappings", {}).get("machine-learning", []),
        },
    }

    return {
        "version": config["version"],
        "effectivePrompt": build_effective_prompt(prompt),
        "activeTools": active_tools,
        "activeSkills": active_skills,
        "executorRoutingTable": routing_table,
        "modelConfiguration": {
            "primary": model["primary"],
            "fallback": model["fallback"],
            "allowed": model.get("allowed", []),
        },
        "agentStructure": config["agent_structure"],
        "context": context,
        "benchmark": config["benchmark"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    args = parser.parse_args()

    try:
        runtime = build_runtime(load_simple_yaml(args.config))
    except (OSError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    payload = json.dumps(runtime, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
