# ADR-116: Client data has its own lane, every use is gated by a recorded consent, and shared models never learn from a client without written opt-in

**Status:** Accepted (owner, 2026-10-26, grill D1–D9 = fast-track **D76**)
**Date:** 2026-10-26
**Related ADRs / decisions:** amends [ADR-115](115-point-in-time-training-data-and-per-shop-model-gate.md)
(dataset shop sets, model assignment scopes); ADR-112 (bronze, ingest jobs); ADR-114 (seller
consent for experiments — same consent table); ADR-089 (fleet work under RLS); ADR-086
(`juli_app` role, RLS); ADR-020 / ADR-030 (Secrets Manager via IAM Roles Anywhere); ADR-075
(`action_card_approvals`). Fast-track: D73 (reviewer sandbox constraints stay), D30.3 (lift-range
calibration). Grill log: [`docs/product/client-data-compliance/GRILL_LOG.md`](../product/client-data-compliance/GRILL_LOG.md).
Client commitments: `juli-client-ops/clients/ory/contract/phu_luc_02_nda.md` (NDA) and
`.../compliance/backend_handoff_nda_zdr.md` (C1–C12, T1–T14).

## Context

Juli signed (Ory, 2026-10) an NDA and a sub-processor list that commit it to: no buyer contact
data (C1); a recorded approval before every change to the shop, with parameters and approver (C2);
no training or fine-tuning on client data, even anonymised, without separate written consent (C3);
only listed sub-processors (C4, T14); access / approval logs and deletion evidence (C5); deletion
within 30 days of revocation (C7); OpenAI with listing content and aggregates only, `store=false`,
no stateful features, every call logged (C8); per-client model parameters are client data (C9).
Phase 2 (direct Shopee API) starts when the Shopee ISV application is approved.

What this branch has (head `f34827bd`, MIG head 102):

- **Raw payloads stored as received.** `services/etl/bronze_append.py:52` / `:87` (order / return
  bronze, called from `services/cdp_speed/targeted_fetch_bronze_handoff.py:128` / `:140`) and
  `services/ingest/gateway.py:208` (`ingest_raw_payloads`, the Juli Connector) store the platform
  body unfiltered. TikTok order detail carries recipient name / phone / address. Only webhooks are
  redacted (`services/tiktok/webhook_raw_log.py:118`). A PII key list exists but serves the demo
  mask only (`services/analytics_kpi_masking/mask.py:12`). `buyer_id` is the platform's raw id
  (`integrations/tiktok/mapping.py:33`, `:252`).
- **No consent record of any kind.** Nothing distinguishes public-market data (FastMoss, Apify,
  Metric.vn, Chrome) from a client's non-public data, and nothing asks whether a shop allowed a use.
- **Pooling paths exist.** ADR-115 datasets take a `shop_set` across shops and model assignments
  resolve by `category` / `shop_group`; `services/lever_flows/measurement.py::fleet_calibration_stats`
  averages `lever_calibrations` over every shop the session sees (a privileged session sees all).
- **OpenAI.** `services/agent/llm/openai_adapter.py` already sends `"store": False` and no
  `previous_response_id`; the key is one env var (`require_env("OPENAI_API_KEY")`, `:192`); no
  per-call log; no notion of client data.
- **Approvals.** `action_card_approvals` (`models/models.py:1289`) is schema only, with
  `approved_by_user_id` NOT NULL. `production_write_authorizations` / `production_write_audit`
  (`:1676`, `:1735`) are keyed by `tiktok_product_id`.
- **Production holds no non-public client data yet** (owner, 2026-10-26): Juli Ops
  (`ops.app-juli.com`) and the Connector hold public data only; Ory's phase 1 has not started.

## Decision

### 1. Two data lanes (D1, D2)

| | Public lane | Client lane |
|---|---|---|
| What | Anything scraped from public pages (FastMoss, Apify, Metric.vn, Chrome), **including a client's own public listing** (NDA Art. 1 excludes lawfully public information) | **Any non-public data of a client, however obtained**: platform API (TikTok Shop, Shopee), sub-account Seller Center exports, Connector posts, files the client sends |
| Where | Non-tenant tables (no `shop_id`), each row with `source`, `collected_at` | Tenant tables with `shop_id` and RLS (`TABLE_CLASSIFICATION_MAP`) |
| Shared model | Always allowed | Only for shops with `pooled_training` consent |

Fujiwa is a development exception: `pooled_training` granted; its existing data is the test bed
for the lane split.

### 2. One consent table, three scopes, channel recorded as evidence (D4)

New tenant-direct table `data_use_consents(id, shop_id, scope, method, terms_version,
evidence_ref, evidence_sha256, granted_by, granted_at, revoked_at)`; append-only for `juli_app`
except setting `revoked_at` once; one open row per (shop, scope).

