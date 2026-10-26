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
```

All run on the caller's session and transaction (nothing commits) and need a session
scoped to the shop (`with_shop_scope`); under RLS a mis-scoped session sees no grant.

| Function | Does |
|---|---|
| `require_consent(session, shop_id, scope)` | The open grant, or `ConsentRequired` (no grant, revoked, unknown scope, failed lookup) |
| `has_consent(session, shop_id, scope)` | `bool` form of the above |
| `grant_consent(session, shop_id, *, scope, method, terms_version, evidence_ref, granted_by, evidence_sha256=None, granted_at=None)` | Records a grant; `InvalidConsent` on a bad vocabulary value, blank field, malformed hash, or an already-open grant |
| `revoke_consent(session, shop_id, scope, *, revoked_at=None)` | Closes the open grant; `InvalidConsent` when there is none |

## Callers (ADR-116 delivery)

None yet in this PR. PR 3 (ingest gateway, `service`), PR 4 (OpenAI gate: `llm_processing` for text, `llm_images` for `vision.py`, `llm_media` for
`content_analysis/openai_media.py`), PR 6 (dataset builder and fleet calibration, `pooled_training`).

## Invariants

- At most one open grant per (shop, scope) — partial unique index.
- `juli_app` may UPDATE only `revoked_at`, only on an open row; no DELETE. Rows go with
  the shop (privacy purge).
- Timestamps are naive UTC (`repositories/_base.py`).
