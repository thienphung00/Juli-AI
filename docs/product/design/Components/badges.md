# Components / badges.md

> Code: `.badge` + `.badge-success` / `.badge-destructive` / `.badge-warning` /
> `.badge-info` / `.badge-live` in `apps/dashboard/src/app/globals.css`.

## Variants

| Variant | Color | Use |
|---|---|---|
| Success | `--success` | Positive delta, growth, approved/completed status |
| Destructive | `--destructive` | Negative delta, risk, rejected status |
| Warning | `--warning` | Caution, threshold proximity, needs_input status |
| Info | `--info` | **Reserved for Juli suggestions only** — never generic status |
| Live | pulsing dot + neutral fill | Real-time/executing state indicator |

## Confidence badge (Decision-specific)

`high` / `medium` / `low` confidence on a `ClarityCard` — text label always
accompanies the color (never color-only), e.g. "Độ tin cậy: Cao".

## Rules

- Every badge pairs its color with a text label or icon.
- Badge text is always short (1–3 words) — badges summarize, they don't explain;
  explanation lives in `Components/dialogs.md` or an expandable reasoning panel.
- `.badge-live` pulse respects `prefers-reduced-motion` — static dot when reduced
  motion is on.

## Anti-patterns

- Using `--info` blue for anything other than a Juli-authored suggestion — it
  would visually conflict with the one reserved "this is Juli talking" signal.
- Badge as the sole means of conveying a Decision's status with no accompanying
  text.
