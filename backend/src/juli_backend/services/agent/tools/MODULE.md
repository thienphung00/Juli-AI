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

## Domain-grouped handlers (added #981/#982, wired to the sanitizer #996)

`product.py` registers the three Optimize Product READ capabilities
(`get_product_information`, `get_seo_keywords`, `check_product_status`);
`product_write.py` registers the three WRITE capabilities (`upload_product_image`,
`update_product_listing`, `update_product_price`). Both take the bound product
identity from a `ProductToolContext` injected by the (not-yet-built) run executor,
never from model input (ADR-070 decision 1). READ `output_model`s are shaped through
`services/agent/sanitize` (ADR-070 decisions 1–4 — provenance envelopes, ISO-8601
timestamps, `Money`, caps with signalled truncation); the inbound fail-closed
banned-pattern chokepoint (decision 6(a)) is a boundary seam applied by whatever
dispatches a tool call, not by the handler itself — see `product.py`'s module
docstring. WRITE `output_model`s carry no raw vendor identifier by construction and
have no vendor-sourced free text/timestamp/money value to shape (they echo
agent-authored input).

## Not yet in this module

A shared/default registry instance, playbook allowlist cross-validation (blocked on
P12, W2-A, which does not exist yet), and the real dispatcher/executor that will apply
the inbound chokepoint and pause CONFIRM tools (W3-A, `WorkflowRunner`).
