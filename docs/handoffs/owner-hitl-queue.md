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

**W7 implementation is complete.** #1326–#1338 are all closed; #1339 is the only open issue
in the wave. State below verified against the deployed database on 2026-09-07.

Each observation has a recorded "legitimate result" that is **not** success, so an honest
negative closes it.

### 1. Role cutover — substantially done, one bullet pending a deploy

The cutover **has happened**: `DATABASE_URL` now connects as `juli_app`, which is a non-owner
role (`rolcanlogin = t`, `rolsuper = f`), while all 35 `public` tables are owned by `postgres`.
So the owner exemption that made the original ten policies dead is gone.

RLS coverage: **33 of 35** tables. The two without are both intentional —
`alembic_version` (migration bookkeeping, no tenant data) and `webhook_raw_events`, which
migration `045_rls_policies.py` documents as "no policy (no read grant in #1326)". Verified
that the grant defense actually holds: `juli_app` has **INSERT only** on that table, and
`select count(*) from webhook_raw_events` returns `ERROR: permission denied`.

A prior session recorded bullets 2, 3 and 4 as **pass** (zero scoping errors; zero RLS denials
since 2026-09-05 05:23; all four partition buckets complete across 31 in-window days). Bullet 1
**failed** — every authenticated request returned 401 because RLS hid the `users` row from the
authenticator — diagnosed and fixed in #1691 / PR #1693.

**Bullet 1 re-verified 2026-09-07 and the mechanism is fixed.** The #1693 release deployed
successfully and is live — `~/releases/current` → `/root/releases/e7c2bef9`, both blue/green
candidates (8000, 8020) healthy. Reproducing the commit's own measurement as `juli_app` against
the deployed database, for auth id `00000000-0000-4000-8000-000000000001`:

```
no GUC                  users row visible: 0     ← the old failure
GUC set from `sub`      users row visible: 1     ← the fix
GUC set from `sub`      total rows visible: 1    ← policy still narrows; not a bypass
```

**What this does not do is sign the observation off.** It confirms the database-level mechanism
on the live release; it is not an end-to-end authenticated HTTP request, which needs the
`gate-1226@app-juli.com` password. The remaining step is one authenticated call against
`api.app-juli.com` returning 200 rather than 401 — then bullets 1–4 are all green and the
observation is the owner's to close.

### 2. Manual red-team pass

Not started. Open findings are the pass *working*. Produces an attestation bound to the
deployed release sha, which #1336's precondition 4 reads.

### 3. Authorization for one production mutation — **declining is the default and a pass**

**No decision is recorded either way.** #1335 made owner authorization *become a row*, and
`production_write_authorizations` currently holds **0 rows**. So this is not "declined" — it is
unanswered. Requires functional RLS and the red-team pass first. The mutation is a single
listing of the owner's choosing. Standing rule until then: sandbox-only writes, never Fujiwa
(`2b1da87b-d0a8-46a6-b3c6-2132be0b5f4f`).

### 4. T+7 impact reading — **not satisfied; the only two rows are the forbidden kind**

`impact_readings` holds 2 rows, both on the sandbox shop, both computed 2026-09-03:

```
kind=preliminary  confidence=suppressed  metric=conversion_rate  impact_pct=NULL
kind=preliminary  confidence=suppressed  metric=items_sold       impact_pct=NULL
```

ADR-077's gate forbids recording a `suppressed` reading as a reading, **by name** — and these
carry no value at all (`impact_pct` is NULL). So the observation is open, and these rows must
not be mistaken for having satisfied it. It needs a real reading with a value and a confidence
tier, which in turn needs observation 3 to produce a write worth measuring.

#1339 **supersedes #1226 observation 2**; #1226 is closed (§1).

---

## 4. Four W7 decisions

Two of these have been **answered by events** since the list was written. Verified against the
deployed database 2026-09-07.

### 1. ✅ Answered — `postgres` does own the tables

All **35** `public` tables are owned by `postgres`. The hypothesis in the original entry was
correct, so **#1326's grant map does not narrow**. The consequence that mattered is already
handled: the runtime no longer connects as the owner, so the exemption that made the ten
original policies dead no longer applies.

### 2. ✅ Answered — `juli_app` has login and is the runtime role

`rolcanlogin = t`, `rolsuper = f`, and `DATABASE_URL` uses it. Provisioning stayed out of git
as designed (NOLOGIN role + grants in-repo, membership granted out of band); the deployed
reality confirms the approach worked. No switch to a console-managed role is needed.

### 3. ⬜ Open — ADR-050 C2 (fleet cold-start engine)

Removed from W7 with a recorded trigger because it roughly doubles the wave. W7 shipped
without it (#1326–#1338 all closed), so it is deferred **in fact**. Confirm it stays deferred,
or make it W7-bis.

### 4. ⬜ Open — GA per-shop credential model

Assessed and deferred; unchanged. What remains is per-shop `seller_connect` scoping, which is
an architecture change, not a fix. Confirm or pull forward.

Context for #1 and #4: the capability taxonomy (`production_read` / `sandbox_write` /
`seller_connect`) is test-era scaffolding — two env-configured merchant ids plus a
least-privilege residual bucket. At GA the axis rotates from "which of our tokens may do what"
to per-shop tenant isolation.

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
