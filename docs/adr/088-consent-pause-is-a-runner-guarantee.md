# ADR-088: Reaching the seller-consent pause is a runner guarantee, not a prompt behaviour

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** Architect with user (owner approved 2026-08-26)

**Completes:** [ADR-072](072-agent-prompt-architecture.md) decision 5, whose stated principle
— "the prompt makes violations rare, the guards make them impossible" — is not honoured on the
one path that matters most. **Amends:** [ADR-073](073-agent-execution-loop-and-write-path-hardening.md)
decision 2, which makes a `final_response` carrying zero confirmed writes a legitimate
terminal outcome. **Scope:** gate [#1226](https://github.com/thienphung00/Juli-AI/issues/1226)
observation 1; the defect chain #1356 → #1359 → #1367.

## Context

### The seller-consent path has never executed against reality

Gate #1226 observation 1 requires one thing: an agent run that proposes a listing change and
**pauses for the seller's decision**. Six of its seven steps are proven on the deployed host.
The seventh has never happened. Three fixes, three walks, three months of the same gate open.

Each fix was correct about the defect it named, and each was defeated by the next one:

| Prompt | Worked example showed | What the model emitted | Filed as |
|---|---|---|---|
| v1 | a prose description of the call | a prose promise — *"mình sẽ chờ bạn phê duyệt"* | #1356 |
| v2 | a concrete call inside a ` ```python ` fence | that fence, copied into the seller message | #1367 |
| v3 | seller prose only, no call | a prose promise again, with a numbered plan | *this ADR* |

Run `d9dac43d` (2026-08-26, v3, on the correct `optimize_product_2` card) closed with:

> Mình sẽ chuẩn bị bản cập nhật **title/description** để bạn phê duyệt. Bạn xác nhận giúp
> mình để mình đăng lên listing nhé.

*"I'll prepare the title/description update for you to approve. Please confirm so I can post
it."* That is v1's failure mode, restored by fixing v2's.

Under v2 the model had already produced correct, concrete `title` and `description` values —
it simply put them in a code fence instead of a tool call. The capability is present. The
channel is not being used.

### Why prompt iteration oscillates rather than converges

A worked example teaches the **surface form** a model reproduces, and that form outranks
instruction prose in the same section when the two disagree. v2's fence sat sixteen lines
below "Never ask the seller to choose in text"; the fence won. v3 removed the fence and with
it the only demonstration that a run *terminates by acting*; the register won instead.

Every exemplar form has a failure mode, so each revision trades one for another. There is no
form that is safe, because the thing being taught — "emit through a channel the reader cannot
see rendered" — has no textual rendering.

### The prompt is load-bearing, contrary to ADR-072 d.5

ADR-072 decision 5 is explicit: *"Safety sections — behavioral, never load-bearing. Every
prompt rule is also enforced server-side (ADR-070 chokepoints, allowlist validation, CONFIRM
pauses); the prompt makes violations rare, the guards make them impossible."*

For reaching the pause, no such guard exists. Verified in code:

| Fact | Location |
|---|---|
| A text block terminates the run unconditionally | `runner/core.py:1407` — `stop_reason = StopReason.FINAL_RESPONSE` |
| `required_steps_completed` is computed and persisted, but gates nothing | `core.py:170-180`; run `d9dac43d` recorded `false` and still `completed` |
| `tool_choice` is never sent to the provider | absent throughout `llm/service.py`, `llm/openai_adapter.py` |
| Iteration budget was not the constraint | `max_iterations=6`; the run used **2** |
| Text and a tool call can coexist in one turn | `llm/openai_adapter.py:289-294` appends text blocks, then tool-call blocks |

That last row matters: narration does not compete with the call. The model can do both in one
turn. It is simply never required to do either.

### `final_response` conflates three different outcomes

Today these are indistinguishable in the event stream and in `workflow_runs.stop_reason`:

1. The agent did the job and the seller decided.
2. The agent looked and there was genuinely nothing worth proposing — a legitimate outcome
   ADR-073 d.2 deliberately protects.
3. The agent had a concrete proposal and narrated it instead of calling.

Only (3) is a defect, and only `required_steps_completed` distinguishes it — a column nothing
reads or alerts on. This is why the defect survived three walks: every failed run looked
exactly like an honest negative.

### The test that should have caught this exists, and has never run

`tests/integration/test_agent_live_smoke_sandbox_write.py` drives a **real** `WorkflowRunner`
through a **real** model and asserts precisely the failing invariant:

```python
assert result_1.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
assert result_1.status == WorkflowRunStatus.WAITING_APPROVAL
assert pending is not None, "a paused_for_confirmation run must persist pending_confirmation"
```

It would have caught v1, v2 and v3. Four independent layers stopped it:

1. **Its CI job is `merge_group`-only** (`pr.yml`, `test-live-sandbox`:
   `if: github.event_name == 'merge_group'`) and this repository has **zero** `merge_group`
   runs — pull requests squash-merge directly. The job has never fired.
2. **Four self-skip preconditions**: `OPENAI_API_KEY`, TikTok app credentials, a
   `sandbox_write` credential row, and a seeded `products` row for the sandbox shop. The
   module's own docstring notes that nothing auto-populates the last one — "an operator must
   seed this row by hand".
3. **A skip counts as a pass** — `pr.yml:1158`:
   `[[ "$result" == "success" || "$result" == "skipped" ]] || fail`.
4. **Unit tests structurally cannot see it.** Every runner test injects `llm/fake.py`. The
   model is the component that misbehaves and it is exactly the component being stubbed. A
   fake that emits a tool call proves the runner *handles* a tool call; it can never prove the
   real model *produces* one.

So the only working detector was a human running seven curl commands against production,
roughly twenty minutes per iteration, three times.

## Decision

**Reaching the consent pause becomes a property the runner enforces. The prompt is demoted to
an optimisation.**

### Decision 1 — Termination is a typed act; prose can never end an unfinished run

Add a side-effect-free terminal tool, `conclude_without_changes(reason: str)`, registered
`AUTO` and available in every playbook whose `TerminationPolicy` declares `required_steps`.

In the runner: a text-only turn is **not terminal** while `required_steps` are incomplete and
iteration budget remains. Instead the runner re-invokes once with `tool_choice="required"`.

The new tool is what makes forcing safe. Without a legitimate "nothing to do" call available,
`tool_choice="required"` would coerce a bogus write on a run that genuinely has nothing to
propose. With it, the model always has an honest option, so "narrate and quit" becomes
structurally impossible rather than merely discouraged.

Bounded to **one** forced retry per run — enough to convert the observed failure, not enough
to loop or to burn the iteration budget.

### Decision 2 — Distinct stop reasons, so this is visible the next time

Split the conflated outcome:

- `concluded_without_changes` — the model explicitly called the terminal tool. The honest
  negative ADR-073 d.2 protects, now recorded through a channel that can be counted.
- `required_steps_unfulfilled` — the forced retry was spent and the model still emitted no
  call. Distinct from `final_response`, and the signal to alert on.

This preserves ADR-073 d.2's intent — a run with nothing to propose is still not a synthetic
failure — while ending its side effect of making a real defect indistinguishable from a
healthy outcome.

Requires a migration widening the `workflow_runs.stop_reason` CHECK constraint (precedent:
`042_stop_reason_prompt_pin` from #1359) and parity in
`packages/contracts/src/agent-events.ts` (`STOP_REASONS`,
`WORKFLOW_FAILED_STOP_REASON_TO_STATUS`).

### Decision 3 — Prompt v4 resolves a genuine internal conflict, as optimisation

Section 7 instructs: *"reasoning first, then expected impact, then concrete next steps."* Run
`d9dac43d` complied exactly, emitting a **Next-steps** heading listing changes it intended to
make. That register is inherited from the scoring copy layer, where a card's "next steps" are
advice for a human to act on later. In an agent run the agent *is* the actor, so the register
instructs narration while the section above instructs action.

v4 changes the terminal-turn register from *what I will do* to *what I am proposing for your
approval now*, and shows the seller message as the accompaniment to a call rather than a
substitute for one.

Under decisions 1 and 2 the prompt is no longer load-bearing, so v4 cannot regress the gate.
It reduces how often the retry fires; it is not what makes the pause reachable.

### Decision 4 — The invariant becomes cheap to test, and the live lane becomes real

**Per-PR, deterministic, free.** Once the runner owns the invariant, the fake LLM is
sufficient to test it — for the first time:

```
fake emits text-only, required_steps incomplete, budget remains
  -> assert the run does NOT terminate
  -> assert the re-invocation carries tool_choice="required"
fake then emits conclude_without_changes
  -> assert stop_reason == concluded_without_changes
fake never calls anything
  -> assert stop_reason == required_steps_unfulfilled, never final_response
```

No API key, no network, no sandbox credential. This is the strongest argument for moving
enforcement out of the prompt: it converts an expensive, manual, owner-blocking check into a
cheap automated one.

**Backstop, for what the fake cannot see.** The live smoke stays the only thing that can catch
"the real model changed its behaviour". To make it real:

- Seed the sandbox `products` row. This was the one precondition nothing auto-populates; it is
  now satisfiable, since gate #1226 established a working sandbox product.
- Move `test-live-sandbox` off `merge_group` — which never fires here — to a nightly schedule
  plus `workflow_dispatch`.
- Add `JULI_REQUIRE_LIVE_SMOKE=1`, honoured in that lane, converting every precondition
  `pytest.skip` into a failure. Silent skips remain the local-development default.
- Extend the assertion to `update_product_listing`; today it covers only the
  `update_product_price` pause.

A test that cannot run is worse than no test, because it is counted as coverage. Both halves
of this decision exist to stop that recurring.

## Consequences

**Positive.** The consent pause becomes a server-side guarantee, consistent with ADR-072 d.5.
The three outcomes currently collapsed into `final_response` become separately countable. The
invariant gains per-PR test coverage that costs nothing. Future prompt edits — including
inevitable future exemplar mistakes — can no longer reopen this gate.

**Costs.** One new tool, a bounded retry in `runner/core.py`, `tool_choice` plumbed through
`llm/service.py` and `llm/openai_adapter.py`, one migration, TS contract parity, and a CI
workflow change. Comparable in shape to #1359, which touched the same file set.

**Risks.** A forced tool call is a real behavioural change to the provider request; the retry
must be strictly bounded and must never fire on a run whose required steps are already
complete. `conclude_without_changes` must be genuinely side-effect-free, or it becomes a
write path that bypasses CONFIRM.

**Deliberately unresolved.** Whether `required_steps_unfulfilled` should alert or page is left
to the observability lane. This ADR only guarantees the outcome is *distinguishable*.

## Alternatives rejected

**A fourth prompt revision alone.** This is what the last three attempts were. Two failure
modes, no convergence, and no reason to expect the fourth form to be the safe one. It also
leaves the invariant testable only against a live model.

**Nudge with a corrective message, without `tool_choice` or a terminal tool.** Roughly one
file, no migration. Rejected: it leaves the model free to narrate a second time, so it is a
fourth attempt at the same class of fix with extra steps, and it does not make the invariant
unit-testable.

**Enforce by rejecting `final_response` outright when required steps are incomplete.**
Rejected: it destroys the legitimate outcome ADR-073 d.2 protects. A run with genuinely
nothing to propose must be able to end honestly; the terminal tool is what preserves that
while closing the gap.

**Post-hoc detection — alert on `required_steps_completed = false`.** Rejected as the primary
fix: it observes the defect rather than preventing it, and the seller still receives a message
promising an action that never happens. Retained as a secondary signal via decision 2.
