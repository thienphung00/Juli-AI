# Phase 3b: Build-AI — Prompt Template (Conditional)

> Use this **in addition to** `3-build.md` when the feature involves AI/LLM integration.
> Copy, fill in the `{{placeholders}}`, and paste into the same chat as the build prompt.

---

```
## AI-Specific Requirements

Read and follow the build-ai skill at `.cursor/skills_B/build-ai/SKILL.md`
before implementing any AI component.

## AI Feature Details

- Feature: **{{feature-name}}**
- AI task type: {{classification / extraction / forecasting / generation / RAG}}
- Model tier: {{1 (Gemini Flash) / 2 (Claude/GPT-4o) / 3 (Ollama local)}}
- Latency requirement: {{real-time < 2s / batch acceptable}}
- Accuracy target: {{e.g., MAPE < 20%, F1 > 0.85}}
- Cost budget: {{daily USD limit per model}}

## AI Implementation Checklist

Follow these when building the AI components:

### Prompt Engineering
- [ ] Create versioned prompt template in `PROMPT_REGISTRY`
- [ ] Use structured output with a Pydantic schema
- [ ] Pin temperature (0.0-0.2 for deterministic, 0.7+ for creative)
- [ ] Set max_tokens appropriate to the task

### Safety & Reliability
- [ ] Separate system/user content (no prompt injection surface)
- [ ] Input sanitization: strip control chars, enforce length limits
- [ ] Output validation: schema enforcement rejects bad formats
- [ ] Confidence threshold: reject results below {{threshold}}
- [ ] Fallback path: define what happens when AI fails or is slow
- [ ] Timeout + retry: `timeout=30, num_retries=3` on all model calls

### Cost Controls
- [ ] Semantic cache check before model call
- [ ] Default to cheapest model tier that meets quality bar
- [ ] Token budget enforced per request and per day
- [ ] Langfuse tracing enabled for cost visibility

### Evaluation
- [ ] Golden dataset created at `tests/eval/{{feature-name}}/`
- [ ] Eval test: parametrized pytest against golden dataset
- [ ] Metrics: {{MAPE / F1 / BLEU / human rating}} computed and asserted
- [ ] Latency p50/p95 measured
- [ ] Cost per request tracked

## Instructions

1. Read the `ai-eval-plan.md` from discover output.
2. Implement using the patterns above — no inline prompts, no unvalidated
   outputs, no model calls without timeout.
3. Write eval tests alongside implementation.
4. Report: model tier chosen, eval results, cost estimate per request.
```

---

### When to use

- Feature involves any LLM call, embedding, or RAG pipeline
- Always pair with `3-build.md` for the non-AI portions

### Exit criteria

- Prompt registered in `PROMPT_REGISTRY` with version
- Structured output schema defined and enforced
- Safety measures implemented (sanitization, confidence, fallback)
- Eval tests passing against golden dataset
- Cost within declared budget

### Next phase

Hand off to **Phase 4: Review** (`4-review.md`)
