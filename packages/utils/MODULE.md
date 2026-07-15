# Module: utils

## Responsibility

Provide deterministic, locale-aware formatting utilities shared by Juli product
apps.

## Public interface

- `formatVND(amount)` — Vietnamese Dong with no fractional digits.
- `formatNumber(value)` — Vietnamese number separators.
- `formatDate(value)` / `formatDateTime(value)` — dates in ICT
  (`Asia/Ho_Chi_Minh`).

## Invariants

- Formatters are pure and perform no network or environment access.
- Dates never render raw ISO strings in product UI.
- This package never imports an app.

## Owners

- domain: web
- code: `packages/utils/`
