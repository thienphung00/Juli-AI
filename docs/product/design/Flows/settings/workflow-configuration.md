# Settings flow — workflow templates and thresholds

> Screen: [`../../Screens/settings.md`](../../Screens/settings.md). Route:
> `/settings` with template detail at `/settings/workflows/[workflowKey]`.

## Flow

1. Open Settings and choose **Mẫu quy trình / Workflow templates** or
   **Ngưỡng / Thresholds**.
2. Select a stable `workflow_key`; display its execution capability before editing.
3. Edit documented defaults, branch preferences, notification cadence, or supported
   trigger thresholds.
4. Validate type, range, required fields, and shop scope. A missing authoritative
   threshold/trigger contract is shown as **Unresolved** and is not editable.
5. Preview which future recommendations the setting affects. Never promise execution
   where the tool or branch is unsupported.
6. Save explicitly. Preserve changes on a transient failure and offer retry.
7. Return to the list with the updated value and audit timestamp.

## Invariants

- Human approval cannot be disabled.
- Settings changes future recommendation/input defaults; it never approves an
  existing recommendation or mutates an active execution.
- FBT fields remain an unfilled, read-only scaffold until authoritative contracts
  and executors exist.
- Threshold changes do not invent recommendation triggers. Where the trigger is
  unresolved, the UI says so.
- Deep links use `apps/dashboard` routes above; no legacy `web/src` path is normative.
