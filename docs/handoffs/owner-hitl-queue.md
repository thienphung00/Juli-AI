# Handoff: owner-only actions (HITL queue), updated 2026-09-07

Owner-only actions: human decisions, console/dashboard work, and merges. Written to be
picked up by a session with **no prior context** — ids, commands, and the reasoning are
inline.

**Two items are live: §3 and §4.** §1, §2 and §5 are closed and kept as record — read them
for what was established, not for work to do.

---

## 1. ✅ CLOSED — gate #1226 observation 1

**Closed 2026-08-27, 7 of 7.** The seller-consent path executed end to end on the deployed
host: run `fcbd287e-c158-4669-b7f6-9cb274b50314`, release `2d37170c`, card `0aa74318`
(`optimize_product_2`), sandbox product `1736363193934775939`.

The write landed and was **verified against the live listing**, not inferred from the tool
result — the sandbox Seller Center shows the new description, with title, photo and price
unchanged because the agent had no grounded signal to change them.

`#1373` (consent pause enforced in the runner, ADR-088) was the last blocker and has merged.
Observation 2 was superseded by #1339 (§3) rather than closed here.

**Nothing for the owner in this section.** The walk procedure, its traps, and the token/approve/
stream/confirm command sequence are preserved in this file's history if a future gate needs
them — `git log --follow docs/handoffs/owner-hitl-queue.md`.

---

## 2. ✅ CLOSED — merge queue

**#1350** (#1309 executability discriminator + named 409 refusal) **merged**. Its hold was
lifted once the gate walk moved to the shop's genuine `optimize_product_2` card, and merging
it ended the silent playbook substitution that made earlier walks ambiguous.

Also merged: #1343 (#1312 demo seed), #1345 (#1310 run list), #1340/#1341/#1342 (W7 planning
+ handoff), #1323/#1324 (W6 planning), #1362 (#1359 prompt pin), #1364, #1368 (#1367 prompt
form), #1372 (ADR-088), #1690 (ADR-094), #1693 (#1691 auth RLS fix).

**Nothing pending.** New PRs are tracked in `gh pr list`, not here.

---

## 3. HITL — gate #1339 (W7 exit gate), four observations

Not startable until the W7-A/W7-B implementation issues land. Each has a recorded
"legitimate result" that is **not** success, so an honest negative closes the observation:

1. **Role cutover** on the deployed host (connect as the non-owner `juli_app` role) — a
   clean revert plus a diagnosis is a pass.
2. **Manual red-team pass** — open findings are the pass *working*; produces an attestation
   bound to the deployed release sha, which #1336's precondition 4 reads.
3. **Authorization for one production mutation** — **declining is the default and a pass.**
   Requires functional RLS and the red-team pass first; the mutation is a single listing of
   the owner's choosing. Standing rule until then: sandbox-only writes, never Fujiwa
   (`2b1da87b-d0a8-46a6-b3c6-2132be0b5f4f`).
4. **T+7 impact reading** — a real `impact_readings` row with a value and confidence tier.
   Recording a `suppressed` reading as a reading is forbidden by name (ADR-077's gate stays
   open until a real one exists).

#1339 **supersedes #1226 observation 2**; #1226 stays open for observation 1 only (§1).

---

## 4. Four W7 decisions

From `docs/handoffs/w7-production-readiness.md`. Answers change scope, not correctness —
the implementation verifies at runtime either way.

1. **Does `postgres` actually own the tables** on the deployed Supabase project? Repo
   evidence (migration `032`'s docstring, `api.env.example`) says the runtime connects as
   the pooler `postgres` role — which owns the tables and is therefore **exempt from row
   policies**, the reason the existing 10 RLS policies are dead. If ownership differs,
   #1326's grant map narrows.
2. **`juli_app` login provisioning** — deliberately out of git (NOLOGIN role + grants
   in-repo; membership granted out of band). Confirm, or switch to a Supabase
   console-managed role.
3. **ADR-050 C2 (fleet cold-start engine)** — removed from W7 with a recorded trigger
   because it roughly doubles the wave. Confirm it stays deferred, or make it W7-bis.
4. **GA per-shop credential model** — assessed and deferred; what remains is per-shop
   `seller_connect` scoping, which is an architecture change, not a fix. Confirm or pull
   forward.

Context for #1: the capability taxonomy (`production_read` / `sandbox_write` /
`seller_connect`) is test-era scaffolding — two env-configured merchant ids plus a
least-privilege residual bucket. At GA the axis rotates from "which of our tokens may do
what" to per-shop tenant isolation.

---

## 5. ✅ CLOSED — Supabase Auth provider configuration

Both items resolved 2026-09-07. Kept as record because the *reasons* matter for W6.

### 5a. Anonymous sign-in — WITHDRAWN, do not enable

[ADR-094](../adr/094-demo-surface-splits-anonymous-replay-and-signed-in-runs.md) decision 4
withdrew this. The anonymous "Dùng thử Demo" entry is now a **client replay with no session,
no authenticated route and no database row**, so there is nothing to authenticate.

