# ADR-076: Demo execution experience — dual-entry auth, recorded-replay demo, staged run view

**Status:** Proposed — **decision 1's active-shop model superseded in part** by #1283
**Date:** 2026-08-12
**Superseded by (in part):** #1283 — `GET /v1/demo/decisions` and
`GET /v1/demo/decisions/{id}` are no longer structurally pinned to the reference shop;
they authenticate (`get_current_user` + `get_active_shop`) and resolve shop scope from
the caller's `X-Shop-Id`, same as every other agent route. `GET /v1/demo/analytics` is
unaffected. See the amendment below.
**Deciders:** grill-with-docs (Architect) with user

**Builds on:** [ADR-074](074-agent-event-streaming-and-relay.md) (event union,
fetch-streaming SSE, replay authority), [ADR-075](075-agent-approval-gate-and-security-prerequisites.md)
(JWT on every agent route, decision requests). **Design spec:**
[`PUI-DESIGN.md`](../product/agent-workflow-execution/PUI-DESIGN.md) — wireframes,
stage model, motion spec, copy table.
**Mandate (user):** structural design policy and theme tokens are lifted for the
Optimize Product surfaces + In-Progress sub-tab; motion is first-class. Binding:
`dictionary.md` copy, the other 10 workflows, accessibility basics; the event
protocol grows only by flagged additive requests.
**Scope:** Phase P-UI of [`PLAN.md`](../product/agent-workflow-execution/PLAN.md).

## Context

The streaming architecture (ADR-071/073/074/075) needs its seller-facing surface. A
long clarification arc settled auth (three credentials untangled: Supabase service
keys ≠ Supabase Auth user identity ≠ TikTok merchant OAuth) and the demo's data mode.
Seven decisions were grilled.

## Decision

1. **Dual entry.** *Try the Demo*: Supabase **anonymous sign-in** mints a real JWT —
   ADR-075 holds with zero carve-outs; each visitor is a distinct user (meaningful
   audit rows); active shop structurally pinned to the reference shop **— superseded
   in part by #1283: the Decisions read routes (`GET /v1/demo/decisions`,
   `GET /v1/demo/decisions/{id}`) no longer enforce that pin themselves. They resolve
   shop scope from the authenticated caller's `X-Shop-Id` via `get_active_shop`; the
   anonymous session's client still ordinarily sends the reference shop's id there,
   but the routes no longer guarantee it structurally. See the amendment below**;
   rate buckets keyed per user-session (config). *Sign in with Google*: Supabase Auth (Google
   provider) → identity; **TikTok OAuth remains shop authorization** — the two facts
   stay separate (multi-shop, staff access, revocation-safe; merchant tokens never
   double as session proof; demo visitors could never merchant-auth the reference
   shop). v1 builds the demo path fully + the Google login and connect-shop screens;
   the live merchant OAuth exchange for arbitrary shops is a flagged follow-up.
   TikTok Login Kit as an identity provider = future additive button. Rejected:
   TikTok-as-IdP (rebuilds session machinery, breaks multi-shop/staff, cannot admit
   demo visitors); shared demo account (shared credentials, indistinguishable audits).

2. **Recorded-replay demo + live flag.** Demo runs are **golden scenarios** captured
   from real sandbox executions and replayed through the identical SSE endpoint,
   protocol, and client — instant, deterministic, zero token cost, immune to
   OpenAI/TikTok outages. Live mode behind config for the phase gate, stakeholder
   demos, and real users. **Realism requirements (user: "make it seem real"):**
   recorded-delta pacing (thinking pauses included), timestamps rebased to now,
   typewriter rendering, genuinely interactive decision request (the pick selects
   its recorded continuation — one captured continuation per option), no replay
   tells. Rejected: live-for-everyone (cost + reliability hostage); hand-authored
   mocks (a second code path that drifts — the localStorage problem re-created).

3. **Staged run view (user directive: one stage at a time, reduce cognitive load).**
   Approve navigates to a dedicated run page; six stages derived from the playbook
   (Phân tích → Thông tin sản phẩm → SEO → Đề xuất → Cập nhật → Hoàn tất); a top
   stepper + full-width stage canvas; back = frozen completed stages (review before
   deciding is encouraged), forward = live edge, future locked; thinking/loading is
   a stage state. Finished runs reopen in the same view frozen — replay-powered
   history for free. Rejected: single stacked feed (the cognitive-load problem);
   inline card expansion and split-drawer (no stage for motion or N-option layouts).

