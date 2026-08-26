# Handoff: owner-only actions (HITL queue), 2026-08-25

Five things only the owner can do. Nothing here is blocked on an agent; every item is
either a human decision, a console/dashboard action, or a merge. Written to be picked up
by a session with **no prior context** — ids, commands, and the reasoning are inline.

Ordering matters in exactly one place: **§1 before merging PR #1350** (see §2).

---

## 1. HITL — gate #1226 observation 1: blocked on #1373, no owner action right now

**Status (2026-08-26):** still six of seven steps. **Nothing for the owner to do until
[#1373](https://github.com/thienphung00/Juli-AI/issues/1373) ships** — walking again
against the current build reproduces run `d9dac43d` exactly.

**The product edit this section used to ask for is DONE.** Product `1736363193934775939`
is now a real listing ("Nồi lẩu điện mini 1.5L có nắp kính, tay cầm tiện dụng") with a
matching photo; the vision tool returns `verdict: aligned`. That removed the original
blocker — the agent now has something concrete to propose, and does propose it.

**What three walks established** (all recorded on #1226):

| Run | Prompt | What happened | Fixed by |
|---|---|---|---|
| `17dab3b5`, `3c504cf2` | v1 | nothing worth proposing — junk listing data | the product edit |
| `ac992b92` | recorded v2, **executed v1** | pin/compose divergence | #1359 |
| `37a0e14e` | v2 | printed the tool call as a ```python fence in the seller message | #1367 |
| `d9dac43d` | v3 | narrated a prose promise instead of calling | **#1373** |

Three prompt revisions oscillated between two failure modes and never converged.
[ADR-088](../adr/088-consent-pause-is-a-runner-guarantee.md) (Accepted) diagnoses why:
reaching the CONFIRM pause was enforced **only** by the prompt, and a worked example
teaches surface form, so every fix traded one failure mode for the other. #1373 moves
enforcement into the runner, which also makes the invariant testable with a fake LLM per
PR — so this should be the last walk needed to close the observation.

**When #1373 has merged and deployed, walk it.** On the VPS
(`ssh -i ~/.ssh/juli_vps_tool root@5.223.68.27`). Two things differ from earlier walks:
the card is the shop's **real `optimize_product_2` card**, already reset to `active`, and
there is **no refresh step** — it is the only active card, so the decisions list is
unambiguous. Earlier walks used a `create_hero_product_1` card silently substituted onto
the Optimize Product playbook, which also stops being approvable once #1350 lands.

```bash
# 0. env + token (password grant; the call itself re-proves ES256/JWKS verification)
set -a; source /etc/juli/api.env; set +a
RESP=$(curl -s "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" -H "Content-Type: application/json" \
  -d '{"email":"gate-1226@app-juli.com","password":"PASTE_PASSWORD"}')
TOKEN=$(printf '%s' "$RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))')
if [ -z "$TOKEN" ]; then echo "LOGIN FAILED: $RESP"; else echo "token_len=${#TOKEN}"; fi
API=https://api.app-juli.com
SHOP=1862f13b-de2c-4fae-a4ad-70298cead913

# 1. approve — no refresh needed; this card is already active and is the only one
CARD=0aa74318-a560-4c2f-bbaa-f1f5e5f4e3d5
curl -s -X POST "$API/v1/demo/decisions/$CARD/approve" \
  -H "Authorization: Bearer $TOKEN" -H "X-Shop-Id: $SHOP" | python3 -m json.tool

# 2. stream — RUN **must** be the run_id from the approve you just did
RUN=<run_id from step 1>
curl -sN "$API/v1/demo/runs/$RUN/events" \
  -H "Authorization: Bearer $TOKEN" -H "X-Shop-Id: $SHOP" \
  | tee /root/gate-1226-obs1-events.log

# 3. when the stream shows the confirmation event, in a SECOND ssh window re-set
#    TOKEN/API/SHOP/RUN, then:
TCID=<tool_call_id from the confirmation event>
OPT=<option_id from the confirmation event>
curl -s -X POST "$API/v1/demo/runs/$RUN/confirmations/$TCID" \
  -H "Authorization: Bearer $TOKEN" -H "X-Shop-Id: $SHOP" \
  -H "Content-Type: application/json" \
  -d "{\"decision\":\"approve\",\"option_id\":\"$OPT\"}" | python3 -m json.tool
```

**Traps that already cost time in the last session:**
- Streaming with a **stale `$RUN`** replays an old run's events and looks like a fresh
  failure. Check the first event's `workflow_run_id` and timestamp match the approve you
  just did.
- `read`-based prompts eat pasted input; paste values inline instead.
- Never name a shell variable `UID` — bash reserves it (silent failure).
- Tokens last ~1h; re-mint on a 401.
- Completed runs consume their card permanently (by design). Failed runs auto-revert since
  #1306, so no manual `UPDATE` is needed any more. **A card spent on a completed run needs
  a manual revert to `active` before the next walk** — ask the agent session, don't hand-edit.
- **Check the first event's `prompt_version` before reading anything else.** If it is not
  the version #1373 shipped, the release has not landed and the walk is uninformative —
  stop rather than spending the card. `gh run list --workflow=release.yml --limit 1`
  confirms the deploy.

**Definition of done:** the write lands in the sandbox, the run reaches a success terminal
event, `/root/gate-1226-obs1-events.log` is the golden-scenario record, and the outcome is
posted on issue #1226. Observation 2 is already recorded as blocked by owner decision
(2026-08-25 comment) — that half of the gate is closed honestly and needs nothing further.

---

## 2. Merge queue

| PR | What | Base | Note |
|---|---|---|---|
| **#1350** | #1309 executability discriminator + named 409 refusal | `feature/agent-w6-wave` | **No longer blocked** — merge freely. |
| (Cursor session's) | #1326, #1331, #1332, #1334, #1335, #1338 | — | Owned by the other session; review status unknown here. |

**#1350's hold is lifted (2026-08-26).** It was held because it makes approve 409-refuse any
card whose `workflow_key` has no registered playbook, and the walk was then using a
`create_hero_product_1` card — one of the ten unregistered keys. The walk has since moved to
the shop's genuine `optimize_product_2` card, which is the one key that *is* registered, so
#1350 cannot take it away. Merging it actually helps: it ends the silent playbook
substitution that made every earlier walk ambiguous about which playbook was running.

Already merged (no action): #1343 (#1312 demo seed), #1345 (#1310 run list),
#1340/#1341/#1342 (W7 planning + handoff), #1323/#1324 (W6 planning), #1362 (#1359 prompt
pin), #1364 (this file's §5b), #1368 (#1367 prompt form), #1372 (ADR-088).

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

## 5. Supabase Auth provider configuration that will block W6

Two settings on the same Supabase project (the one behind `SUPABASE_URL` in
`/etc/juli/api.env`). Both are dashboard actions; do them in one sitting.

### 5a. Anonymous sign-in — blocks #1313

Issue #1313 ("Dùng thử Demo mints a real anonymous session scoped to the demo tenant")
needs it for its post-deploy journey. ADR-084 **forbids a shared demo account**, so there
is no workaround: without the toggle the executor can build and pre-merge-test everything
except the live journey, and the issue cannot be fully verified.

Supabase dashboard → Authentication → Providers/Sign-in methods → enable
**Anonymous sign-ins**.

### 5b. Google provider + a GCP OAuth client — blocks #1319

Issue #1319 ("Dual entry — Dùng thử Demo and Đăng nhập với Google") builds two doors on
the landing page. The second one, **Đăng nhập với Google**, goes through Supabase Auth's
Google provider, which needs an OAuth client you create in Google Cloud. Reference:
<https://supabase.com/docs/guides/auth/social-login/auth-google>.

What it needs:

1. A **GCP project** (any project; it exists only to own the OAuth client).
2. An **OAuth 2.0 Client ID** of type *Web application*, plus its client secret.
3. The Supabase project's **callback URL** registered as an Authorized redirect URI on
   that client. Supabase shows the exact URL on the Google provider page — copy it from
   there rather than composing it by hand; a `redirect_uri_mismatch` is the usual symptom
   of getting this wrong, and it only appears post-deploy.
4. The client ID and secret pasted into Supabase dashboard → Authentication → Providers →
   **Google**, then enabled.
5. The OAuth consent screen filled in far enough for the account you will test with. While
   the app is in *Testing*, only listed test users can complete the flow.

The public surface for this slice is `demo.app-juli.com` (per #1319's release-evidence
section), so that host is where the journey gets verified after deploy.

**Not blocked on TikTok.** #1319 deliberately does not wire live TikTok merchant OAuth —
it builds the "Kết nối TikTok Shop" connect-shop screen and requires it to state its real
state honestly rather than implying a working exchange. So Google sign-in reaching that
screen is the whole acceptance bar here; connecting an arbitrary merchant shop is a
separate flagged follow-up. Don't wait on TikTok credentials to do this setup.

**Timing.** #1319 is blocked by #1313, which is itself blocked on the #1353 decision, and
#1319 hasn't started — so this is not urgent today. It *will* gate that slice's
acceptance criteria, which require the Google entry to reach the connect-shop screen and
to preserve runs across identity linking; neither is demonstrable against an unconfigured
provider.

**Nothing in W7 needs a GCP project** — verified by scanning every W7 issue (#1326–#1339)
for Google/GCP requirements. This is a W6-only dependency.

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
