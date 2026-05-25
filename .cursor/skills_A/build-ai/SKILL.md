---
name: build-ai
description: >-
  Centralized AI engineering standards — the ONE AI operating system for the project.
  Covers prompt engineering, structured outputs, tool calling, AI safety, hallucination
  prevention, evaluation frameworks, cost controls, model routing, RAG patterns, and
  caching strategies. Use when implementing AI features, writing prompts, integrating
  LLMs, designing evaluations, optimizing AI costs, or building RAG pipelines.
disable-model-invocation: true
---

# AI Platform

Centralizes ALL AI-specific logic. Prevents every feature team from reinventing AI infrastructure badly.

## Architecture

```
Request → Semantic Cache Check → Model Router → LiteLLM Gateway → Model Tier → Output Validation → Response
                                                                                      ↓
                                                                              Langfuse Trace
```

### Model Tiers

| Tier | Models | Use Case | Volume |
|------|--------|----------|--------|
| 1 | Gemini Flash | 90-95% requests: classification, extraction, formatting | High |
| 2 | Claude / GPT-4o | Complex reasoning, multi-step analysis, anomaly explanation | Low |
| 3 | Ollama / vLLM | Local embeddings, sensitive data processing | Variable |

**Default to Tier 1.** Escalate only when Tier 1 demonstrably fails quality thresholds.

## Prompt Standards

### Template Structure

```python
PROMPT_REGISTRY = {
    "inventory_forecast": {
        "version": "1.2.0",
        "system": "You are an inventory analyst for a Vietnamese POS system...",
        "user_template": "Given sales data: {sales_data}\nForecast next {horizon} days.",
        "output_schema": ForecastOutput,
        "model_tier": 1,
        "max_tokens": 1024,
        "temperature": 0.1,
    }
}
```

### Rules

1. **Never hardcode prompts inline** — use versioned templates in a registry
2. **Always request structured output** — JSON mode or function calling
3. **Pin temperature** — 0.0-0.2 for deterministic tasks, 0.7+ only for creative generation
4. **Include output schema** — Pydantic model for validation
5. **Version prompts** — SemVer, track changes, enable rollback

### Structured Output Pattern

```python
from pydantic import BaseModel

class ForecastOutput(BaseModel):
    product_id: str
    predictions: list[DailyPrediction]
    confidence: float
    model_used: str

async def get_forecast(sales_data: dict, horizon: int) -> ForecastOutput:
    response = await litellm.completion(
        model="gemini-flash",
        messages=build_messages("inventory_forecast", sales_data=sales_data, horizon=horizon),
        response_format={"type": "json_object"},
        timeout=30,
        num_retries=3,
    )
    return ForecastOutput.model_validate_json(response.choices[0].message.content)
```

## AI Safety

### Prompt Injection Defense

1. **Separate system/user content** — never concatenate user input into system prompt
2. **Input sanitization** — strip control characters, limit length
3. **Output validation** — schema enforcement rejects unexpected formats
4. **Privilege boundaries** — AI outputs never directly execute (human/code gate)

### Hallucination Prevention

1. **Ground in data** — always provide source data in context
2. **Confidence thresholds** — require model to output confidence score, reject below threshold
3. **Fact-checking pipeline** — cross-reference AI output against source data
4. **Constrained outputs** — enum fields, bounded numerics, known-entity lists

### Failure Handling

```python
async def safe_ai_call(prompt_key: str, **kwargs) -> Result:
    try:
        result = await ai_call(prompt_key, **kwargs)
        if result.confidence < CONFIDENCE_THRESHOLD:
            logger.warning("low_confidence_ai_result", extra={...})
            return fallback_result(**kwargs)
        return result
    except (TimeoutError, RateLimitError) as e:
        logger.warning("ai_call_degraded", extra={"error": str(e)})
        return fallback_result(**kwargs)
    except Exception as e:
        logger.error("ai_call_failed", exc_info=True)
        raise
```

## Evaluation Framework

### Eval Types

| Type | When | Tool |
|------|------|------|
| Unit eval | Every prompt change | pytest + golden datasets |
| Regression | Pre-merge CI | Automated scoring pipeline |
| A/B test | Model/prompt upgrades | Production traffic split |
| Human eval | Quality gates | Review queue for edge cases |

### Eval Pattern

```python
@pytest.mark.parametrize("case", load_golden_dataset("inventory_forecast"))
async def test_forecast_quality(case):
    result = await get_forecast(case.input_data, case.horizon)
    assert result.confidence > 0.7
    assert mape(result.predictions, case.expected) < 0.20
```

### Metrics

- **MAPE** — Mean Absolute Percentage Error (forecasting)
- **F1 / Precision / Recall** — classification tasks
- **BLEU / ROUGE** — text generation quality
- **Human rating** — 1-5 scale for subjective quality
- **Latency p50/p95** — response time distribution
- **Cost per request** — tokens * price per model

## Cost Controls

### Token Budgeting

```python
MODEL_BUDGETS = {
    "gemini-flash": {"max_tokens_per_request": 2048, "daily_budget_usd": 50},
    "claude-sonnet": {"max_tokens_per_request": 4096, "daily_budget_usd": 20},
    "gpt-4o": {"max_tokens_per_request": 4096, "daily_budget_usd": 10},
}
```

### Cost Optimization Strategies

1. **Semantic cache first** — LiteLLM cache for repeated/similar queries
2. **Model routing** — use cheapest model that meets quality threshold
3. **Batch operations** — aggregate multiple items into single prompt
4. **Progressive detail** — start with Tier 1, escalate only on failure
5. **Token-aware prompts** — minimize prompt size without losing quality

### Monitoring

- Track cost per feature, per tenant, per model
- Alert on budget threshold breaches (80% warning, 95% critical)
- Weekly cost reports with trend analysis
- Langfuse dashboard for per-trace cost visibility

## RAG Patterns

### When to Use RAG

- Knowledge base exceeds context window
- Data changes frequently (menus, inventory, policies)
- Need citation/provenance for answers

### Architecture

```
Query → Embed (Tier 3) → Vector Search → Context Assembly → LLM (Tier 1/2) → Response
```

### Best Practices

1. **Chunk strategy** — 512-1024 tokens, overlap 10-20%
2. **Embedding model** — local via Ollama (Tier 3) for cost control
3. **Retrieval** — top-k=5, rerank before context assembly
4. **Context window budget** — reserve 60% for retrieved content, 40% for prompt + output

## Additional Resources

- For integration checklists, see `review` skill
- For prompt template examples, see [prompt-examples.md](prompt-examples.md)
- For eval dataset guidelines, see [eval-guide.md](eval-guide.md)
