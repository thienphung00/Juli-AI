# Components / buttons.md

> Tokens: `colors_and_type.css`. Product implementation:
> `apps/dashboard/src/app/globals.css`.

## Variants

| Variant | Fill | Use |
|---|---|---|
| Primary (gradient) | `--brand-gradient` (135deg `#F86BA5` → `#FAA5C4`) | Approve, submit, primary CTA — one per screen/section |
| Secondary (outline) | Transparent fill, `--border` outline, `--foreground` text | Từ chối, cancel, back |
| Ghost | No fill, no border, `--muted-foreground` text | Mở rộng reasoning and other tertiary actions |

## Sizes

| Size | Height | Text | Use |
|---|---|---|---|
| Large | 48px | `text-base font-semibold` | Full-width CTAs (login submit, approve) |
| Default | 44px | `text-sm font-semibold` | Standard in-card actions |
| Small | 36px | `text-xs font-semibold` | Inline actions inside dense rows (never below 44px hit *target* — pad the tap area even if the visual height is 36px) |

## States

The interactive-state contract applies: default, hover,
active/pressed (`scale(0.98)` + darker fill), focus-visible (3px ring + offset),
disabled (muted fill, `cursor: not-allowed`), loading (inline `.spinner`, label
stays visible or is replaced per context — never a blank button).

## Rules

- Exactly one primary button visible at a time in a given card/section — never two
  gradient buttons competing.
- Recommendation cards always expose **Phê duyệt**, **Từ chối**, and **Mở rộng**.
  Phê duyệt opens prefilled/editable workflow inputs before execution; it is never
  presented as opaque autonomous action.
- Icon-only buttons require `aria-label`.
- Loading state disables the button and shows `.spinner` inline — never a separate
  full-screen spinner for a button-triggered action.

## Anti-patterns

- Gradient fill on more than one button in the same view.
- A destructive action (Từ chối) styled identically to the primary gradient
  button — reject should read as secondary/ghost, never as an equally weighted CTA.
- Any legacy two-action pair used in place of the locked recommendation actions.
