# In Progress — shared list/detail shell

> Routes: `/decisions?tab=in-progress` and
> `/decisions/in-progress/[executionId]`. Workflow-specific state definitions live in
> `../recommendations/1-workflow.md` through `9-workflow.md`.

## Preserved lifecycle model

The existing lifecycle remains unchanged:

1. `needs_input` / **Cần thêm thông tin** — approval exists but a required seller
   value or external prerequisite is missing.
2. `executing` / **Đang thực hiện** — an action is queued/running or the workflow is
   waiting for an authoritative webhook/external event.
3. `completed` / **Hoàn tất** — terminal success or terminal handled outcome.

Failures do not create a fourth lifecycle status. They are recoverable or terminal
substates inside the current action while the execution retains its persisted status.

## List shell

Each item shows workflow name, lifecycle badge, current numbered state, start/update
time in ICT, capability status, and the next seller action when one exists. Filters may
select lifecycle values but may not rename or add statuses.

## Detail shell

One stable detail route renders:

- identity (`executionId`, `workflow_key`, tool name, branch);
- approved input snapshot and idempotency state;
- vertical numbered timeline from the matching workflow spec;
- active action/wait/outcome state with plain-language explanation;
- retries and errors without secrets or raw sensitive payloads;
- outcome summary and link to the relevant Analytics metric when real.

## Shared state behavior

- **Action:** show pending → running → succeeded/failed; do not claim success before
  the worker outcome.
- **Wait:** show what external event is expected, last checked/received time, and a
  safe refresh action. No fabricated ETA.
- **Outcome:** show result, partial-result warning if applicable, and next step.
- **Transient error:** preserve inputs and allow retry with the same idempotency key.
- **Validation/business error:** identify the field/rule and route back to editable
  inputs where safe.
- **Unknown error:** provide retry/support path; never expose credentials or payloads.

FBT scaffolds are not rendered as executable timelines until their contracts and
executors are authoritative.
