# ADR-098: Onboarding is a stage-keyed first-time layer over the surfaces every workflow already shares

**Status:** Proposed
**Date:** 2026-09-08
**Deciders:** grill-with-docs (Architect) with user

**Builds on:** [ADR-094](094-demo-surface-splits-anonymous-replay-and-signed-in-runs.md) (two doors, Google-only identity, replay for
the demo door), [ADR-055](055-decision-plan-review.md) (card anatomy), [ADR-087](087-subject-scoped-action-cards-and-card-revisions.md)
(subject-scoped cards), `PLAN.md` §14 "Common workflow structure — identical UX, per-case internals",
`v1-workflow-spec.md` S-FR-1 (the seven identical surfaces) and S-NFR-11 (v1 done = a real connected
seller end to end).
**Supersedes, for the demo app:** the onboarding wizard in
[`docs/product/design/Flows/home/onboarding.md`](../product/design/Flows/home/onboarding.md) (a
shop-connection wizard with an autonomy-mode question) and the `empty.decisions.waiting_data` copy
promising first recommendations "trong vòng 24 giờ".
**Does not decide:** sign-in (deferred by the owner until the W6 UI lands — see Open questions),
the TikTok connect step's permissions copy, or the bootstrap pipeline itself (ADR-050 C2, #1365).
**Wave:** W10 or W11, placed by the owner once the W6 UI is visible.

## Context

**The objective, as the owner stated it (2026-09-08):** onboarding must help a seller understand
Juli's core feature, guide them through a seamless first interaction with the agent, and get them to
the moment where they see the impact of their first workflow. It must be **dynamic** — not tied to
any one workflow, because different sellers see different first cards — **cheap to implement**, and
**identical for the demo visitor and the connected seller**.

**What exists.** On `feature/agent-w6-wave`, #1319 shipped the two-door landing, Google sign-in,
the auth callback and a connect-shop screen with a disabled button. `main` still carries the
mock-only demo. The plan-review card is built and matches ADR-055; the confirmation sheet, run view,
completion message, notification centre and deadline list are W9-D work; the per-act record and
tracked checklist items are W9-A (#1712, #1713). For a connected seller, OAuth → first data does
not fire today: the callback provisions the shop and stops, the polls are gated to the reference
shop's credential, and the designed seven-day bootstrap (first cards in ≈ 6–8 minutes, ≈ 55 vendor
calls) is unbuilt with no status surface.

**Why a workflow-specific onboarding is the wrong shape.** Every workflow runs the same five stages
(monitoring → card and approval → run with one confirmation and one write → close-out → measure) on
the same seven surfaces; only the content differs. The card already carries the workflow-specific
explanation (situation, evidence, proposed change, tied metric). An onboarding keyed on the
**stage** the seller is meeting for the first time needs no knowledge of which workflow produced
the card, adds no workflow-specific screens, and stays correct as workflows are added.

