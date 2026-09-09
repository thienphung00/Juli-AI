# Module: agent/tools

## Responsibility

Agent tool registry core (ADR-069 decision 3, issue #980 / W1-A) — holds `ToolSpec`
capability definitions for the LLM-driven agent execution loop and renders each
definition's model-facing JSON schema straight from its declared Pydantic input model,
so schema and validation cannot drift.

Handlers register here: `product.py` (4 READ), `product_write.py` (3 WRITE) and
`terminal.py` (`conclude_without_changes`, ADR-088) — eight tools. No marketplace
client or I/O lives in this module. Distinct from the legacy Celery tool
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

`product.py` registers the four Optimize Product READ capabilities
(`get_product_information`, `get_seo_keywords`, `check_product_status`,
`inspect_product_image`);
`product_write.py` registers the three WRITE capabilities (`upload_product_image`,
`update_product_listing`, `update_product_price`). Both take the bound product
identity from a `ProductToolContext` injected by the run executor,
never from model input (ADR-070 decision 1). READ `output_model`s are shaped through
`services/agent/sanitize` (ADR-070 decisions 1–4 — provenance envelopes, ISO-8601
timestamps, `Money`, caps with signalled truncation); the inbound fail-closed
banned-pattern chokepoint (decision 6(a)) is a boundary seam applied by whatever
dispatches a tool call, not by the handler itself — see `product.py`'s module
docstring. WRITE `output_model`s carry no raw vendor identifier by construction and
have no vendor-sourced free text/timestamp/money value to shape (they echo
agent-authored input).

## Registry, allowlist and dispatcher — all shipped

The shared registry, the playbook allowlist cross-validation (W2-A, #1107) and the
dispatcher (W3-A, #1183) are merged; a new tool is one `ToolSpec` registration in its
domain module.
