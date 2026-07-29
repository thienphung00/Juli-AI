# backend/src/juli_backend/services/tiktok

## Purpose

TikTok Shop **application services** — OAuth callback infrastructure, webhook
verify/dispatch/catalog routing, and signature verification. Distinct from
``juli_backend.integrations.tiktok`` (signed HTTP client + resources).

## Public Interface

Import from the package root only:

```python
from juli_backend.services.tiktok import TikTokWebhookService, ...
```

### Package facade (`__init__.py`)

Matches ``__all__`` — re-exports only:

- **Webhook routing** — ``ACCOUNT_LIFECYCLE_CHANNEL``, ``EVENT_CATEGORY_ROUTES``,
  ``resolve_ingest_channel``, ``should_handoff_to_etl``
- **Phase 2 catalog** — ``PHASE2_CATALOG``, ``PHASE2_CATALOG_IDS``,
  ``resolve_catalog_entry``
- **OAuth infrastructure** — ``TikTokOAuthInfrastructureService``
- **Webhook assembly** — ``TikTokWebhookDispatcher``, ``TikTokWebhookService``,
  ``TikTokWebhookSignatureVerifier``

## Dependencies

- ``juli_backend.integrations.tiktok`` — Partner API client types (via OAuth/verify paths)
- ``juli_backend.services.ingestion`` — ``HandoffFn`` contract for ETL handoff
- ``juli_backend.database`` — credential and shop persistence (OAuth callback wiring)
- No direct ETL transform imports — ingest channels are resolved and handed off upstream

## Related modules (internal)

- ``webhook_catalog.py`` — Phase 2 event registry (#1–#68 subset)
- ``webhook_handlers.py`` — workflow signals + account lifecycle side effects
- ``webhook_raw_log.py`` — ``RawWebhookEventRecorder`` + DB impl (#392)
- ``webhook_redaction.py`` — denylist PII redaction before archive
- ``oauth.py`` — ``build_tiktok_oauth_service``, ``complete_tiktok_oauth_callback``
- ``dispatcher.py``, ``signature.py``, ``schemas.py`` — webhook parse/verify helpers

## Owners

- domain: integrations (TikTok runtime)
- code: backend/src/juli_backend/services/tiktok/
