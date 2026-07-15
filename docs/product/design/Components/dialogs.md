# Components / dialogs.md

> Historical references: `TaskDismissModal.tsx`, `TaskExecutorModals.tsx`,
> `EvidenceDrawer.tsx`. These files are provenance only; current behavior follows
> the recommendation/execution model. Tokens: `--shadow-md`.

## Modals

- Centered overlay, `--shadow-md`, `--radius` corners, backdrop dims the page to
  ~40% black.
- `aria-modal="true"`, labelled title (`aria-labelledby`), focus trap on open,
  focus returns to the triggering element on close.
- Close via explicit ✕ button, backdrop tap, or Escape key — all three always
  available together, never just one.

## Confirmations

- Used before an irreversible action beyond the normal approve/reject flow (e.g.
  a workflow-triggered execution step that can't be rolled back).
- States the consequence in one sentence, then a primary/secondary button pair —
  never a single "OK" dismiss for a decision with real consequence.

## Sheets

- Bottom sheet on mobile-web/native for secondary detail that doesn't warrant a
  full route change (e.g. `EvidenceDrawer` masked drill-down).
- Drag handle affordance, swipe-down or backdrop tap to dismiss.

## Alert dialogs

- Reserved for errors that block progress (e.g. session expired mid-approval).
- Always paired with the specific recovery action, never a bare "OK."

## Backdrop behavior

- Backdrop tap dismisses non-destructive dialogs immediately.
- Backdrop tap on a dialog mid-destructive-action (e.g. mid task-dismiss with a
  reason already typed) prompts a lightweight "discard?" confirmation instead of
  silently losing input.

## Rules

- Only one modal/sheet open at a time — never stack a confirmation on top of a
  modal on top of a sheet.
- Dialog titles are always a real Vietnamese sentence or noun phrase, never a
  generic "Confirm" / "Alert."
- **Mở rộng** reasoning is inline on the recommendation card, not a modal.
- Workflow templates and thresholds are edited in Settings, not a Decisions dialog.

## Anti-patterns

- Modals that trap focus without a visible close affordance.
- Using a modal for content that should be its own route (e.g. the full Decision
  detail flow — that's a route, not a modal, per `Screens/decisions.md`).