**Leave `Allow anonymous sign-ins` OFF.** Supabase's own warning on that toggle is the
sharpest argument for the rescope: anonymous users receive the `authenticated` role, so they
would be subject to the same RLS policies as real users. Those policies
(`045_rls_policies.py`) carry **no `TO` clause** and key on `current_setting('app.current_shop_id')`
— a GUC that only Juli's backend sets. That is fail-closed today, but it makes safety depend
on *every* tenant-scoped table having a policy, an invariant that already failed once
(migration 045 missed `ml_feature_snapshots` and `processed_events`; #1329 caught it, 046
fixed it). Enabling the toggle would add a self-service principal class to a model built for
a single trusted caller.

### 5b. Google provider — DONE and verified

| | |
|---|---|
| GCP project | `juli-auth-51452` ("Juli Auth"), under the `app-juli.com` org (`89219823463`) |
| Owning account | `thien.phung@app-juli.com` |
| OAuth client | Web application; **JavaScript origins empty** (Supabase uses the server-side code flow) |
| Authorized redirect URI | `https://rmxzbvgiwrvjuzlzqdcz.supabase.co/auth/v1/callback` |
| Client ID | `77566792969-v897lb3l03jadn2lhqhp2rg5a7oisrtd.apps.googleusercontent.com` |
| Client secret | **Supabase provider config + a password manager only.** No code reads it — verified: zero references to a Google client id/secret across `backend`, `apps`, `packages`. Never put it in `/etc/juli/api.env`, a `.env`, or this file. Rotating it needs no deploy. |

**No domain verification was needed.** The `app-juli.com` org already existed (Workspace
creates it), and `thien.phung@app-juli.com` already had project-creation rights. A personal
Gmail account is also viable — it creates projects with "No organization".

Verified on the deployed project (`rmxzbvgiwrvjuzlzqdcz`):

```
GET /auth/v1/settings                    → external.google = true
GET /auth/v1/authorize?provider=google   → HTTP 302 accounts.google.com/o/oauth2/v2/auth
                                           client_id=77566792969-…  response_type=code
                                           redirect_uri=…/auth/v1/callback
```

The 302 is the check that matters — the settings flag can read true with credentials Supabase
never accepted.

Supabase provider toggles, as set: `Allow new users to sign up` **ON**; `Allow manual
linking`, `Allow anonymous sign-ins`, `Skip nonce checks`, `Allow users without an email`
all **OFF**.

### 5c. Still open — publishing the consent screen (a Demo Launch gate)

The consent screen is **External + Testing**. Testing works for verification (add test users,
100 max) but **only listed test users can sign in**, so a public Demo Launch needs
**Publish app**.

Publishing requires an application home page, **privacy policy** and **terms of service**
URLs. Today:

```
https://app-juli.com          → 200   ✓
https://app-juli.com/privacy  → 404
https://app-juli.com/terms    → 404
apps/landing/src/app/         → page.tsx is the only route
```

So it is two legal documents plus a small `apps/landing` slice, not a toggle. Deliberately
deferred — the privacy policy describes what Juli collects from TikTok sellers and is a public
commitment, not filler. Because the scopes are the defaults (`openid`, `email`, `profile`,
all non-sensitive), publishing needs **no Google verification review** once the URLs exist.

**Blocked on nothing but content.** Put it on the Demo Launch checklist, not the W6 build.

---

## Quick reference

| Thing | Value |
|---|---|
| VPS | `ssh -i ~/.ssh/juli_vps_tool root@5.223.68.27` (env at `/etc/juli/api.env`) |
| API | `https://api.app-juli.com` (behind Cloudflare; zero-byte streams die at ~100s with 524) |
| Gate test seller | `gate-1226@app-juli.com`, auth id `00000000-0000-4000-8000-000000000001` |
| Sandbox shop (walks) | `1862f13b-de2c-4fae-a4ad-70298cead913` |
| Sandbox-write merchant | `7658096633384781588` |
| Sandbox product (edited, now a real listing) | `1736363193934775939` |
| Gate walk card (`optimize_product_2`, active) | `0aa74318-a560-4c2f-bbaa-f1f5e5f4e3d5` |
| Fujiwa production shop | `2b1da87b-d0a8-46a6-b3c6-2132be0b5f4f` — **never write to it** |
| W6 wave branch | `feature/agent-w6-wave` (manifest `agent-runtime/artifacts/waves/wave-agent-w6.json`) |
| API is blue/green | candidates on ports 8000/8020 — grep BOTH journals when checking what's live |
| Supabase project | `rmxzbvgiwrvjuzlzqdcz` — the project the API verifies JWTs against; Google sign-in must be configured on **this** one |
| GCP project (OAuth) | `juli-auth-51452`, org `app-juli.com` (`89219823463`), owner `thien.phung@app-juli.com` |
| Google consent screen | **External + Testing** — only listed test users can sign in until §5c is done |
