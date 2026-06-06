"""Rules-vs-ML comparison report."""

from __future__ import annotations

from typing import Any

from sklearn.base import BaseEstimator

from src.modules.ml.seller_stage.inference import predict_seller_stage
from src.modules.ml.seller_stage.rules import classify_seller_stage
from src.modules.ml.seller_stage.types import ComparisonReport


def compare_to_rules_baseline(
    model: BaseEstimator,
    profiles: list[dict[str, Any]],
) -> ComparisonReport:
    """Compare ML predictions against the Phase 1 rules baseline on the same profiles."""
    disagreements: list[dict[str, Any]] = []
    agreements = 0

    for index, profile in enumerate(profiles):
        rules_stage = classify_seller_stage(profile)  # type: ignore[arg-type]
        ml_result = predict_seller_stage(model, profile)
        if rules_stage == ml_result.stage:
            agreements += 1
        else:
            disagreements.append(
                {
                    "profile_index": index,
                    "rules_stage": rules_stage,
                    "ml_stage": ml_result.stage,
                    "ml_confidence": ml_result.confidence,
                    "profile": profile,
                }
            )

    total = len(profiles)
    agreement_rate = 1.0 if total == 0 else agreements / total
    return ComparisonReport(
        agreement_rate=agreement_rate,
        total_profiles=total,
        agreements=agreements,
        disagreements=disagreements,
    )
