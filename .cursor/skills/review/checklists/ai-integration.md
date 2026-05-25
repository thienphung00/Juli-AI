# AI Integration Checklist

Apply when code integrates with any AI model (LiteLLM, OpenAI, Gemini, Claude, Ollama).

## Model Call Safety
- [ ] Timeout configured (30s default, adjust for model tier)
- [ ] Retry with exponential backoff (3 retries default)
- [ ] Fallback model defined (e.g., Tier 1 → moving average)
- [ ] Token budget enforced (max_tokens set)
- [ ] Rate limiting respected (per-model, per-tenant)

## Prompt Safety
- [ ] System prompt injection defenses in place
- [ ] User input sanitized before inclusion in prompts
- [ ] Structured output format requested (JSON mode when possible)
- [ ] Prompt template versioned and not hardcoded inline

## Output Validation
- [ ] AI response schema validated before use
- [ ] Hallucination guardrails (confidence thresholds, fact-checking)
- [ ] Graceful handling of malformed/empty responses
- [ ] Human-in-the-loop for high-stakes decisions

## Observability
- [ ] Langfuse trace wraps the model call
- [ ] Token usage logged per request
- [ ] Latency measured and reported
- [ ] Cost tracked (model + tokens)

## Cost Control
- [ ] Semantic cache checked before model call
- [ ] Appropriate model tier selected (don't use Tier 2 for Tier 1 work)
- [ ] Batch operations preferred over individual calls
- [ ] Token budget alerts configured

## Evaluation
- [ ] Benchmark dataset exists for this use case
- [ ] Regression test covers known-good outputs
- [ ] Quality scoring metric defined (MAPE, F1, human rating, etc.)
- [ ] A/B testing plan for model changes