| `scope` | Grants | Source of permission | Default |
|---|---|---|---|
| `service` | Analysis for that shop, its client layer (§3), KPI work | The contract or Terms of Service; no separate step | Granted with the contract / ToS acceptance |
| `llm_processing` | Sending that shop's listing text and aggregate metrics to OpenAI (§5) | Contract / Terms + approved sub-processor list or privacy policy | Granted when the client approves the list that names OpenAI |
| `llm_images` | Sending product images to OpenAI (image inspection) | Only a list / policy that names images | Self-serve: with the Terms (privacy policy names images). Ory v1: **not granted** |
| `llm_media` | Sending video / LIVE frames and audio to OpenAI (content analysis, transcription) | Only a list / policy that names them | Self-serve: with the Terms. Ory v1: **not granted** |
| `pooled_training` | That shop's data in shared models | Separate written opt-in | **Off** |

`method` ∈ {`contract_paper`, `in_app_click`, `email`}. A paper contract locks the in-app toggle
("theo hợp đồng"). One helper, `services/consent/check.py::require_consent(session, shop_id,
scope)`, is the only reader; it fails closed (no row, revoked, or lookup error → refused).

### 3. Public model + per-client layer (D3) — amends ADR-115

- **Public model**: trained on the public lane plus shops holding `pooled_training`. The ADR-115
  builder (`services/ml/dataset/builder.py`) filters `shop_set` through `require_consent(…,
  'pooled_training')` at build time and writes each shop's consent row id into the manifest.
  A manifest containing a shop without that consent fails the build (test).
- **Client layer**: the public model (pinned `base_model_version`) as starting point plus a
  correction fitted only on that shop's data, under `service` consent. Stored in tenant-direct
  tables with `shop_id`; served only to that shop; ADR-115 assignments with `scope_kind = shop`.
  `category` / `shop_group` assignments may serve **public models only**.
- **Fleet calibration**: `fleet_calibration_stats` aggregates only shops holding `pooled_training`;
  everyone else gets the prior or their own shop level (D30.3 unchanged otherwise).
- **Ops console (D11)**: monitoring and measuring **one shop with its own data** is `service`.
  Any figure **pooled across shops** — the card-group lift EB prior (`ops_group_lift_draws()` →
  `apply_pooled_eb` / `estimate_prior`), the D30.3 fleet factor, statistics used to refine shared
  features — reads only shops with `pooled_training`; other shops fall back to their own data.
  Juli's own operating figures (OpenAI cost, run counts) are not client data.
- **Withdrawal**: consent revoked → serving falls back to the public model at once; the client
  layer, its features and predictions are deleted with the shop's data (offboarding, T8) within
  30 days, and the deletion certificate names the layer version deleted. The public model is never
  retrained because of a withdrawal — it never saw that client.
- A new public model version does not silently move client layers: each stays on its
  `base_model_version` until refitted.

### 4. Buyer data never lands (D5, D8)

- A field **allowlist** per (`platform`, `endpoint`) — `services/privacy/payload_allowlist.py` —
  applied before every raw write: the bronze handoff (order, return), the ingest gateway, and every
  future platform adapter. Anything not listed is dropped at any depth. Buyer name, phone, address,
  email and messages are never listed.
- `buyer_id` is stored as `HMAC-SHA256(shop_key, buyer_id)` in bronze and silver alike, so
  within-shop joins (repeat buyers, `ai/anomaly`) still work and ids cannot be linked across shops
  or back to the platform. Per-shop random keys live in tenant table `shop_pseudonym_keys`
  (migration 104), Fernet-sealed with a key derived from the existing token-encryption secret for
  this purpose only (the VPS role is read-only in Secrets Manager, so per-shop secrets there are
  not possible); deleting the row at offboarding makes the ids permanently anonymous.
- A one-off operator command (`python -m juli_backend.services.privacy.payload_cleanup`, dry run
  then `--apply`; a data change cannot be a `versions/` migration under the additive deploy gate)
  removes non-allowlisted fields from stored payloads and re-keys `buyer_id`, printing row counts
  per table. An unknown (platform, endpoint) is refused, never stored.
- The ingest gateway also requires `service` consent before accepting a post. No client shop pairs
  the Connector before the client approves a sub-processor list that covers Supabase / Hetzner for
  that phase (T14).

### 5. OpenAI through one gate; the backend has one project (D6, revised 2026-10-26)

