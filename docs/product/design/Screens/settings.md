# Settings — Cài đặt

> Dashboard route: `/settings`. Flow:
> [`../Flows/settings/workflow-configuration.md`](../Flows/settings/workflow-configuration.md).
> Settings is one of the four primary destinations.

Settings owns workflow templates and thresholds. It does not contain recommendations,
execution status, or KPI reporting.

## Sections

1. **Mẫu quy trình / Workflow templates** — one row per workflow key, capability
   badge, enabled state, and link to editable defaults.
2. **Ngưỡng / Thresholds** — rule thresholds used to surface recommendations.
3. **Notifications** — reminder cadence only; it cannot remove human approval.

## Template detail

Show display name, `workflow_key`, capability status, default inputs, branch defaults,
and unresolved fields. Unsupported FBT settings are read-only and labelled unresolved
or deferred. Never imply that enabling a template creates a missing trigger, contract,
or executor.

## States

1. **List loaded** — templates grouped by product domain.
2. **Template editing** — current defaults and threshold values with validation.
3. **Unsaved changes** — explicit Save/Discard controls and navigation warning.
4. **Saving** — controls disabled; existing values remain visible.
5. **Saved** — confirmation names the updated template.
6. **Validation error** — identify the field and allowed range.
7. **Capability unavailable** — read-only explanation and no fake activation control.
8. **Load/save error** — preserve edits and offer retry.

All threshold and template changes are shop-scoped and must use the same Vietnamese
terminology on web, mobile web, and native clients.
