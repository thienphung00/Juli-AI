# Flows/home/login.md — Login & Session Recovery

> Unauthenticated route; not covered by [`../../Screens/home.md`](../../Screens/home.md).
> Source target: `apps/dashboard`.

## Steps

1. **Landing** — centered form, brand wordmark (`.brand-wordmark-lg`), email +
   password fields (`Components/forms.md`).
2. **Submit** — primary button shows loading spinner; on success, route to
   `/mode-select` if no `juli_workspace_mode` is persisted, else straight to Home.
3. **OTP (if enabled)** — 6-box segmented input (`Components/forms.md`), auto-
   advance, auto-submit on completion, native SMS autofill on iOS.
4. **Forgot password** — link below the submit button → email-based reset flow →
   confirmation screen → back to login.
5. **Session recovery** — on an expired session anywhere in the app, an alert
   dialog (`Components/dialogs.md`) explains the session ended and routes back to
   login on dismiss; in-progress form input elsewhere in the app is preserved
   where technically possible, discarded with a warning otherwise.

## Error states

| Case | Copy pattern |
|---|---|
| Wrong password | "Sai email hoặc mật khẩu. Vui lòng thử lại." |
| Wrong OTP | "Mã OTP không đúng. Vui lòng thử lại." |
| Account not found | "Không tìm thấy tài khoản với email này." + link to sign-up if applicable |
| Network error | "Không thể kết nối. Vui lòng kiểm tra mạng và thử lại." |

## Platform parity

Identical field set and copy across web/mobile-web/native. Native adds SMS OTP
autofill only ([`../../flows.md`](../../flows.md) §Platform parity) — no
different login steps.

## Mode-select gate (`/mode-select`)

Shown once, immediately after first login, before the seller ever sees Home:

- Two choices: **Seller** (light theme, full Decision Copilot IA) or **Affiliate**
  (dark theme, out-of-scope placeholder shell).
- Choice persists to `juli_workspace_mode` in `localStorage`; skipped on every
  subsequent login once set.
