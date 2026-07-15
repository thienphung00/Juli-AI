# Components / popovers.md

> Tokens: `colors_and_type.css`. This contract covers lightweight,
> non-destructive contextual explanations. Dialog behavior belongs in
> `Components/dialogs.md`.

## Unavailable KPI information popover

Use this pattern to explain why a visible Main KPI cannot yet be selected.

### Trigger

- A separate `button` with a minimum 44×44px target.
- Accessible name: `Vì sao [KPI] chưa khả dụng?`.
- Exposes `aria-expanded` and `aria-controls`.
- Sits beside the `Chưa khả dụng` label; never nests inside a disabled or
  selectable KPI button.

### Content

- Non-modal `role="dialog"` with `aria-labelledby` pointing to its heading.
- Heading: `[KPI] chưa khả dụng`.
- Body names the missing `Nguồn dữ liệu` and the concrete activation
  requirement. It never promises a date that is not known.
- Optional close button has `aria-label="Đóng giải thích"`.
- Uses `--card`, `--foreground`, `--border`, and `--shadow-md`; no invented
  overlay colors.

### Focus and dismissal

1. Opening moves focus to the popover heading or close button.
2. Tab order stays within the small content while open when the implementation
   includes multiple focusable controls.
3. Escape and outside click close it.
4. Closing returns focus to the trigger.
5. Opening another unavailable-KPI popover closes the current one.

The popover is anchored when space allows and may become a bottom sheet on a
narrow native viewport. Its information, labels, and dismissal behavior remain
the same.

## Anti-patterns

- Tooltip-only explanations that disappear before they can be read.
- Hover-only or icon-only triggers without an accessible name.
- Nesting the trigger inside a disabled selector card.
- Generic copy such as `Không có dữ liệu` without the missing source and
  activation requirement.
- Trapping the entire page in a modal flow for a short explanation.
