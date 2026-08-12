"""Agent workflow execution package (ADR-068).

Parent package for the agent-loop modules landing across the phases in
`docs/product/agent-workflow-execution/PLAN.md`:

- `tools/`    — agent tool registry and capability specs (ADR-069)
- `llm/`      — neutral block interface over the provider adapter (ADR-071)
- `sanitize/` — agent-safe result and output contract (ADR-070)

No provider or vendor SDK code belongs directly under this package; each
subordinate module owns its own containment boundary.
"""
