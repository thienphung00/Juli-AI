# Components / forms.md

> Tokens: `colors_and_type.css`. Code: `.field-input` in
> `apps/dashboard/src/app/globals.css`.
> Reference: `LoginForm.tsx`, `Flows/home/login.md`.

## Text / email / password inputs

- `.field-input` — 44px minimum height, `--radius` corners, `--border` outline,
  `--pink-main` focus-visible ring.
- Label always present via `<label htmlFor>` — never a placeholder-only field.
- Password fields include a show/hide toggle (icon button, `aria-label` "Hiện mật
  khẩu" / "Ẩn mật khẩu").

## OTP segmented input

- 6 individual boxes, 44×44px minimum each, auto-advance focus on entry,
  auto-submit on the 6th digit if valid.
- Native iOS supports SMS autofill as an input affordance, not a divergent IA.
- Error state: all 6 boxes take the error border color simultaneously; error copy
  below states problem + recovery: "Mã OTP không đúng. Vui lòng
  thử lại."

## Workflow input forms

- Open after **Phê duyệt** from a recommendation card with supported values
  prefilled and editable.
- Group fields by execution step; show the source/default and validation before
  the seller continues.
- Preserve values across the shared execution-detail states and expose recovery
  actions without silently restarting the workflow.

## Settings forms

- Workflow templates and trigger thresholds live under `/settings`, not a
  Decisions sub-tab.
- Threshold changes show units, current value, allowed range, and the workflows
  affected before save.

## Validation & error messages

- Inline, below the field, linked via `aria-describedby`.
- Validate on blur for format errors (email shape, password length); validate on
  submit for server-side errors (wrong OTP, account not found).
- Error copy always states problem + recovery — never a bare "Invalid input."

## Rules

- Every form has exactly one primary submit action (`Components/buttons.md`
  Primary), disabled until the form is valid, showing `.spinner` while submitting.
- Required fields are marked; do not rely on color alone to indicate a required
  field — use explicit text or an asterisk with an accessible label.
- Autofocus the first field on a fresh form screen (login, OTP) — never on a form
  reached mid-flow where autofocus would steal scroll position.

## Anti-patterns

- Placeholder text used as a label substitute.
- Validation errors that disappear before the seller has read them (no premature
  auto-dismiss on form errors — only toasts auto-dismiss, per
  `Components/toasts.md`).
