# ADR-084: The demo surface — its own tenant, tool-captured scenarios, honest executability

**Status:** Proposed
**Date:** 2026-08-25
**Deciders:** grill-with-docs (Architect) with owner

**Amends:** [ADR-076](076-agent-demo-execution-experience.md) decisions 1, 2 and 4.
**Builds on:** [ADR-074](074-agent-event-streaming-and-relay.md) (event union, replay
authority), [ADR-075](075-agent-approval-gate-and-security-prerequisites.md) (JWT on every
agent route), [ADR-082](082-agent-run-product-binding.md) (server-derived product binding),
[ADR-083](083-agent-concurrency-target-nfrs.md) T4 (polled progress read model).
**Design spec:** [`PUI-DESIGN.md`](../product/agent-workflow-execution/PUI-DESIGN.md) —
unchanged and still the wireframe, stage-model, motion and copy authority.
**Scope:** Phase P-UI / W6 of [`PLAN.md`](../product/agent-workflow-execution/PLAN.md).
PRD #1308.

## Context

ADR-076 settled the demo execution experience on 2026-08-12, before any of it had been
run against a deployed system. Between then and now, W3, W4 and W5 shipped and were each
walked against reality, and the walks contradicted four of ADR-076's premises. This ADR
records the corrections so W6 builds against what is true rather than against what was
reasonable in August.

Four findings drive it:

