# Module: agent/tools

## Responsibility

Agent tool registry core (ADR-069 decision 3, issue #980 / W1-A) — holds `ToolSpec`
capability definitions for the LLM-driven agent execution loop and renders each
definition's model-facing JSON schema straight from its declared Pydantic input model,
so schema and validation cannot drift.

This slice is registry + rendering only: no marketplace client, no marketplace I/O, and
no real capability handlers are registered here. Distinct from the legacy Celery tool
registry (`services/execution/runner.py`), which is name -> callable with no metadata and
stays untouched.

## Public Interface

- `ToolSpec` (frozen dataclass) — `name`, `description`, `input_model`, `output_model`
  (Pydantic `BaseModel` subclasses), `classification` (`ToolClassification`), `policy`
  (`ToolPolicy`), `timeout_seconds`
- `ToolSpec.render_input_schema()` — the model-facing JSON schema, exactly
  `input_model.model_json_schema()`
- `ToolClassification` — `READ` | `WRITE`
- `ToolPolicy` — `AUTO` | `CONFIRM` (NEVER-class operations are never registered — ADR-068)
- `ToolRegistry` — explicit `register(spec)`, `get(name)`, `list_all()`
- `DuplicateToolError` — raised by `register` on a duplicate name
- `UnknownToolError` — raised by `get` on an unknown name (names it in the message)

## Not yet in this module

Domain-grouped handlers (`product.py` first), a shared/default registry instance,
playbook allowlist cross-validation, and any real capability — later slices per
`docs/product/agent-workflow-execution/PLAN.md` P3+P4.
