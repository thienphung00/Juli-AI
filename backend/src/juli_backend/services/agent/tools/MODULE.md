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

- `ToolSpec` (frozen dataclass) — `name`, `description` (LLM-facing English, unchanged by
  #1904), `seller_rationale_vi` (required; dictionary-governed seller-facing Vietnamese —
  distinct from `description`, issue #1904/W6-FIX), `input_model`, `output_model`
  (Pydantic `BaseModel` subclasses), `classification` (`ToolClassification`), `policy`
  (`ToolPolicy`), `timeout_seconds`, `domain` (issue #1704 — the tool domain dispatch
  resolves its handler through; a spec naming none is refused at construction, which for
  a module-level spec is import time, and again by `register`)
- `DomainlessToolError` — raised for a spec that names no domain
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

## Tool domains (#1704, W9-A/P-SHARED-4)

`domains.py` holds the types — `ToolDomain`, the subject-generic `ToolContext`,
`RunSubject`, and the three named refusals (`UnregisteredToolDomainError`,
`ToolNotInDomainError`, `ToolDomainBindingError`). `domain_registry.py` holds ONE
explicit dict literal registering them, the shape `playbooks/__init__.py`
established: import the domain artifact and add one line. `product_domain.py`
assembles the product domain from `product.py`'s READ table and
`product_write.py`'s WRITE table (disjointness asserted at import) and unwraps
the `ProductToolContext` its handlers take; `terminal.py` declares its own,
subject-agnostic and resource-free.

Dispatch (`runner/tool_executor.py`) resolves a tool's declared domain first,
so a tool absent from that domain's handler table is unreachable by
construction and refused by name. Adding a WRITE-CONFIRM capability is one
handler plus one spec in the domain's own module, and nothing in `runner/`
moves — the CONFIRM pause hangs off `ToolSpec.policy`, never off the domain.

## Registry, allowlist and dispatcher — all shipped

The shared registry, the playbook allowlist cross-validation (W2-A, #1107) and the
dispatcher (W3-A, #1183) are merged; a new tool is one `ToolSpec` registration in its
domain module.