1. **The reference shop is a real merchant.** ADR-076 decision 1 pins the anonymous
   session's active shop to `DEMO_REFERENCE_SHOP_ID`, "structural, not a flag". On the
   deployed host that setting resolves to **Fujiwa Vietnam Store**, a live seller's
   production shop — which is how `GET /v1/demo/decisions` came to serve a real merchant's
   titles, descriptions, rationales and expected-impact figures to any unauthenticated
   caller (#1283, found while walking #1226). #1283 authenticated those routes and removed
   the structural pin. It did not answer where a visitor's data should come from.

2. **The "identical SSE endpoint" replay does not exist.** ADR-076 decision 2 specifies
   golden scenarios "replayed through the identical SSE endpoint, protocol, and client".
   No mechanism does that, and no scenario file format exists. The two event logs captured
   at the #1226 gate walk are raw operational output on a host, not artifacts.

3. **Every approval runs Optimize Product.** `services/agent/approval.py` pins the run's
   playbook to `OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key` regardless of the approved card's
   own `workflow_key`, and says so in a comment. Meanwhile the demo Decisions envelope
   deliberately withholds `workflow_key` under the no-PII/no-raw-payload discipline. So the
   client cannot tell which cards are agent-executable, and the server does not refuse the
   ones that are not — it substitutes.

4. **The stream carries internal machinery.** `ToolCompletedPayload.summary` reaches the
   browser with raw tool names, playbook keys and raw Pydantic error structures, and
   `ConfirmationOptionPayload.rationale` is set from `ToolSpec.description` — English prose
   written as an LLM tool-schema description — and shown to the seller as the reason Juli
   wants to change their price (#1272).

## Decision

1. **The demo gets its own seeded tenant.** ADR-076 decision 1's "active shop pinned to the
   reference shop" is superseded: the anonymous *Dùng thử Demo* session is scoped to a
   **demo tenant** — a shop that belongs to no live business and is not the sandbox-write
   shop — provisioned by an idempotent, committed seed rather than by hand on a host. Its
   action cards are seeded `active` **and surfaced**; its `workflow_key` resolves to a
   registered playbook; it holds no credential granting any write capability. With the
   setting naming it unset, the anonymous path **fails loudly**; falling back to the
   reference merchant is structurally forbidden, because that fallback is exactly how #1283
   happened. ADR-075 is otherwise untouched: the visitor's session is a real JWT for a
   distinct anonymous user, with per-session rate buckets, and every route stays
   authenticated.

   *Rejected:* re-pointing `DEMO_REFERENCE_SHOP_ID` at a non-merchant shop without a seed —
   it leaves the demo's content a property of one host's database, which is what made the
   #1226 walk a provisioning exercise. *Rejected:* a shared demo account — indistinguishable
   audit rows, already rejected in ADR-076 d.1 and still right.

2. **Scenarios are produced by a tool and replayed by the server.** A golden scenario is
   `{scenario_id, workflow_key, prompt_sha256, captured_at, events[], continuations{}}`,
   produced by a capture tool that sanitizes a real run's persisted `workflow_run_events`,
   and validated against the **shared event union** in `packages/contracts` — a scenario
   that does not validate fails CI. A demo run seeds those events as real
   `workflow_run_events` rows, so `GET /v1/demo/runs/{id}/events` serves them unmodified:
   same handler, same sequence semantics, same `Last-Event-ID` replay. Timestamps are
   rebased to now, recorded inter-event deltas are preserved, and answering a decision
   request appends that option's captured continuation. `prompt_sha256` on the scenario is
   what makes staleness after a prompt bump detectable by a command rather than by someone
   noticing.

   **Hand-authored event JSON is not an acceptable input** anywhere in this pipeline. The
   reason is the same one that deletes the localStorage mock: a second, hand-maintained
   source drifts from the first, and both suites stay green while they diverge. This is the
   defect class that produced six W3 post-merge fixes and the "every tool reached the model
   declared as taking no arguments" bug. A scenario needed for a test that the tool cannot
   yet produce is a gap in the tool.

3. **Executability is an explicit, non-leaking property of a decision.** Two halves.
   Server: approving a card whose `workflow_key` has **no registered playbook** is refused
   with a named 409 — never substituted with Optimize Product — and a card that does have
   one runs *its own* playbook, read from the registry. Client-facing: the Decisions
   envelope gains a discriminator saying whether Juli can carry this recommendation out
   itself, derived from the real playbook registry and **revealing no workflow taxonomy**;
   `workflow_key` stays absent from the envelope, preserving the discipline
   `_build_masked_item` already enforces.

   This makes the single-workflow constraint honest. It does **not** remove it: onboarding
   the remaining ten workflows stays P13/W10.

4. **The run ledger is a polled Postgres read model, not a stream.** `GET /v1/demo/runs`
   reads the same rows the event stream persists, per [ADR-083](083-agent-concurrency-target-nfrs.md)
   T4, so the list and any opened per-run stream cannot disagree — and a `queued` run, which
   has emitted no events, is still visible. An opened run uses the existing per-run SSE with
   replay, unchanged. A multiplexed per-shop stream stays deferred behind ADR-083 T4's own
   trigger.

5. **No internal identifier reaches the seller's browser.** Seller-visible text on the event
   path becomes seller-facing reason codes rendered as Vietnamese copy; tool names, playbook
   keys and validation-error structures are logged server-side and never enter
   `workflow_run_events.payload`. `ConfirmationOptionPayload.rationale` carries a
   seller-readable reason for the specific proposed change and stops being a tool-schema
   description. The invariant is asserted over a **real run's persisted event log**, not
   over a constructed payload. (#1272 is the slice; this decision is why it is in this wave
   rather than a later one — the option picker's entire job is rendering that field.)

6. **Card consumption is rendered, not hidden.** A completed run consumes its action card
   permanently; only a failed run reverts it (#1305, by design). The ledger and the Decisions
   list show that as it is, and the path to a new recommendation is a refresh. **No
   retry-in-place control exists**, asserted structurally — a new run requires a new
   approval by the approval gate's design, and a convenience button is the obvious way that
   gate gets bypassed.

## Consequences

- **The public demo becomes unbreakable and honest at the same time.** Replay means no
  external dependency at demo time; the seeded tenant means no live merchant's data is ever
  the thing on screen. Live mode stays one flag away and is exercised at the wave gate.
- **Re-capturing scenarios becomes a small maintained practice** — a command, keyed to
  `prompt_sha256`. ADR-076 anticipated this; decision 2 gives it a mechanism.
- **The demo is no longer a "no-backend" app.** `apps/demo/MODULE.md`'s invariants —
  including "Mock is the only enabled mode" and sign-in that "never routes or requests
  data" — are retired for these surfaces and must be rewritten in the same wave, not left
  contradicting the code.
- **Decision 3 makes a real product limitation visible rather than papering over it.** A
  seller will now be told Juli cannot execute ten of its eleven recommendations. That is the
  truth, and hiding it was worse: a seller approving a fulfillment card was getting a
  product optimization.
- **Decision 5 costs some diagnosability at the surface and must not cost it server-side.**
  The internal detail moves to logs keyed to the run; deleting it rather than relocating it
  would trade one honesty problem for another.
- **The product-binding gap stays open.** ADR-082 named product-scoped action cards as "a
  real W6 item". This ADR does not do it — it is a wave, not a slice, reaching scoring, the
  emission budget, the dashboard and the fixtures. W6 discloses the bound product at the
  product-snapshot stage instead, which is the disclosure ADR-082 decision 5 already relies
  on. Product-scoped cards remain scheduled work, unscheduled.

## Numbering correction

`082-agent-concurrency-target-nfrs.md` and `082-agent-run-product-binding.md` were both filed
as ADR-082, four days apart, and both are cited as "ADR-082" — the product-binding one from
code comments, migrations and the W5 parent cache, the concurrency one from
`system-design.md`. The concurrency ADR is renumbered to **083** in the same change that adds
this one, because the product-binding number is load-bearing in code and the concurrency
number is cited from two documents. An issue body saying "ADR-082" is otherwise ambiguous to
whoever reads it next, which in this repository is an executor with no way to ask.
