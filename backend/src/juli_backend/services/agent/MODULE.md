# backend/src/juli_backend/services/agent

## Purpose

Agent-workflow services (ADR-068/069/070). This slice adds the shared
banned-pattern source loader (#990, decision 6), provenance envelopes and
machine-shaped values (#991, decisions 3/4), hard size caps with
always-signalled truncation (#992, decision 2), marketplace error
translation (#993, decision 5), and the two fail-closed banned-pattern
chokepoints that bracket the agent loop (#994, decision 6). The golden-file
gate that exercises all of it together is a separate issue (#995).


## Subpackages

- `sanitize` — loads `packages/contracts/seller-copy-banned-patterns.json`, the
  single language-neutral source of banned seller-copy patterns also consumed by
  the TypeScript guard (`packages/contracts/src/seller-copy.ts`). See
  `sanitize/banned_patterns.py`. Also provides `sanitize/provenance.py`
  (source-tagged text envelopes), `sanitize/machine_values.py` (ISO-8601
  timestamps, `Money`, bare-number rates), `sanitize/caps.py` (list/text/image
  size caps with signalled truncation), `sanitize/errors.py` (marketplace
  error -> `{"error": {"category", "message", "retryable"}}` translation),
  `sanitize/hidden_text.py` (ADR-075 decision 5, #1218 — strips control
  characters, zero-width/invisible Unicode, and bidi overrides from
  vendor-tagged text; Vietnamese diacritics and emoji are untouched), and
  `sanitize/chokepoints.py` (the two fail-closed banned-pattern seams:
  `guard_inbound_tool_result` — which strips hidden text from vendor
  fields before it scans — and `guard_outbound_agent_output`).

## Public Interface

```python
from juli_backend.services.agent.sanitize import (
    BANNED_PATTERNS_JSON_PATH,
    BannedPatternEntry,
    load_banned_pattern_entries,
    load_banned_patterns,
    # caps (#992, ADR-070 decision 2)
    FREE_TEXT_CHAR_CAP,
    LIST_ITEM_CAP,
    PER_RESULT_TOKEN_CEILING,
    PER_RESULT_TOKEN_TARGET,
    CappedImages,
    CappedList,
    CappedText,
    ImageDimensions,
    cap_list,
    cap_text,
    estimate_result_tokens,
    estimate_tokens,
    sanitize_images,
    # errors (#993, ADR-070 decision 5)
    RETRYABLE_VENDOR_CODES,
    TranslatedError,
    to_error_envelope,
    translate_marketplace_error,
    # hidden_text (#1218, ADR-075 decision 5)
    strip_hidden_text,
    strip_hidden_text_from_vendor_fields,
    # chokepoints (#994, ADR-070 decision 6 / ADR-068 decision 6(c); #1218 for stripping)
    BannedPatternGuardFailure,
    BannedPatternHit,
    BannedPatternScanError,
    find_banned_pattern_hits,
    guard_inbound_tool_result,
    guard_outbound_agent_output,
)
```

Tool domains — issue #1704, W9-A/P-SHARED-4, spec P0-3. A tool domain is the
family of tools sharing one handler table, one rule for which run subjects
they act on, and one way of turning the subject-generic tool context into
whatever their handlers take. Dispatch resolves a tool's declared domain
first, so a tool absent from that domain's table is unreachable by
construction and refused by name rather than falling through.

```python
from juli_backend.services.agent.tools.domains import (
    PRODUCT_DOMAIN,
    TERMINAL_DOMAIN,
    ContextBinder,
    RunSubject,
    ToolContext,
    ToolDomain,
    ToolDomainBindingError,
    ToolDomainError,
    ToolHandler,
    ToolNotInDomainError,
    UnregisteredToolDomainError,
    subject_generic_context,
)
from juli_backend.services.agent.tools.domain_registry import (
    bindable_subject_types,
    get_registered_tool_domains,
    get_tool_domain,
    reachable_tool_names,
    tool_domain_registered_for_test,
)
from juli_backend.services.agent.tools.product_domain import (
    PRODUCT_SUBJECT_TYPES,
    PRODUCT_TOOL_DOMAIN,
    PRODUCT_TOOL_HANDLERS,
    bind_product_context,
)
from juli_backend.services.agent.tools.terminal import TERMINAL_TOOL_DOMAIN
from juli_backend.services.agent.tools.registry import DomainlessToolError
from juli_backend.services.agent.runner.tool_executor import DomainToolExecutor
```

- RunSubject — what a run is about, the workflow_runs subject_type/subject_ref
  pair #1701 added; server-held run state, never read from tool params
- ToolContext — the subject-generic per-call context: the run's subject, the
  already-guarded marketplace resources for this call, and the domain's own
  opaque binding. Carries no product id, and no field naming any other single
  subject kind
- ToolDomain — name, handler table, the subject kinds it acts on (None for
  subject-agnostic), whether its handlers take resources, and its context
  binder; handler_for and context_for are the two resolution steps
- get_tool_domain, get_registered_tool_domains — resolution against one
  explicit dict literal, shaped after the playbook registry; never a fallback
  to the product domain
- reachable_tool_names, bindable_subject_types — derived from the registered
  domains' own tables, never a second hand-maintained list
- tool_domain_registered_for_test — the supported test seam for a second
  domain, refusing to shadow a registered one
- DomainToolExecutor — the subject-generic ToolExecutor; ProductToolExecutor
  is its product-bound specialization and keeps its own constructor
- DomainlessToolError — a tool spec naming no domain, refused at construction
  (import time for a module-level spec) and again at registration

- `load_banned_patterns() -> tuple[re.Pattern[str], ...]` — compiled patterns,
  cached.
- `load_banned_pattern_entries() -> tuple[BannedPatternEntry, ...]` — raw
  `(id, source, flags)` records, file order.
- `BANNED_PATTERNS_JSON_PATH` — resolved path to the shared JSON source.
- `cap_list(items, *, cap=LIST_ITEM_CAP) -> CappedList` — cuts to the top `cap`
  entries in the caller's own order (never re-sorts); `.to_dict()` omits the
  `truncated`/`omitted_count` keys entirely when nothing was cut.
- `cap_text(text, *, cap=FREE_TEXT_CHAR_CAP) -> CappedText` — text at or under
  the cap passes through verbatim, byte-for-byte.
- `sanitize_images(images, *, cap=LIST_ITEM_CAP) -> CappedImages` — reduces raw
  vendor image payloads to `{count, dimensions}`; only `width`/`height` survive
  per image, `count` is always the true total.
- `estimate_tokens(text) -> int` / `estimate_result_tokens(result) -> int` — a
  stdlib-only, deterministic (rounds up) `chars/4` token estimate against
  `PER_RESULT_TOKEN_CEILING` (2000) / `PER_RESULT_TOKEN_TARGET` (800). Not a
  real tokenizer — no tokenizer dependency is declared anywhere in this repo.
- `translate_marketplace_error(exc) -> TranslatedError` /
  `to_error_envelope(error) -> dict` — every marketplace failure maps to
  `{"error": {"category", "message", "retryable"}}`; `category` reuses
  `ExecutionErrorCategory`, `retryable` derives from `RETRYABLE_VENDOR_CODES`
  (`{100005, 100006, 36009003}`) plus transport-level failures.
- `guard_inbound_tool_result(result, *, tool_name) -> Mapping` — strips hidden
  text from every vendor-tagged field in `result` (#1218, ADR-075 decision 5
  — see `strip_hidden_text_from_vendor_fields` below), **then** scans the
  stripped result for a banned-pattern hit before it enters the
  conversation. Stripping runs before the scan deliberately: an identifier
  obfuscated with an invisible character would evade the scan's regexes
  otherwise. On a hit, or on any failure inside the scanning machinery
  itself, discards the result and returns the same `to_error_envelope`
  shape (`category="validation"`, `retryable=False`) — the model never sees
  the leaked value. The hit is logged server-side (`logger.warning`) with
  pattern id, structural path, and matched text. A clean result with
  nothing to strip is returned as the exact same object it was passed in
  as (object-identity preserved) — a clean result that *was* stripped
  comes back as a new, equal-except-for-the-stripped-text object.
- `guard_outbound_agent_output(output) -> None` — scans agent-authored output
  before it streams or persists. Raises `BannedPatternGuardFailure` on a hit,
  or on a scanning-machinery failure. Seam only — no repair-retry or
  rules-template fallback (that recovery behavior is deferred to the
  user-deferred structured-output phase, #994).
- `strip_hidden_text(text) -> str` — removes control characters (Unicode
  category `Cc`, minus `\t`/`\n`/`\r`) and format characters (category `Cf`
  — every zero-width character and every bidi-override control character
  lives in this one category) from `text`. Vietnamese combining diacritics
  (`Mn`) and emoji (`So`/`Sk`) are untouched (#1218, ADR-075 decision 5).
- `strip_hidden_text_from_vendor_fields(value) -> Any` — recursively strips
  hidden text from every node shaped `{"source": "vendor", "text": ...}`
  inside `value`; `seller`/`juli` envelopes and plain strings are left
  alone. This is the function `guard_inbound_tool_result` calls ahead of
  its scan (#1218).
- `find_banned_pattern_hits(value) -> tuple[BannedPatternHit, ...]` — the
  shared whole-structure scan both guards use; raises
  `BannedPatternScanError` if the shared pattern source fails to load/compile.

The package facade itself. The import-boundary contract caps a
cross-package caller at depth 2 (importlinter's max_cross_package_depth), so
the api package reaches this one by importing a MODULE OBJECT, never a symbol
inside one -- and the name it imports is part of this package's public surface
just as much as a function would be. Both names below are that surface,
recorded here because nothing else records it:

- `approval` — the approve-is-run-creation transaction module, imported as
  "from juli_backend.services.agent import approval as approval_module" by
  api/routes/demo_execution.py. Its contents are listed immediately below.
- `abuse_limits` — the inbound abuse-limit gate for the agent-run routes,
  imported the same way by api/routes/demo_execution.py,
  api/routes/agent_runs.py and api/main.py. Described in full under
  "Top-level modules".

Neither name is an export in the syntax-tree sense -- a submodule is not a
function or a class -- so the symbol scanner cannot see it, and the derived
drift allowlist therefore records both as orphan entries. That is a limitation
of the symbol scanner, not a claim that the names are unused: the
module-boundary gate reads this same section and refuses the import without
them.

Approve-is-run-creation (approval.py, reached as `from
juli_backend.services.agent import approval`):

- The transaction and its result (ADR-075 decision 1, ADR-082, #1222;
  rewritten by #1702) — `approve_action_card` returns an `ApprovalResult`
  carrying the new run's id, the card's id, the approval audit row's id, and
  the run's bound product, workflow key, subject type, subject ref and
  status. It resolves the approved card's OWN workflow through the playbook
  registry and the approved card's OWN subject from the card's subject
  columns, and never commits — the caller does.
- The four fail-closed refusals, every one raised BEFORE the flush and all
  translated to HTTP by the approve route — `ActionCardNotFound` (404,
  identical for a nonexistent and a cross-tenant card so the route cannot
  become an existence oracle), `ActionCardNotActive` (409),
  `WorkflowNotExecutable` (409, the card's workflow key has no registered
  playbook — ADR-084 decision 3), and `CardSubjectNotApprovable` (409, the
  card carries no subject, or a subject kind this runtime cannot bind a run
  to yet). The zero-products refusal was deleted by #1702 together with the
  highest-revenue derivation it reported: approve no longer asks the shop
  for a product, so "this shop has no products" stopped being a reason it
  can fail.

The run-status vocabulary and the runner's external-wait refusal (#1706,
W9-A/P-SHARED-6). `status.py` is a neutral leaf that imports nothing from
juli_backend, which is what lets the runner package and the events package
both depend on it rather than one depending on the other (#1139):

```python
from juli_backend.services.agent.status import SUSPENDED_STATUSES
from juli_backend.services.agent.runner import ExternalWaitNotPermitted
```

- `SUSPENDED_STATUSES` — the statuses a run is parked in rather than stopped
  at: paused on a person, and since #1706 paused on the world. Named here
  because two packages outside this one need the same answer and were each
  spelling it as a literal exception inside a subtraction over the whole
  enum — one stamps a completion time for every status NOT in the exception
  set, the other closes the SSE stream for every status NOT in it. Both
  derivations are written to absorb a new enum member automatically, so both
  absorbed the new one as terminal, which for a suspended run means a
  completion time it does not have and a stream closed under a run that is
  still going. Which statuses are suspended is a product fact about each
  member, not something the enum's shape can answer, so it is recorded once,
  beside the enum.
- `ExternalWaitNotPermitted` — raised when a run is asked to wait on the world
  under a workflow whose termination policy declares no external-wait timeout.
  That field is None by default and means "this workflow may not wait", never
  "wait forever": a run parked in a state its own policy has no timeout for
  could never be reaped and would hold its subject indefinitely. The refusal
  is what makes the capability declarative — a workflow acquires it by putting
  a number on its own policy and by no other means.

## Dependencies

- stdlib only (`json`, `re`, `pathlib`, `dataclasses`, `functools`, `math`,
  `unicodedata`, `logging`, `inspect`/`ast` in tests only) plus `requests`
  (transport-error detection in `errors.py`) and `juli_backend.integrations.tiktok` /
  `juli_backend.services.execution.types` (existing in-repo modules, not new
  dependencies).
- Reads `packages/contracts/seller-copy-banned-patterns.json` via a
  monorepo-relative path (six parents up from `sanitize/banned_patterns.py`, same
  convention as `juli_backend.core.config.runtime._repo_root`).

## Invariants

- No pattern is added, removed, or altered by this loader — it only compiles what
  the JSON source contains. New patterns must compile under both Python `re` and
  JavaScript `RegExp` — enforced by
  `tests/unit/test_agent_banned_patterns_contract.py`.
- Only the `i` (case-insensitive) JS regex flag is translated; any other flag
  raises `re.error` naming the offending pattern id rather than being silently
  dropped.
- `hidden_text.py`: stripping is scoped to Unicode categories `Cc` (minus
  `\t`/`\n`/`\r`) and `Cf` only — Vietnamese combining diacritics (`Mn`) and
  emoji (`So`/`Sk`, plus the `Mn` variation selector) are never touched, in
  either NFC or NFD form, enforced by `tests/unit/test_agent_sanitize_hidden_text.py`.
  Stripping is scoped to `source: "vendor"` text only — `seller`/`juli`
  envelopes and plain unwrapped strings are left alone. `chokepoints.py`
  calls this **before** its banned-pattern scan, never after — enforced by
  `tests/unit/test_agent_sanitize_chokepoints.py::TestInboundStripsHiddenTextFromVendorTextBeforeScanning`.
- `caps.py`: every cut is deterministic server code (pure slicing — no model
  call, no randomness, no wall-clock branching); the same input always produces
  a byte-identical serialized result, enforced by
  `tests/unit/test_agent_sanitize_caps.py`. A `CappedList`/`CappedText`/
  `CappedImages` cannot be constructed with an inconsistent `truncated`/
  `omitted_count` pair — `__post_init__` raises `ValueError`.
- `errors.py`: raw vendor codes, request ids, and endpoint paths are emitted to
  server-side logs only and never appear in a `TranslatedError`/error envelope
  — enforced by `tests/unit/test_agent_sanitize_errors.py`.
- `chokepoints.py`: both `guard_inbound_tool_result` and
  `guard_outbound_agent_output` fail closed — a failure inside their own
  scanning machinery (e.g. the pattern source fails to load) blocks the
  content exactly as a real hit would, never passing it through — enforced by
  `tests/unit/test_agent_sanitize_chokepoints.py`. Both consume the shared
  #990 pattern source only; no second copy of the banned-pattern list exists
  in `chokepoints.py`.

## Top-level modules

- `abuse_limits.py` (ADR-075 decision 4, #1223) — inbound abuse limits for
  the agent-run routes: approve/run creation (5/hour, burst 2), confirmations
  (30/hour), and SSE (10 concurrent streams), all keyed by shop after
  authentication and config-driven (`AGENT_APPROVE_RATE_LIMIT_*`,
  `AGENT_CONFIRMATION_RATE_LIMIT_*`, `AGENT_SSE_*` env vars, named defaults
  in the module). `AbuseLimitGate` (`try_acquire_approve` /
  `try_acquire_confirmation` / `try_acquire_stream` / `release_stream`) is
  implemented by `RedisAbuseLimitGate` (production — async-native
  fixed-window INCR+EXPIRE over the shared `redis.asyncio` client, fails
  closed on any Redis error), `UnavailableAbuseLimitGate` (bound when
  `REDIS_URL` is unset — also fails closed), and `InMemoryAbuseLimitGate`
  (test double). `get_agent_abuse_limit_gate()` / `set_agent_abuse_limit_gate()`
  / `bind_agent_abuse_limit_gate()` follow the exact binding idiom
  `services.action_cards.refresh_cooldown` already established. Cancel
  (`api/routes/agent_runs.py::cancel_run`) never imports or calls this
  module at all — the safety-valve exemption is structural, not a
  fail-open branch inside it. Imported from `api` as `from
  juli_backend.services.agent import abuse_limits` (never `from
  juli_backend.services.agent.abuse_limits import ...`, which the
  `.importlinter.toml` depth-2 cap forbids), the same idiom this
  package's `approval.py` already uses.