- Every backend OpenAI call carries shop data (agent runs, image inspection, content-analysis
  media and scoring, content card drafts), so the backend uses **one** OpenAI project,
  `juli-client-data`, with one restricted service-account key (permission: Model capabilities
  only; Threads, Files, Vector Stores, Batch, Fine-tuning, Evals off; model allowlist
  `gpt-5.4-nano`, `whisper-1`). Its key is the existing `OPENAI_API_KEY` field of
  `juli/api/production`, delivered by `fetch-secrets.sh` / `refresh-secrets.sh` like every other
  secret: rotation = edit the secret, the daily refresh restarts the API. No per-client keys, no
  key routing in code. The previous project is research-only (`~/.juli-sim.env`), never on the
  server.
- Per-client usage comes from Juli, not OpenAI (OpenAI splits by project / key / model only):
  `llm_call_log` per call, priced with the model table; the monthly per-project token total must
  reconcile with OpenAI's figure for `juli-client-data` (a gap = a call bypassed the gate). The
  existing per-shop cap (`services/shop_rules/openai_cap.py`, D25.8) stays.
- All four call paths go through one gate (today `vision.py` and `content_analysis/openai_media.py`
  call OpenAI directly). A request carrying a `shop_id` is sent only if
  the consent for its input passes (`llm_processing` for text, `llm_images` for images,
  `llm_media` for frames / audio — checked per input, so a text-only grant blocks `vision.py` and
  transcription), the body was built by the T3 allowlist (listing
  content, attributes, aggregates, media of the shop's own listings; no shop name / id,
  `buyer_id`, credentials), and `store=false`, no `previous_response_id`, no `background`.
  Otherwise refused.
- The gate writes append-only `llm_call_log(shop_id, purpose, model, endpoint, project,
  input_tokens, output_tokens, request_id, created_at)` — metadata only, no prompt or output;
  no `UPDATE` / `DELETE` for `juli_app`.
- CI rule: no call to `files`, `vector_stores`, `assistants`, `threads`, `conversations`,
  `batches`, `fine_tuning`, `evals`.
- **ZDR is deferred** (owner, 2026-10-26). Until OpenAI approves it for `juli-client-data`,
  OpenAI's abuse-monitoring retention (up to 30 days) applies, as the sub-processor list sent to
  Ory already states. When requesting it, confirm whether `whisper-1` transcription is covered.
- A future per-client project (an enterprise asking for its own ZDR or residency) is a routing
  table `shop → project`; not built now.

### 6. Shop writes need the client's own click (D7)

- An approval is an `action_card_approvals` row by a user who belongs to that shop
  (`approved_by_user_id` stays NOT NULL; checked in the service, not only by RLS). There is no
  operator-recorded approval path.
- The executor writes only when an approval matches the card's before / after values exactly
  (hash of `card_snapshot`), is younger than 72 h, and a read-back immediately before the write
  still equals the "before" value. Anything else is refused and logged in `production_write_audit`.
- `production_write_authorizations` / `production_write_audit` move from `tiktok_product_id` to
  `platform` + `platform_product_id`.
- Phase 1: Juli does not write to the client's shop; the client executes in Seller Center and the
  change is attributed `seller_change`. D73 reviewer constraints are unchanged.

## Consequences

- Phase 2 can start the day ISV is approved without a C1 / C3 / C8 breach on the first sync.
- Answering "which models contain shop X" is one query (manifests list consent row ids; client
  layers carry `shop_id`).
- Shared models learn only from public data and Fujiwa until a client opts in; early public-model
  quality is bounded by public data. Accepted.
- Fleet calibration loses other shops' readings until they opt in. Accepted (today it is one shop).
- Every new platform adapter, ingest path or LLM call site must go through §4 / §5; a raw write or
  LLM call that bypasses them is a review failure.

## Delivery (D9)

PRs on `fasttrack/optimize-product`, each from its own `fasttrack/nda-*` branch, migrations after
102, none merged before the owner deploys P68:
(1) this ADR + grill log → (2) `data_use_consents` + `require_consent` → in parallel
(3) allowlist + HMAC + clean-up migration (§4), (4) OpenAI gate on all four call paths + `llm_call_log` (§5),
(5) approvals (§6) → (6) fleet calibration (§3), then the Ops pooled-prior filter (migration 107).
Access log (T6) and offboarding with deletion certificates (T8) follow in a second wave.

## Verification

- Allowlist: a captured TikTok order fixture with recipient fields → stored bronze, silver and
  ingest rows contain none of them at any depth; `buyer_id` equals the HMAC.
- Consent: no row / revoked row → `require_consent` refuses; LLM request for that shop makes zero
  HTTP calls; dataset build excludes the shop; fleet calibration ignores it.
- OpenAI: every request body has `store: false`, no `previous_response_id`, no `background`;
  a shop request with only the internal key set makes zero HTTP calls; one `llm_call_log` row per
  call.
- Approvals: missing, expired, mismatched or non-member approval → refused and audited; a changed
  read-back → refused.
- Withdrawal: deleting a shop's client layer → that shop is served by the public model.