**Reference patterns** were selected through the Mobbin MCP (layout and flow only; colour and
copy come from `packages/theme` and `dictionary.md`): anchored coach marks with a step counter
([My BMW](https://mobbin.com/flows/c329076f-a46e-4ec7-9078-eda8f57a4e82),
[monday.com](https://mobbin.com/flows/d35a64a4-8d5e-41f8-8656-c881c7b0b923)); a collapsible
setup card with struck-through done rows and the next row expanded
([monday.com home](https://mobbin.com/screens/17658b1b-2a5e-4f8e-a4e9-dfcf1523cd7f),
[Linktree setup checklist](https://mobbin.com/screens/81665091-4921-4301-8526-abc5c80149af),
[Cleo next steps](https://mobbin.com/screens/c4c792f5-88dc-4698-905b-30c3f538380a)); a one-sheet
feature intro with icon rows and one button
([Forest Time Guard](https://mobbin.com/flows/ed6a3e2b-f598-47cf-a596-0a2c966474ad)); a live
sync-step list over a dimmed preview
([Origin](https://mobbin.com/screens/0a3297f4-b800-471a-a2bc-8236974a31ac),
[Monarch](https://mobbin.com/screens/33fc9bf6-cf4c-46f2-be9d-6373759dc721)). Rejected patterns:
multi-screen personalisation quizzes (Numo, Tiimo, Matter), fake progress percentages (Evernote,
Noom), and setup to-do lists that ask for chores (Strava).

## Decisions

1. **Onboarding is a first-time layer keyed on the five stages, not on any workflow.** The layer
   knows only which of the five stages the seller has met. It renders on the existing surfaces and
   adds no surface of its own. The workflow-specific content comes from the card. *Rejected:* a
   scripted onboarding around one workflow (cannot replay for a seller whose first card is a
   different workflow; goes stale with every new workflow); a static tour before the first list
   (teaches from pictures, skipped).

2. **Five stage explainers, one sentence each, shown once.** Anchored strips on: the decision list
   ("Juli đã theo dõi shop và tìm thấy việc này; chưa có gì xảy ra cho đến khi bạn phê duyệt"), the
   plan review ("đây là việc Juli sẽ làm và lý do; bạn phê duyệt hoặc chỉnh số"), the confirmation
   sheet ("đây là thay đổi duy nhất; xác nhận hoặc không thực hiện, không gì khác thay đổi"), the run
   view ("Juli đang thực hiện; bạn có thể huỷ bất cứ lúc nào"), and the completion message ("xong;
   kết quả sẽ có sau 7 ngày, Juli sẽ báo"). Each carries a "bước n/5" counter against the stages,
   not against screens, and is dismissed by the tap that advances the stage. No Back/Next chain
   across screens: the seller reaches stages in their own order and time. Final copy lands in
   `dictionary.md` (ADR-028) before implementation; the strings above are placeholders for grilling.

3. **A setup card on the first non-empty list is both the "start here" marker and the progress.**
   One collapsible card above the list: five rows for the five stages, met rows struck through, the
   current row expanded with one line and a button that scrolls to the **first card in the list's
   own ordering** (by deadline where the workflow has one, else basis recency). The card disappears
   when all five stages are met. The fifth row stays open after the write — "kết quả đầu tiên sẽ có
   sau 7 ngày" — and is struck through by the first impact-reading act record. *Rejected:* a task
   checklist (asks for chores; the rows here are stages the seller passes through by using the
   product).

4. **"What Juli does" is one sheet of five rows, shown once, on both doors.** Icon, verb phrase, one
   grey line per stage — theo dõi, đề xuất, bạn phê duyệt, Juli thực hiện, bạn thấy kết quả — and a
   single button into the first list. It states the core feature in the vocabulary the rest of the
   app uses. *Rejected:* preference questions before the first list; the design package's
   autonomy-mode question, which contradicts v1 (no autonomy).

5. **The impact moment is an act record, not a screen.** The first impact-reading record in the
   notification centre (W9-A #1713) closes the fifth stage; the demo door's replayed scenario
   carries its reading, so the same closure fires on replay. Nothing new is built for it.

6. **The connected seller's empty first list is a live three-step list fed by real bootstrap
   status.** Rows: kết nối shop, đọc sản phẩm và đơn hàng, chuẩn bị đề xuất đầu tiên — each done,
   in progress or pending, over a dimmed preview of the list. A step turns done only when the
   corresponding job finishes. This is the layer's **one backend dependency**: a small per-shop
   bootstrap-status record written by the backfill and the polls as they progress and read by the
   app; it lands with the bootstrap itself (ADR-050 C2, #1365 family), not as UI work. The
   24-hour promise in `empty.decisions.waiting_data` is retired. The demo visitor never sees this
   state. *Rejected:* a static "we are reading your shop" notice (a promise, not a status; leaves
   the seller with an empty screen and no reason to wait).

7. **Same layer, both doors.** The demo visitor and the connected seller run identical code; the
   replayed scenario and the seller's own shop are the two data sources under the same surfaces,
   as everywhere else in the app.

8. **Seen-state lives in the browser in v1.** Five booleans in browser storage, per device, for
   both doors; a connected seller's stages may move to the per-act record later if cross-device
   continuity is wanted. Rendering must be correct with no stored state (first visit) and when
   storage is unavailable.

9. **Cost envelope.** Five strips, one card, one sheet, one hook over five booleans, roughly eight
   dictionary entries, and the bootstrap-status read. No new surface, no workflow-specific screen,
   nothing that changes when a fifth workflow arrives.

## Rationale

*Extracted during the W6→main reconcile to satisfy `check_adr`, which requires a
`## Rationale` heading (#1853). Nothing below is new reasoning — it summarises what
this ADR already argues in the section named, which remains the fuller account.*

From **Context**, quoting the objective as the owner stated it (2026-09-08):
onboarding must help a seller understand Juli's core feature, guide them through
a seamless first interaction with the agent, and get them to the moment where
they see the impact of their first workflow. The three constraints that follow —
**dynamic** (not tied to one workflow, because different sellers see different
first cards), **cheap to implement**, and minimal — are what select a stage-keyed
layer over a scripted tour.

## Consequences

- **UI slices (W9-D or the onboarding wave):** the explainer strip component with a stage counter;
  the setup card; the feature sheet; the seen-state hook; the empty-list step list bound to the
  status endpoint; dictionary entries. All mount on surfaces W9-D builds; none may add a surface
  (S-FR-1).
- **Backend:** one bootstrap-status record per shop and its read endpoint, delivered with the
  bootstrap (ADR-050 C2). Until it exists, the connected seller's empty list shows the three rows
  with only the first ("kết nối shop") done — honest, and visibly incomplete.
- **Copy:** `empty.decisions.waiting_data` retired; the five explainers, the five sheet rows, the
  three bootstrap rows and the setup-card lines enter `dictionary.md` first.
- **Design package:** `Flows/home/onboarding.md` is superseded for the demo app by this ADR; the
  autonomy-mode question is removed; the Mobbin references above are the layout authority for the
  four components.
- **Common structure:** the layer instantiates no stage of its own; it annotates the five. Its
  instantiation row in `PLAN.md` §14 reads: subject none; trigger first render of each surface;
  deterministic rule none; write none; suspended no; guards seen-state only; measure the five
  stage-met timestamps per seller (an execution-quality fact, not an impact reading).

## Open questions (deferred by the owner)

- **Sign-in and connect**, revisited when the W6 UI lands: which branch is the base (the wave carries
  #1319); how the demo host reaches `/v1/*` at all (the vhost proxies nothing to the API and a test
  forbids it); who provisions the users row on first Google sign-in (401 today, unowned); whether
  launch includes a working TikTok connect (needs an authenticated OAuth-start route, seller-credential
  consumption #1365, and the bootstrap); the Seller/Affiliate mode gate (recommended out); the design
  package's login flow (dashboard-targeted, email/OTP); implicit grant vs PKCE; publishing the Google
  consent screen (needs privacy and terms pages).
- **Wave placement:** W10 or W11, by the owner after seeing the W6 UI.
