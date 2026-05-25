# Evaluation Guide

## Golden Dataset Structure

```
/tests/ai_evals/
  datasets/
    inventory_forecast/
      cases.json        # Array of {input, expected_output, metadata}
      README.md         # Dataset description, collection method, update policy
    order_classification/
      cases.json
      README.md
```

### Case Format

```json
{
  "id": "forecast_001",
  "input": {
    "product_name": "Boba Milk Tea",
    "sku": "BMT-001",
    "sales_data": [45, 52, 48, 55, 42, 60, 58],
    "current_stock": 30,
    "horizon": 7
  },
  "expected_output": {
    "predictions": [50, 52, 49, 54, 47, 58, 55],
    "should_reorder": true
  },
  "metadata": {
    "difficulty": "standard",
    "added": "2025-01-15",
    "source": "production_data_anonymized"
  }
}
```

## Scoring Functions

### MAPE (Forecasting)

```python
def mape(predicted: list[float], actual: list[float]) -> float:
    errors = [abs(p - a) / max(a, 1e-6) for p, a in zip(predicted, actual)]
    return sum(errors) / len(errors)
```

Thresholds:
- Excellent: < 10%
- Acceptable: < 20%
- Needs improvement: < 30%
- Failing: >= 30%

### Classification Metrics

```python
from sklearn.metrics import precision_recall_fscore_support

def evaluate_classification(predictions, ground_truth):
    precision, recall, f1, _ = precision_recall_fscore_support(
        ground_truth, predictions, average="weighted"
    )
    return {"precision": precision, "recall": recall, "f1": f1}
```

Thresholds:
- Production ready: F1 > 0.90
- Beta ready: F1 > 0.80
- Needs work: F1 < 0.80

## Running Evals

### In Development

```bash
pytest tests/ai_evals/ -v --tb=short
```

### In CI (Pre-merge)

```yaml
# .github/workflows/ai-eval.yml
- name: Run AI Evals
  run: pytest tests/ai_evals/ --junitxml=eval-results.xml
  env:
    AI_EVAL_MODE: "ci"  # Uses cached responses when available
```

### Production Monitoring

- Langfuse traces with quality scores
- Weekly automated eval run against production outputs
- Alert on quality degradation > 5% from baseline

## Dataset Maintenance

1. **Add cases when**: new edge case found in production, new feature launched, regression detected
2. **Review quarterly**: remove stale cases, update expected outputs if business logic changes
3. **Never delete without replacement**: maintain minimum dataset size per feature
4. **Track provenance**: every case should note its source and collection date
