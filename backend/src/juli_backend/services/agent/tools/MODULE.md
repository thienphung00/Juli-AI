# Module: agent/tools

## Responsibility

Agent tool registry core (ADR-069 decision 3, issue #980 / W1-A) — holds `ToolSpec`
capability definitions for the LLM-driven agent execution loop and renders each
definition's model-facing JSON schema straight from its declared Pydantic input model,
so schema and validation cannot drift.

Handlers register here: `product.py` (7 READ, incl. `get_shop_identity` — P63), `product_write.py`
(3 WRITE) and `terminal.py` (`conclude_without_changes`, ADR-088) — eleven tools. `diagnosis_labels.py`
holds the TikTok diagnosis code -> short Vietnamese label table (pure data). `listing_codes.py`
(P79) is the codes a listing edit may cite, per field: TikTok's ∪ Juli's own listing check ∪ the
action card's evidence (pure). No marketplace
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
  `input_model.model_json_schema()` (the adapter puts it in OpenAI strict form on the wire,
  P76-1 / D78)
- `ToolSpec.parse_input(arguments)` — the one place a model-proposed call is validated
  against `input_model`; an explicit `null` for a field whose default is not `None` becomes
  that default (`null_as_default`, recursive), since strict mode makes the model send `null`
  for every optional field it leaves out
- `ToolClassification` — `READ` | `WRITE`
- `ToolPolicy` — `AUTO` | `CONFIRM` (NEVER-class operations are never registered — ADR-068)
- `ToolRegistry` — explicit `register(spec)`, `get(name)`, `list_all()`
- `DuplicateToolError` — raised by `register` on a duplicate name
- `UnknownToolError` — raised by `get` on an unknown name (names it in the message)

## Domain-grouped handlers (added #981/#982, wired to the sanitizer #996)

`product.py` registers the seven Optimize Product READ capabilities
(`get_product_diagnoses` (AC-8.4, the playbook's first step), `get_shop_identity` (P63, optional step 0.5: Get Authorized Shops with the run shop's own credential, matched to its stored cipher; `verified` / `mismatch` / `unverifiable` / `unavailable`, never an id), `get_product_information`, `get_seo_keywords`, `check_product_status`,
`inspect_product_image`, `find_product_promotions`);
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

## Listing edits as operations (fast track P76-6, D78)

`update_product_listing` takes `edits: ListingEditOps | None` (strict-schema: required +
nullable; the discriminated `description_ops` union goes out as `anyOf`). A domain may
register `ToolDomain.resolvers` (`ProposalResolver` -> `ProposalResolution`): run FIRST for
a CONFIRM proposal, before the normalizer and the precheck. The product domain's
`resolve_update_product_listing` applies the ops to the current listing
(`shop_rules.listing_structure.apply_ops`, with the run's TikTok-flagged codes) and hands
the runner params carrying the APPLIED full title / description (`edits` dropped), so the
consent panel, `params_sha` and the write all see the applied text; an `EditRejection`
(or `edits_with_text` / `edits_change_nothing` / `listing_unavailable`) is refused through
`listing_rules.edit_refusal` and counted in `RunState.proposal_refusals` like a validator
violation. `get_product_information` adds `description_sections` (the numbered sections
the ops address). Plain `title` / `description` still work (revert, prompt v3).

## Registry, allowlist and dispatcher — all shipped

The shared registry, the playbook allowlist cross-validation (W2-A, #1107) and the
dispatcher (W3-A, #1183) are merged; a new tool is one `ToolSpec` registration in its
domain module.
