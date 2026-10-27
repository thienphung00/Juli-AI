# backend/src/juli_backend/services/consent

## Purpose

Per-shop data-use consent (ADR-116 §2, fast track D76; migration 103, model
`models/consent.py`, repository `repositories/consent.py`). Records what each shop
allowed Juli to do with its non-public data, and answers "may we?" for every gate
that touches client data. The answer fails closed.

## Scopes

| `scope` | Allows | Where the permission comes from |
|---|---|---|
| `service` | Analysis for the shop, its own client layer, KPI work | The contract or Terms of Service |
| `llm_processing` | Sending the shop's listing text and aggregate metrics to OpenAI | Contract / Terms + the approved sub-processor list or privacy policy naming OpenAI |
| `llm_images` | Sending product images to OpenAI (image inspection) | Only where the approved list / privacy policy names images |
| `llm_media` | Sending video / LIVE frames and audio to OpenAI (content analysis, transcription) | Only where the approved list / privacy policy names them |
| `pooled_training` | The shop's data in shared models | A separate written opt-in; off unless granted |

`method` (`contract_paper`, `in_app_click`, `email`) records the channel as evidence.

## Public API

```python
from juli_backend.services.consent import (
    ConsentRequired, InvalidConsent, grant_consent, has_consent, require_consent, revoke_consent,
)
from juli_backend.services.consent.terms import grant_terms_consents  # and the two wrappers below
```

All run on the caller's session and transaction (nothing commits) and need a session
scoped to the shop (`with_shop_scope`); under RLS a mis-scoped session sees no grant.

| Function | Does |
|---|---|
| `require_consent(session, shop_id, scope)` | The open grant, or `ConsentRequired` (no grant, revoked, unknown scope, failed lookup) |
| `has_consent(session, shop_id, scope)` | `bool` form of the above |
| `grant_consent(session, shop_id, *, scope, method, terms_version, evidence_ref, granted_by, evidence_sha256=None, granted_at=None)` | Records a grant; `InvalidConsent` on a bad vocabulary value, blank field, malformed hash, or an already-open grant |
| `revoke_consent(session, shop_id, scope, *, revoked_at=None)` | Closes the open grant; `InvalidConsent` when there is none |

## Terms acceptance grants consent (D10)

`terms.py`. Accepting the Terms in the app grants, for every shop the seller owns,
`service`, `llm_processing`, `llm_images`, `llm_media` (never `pooled_training`):
method `in_app_click`, `terms_version` = the accepted legal text's date
(`2026-10-18`), `evidence_ref` = `users.terms_accepted_at:<user id>`, `granted_by` =
the user id (no contact detail), `granted_at` = the acceptance instant.

| Function | Does |
|---|---|
| `grant_terms_consents(session, user_id, shop_ids, *, accepted_at, terms_version, write=True)` | The four scopes per shop; skips a scope already open; `write=False` only counts |
| `grant_terms_consents_for_owned_shops(session, user_id, *, accepted_at, terms_date)` | Every shop the user owns (read under their user scope) |
| `grant_terms_consents_if_accepted(session, user_id, shop_ids)` | Only when the owner has `terms_accepted_at` and `terms_date_accepted` |

Each shop's writes run in a SAVEPOINT under `with_shop_scope`; the rollback also
restores the caller's tenant GUCs. A failure is logged as `consent_terms_grant_failed`
(shop id + error type only) and never raised -- the `card_events` writer's shape --
so acceptance and connect always succeed; a shop left without a grant fails closed and
the next `backfill-terms` run picks it up.

## Callers

| Caller | Calls |
|---|---|
| `services/privacy/prefs.record_consent` (`POST /v1/me/consents`) | `grant_terms_consents_for_owned_shops` |
| `services/tiktok/oauth.complete_tiktok_oauth_callback` (seller connect, signed state) | `grant_terms_consents_if_accepted` for the connected shop, before the commit |
| `cli.py` | below |

ADR-116 delivery: PR 4 (done) is the OpenAI gate `services/llm_gate` (`open_gate`
reads `llm_processing`, `llm_images`, `llm_media` through `has_consent`, once per run
leg / analysis / draft; each request needs the scope of every input kind it carries).
Still to come: PR 3 (ingest gateway, `service`), PR 6 (dataset builder,
`pooled_training`). The stateless app-review connect (non-production only) grants nothing.

Ops pooled prior (D11, migration 107): `ops_group_lift_draws()` reads the open
`pooled_training` rows of every shop inside its SECURITY DEFINER body (the only
cross-shop reader of this table; it returns draws, never grants); the Ops groups route
asks `has_consent(..., "pooled_training")` for the viewed shop.

## Operator CLI

Dry run by default (writes nothing, prints what it would do); `--apply` writes.
`DATABASE_URL` must be a role that is a member of `juli_ops` (the app runtime role is).

```bash
# Sellers who accepted the Terms before D10 shipped (idempotent; counts only):
python -m juli_backend.services.consent.cli backfill-terms
python -m juli_backend.services.consent.cli backfill-terms --apply

# A contract client, one shop (--scope repeats; an open scope is skipped):
python -m juli_backend.services.consent.cli grant --shop-id <shop uuid> \
    --scope service --scope llm_processing --scope llm_images --scope llm_media \
    --scope pooled_training --method contract_paper --terms-version <contract version> \
    --evidence-ref <contract file name> --evidence-sha256 <sha256 of the scan> \
    --granted-by "<signatory>" --granted-at 2026-10-24T09:00:00 --apply

# A withdrawal:
python -m juli_backend.services.consent.cli revoke --shop-id <shop uuid> \
    --scope pooled_training --apply
```

`backfill-terms` enumerates shops with the existing `ops_list_shops()` (SECURITY
DEFINER, EXECUTE to `juli_ops`, ADR-089 decision 3) under `ops_role`, reads each owner
under their user scope and writes each shop under its own scope -- no new migration.
One transaction per owner; exit 1 when any shop or owner failed. `grant` exits 2 and
writes nothing on a malformed request.

## Invariants

- At most one open grant per (shop, scope) — partial unique index.
- `juli_app` may UPDATE only `revoked_at`, only on an open row; no DELETE. Rows go with
  the shop (privacy purge).
- Timestamps are naive UTC (`repositories/_base.py`).
