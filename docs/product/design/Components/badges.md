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
| Live | pulsing dot + neutral fill | Real-time/executing state indicator; also the Home activity tracker's "Running" tile (`Components/home-activity-tracker.md`) |

## Gợi ý bởi Juli (suggestion label)

The Info variant's one real use case. A small pill/label reading **Gợi ý bởi
Juli** paired with the suggestion glow on the associated field
(`Components/forms.md` Suggestion glow) — appears next to any prefilled-but-
editable value Juli supplied. Never implies confidence or certainty, only that
Juli suggested this value and the seller can change it.

## Retired: confidence badge

The former `high`/`medium`/`low` confidence badge on `ClarityCard`/
`RecommendationCard` (and any "Độ tin cậy" label) is **removed** — locked by
[PRD #600](https://github.com/thienphung00/Juli-AI/issues/600): no confidence
score appears on any seller card or approve surface. Do not reintroduce it
without a new product decision superseding that lock.

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
- Reintroducing a confidence/`Độ tin cậy` badge on any seller-facing surface.
