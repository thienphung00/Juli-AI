#!/usr/bin/env python3
"""Schema-aware read/modify tool for harness configuration targets.

Agents must use this module instead of raw ApplyPatch when changing harness
surfaces declared in harness-editable.yml. Forbidden paths are enforced via
harness-safelist.yml before any write.
"""

from __future__ import annotations

import argparse
import difflib
import fnmatch
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_runtime import (  # noqa: E402
    ConfigError,
    dump_simple_yaml,
    load_simple_yaml,
    nested_get,
    nested_set,
    validate_config,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_RUNTIME_ROOT = REPO_ROOT / "agent-runtime"
DEFAULT_EDITABLE = AGENT_RUNTIME_ROOT / "config" / "harness-editable.yml"
DEFAULT_SAFELIST = AGENT_RUNTIME_ROOT / "config" / "harness-safelist.yml"
DEFAULT_CONFIG = AGENT_RUNTIME_ROOT / "config" / "agent-runtime.config.yml"
CONFIG_FILE_LABEL = "agent-runtime/config/agent-runtime.config.yml"

VALIDATION_RE = re.compile(
    r"^(>=|<=|>|<|==)\s*(-?\d+(?:\.\d+)?)$"
)


@dataclass(frozen=True)
class FieldSpec:
    target_id: str
    file: str
    path: str
    field_type: str
    validation: str
    auto_apply: bool


class HarnessConfigError(ValueError):
    """Raised when a harness config operation violates schema or safelist rules."""


def load_editable(path: Path = DEFAULT_EDITABLE) -> dict[str, Any]:
    if not path.exists():
        raise HarnessConfigError(f"harness-editable.yml not found: {path}")
    return load_simple_yaml(path)


def load_safelist(path: Path = DEFAULT_SAFELIST) -> dict[str, Any]:
    if not path.exists():
        raise HarnessConfigError(f"harness-safelist.yml not found: {path}")
    return load_simple_yaml(path)


def _normalize_repo_path(path: str | Path) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return candidate.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return candidate.as_posix()
    normalized = candidate.as_posix()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _pattern_matches(pattern: str, target: str) -> bool:
    normalized = _normalize_repo_path(target)
    if pattern.endswith("/**"):
        base = pattern[:-3].rstrip("/")
        return normalized == base or normalized.startswith(base + "/")
    if pattern.startswith("**/"):
        tail = pattern[3:]
        return fnmatch.fnmatch(normalized, tail) or fnmatch.fnmatch(Path(normalized).name, tail)
    if "**" in pattern:
        return fnmatch.fnmatch(normalized, pattern.replace("**", "*"))
    return fnmatch.fnmatch(normalized, pattern) or normalized == pattern


def check_path(path: str | Path, *, safelist: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Return (allowed, reason). False when path matches a forbidden pattern."""
    safelist = safelist or load_safelist()
    normalized = _normalize_repo_path(path)
    for entry in safelist.get("forbidden", {}).get("path_patterns", []):
        pattern = str(entry.get("pattern", ""))
        if not pattern:
            continue
        if _pattern_matches(pattern, normalized):
            exceptions = [str(item) for item in entry.get("except", [])]
            if any(_normalize_repo_path(item) == normalized for item in exceptions):
                continue
            return False, str(entry.get("reason", f"forbidden pattern: {pattern}"))
    return True, "path not forbidden"


def check_field(path: str, *, safelist: dict[str, Any] | None = None) -> tuple[bool, str]:
    safelist = safelist or load_safelist()
    for entry in safelist.get("forbidden", {}).get("field_patterns", []):
        pattern = str(entry.get("pattern", ""))
        if pattern.endswith("*") and path.startswith(pattern[:-1]):
            return False, str(entry.get("reason", f"forbidden field pattern: {pattern}"))
        if path == pattern:
            return False, str(entry.get("reason", f"forbidden field: {pattern}"))
    return True, "field not forbidden"


def iter_field_specs(editable: dict[str, Any] | None = None) -> list[FieldSpec]:
    editable = editable or load_editable()
    specs: list[FieldSpec] = []
    for target in editable.get("eligible_targets", []):
        target_id = str(target.get("id", ""))
        file_path = str(target.get("file", ""))
        auto_apply = bool(target.get("auto_apply", True))
        for field in target.get("fields", []):
            specs.append(
                FieldSpec(
                    target_id=target_id,
                    file=file_path,
                    path=str(field.get("path", "")),
                    field_type=str(field.get("type", "string")),
                    validation=str(field.get("validation", "")),
                    auto_apply=auto_apply,
                )
            )
    return specs


def find_field_spec(field_path: str, editable: dict[str, Any] | None = None) -> FieldSpec | None:
    for spec in iter_field_specs(editable):
        if spec.path == field_path:
            return spec
    return None


def list_targets(editable: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    editable = editable or load_editable()
    targets: list[dict[str, Any]] = []
    for target in editable.get("eligible_targets", []):
        fields = [
            {
                "path": spec.path,
                "type": spec.field_type,
                "validation": spec.validation,
                "autoApply": spec.auto_apply,
            }
            for spec in iter_field_specs(editable)
            if spec.target_id == target.get("id")
        ]
        targets.append(
            {
                "id": target.get("id"),
                "file": target.get("file"),
                "description": target.get("description", ""),
                "mode": target.get("mode", "yaml_field"),
                "autoApplyDefault": target.get("auto_apply", True),
                "fields": fields,
                "sections": target.get("sections", []),
            }
        )
    return targets


def allowed_auto_apply_fields(editable: dict[str, Any] | None = None) -> set[str]:
    return {
        spec.path
        for spec in iter_field_specs(editable)
        if spec.auto_apply and spec.file == CONFIG_FILE_LABEL
    }


def _coerce_value(field_type: str, raw: Any) -> Any:
    if field_type == "integer":
        return int(raw)
    if field_type == "float":
        return float(raw)
    if field_type == "boolean":
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in {"1", "true", "yes"}
    return raw


def _eval_clause(value: float | int, clause: str) -> bool:
    match = VALIDATION_RE.match(clause.strip())
    if not match:
        raise HarnessConfigError(f"unsupported validation clause: {clause!r}")
    operator, bound_raw = match.groups()
    bound = float(bound_raw)
    numeric = float(value)
    if operator == ">=":
        return numeric >= bound
    if operator == "<=":
        return numeric <= bound
    if operator == ">":
        return numeric > bound
    if operator == "<":
        return numeric < bound
    if operator == "==":
        return numeric == bound
    return False


def validate_field_value(spec: FieldSpec, value: Any) -> None:
    coerced = _coerce_value(spec.field_type, value)
    if not spec.validation:
        return
    clauses = [part.strip() for part in spec.validation.split("and")]
    for clause in clauses:
        if not _eval_clause(coerced, clause):
            raise HarnessConfigError(
                f"{spec.path}={coerced!r} failed validation {spec.validation!r}"
            )


def _resolve_config_path(field_path: str, config_path: Path | None = None) -> Path:
    spec = find_field_spec(field_path)
    if spec is None:
        raise HarnessConfigError(f"field not in harness-editable.yml: {field_path}")
    if spec.file != CONFIG_FILE_LABEL:
        raise HarnessConfigError(
            f"{field_path} maps to {spec.file}; use markdown workflow for non-YAML targets"
        )
    return config_path or (REPO_ROOT / spec.file)


def read_field(field_path: str, *, config_path: Path | None = None) -> Any:
    spec = find_field_spec(field_path)
    if spec is None:
        raise HarnessConfigError(f"field not eligible: {field_path}")
    path = _resolve_config_path(field_path, config_path)
    allowed, reason = check_path(path)
    if not allowed:
        raise HarnessConfigError(reason)
    config = load_simple_yaml(path)
    return nested_get(config, field_path)


def _file_unified_diff(before_text: str, after_text: str, file_label: str) -> str:
    return "".join(
        difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile=f"a/{file_label}",
            tofile=f"b/{file_label}",
        )
    )


def preview_change(
    field_path: str,
    value: Any,
    *,
    config_path: Path | None = None,
    editable: dict[str, Any] | None = None,
    safelist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = find_field_spec(field_path, editable)
    if spec is None:
        raise HarnessConfigError(f"field not eligible: {field_path}")

    field_allowed, field_reason = check_field(field_path, safelist=safelist)
    if not field_allowed:
        raise HarnessConfigError(field_reason)

    path = _resolve_config_path(field_path, config_path)
    path_allowed, path_reason = check_path(path, safelist=safelist)
    if not path_allowed:
        raise HarnessConfigError(path_reason)

    coerced = _coerce_value(spec.field_type, value)
    validate_field_value(spec, coerced)

    before_text = path.read_text(encoding="utf-8")
    config = load_simple_yaml(path)
    before_value = nested_get(config, field_path)
    nested_set(config, field_path, coerced)
    validate_config(config)
    after_text = "\n".join(dump_simple_yaml(config)) + "\n"
    unified = _file_unified_diff(before_text, after_text, path.name)

    return {
        "targetFile": _normalize_repo_path(path),
        "field": field_path,
        "targetId": spec.target_id,
        "before": before_value,
        "after": coerced,
        "validation": spec.validation,
        "autoApplyEligible": spec.auto_apply,
        "humanApprovalRequired": True,
        "unifiedDiff": unified,
    }


def apply_change(
    field_path: str,
    value: Any,
    *,
    config_path: Path | None = None,
    confirm: bool = False,
    approval_artifact: Path | None = None,
) -> dict[str, Any]:
    preview = preview_change(field_path, value, config_path=config_path)
    if not confirm:
        preview["applied"] = False
        preview["appliedStatus"] = "proposed"
        preview["message"] = "Dry-run only; pass --confirm after human approval"
        return preview

    if approval_artifact is not None:
        artifact = json.loads(approval_artifact.read_text(encoding="utf-8"))
        status = artifact.get("appliedStatus")
        if status not in {"accepted", "applied"}:
            raise HarnessConfigError(
                f"approval artifact appliedStatus must be accepted/applied; got {status!r}"
            )
        if artifact.get("configTarget") != field_path:
            raise HarnessConfigError(
                f"approval artifact configTarget mismatch: {artifact.get('configTarget')} != {field_path}"
            )

    path = REPO_ROOT / preview["targetFile"]
    config = load_simple_yaml(path)
    nested_set(config, preview["field"], preview["after"])
    validate_config(config)
    path.write_text("\n".join(dump_simple_yaml(config)) + "\n", encoding="utf-8")
    preview["applied"] = True
    preview["appliedStatus"] = "applied"
    preview["message"] = f"Applied {field_path}={preview['after']!r} to {preview['targetFile']}"
    return preview


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--editable", type=Path, default=DEFAULT_EDITABLE)
    parser.add_argument("--safelist", type=Path, default=DEFAULT_SAFELIST)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list-targets", help="list eligible harness targets and fields")

    read_parser = subparsers.add_parser("read", help="read an eligible field value")
    read_parser.add_argument("--field", required=True, help="dotted config path")

    preview_parser = subparsers.add_parser("preview", help="dry-run a harness field change")
    preview_parser.add_argument("--field", required=True)
    preview_parser.add_argument("--value", required=True, help="scalar value to set")

    apply_parser = subparsers.add_parser("apply", help="apply a harness field change")
    apply_parser.add_argument("--field", required=True)
    apply_parser.add_argument("--value", required=True)
    apply_parser.add_argument(
        "--confirm",
        action="store_true",
        help="apply after human approval (default is dry-run preview only)",
    )
    apply_parser.add_argument(
        "--approval-artifact",
        type=Path,
        help="harness-optimization-artifact.json with appliedStatus accepted/applied",
    )

    check_parser = subparsers.add_parser("check-path", help="check whether a repo path is forbidden")
    check_parser.add_argument("--path", required=True)

    return parser


def _parse_cli_value(raw: str) -> Any:
    stripped = raw.strip()
    if stripped.lower() in {"true", "false"}:
        return stripped.lower() == "true"
    try:
        if "." in stripped:
            return float(stripped)
        return int(stripped)
    except ValueError:
        return stripped


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    try:
        if args.command == "list-targets":
            print(json.dumps(list_targets(load_editable(args.editable)), indent=2))
            return 0

        if args.command == "read":
            value = read_field(args.field, config_path=args.config)
            print(json.dumps({"field": args.field, "value": value}, indent=2))
            return 0

        if args.command == "preview":
            result = preview_change(
                args.field,
                _parse_cli_value(args.value),
                config_path=args.config,
                editable=load_editable(args.editable),
                safelist=load_safelist(args.safelist),
            )
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "apply":
            result = apply_change(
                args.field,
                _parse_cli_value(args.value),
                config_path=args.config,
                confirm=args.confirm,
                approval_artifact=args.approval_artifact,
            )
            print(json.dumps(result, indent=2))
            return 0 if result.get("applied") else 2

        if args.command == "check-path":
            allowed, reason = check_path(args.path, safelist=load_safelist(args.safelist))
            print(json.dumps({"path": args.path, "allowed": allowed, "reason": reason}, indent=2))
            return 0 if allowed else 1
    except (HarnessConfigError, ConfigError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
