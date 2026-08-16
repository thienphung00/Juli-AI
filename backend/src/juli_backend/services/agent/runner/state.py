"""`RunState` — the explicit run-state object `WorkflowRunner` will resume
from (ADR-073 decision 1, issue #1118 / AGT-W3A).

This module ships state only: no `WorkflowRunner`, no block dispatch, no
termination-policy evaluation. Those land in a later slice (#1119) that
constructs a runner around this object and the `ConversationStore` protocol
(`conversation_store.py`, alongside this module).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The message shape `LLMService.complete()` consumes
# (`services/agent/llm/service.py`'s `Message = Mapping[str, Any]`).
# `RunState` stores the durable, JSON-safe form of that window: a plain
# dict per message, since the whole window round-trips through the
# `workflow_runs.state` JSONB blob.
ConversationMessage = dict[str, Any]

# The durable, versioned field names a `RunState` blob is currently
# required to carry. Anything else found on `from_dict` is forward-compat
# "unknown" data (see `from_dict`/`to_dict` below), not a defect.
_KNOWN_FIELDS = (
    "conversation_window",
    "iteration_count",
    "extensions_granted",
    "next_sequence",
    "pending_confirmation",
    "basis_snapshots",
    "running_seconds_elapsed",
)


class RunStateFieldMissingError(ValueError):
    """Raised by `RunState.from_dict` when a blob is missing one of the
    currently-required fields.

    A corrupted or truncated blob must never be mistaken for a fresh run by
    silently defaulting the missing field — ADR-073 decision 1's state
    object is the thing `WorkflowRunner` resumes mid-run from, so a quiet
    default here would resume with wrong data instead of failing loudly.
    """


@dataclass
class RunState:
    """Everything `WorkflowRunner` needs to resume a run mid-flight
    (ADR-073 decision 1).

    Not itself persisted directly — `ConversationStore.load`/`persist`
    (`conversation_store.py`) serialize/deserialize it to and from the
    `workflow_runs.state` JSONB blob (`models/models.py`, shipped by
    #1117).

    Fields:
    - `conversation_window`: the message history the LLM sees, in the
      shape `LLMService.complete(messages=...)` accepts.
    - `iteration_count`: number of `LLMService.complete()` calls made so
      far this run (ADR-073 decision 2's `max_iterations` is compared
      against this).
    - `extensions_granted`: number of soft-cap extensions the runner has
      auto-granted (ADR-073 decision 2, `max_extensions`).
    - `next_sequence`: the runner-owned counter backing ADR-074's event
      sequence numbers (interface I5: "runner owns sequence numbers").
      Only `allocate_sequence` below reads and advances it — no other
      code, in this slice or the runner that consumes it, should mutate
      this field directly.
    - `pending_confirmation`: the CONFIRM-policy tool call awaiting seller
      approval, or `None` when nothing is paused.
    - `basis_snapshots`: P1-6's per-field basis hashes, held here
      *structurally separate* from `conversation_window` (ADR-073 decision
      4) — a server-held hash the LLM must never see. See
      `conversation_window_for_llm` for the enforcement.
    - `running_seconds_elapsed`: the wall-clock accumulator P1-4 measures
      over *running* time only — the clock pauses while
      `waiting_approval` (ADR-073 decision 2). A float so the runner can
      accumulate sub-second deltas per iteration; `workflow_runs`'s own
      `running_seconds_elapsed` integer column (#1117) is a separate,
      denormalized mirror the runner writes from this value — not this
      field itself.
    """

    conversation_window: list[ConversationMessage] = field(default_factory=list)
    iteration_count: int = 0
    extensions_granted: int = 0
    next_sequence: int = 0
    pending_confirmation: dict[str, Any] | None = None
    basis_snapshots: dict[str, str] = field(default_factory=dict)
    running_seconds_elapsed: float = 0.0

    # Fields present on a deserialized blob that this version of RunState
    # does not recognize (ADR-073 decision 5, the P-CS forward-compat
    # seam). Preserved verbatim here and re-emitted by `to_dict` so a
    # newer writer's fields survive being read and rewritten by this
    # version, rather than being silently dropped.
    unknown_fields: dict[str, Any] = field(default_factory=dict, repr=False)

    def allocate_sequence(self) -> int:
        """Mint the next event sequence number (ADR-074 interface I5:
        "runner owns sequence numbers").

        `RunState` is the *only* place this counter is read and advanced —
        callers never do ``state.next_sequence += 1`` themselves, so there
        is no gap or reuse logic hidden anywhere outside this object.
        Returns the value just minted and advances the counter for next
        time, so two calls in a row always yield two increasing integers
        with no reuse.
        """
        value = self.next_sequence
        self.next_sequence += 1
        return value

    def conversation_window_for_llm(self) -> list[ConversationMessage]:
        """The exact value an `LLMService.complete(messages=...)` call
        should receive: the conversation window and nothing else.

        `basis_snapshots` (and every other `RunState` field) is
        structurally unreachable from this method's return value — that is
        how ADR-073 decision 4's "invisible to the LLM" rule is enforced
        at the data-shape level in this slice; P1-6 enforces the same rule
        again at the write-path level.
        """
        return list(self.conversation_window)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the JSON-safe blob shape written to
        `workflow_runs.state`.

        Unknown fields captured by a prior `from_dict` call are re-emitted
        at the top level of the blob, so a future version's data survives
        being read and rewritten by this one (ADR-073 decision 5).
        """
        blob: dict[str, Any] = {
            "conversation_window": list(self.conversation_window),
            "iteration_count": self.iteration_count,
            "extensions_granted": self.extensions_granted,
            "next_sequence": self.next_sequence,
            "pending_confirmation": self.pending_confirmation,
            "basis_snapshots": dict(self.basis_snapshots),
            "running_seconds_elapsed": self.running_seconds_elapsed,
        }
        blob.update(self.unknown_fields)
        return blob

    @classmethod
    def from_dict(cls, blob: dict[str, Any]) -> RunState:
        """Deserialize a `workflow_runs.state` blob into a `RunState`.

        Raises `RunStateFieldMissingError` if any currently-required field
        (`_KNOWN_FIELDS`) is absent — a corrupted or truncated blob must
        fail loudly, never be silently treated as a fresh run.

        Any key not in `_KNOWN_FIELDS` is preserved verbatim in
        `unknown_fields` rather than dropped (ADR-073 decision 5,
        "preserve and round-trip"): a later P-CS implementation can add
        fields to the blob without this version's read-modify-write cycle
        destroying them.
        """
        missing = [name for name in _KNOWN_FIELDS if name not in blob]
        if missing:
            raise RunStateFieldMissingError(
                f"RunState blob missing required field(s): {', '.join(missing)}"
            )
        unknown = {key: value for key, value in blob.items() if key not in _KNOWN_FIELDS}
        return cls(
            conversation_window=list(blob["conversation_window"]),
            iteration_count=blob["iteration_count"],
            extensions_granted=blob["extensions_granted"],
            next_sequence=blob["next_sequence"],
            pending_confirmation=blob["pending_confirmation"],
            basis_snapshots=dict(blob["basis_snapshots"]),
            running_seconds_elapsed=blob["running_seconds_elapsed"],
            unknown_fields=unknown,
        )
