# Reviewer login runbook — App Review (#260)

> **Parent:** [#249](https://github.com/thienphung00/Juli-AI/issues/249) · **Issue:** [#260](https://github.com/thienphung00/Juli-AI/issues/260)  
> **Prerequisites:** [#257](frontend-deploy-runbook.md) (frontend) · [#258](backend-deploy-runbook.md) (backend)  
> **Next:** [#254](https://github.com/thienphung00/Juli-AI/issues/254) (E2E verification)

Enable TikTok App Review testers to log into Juli **without becoming real
production users** and **without real seller business data**.

---

## Decision: UI-only demo login (preferred)

App Review uses **one-click demo login** — no phone OTP, no Supabase Auth
session, no production user records.

| Path | When | Backend auth required |
|------|------|----------------------|
| **UI-only** (`NEXT_PUBLIC_UI_ONLY=1`) | **Default for App Review** | No — mock data in the browser |
| Supabase OTP (optional) | Only if TikTok explicitly requires API-backed login | Yes — `SUPABASE_JWT_SECRET` on API |

ADR-002: phone-OTP login was removed (2026-07). Supabase free tier remains for
**Postgres** (`DATABASE_URL`) and optional JWT validation — not for reviewer entry.

---

## UI-only path (default)

### Build contract

`NEXT_PUBLIC_UI_ONLY=1` is **baked at build time**. Reviewers see demo login at
`https://app-juli.com/login` only when the frontend was built with the review script.

```bash
cd ~/Juli-AI-v2

# web/.env.production must include:
#   NEXT_PUBLIC_API_URL=https://api.app-juli.com
#   NEXT_PUBLIC_UI_ONLY=1

./infra/scripts/build-frontend-review.sh   # forces NEXT_PUBLIC_UI_ONLY=1
sudo systemctl restart juli-web
```

### Reviewer flow

1. Open `https://app-juli.com/login` over HTTPS.
2. Tap **Tiếp tục vào ứng dụng** — no OTP, no credentials to type.
3. Select **Seller** workspace on `/mode-select` (if not already persisted).
4. Browse Home, Decisions, and Juli AI with **mock demo data** — no API auth calls.

Login implementation: `web/src/components/LoginForm.tsx` → `loginAsReviewer()` in
`web/src/lib/auth-context.tsx` stores a local demo token and shop id.

### Verify (HITL)

```bash
cd ~/Juli-AI-v2
APP_DOMAIN=app-juli.com API_DOMAIN=api.app-juli.com ./infra/scripts/smoke-test.sh
```

Smoke test checks #6–7 assert the login chunk contains demo markers
(`loginAsReviewer`, `Tiếp tục`) and home chunks load after auth.

---

## Optional: Supabase OTP auth (only if required)

Use this path **only** when TikTok App Review explicitly requires API-backed phone
login. Otherwise stay on UI-only — it satisfies App Review without creating users.

### Supabase free-tier project (HITL)

Create or reuse a **dedicated review project** on Supabase free tier. Do **not**
point App Review at production Supabase.

| Setting | Value |
|---------|-------|
| Project | Dedicated App Review project (free tier) |
| Site URL | `https://app-juli.com` |
| Redirect URLs | `https://app-juli.com/**` |
| Database | Session pooler URI in `DATABASE_URL` (see [`backend-deploy-runbook.md`](backend-deploy-runbook.md)) |

**Dashboard steps:**

1. Supabase Dashboard → **Authentication** → **URL Configuration**.
2. Set **Site URL** to `https://app-juli.com`.
3. Add **Redirect URL** `https://app-juli.com/**` (wildcard covers `/login` callbacks).
4. Enable Phone provider only if OTP is required; configure test numbers per Supabase docs.
5. Copy `SUPABASE_JWT_SECRET` to `~/Juli-AI-v2/.env` on the VPS (never commit).

Rebuild frontend **without** `NEXT_PUBLIC_UI_ONLY=1` only when switching to OTP —
that is out of scope for the default App Review slice and needs a separate issue.

---

## Credentials and instructions (outside source control)

**Never commit** reviewer credentials, Supabase keys, or TikTok Partner Center
secrets. Store them only in:

- VPS env files (`~/Juli-AI-v2/.env`, `~/Juli-AI-v2/web/.env.production`)
- A password manager or secret manager
- Operator ops notes (not this repository)

### Reviewer handoff template (copy to ops notes)

```text
Juli App Review — reviewer access
URL:      https://app-juli.com/login
Login:    Tap "Tiếp tục vào ứng dụng" (demo — no password)
Workspace: Select "Seller" on first visit
Data:     Mock demo shop only — no real seller data
Support:  <operator contact>
```

For OTP path only, add test phone numbers and OTP delivery notes — still **outside git**.

---

## No real seller business data

| Area | App Review behavior |
|------|---------------------|
| Login | Local demo token; no user row created |
| Home / Decisions | Mock fixtures when `NEXT_PUBLIC_UI_ONLY=1` |
| API | Health + OAuth callback only; protected routes optional |
| Database | Schema for OAuth persistence only; no production dataset import |

Reviewers do **not** need real TikTok Shop orders, PII, or production shop records.

---

## Sign-off checklist

- [ ] Frontend built with `NEXT_PUBLIC_UI_ONLY=1` (`build-frontend-review.sh`)
- [ ] `https://app-juli.com/login` shows one-click demo entry (not phone OTP)
- [ ] Demo login reaches Home with mock data (no blank page after auth)
- [ ] `./infra/scripts/smoke-test.sh` passes login + home chunk checks
- [ ] Supabase Site URL = `https://app-juli.com` **if** OTP path is enabled
- [ ] Redirect URLs include `https://app-juli.com/**` **if** OTP path is enabled
- [ ] Reviewer instructions stored in ops notes / secret manager — **not in git**
- [ ] No production users or real seller business data required

---

## Troubleshooting

### Login shows phone OTP instead of demo entry

Build predates UI-only or was not built with the review script:

```bash
grep NEXT_PUBLIC_UI_ONLY=1 web/.env.production
./infra/scripts/build-frontend-review.sh
sudo systemctl restart juli-web
```

### Blank page after demo login

Stale partial `.next` build — see [`frontend-deploy-runbook.md`](frontend-deploy-runbook.md#blank-homepage-after-login).

### Smoke test: login chunk missing demo markers

Same as above — rebuild with `build-frontend-review.sh`.

---

## Related docs

| Doc | Purpose |
|-----|---------|
| [`frontend-deploy-runbook.md`](frontend-deploy-runbook.md) | Build + `juli-web` (#257) |
| [`backend-deploy-runbook.md`](backend-deploy-runbook.md) | `juli-api` + `DATABASE_URL` (#258) |
| [`app-review-runbook.md`](app-review-runbook.md) | Full topology + env vars |
| [`env/web.env.example`](env/web.env.example) | Frontend env template |
