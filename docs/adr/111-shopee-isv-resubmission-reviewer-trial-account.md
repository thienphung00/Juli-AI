# ADR-111: Shopee ISV resubmission — a per-platform, expiring reviewer trial account that shows the live TikTok Shop integration on masked Fujiwa data with simulated approval and execution, and public pages that state Shopee's status honestly

**Status:** Proposed
**Date:** 2026-10-14
**Deciders:** grill session (Architect) with the owner, seven questions.
**Builds on:** [ADR-037](037-phase-2.10-demo-real-data-no-auth.md) and
[ADR-038](038-phase-2.10-dual-layer-pipeline.md) (masked reference-shop data, no Fujiwa writes
from the public Demo); [ADR-094](094-demo-surface-splits-anonymous-replay-and-signed-in-runs.md)
(two doors: anonymous replay and signed-in runs).
**Does not change:** the real-merchant path (Google → Supabase Auth → TikTok OAuth), Fujiwa's
`production_read` credential, or any executor.
**Scope:** what a marketplace reviewer (Shopee first; TikTok, Lazada later) sees and can do.

## Context

Shopee rejected Juli's Third-party Partner Platform (ISV) application:

> Since you're the ISV, the service/function you provided doesn't comply with Shopee policy … or
> we are unable to identify the actual service you provide via Test URL.

Shopee's criteria ([Developer account registration §3.2](https://open.shopee.com/developer-guide/12),
read 2026-10-14) require that the product be **live, with existing ecommerce integrations
identifiable via a provided trial account**, that **live URL + trial login details** are submitted
with **all features enabled** for testing, and that the URL is HTTPS, TLS ≥ 1.2, security rating
"A". [Platform Partner Rules §4](https://open.shopee.com/developer-guide/34) penalises "offering
services that are different from submitted descriptions".

What the reviewer met on 2026-10-14:

- `app-juli.com`: "Dành cho người bán TikTok Shop", no Shopee text in the served HTML.
- `demo.app-juli.com`: mock data; both "Đăng nhập với Google" and "Đăng nhập bằng email" render
  disabled ("chưa sẵn sàng trong môi trường này"); email sign-in has no implementation.
- `/privacy`: "Shopee support is in development; this policy will be updated before Juli reads any
  data". `/terms`: TikTok Shop only. `/login`: 404. `dashboard.app-juli.com`: does not resolve.

The reviewer could not sign in and could not see any live integration. The ISV profile is
submitted **before** an app (and so a Shopee partner_id or sandbox) exists, so Shopee is asking to
see an integration Juli already runs — TikTok Shop — not a Shopee one.

TLS was verified on 2026-10-14: TLS 1.0/1.1 refused, HSTS `max-age=15552000`, `nosniff`,
SSL Labs **A+** on all four `app-juli.com` endpoints. No work remains there.

## Decisions

1. **The reviewer sees the live TikTok Shop integration; Shopee is presented as the integration
   being applied for.** No Shopee connection is built before approval.
2. **Sign-in is email + password** (Supabase `signInWithPassword`), enabled in production on
   `demo.app-juli.com`. It matches the username/password fields of Shopee's form and does not
   depend on Google's consent screen (#1971) or on Google accepting a foreign-IP login.
3. **The trial account reads Fujiwa Vietnam Store, masked** (aliased shop name and ids, real
   magnitudes — the existing ADR-038 mask), through the real TikTok read path.
4. **Approval and execution are simulated for the reviewer role, and never reach Fujiwa.** The
   approval flow and the "Thực hiện" step run end to end and show the change that would be sent,
   labelled as a trial-mode simulation. The guarantee is server-side: a reviewer session cannot
   reach any executor or write-capable credential, enforced at the API boundary and covered by a
   test that fails if any write call is issued for a reviewer session. Hiding buttons is not the
   guarantee.
5. **One reviewer account per platform, expiring.** E.g. `shopee-review@app-juli.com`, role
   `reviewer`, structurally pinned to the masked reference shop, default lifetime **30 days**
   (covers Shopee's 10–14 working-day review), renewable by an operator. Per-platform accounts give
   per-platform audit rows and independent revocation.
6. **Public pages state Shopee's status honestly and specifically.** The landing names Shopee in
   text (not only in an image) as "đang tích hợp qua Shopee Open Platform". `/privacy` and
   `/terms` replace the "in development" sentence with a Shopee section: which Shopee data Juli
   will process, why, retention, and adherence to Shopee's Data Protection Policy, effective when
   a seller connects a Shopee shop.
7. **The Services Information text is English prose plus numbered reviewer steps, no video**,
   versioned in the repo so later platform reviews reuse it. It describes Juli, the live TikTok
   Shop integration as the existing-integration evidence, what Juli will do with Shopee Open API,
   and the steps: sign in → masked reference shop → analysis → a recommendation → approve →
   simulated execution.

## Consequences

- Delivery: one epic, four issues — (a) email + password sign-in in production; (b) reviewer
  role, expiry, reference-shop pin and server-side simulated execution with the no-write test;
  (c) landing / privacy / terms Shopee copy; (d) Services Information text. Resubmission waits on
  all four.
- The reviewer sees Vietnamese UI; decision 7's numbered steps carry the navigation.
- Simulated execution is a second execution path that must stay visibly labelled; it must never
  be reachable from a seller session.
- Shopee features are promised publicly; copy must change again when the Shopee integration
  ships, and anything described in the form must match what the trial account shows (Rules §4).
- Juli must not crawl Shopee for any data (Rules §3), including competitor research.
