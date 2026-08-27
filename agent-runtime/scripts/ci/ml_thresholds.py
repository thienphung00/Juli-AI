"""Scan ML module source for cold-start and promotion threshold constants."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
ML_ROOT = REPO_ROOT / "backend" / "src" / "juli_backend" / "ai"

# Inference/training modules that must define cold-start constants in thresholds.py.
COLD_START_CONSTANTS: dict[str, tuple[str, ...]] = {
    "ad_performance": (
        "SPARSE_HISTORY_MIN_IMPRESSIONS",
        "SPARSE_HISTORY_MIN_CLICKS",
        "SPARSE_MAX_CONFIDENCE",
    ),
    "anomaly": ("ANOMALY_CONFIDENCE_THRESHOLD",),
    "seller_stage": ("RETURN_RATE_LEAKAGE_MIN", "ORDER_COUNT_NEW_MAX"),
}

# Promotion gates live in artifacts/thresholds.py when any trainer module is touched.
PROMOTION_CONSTANTS: tuple[str, ...] = (
    "SELLER_STAGE_MIN_PRECISION",
    "ANOMALY_MIN_PRECISION",
    "AD_PERFORMANCE_MAX_ROAS_MAPE",
)

TRAINER_MODULE_LEAVES = frozenset({"ad_performance", "anomaly", "seller_stage", "artifacts"})


def module_leaf(module_path: str) -> str:
    normalized = module_path.replace("\\", "/").rstrip("/")
    if normalized.startswith("backend/src/juli_backend/ai/"):
        return normalized.removeprefix("backend/src/juli_backend/ai/").split("/")[0]
    if normalized.startswith("backend/ai/"):
        return normalized.removeprefix("backend/ai/").split("/")[0]
    if normalized in {"backend/ai", "backend/src/juli_backend/ai"}:
        return ""
    return normalized.split("/")[-1]


def parse_threshold_constants(thresholds_file: Path) -> dict[str, float | int | str]:
    """Return top-level numeric/string constants from a thresholds.py file."""
    if not thresholds_file.is_file():
        return {}
    try:
        tree = ast.parse(thresholds_file.read_text(encoding="utf-8"), filename=str(thresholds_file))
    except SyntaxError:
        return {}
    constants: dict[str, float | int | str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                    value = node.value.value
                    if isinstance(value, (int, float, str)):
                        constants[target.id] = value
    return constants


def verify_cold_start_thresholds(
    touched_modules: list[str],
) -> tuple[bool, list[str], dict[str, Any]]:
    """Verify cold-start constants exist in source for inference ML modules."""
    problems: list[str] = []
    details: dict[str, Any] = {"modules": {}, "required": []}
    leaves = {module_leaf(m) for m in touched_modules}
    required_leaves = sorted(leaves & COLD_START_CONSTANTS.keys())
    details["required"] = required_leaves
    if not required_leaves:
        return True, [], details

    for leaf in required_leaves:
        thresholds_path = ML_ROOT / leaf / "thresholds.py"
        expected = COLD_START_CONSTANTS[leaf]
        found = parse_threshold_constants(thresholds_path)
        missing = [name for name in expected if name not in found]
        module_detail = {
            "thresholdsFile": thresholds_path.relative_to(REPO_ROOT).as_posix(),
            "expected": list(expected),
            "found": {k: found[k] for k in expected if k in found},
            "missing": missing,
        }
        details["modules"][leaf] = module_detail
        if missing:
            problems.append(
                f"{leaf}/thresholds.py missing cold-start constants: {', '.join(missing)}"
            )
    return len(problems) == 0, problems, details


def verify_promotion_thresholds(
    touched_modules: list[str],
) -> tuple[bool, list[str], dict[str, Any]]:
    """Verify promotion gate constants in artifacts/thresholds.py."""
    leaves = {module_leaf(m) for m in touched_modules}
    if not leaves & TRAINER_MODULE_LEAVES:
        return True, [], {"skipped": True, "reason": "no trainer modules touched"}

    thresholds_path = ML_ROOT / "artifacts" / "thresholds.py"
    found = parse_threshold_constants(thresholds_path)
    missing = [name for name in PROMOTION_CONSTANTS if name not in found]
    details: dict[str, Any] = {
        "thresholdsFile": thresholds_path.relative_to(REPO_ROOT).as_posix(),
        "expected": list(PROMOTION_CONSTANTS),
        "found": {k: found[k] for k in PROMOTION_CONSTANTS if k in found},
        "missing": missing,
    }
    if missing:
        return (
            False,
            [f"artifacts/thresholds.py missing promotion constants: {', '.join(missing)}"],
            details,
        )
    return True, [], details


def verify_ml_gates_threshold_values(
    touched_modules: list[str],
) -> tuple[bool, list[str], dict[str, Any]]:
    """Verify required threshold constants exist in source, and report their values."""
    problems: list[str] = []
    details: dict[str, Any] = {"sourceScan": {}}

    cold_ok, cold_problems, cold_details = verify_cold_start_thresholds(touched_modules)
    promo_ok, promo_problems, promo_details = verify_promotion_thresholds(touched_modules)
    problems.extend(cold_problems)
    problems.extend(promo_problems)
    details["sourceScan"]["coldStart"] = cold_details
    details["sourceScan"]["promotion"] = promo_details

    # Thresholds are READ from source, never demanded from the artifact.
    #
    # `mlGates.thresholds` used to be a hand-typed copy that this function
    # compared back to source. The comparison was optional — omit the field and
    # no check ran — so declaring thresholds could only ever hurt you, and
    # omitting them was the strictly safer move. It bought no floor, cost a
    # restatement on every threshold change, and rewarded silence.
    #
    # Any declared copy is now ignored. The gate reports what source actually
    # says, so the artifact records a value nobody had to transcribe correctly.
    source_constants: dict[str, float | int | str] = {}
    for leaf in COLD_START_CONSTANTS:
        source_constants.update(parse_threshold_constants(ML_ROOT / leaf / "thresholds.py"))
    source_constants.update(parse_threshold_constants(ML_ROOT / "artifacts" / "thresholds.py"))
    details["sourceThresholds"] = source_constants

    return len(problems) == 0, problems, details
