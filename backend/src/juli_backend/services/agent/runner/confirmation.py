"""Decision-request construction at a CONFIRM pause (ADR-075 decision 2,
issue #1221 / AGT-W5A).

`WorkflowRunner._pause_pending_confirmation` (`core.py`) calls
`build_confirmation_options` once, at the pause site, to build the
`options[]` list `workflow.approval_required` carries *and* the same
list `ConversationStore.persist`'s `pending_confirmation=` kwarg writes to
`run_confirmations.options` -- one construction, two consumers, so the
event a seller sees and the row #1224 authorizes against can never
independently drift (`ConfirmationOptionPayload`, `events/payloads.py`, is
the single shape both write).

**`params_sha` is a NEW, independent fingerprint -- not
`runner/concurrency.py::_hash_field`.** `_hash_field` is a narrower
mechanism: it hashes one *individual mutable product field*
(title/description/price/images) for the stale-read compare-before-write
guard (ADR-073 decision 4). `compute_params_sha` here hashes the *whole
tool-params dict* a CONFIRM tool call proposed, as the seller-consent
fingerprint #1224 re-derives from reconstructed run state before allowing
a write to proceed. Two different scopes, two different purposes -- this
module does not rename or reuse `_hash_field`, it defines its own
canonicalization from scratch.

**Canonicalization contract (must stay reproducible byte-for-byte by any
future re-deriver, including #1224):**

1. Recurse into dicts and lists; every other value (str/int/float/bool/
   None) passes through unchanged.
2. Every string, at any depth (including dict keys, though keys here are
   always plain ASCII tool-param names), is Unicode NFC-normalized before
   serialization -- two byte-different-but-canonically-equal strings (a
   precomposed Vietnamese diacritic vs. the same character spelled as
   base + combining mark, both legal UTF-8 a model could emit) must hash
   identically.
3. Serialized with `json.dumps(..., sort_keys=True, ensure_ascii=True,
   separators=(",", ":"))` -- `sort_keys=True` makes the result
   independent of the dict's construction/insertion order (proven with a
   shuffled-key input, not assumed); `ensure_ascii=True` makes the byte
   output independent of the platform's default string encoding;
   `separators=(",", ":")` removes incidental whitespace. List *order* is
   preserved (never sorted) -- order is semantically meaningful for a
   list of SKU price changes, unlike dict keys.
4. Numbers are rendered via `json.dumps`'s own standard, deterministic
   int/float formatting -- this module does not additionally normalize
   numeric *type* (e.g. `179000` int vs `"179000"` str vs `179000.0`
   float hash differently, on purpose: reconciling that is the tool
   input model's job via Pydantic validation, not this hashing layer's).
5. The canonical string is UTF-8 encoded, then SHA-256 hex-digested.

`sort_keys=True` sorts by Python string comparison, not by `hash()`, so
this canonicalization is inherently independent of `PYTHONHASHSEED` --
`test_agent_runner_confirmation.py` proves that directly by spawning a
fresh subprocess (no seed pinned) rather than assuming it.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

from juli_backend.services.agent.events.payloads import ConfirmationOptionPayload

#: Binary confirm's single option always carries this id (ADR-075 decision
#: 2: "binary confirm is the N=1 case"). Generating genuinely distinct
#: multi-option proposals (option_id "2", "3", ...) is a prompt concern,
#: explicitly out of this slice -- this constant is the only option_id
#: this module ever mints.
_SINGLE_OPTION_ID = "1"


def _normalize_for_hash(value: Any) -> Any:
    """Recursively NFC-normalize every string in `value`; every other type
    passes through unchanged. See module docstring rule 2."""
    if isinstance(value, dict):
        return {key: _normalize_for_hash(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_normalize_for_hash(item) for item in value]
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    return value


def canonicalize_params(params: dict[str, Any]) -> str:
    """The canonical JSON string `compute_params_sha` hashes. Exposed
    separately so a test (or a future re-deriver) can assert the
    intermediate string directly, not only the digest. See module
    docstring for the full canonicalization contract."""
    normalized = _normalize_for_hash(params)
    return json.dumps(normalized, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def compute_params_sha(params: dict[str, Any]) -> str:
    """SHA-256 hex digest of `params`'s canonical JSON form (module
    docstring's canonicalization contract) -- the consent fingerprint
    #1224 re-derives from reconstructed run state and compares before
    executing an approved write."""
    canonical = canonicalize_params(params)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_confirmation_options(
    *, rationale: str, arguments: dict[str, Any]
) -> list[ConfirmationOptionPayload]:
    """Binary confirm is the N=1 case (ADR-075 decision 2): exactly one
    `ConfirmationOptionPayload`, wrapping the CONFIRM tool call's raw
    `arguments` verbatim -- never re-derived through the tool's
    `input_model` (a re-typed/re-formatted value would no longer be "what
    was shown"). `params_sha` is computed over that exact same verbatim
    dict, so the option's own fingerprint always matches its own
    `proposed_change` by construction.

    `rationale` is caller-supplied (`_pause_pending_confirmation` passes
    the tool's own `ToolSpec.description`) rather than generated here --
    generating a genuinely reasoned, signal-grounded rationale per option
    is P12's prompt-content concern (ADR-075 consequences), not this
    slice's; this function only ever carries whatever string it is given.
    There is no `tool_name` parameter here: the tool's name already lives
    once on the enclosing `WorkflowApprovalRequiredPayload.tool_name`
    (`_pause_pending_confirmation`'s other sibling field on the same
    event) and is not part of the per-option shape.
    """
    proposed_change = dict(arguments)
    return [
        ConfirmationOptionPayload(
            option_id=_SINGLE_OPTION_ID,
            proposed_change=proposed_change,
            rationale=rationale,
            params_sha=compute_params_sha(proposed_change),
        )
    ]