4. **Consent-grade option picker.** Side-by-side option cards: prominent value,
   before→after diff on a miniature of the real listing element, rationale,
   expected effect from the signals payload (never invented client-side). Two-step
   consent (select arms → confirm fires; no single-click mutation authority);
   decline is quiet and first-class with outcome copy; visible 4h expiry. Motion:
   staggered card arrival, selected card carries forward into Cập nhật.

5. **In-Progress = run ledger.** Three priority sections (Đang chờ bạn pinned with
   countdowns / Đang chạy with breathing latest-line cards / Hoàn tất with honest,
   distinct terminal states incl. decline-as-choice and `worker_lost` honesty). No
   retry-in-place (a new run needs a new approval by the gate's design). Active
   run's card may hold a stream; the rest refetch.

6. **Client architecture.** `useRunStream` (fetch-streaming, bearer headers,
   `Last-Event-ID` backoff reconnect) + a **pure event→stage reducer** tested
   directly on the golden fixtures — replay and live share one code path by
   construction. Mock layer retired for this workflow (localStorage `startExecution`
   deleted, `fetchRecommendations` path bug fixed, silent fixture fallback removed).
   Reconnect UX separates stream error from run error: quiet "Đang kết nối lại…",
   gapless catch-up, calm offline banner. State local; no global store.

7. **Unique documentation + tests + gate.** Two artifacts: `PUI-DESIGN.md` (spec:
   wireframes, motion table, copy table — new VI strings land in `dictionary.md`
   with implementation) + this ADR. Tests: reducer units on fixtures, consent/
   navigation component tests, **deterministic replay-based Playwright E2E in CI**,
   a11y checks, other-workflow regression. Gate: replay E2E green + one observed
   live-mode run end-to-end + dictionary entries + MODULE.md invariant updated +
   spec published + zero regressions.

## Consequences

- The demo is unbreakable in public (no external dependency at demo time) while the
  live path stays one flag away and is exercised at the gate.
- Recording golden scenarios becomes a small maintained practice: re-capture when
  the prompt version bumps (`prompt_sha256` on runs tells when scenarios are stale).
- The anonymous→Google identity-linking seam gives "keep your account" for free.
- `apps/demo/MODULE.md`'s no-backend invariant is fully retired for this workflow's
  surfaces; the other 10 workflows keep their existing flows untouched until P13.

## Amendment — Demo Decisions read auth (2026-08-24, #1283)

`GET /v1/demo/decisions` and `GET /v1/demo/decisions/{action_card_id}` are
**authenticated as of #1283** — `get_current_user` + `get_active_shop`, the same
pattern every other agent route already requires (ADR-075 decision 3). Found while
walking #1226's HITL gate on the deployed host: both routes were unauthenticated and
resolved a **server-bound reference shop** (`DEMO_REFERENCE_SHOP_ID`) — decision 1's
"active shop structurally pinned to the reference shop" above, taken literally as an
enforcement mechanism baked into the routes themselves, not just a product default for
the anonymous session. On the deployed host that reference shop was a real merchant's
production shop (Fujiwa Vietnam Store), so the routes served a live seller's
recommendations — titles, descriptions, rationales, expected-impact figures — to any
caller who could reach the URL, with no credentials at all. ADR-075 decision 3 had
deliberately left these two read-only routes open: "Read-only legacy demo fixture
endpoints are P-UI's call." #1283 is that call.

**Consequence for W6.** The option picker (decision 4) can no longer assume every
visitor's Decisions list is scoped to a single, server-bound shop. It operates on the
**authenticated caller's own shop**, passed via `X-Shop-Id` and ownership-checked by
`get_active_shop` — for the *Try the Demo* anonymous-JWT path (decision 1), that header
still ordinarily carries the reference shop's id (nothing about anonymous-session
provisioning changed), but the Decisions routes no longer structurally guarantee it;
it is a property of whatever shop the caller's session is scoped to, resolved the same
way as every other authenticated `/v1/*` route. A caller scoped to a shop with no cards
sees an empty list, never another shop's — the option picker must design for that case,
not assume the reference shop's four production cards are always present.

**What did not change.** `GET /v1/demo/analytics` remains unauthenticated and still
resolves `get_demo_reference_shop_id` / `DEMO_REFERENCE_SHOP_ID` — it was out of scope
for #1283 (a separate, still-open call under ADR-075 decision 3) and continues to serve
the server-bound reference shop's masked KPI envelope to any caller. Do not read this
amendment as the whole demo surface closing its no-auth posture; only the two Decisions
read routes did.
