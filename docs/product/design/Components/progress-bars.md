# Components / progress-bars.md

> Reference: `RealEstimatedBar.tsx`, `DecisionDetailStepIndicator.tsx`.

## Standard progress

- Simple filled bar, `--pink-main` fill on `--border` track, `--radius` full
  (pill shape). Used for the Decision detail 5-step indicator and any linear
  completion state.

## RealEstimatedBar

- Two-segment bar: **real** (solid `--pink-main` fill, left portion) + **estimated**
  (same hue at reduced opacity + a subtle glow pulse, right portion, disabled
  under `prefers-reduced-motion`).
- The boundary between real and estimated is the "today" marker — visually
  distinct (a thin line or tick), not just an opacity change alone.
- In Analytics, tapping the estimated segment may deep-link to
  `/decisions?highlight=<workflow_id>` — see `Components/charts.md`.

## Step indicator (Decision detail flow)

- 5 steps (Why → Analytics → Inputs → Preview → Approve), current step filled,
  completed steps checked, future steps outlined only.
- Back navigation always available except from step 1; forward navigation
  requires the current step's required inputs to be valid.
- After approval, execution progress continues in the shared workflow detail and
  is summarized by the card under Decisions → Đang thực hiện.

## Rules

- Progress bars never imply false precision — if a value is estimated, it must
  visually read as estimated (opacity/glow), never presented identically to a
  confirmed real value.
- Threshold ticks (on Shop Health bars, see `Components/health-bars.md`) share the
  same tick-mark visual language as this file's step indicator ticks — one
  consistent "marker" vocabulary system-wide.

## Anti-patterns

- A progress bar with no label of what it's measuring.
- Real and estimated segments rendered in different hues instead of the same hue
  at different opacity — that would suggest they're different metrics, not
  different confidence levels of the same metric.
