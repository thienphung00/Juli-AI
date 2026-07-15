# Components / toasts.md

> Elevation: `--shadow-lg`. Trigger reference: approval success flow in
> `Flows/decisions/README.md` stage 4 (Decide).

## Behavior

- Appears from the top or bottom edge (mobile: bottom, above the nav bar; desktop:
  top-right), auto-dismisses after **4 seconds** for success, **6 seconds** for
  actionable/error toasts (longer read time for more consequential copy).
- Never blocks interaction with the rest of the screen — no backdrop, no focus
  trap.

## Stacking

- Maximum 2 toasts visible at once; a 3rd queues and appears after the oldest
  dismisses. Never stack more than 2 — it becomes noise, not feedback.

## Content

- Short Vietnamese sentence stating what happened, e.g. "Đã phê duyệt đề xuất."
  Error toasts state the problem and recovery.
- Approval feedback confirms that the workflow is ready or started and links to
  Decisions → Đang thực hiện; it never claims Juli acted autonomously.
- Optional inline action (e.g. "Hoàn tác" / Undo) — only when the action is
  genuinely reversible within the toast's visible window.

## Accessibility

- `aria-live="polite"` region so screen readers announce the toast without
  interrupting the current task; `aria-live="assertive"` only for error toasts
  that require immediate attention.
- Auto-dismiss timing pauses on hover/focus so a screen-reader or mouse user has
  time to read before it disappears.

## Anti-patterns

- Toasts used for validation errors that need to stay visible until fixed — those
  belong inline on the form (`Components/forms.md`), not in a toast that
  disappears.
- More than one toast conveying the same event.
