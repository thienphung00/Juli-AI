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
- **Poll-cycle vendor resources (#1949)** — ``build_fujiwa_poll_vendor_resources``:
  the seam the beat task calls at this package root instead of reaching across
  a forbidden import-boundary edge itself (see poll_resources.py's docstring)
- **Credential binding (#1995)** — ``make_binding_verifier``: builds the binding
  verifier the OAuth service checks a token's real shop identity with.
  Re-exported here because services/action_cards/refresh.py consumes it and was
  reaching the credential_binding leaf module by deep import. Lazy, like the
  entry above: that leaf imports juli_backend.core.security at its own top level

### OAuth callback surface (``oauth.py``, consumed by ``api/routes/auth_tiktok.py``)

Documented here, and removed from the check_module_drift known-drift allowlist, as
part of #1963's burn-down. These have been the route's real public surface since the
route existed; leaving them undocumented made check_module_boundaries — which has no
allowlist of its own — report five "cross-module import outside public surface"
violations for any PR that touched api/routes/auth_tiktok.py, verified against
origin/main content on 2026-09-20.

- ``build_tiktok_oauth_service() -> TikTokOAuthInfrastructureService`` — constructs the
  callback service from ``TIKTOK_APP_KEY``/``TIKTOK_APP_SECRET`` and the base-URL
  overrides
- ``complete_tiktok_oauth_callback(session, *, code, state=None, ...) -> TikTokOAuthCallbackResult``
  — exchanges the authorization code and persists shop + credentials through the Auth
  facade. A missing state is refused in production (#1748); a present state binds the
  shop to the user it names and can never reach the app-review row (#1970)
- ``TikTokOAuthCallbackResult`` — the callback response model (``schemas.py``)
- ``TikTokOAuthNotConfiguredError`` — raised when the OAuth environment is incomplete;
  the route answers 503
- ``TikTokOAuthTokenExchangeFailed`` — raised when TikTok rejects the code exchange;
  the route answers 502
- ``access_token_expires_at(expires_in)`` — the single place an
  ``access_token_expire_in`` becomes a stored timestamp (``token_expiry.py``); consumed
  by the Auth facade when it writes a credential

### Seller-initiated connect (``oauth.py``, issue #1970)

The half of the TikTok handshake a signed-in seller starts. ADR-094 decision 3 named
it as the follow-up that makes real runs on a seller's own shop possible; before it,
``GET /v1/auth/tiktok/start`` returned 404 in production and no seller could connect.

- ``begin_tiktok_oauth(user_id, *, oauth_service=None) -> TikTokOAuthStartResult`` —
  starts a connect for an ALREADY-AUTHENTICATED user. Seals that user id into a
  signed, flow-scoped, TTL-bounded OAuth state and returns the Partner authorize URL
  carrying it. The id must come from the verified JWT: it is the only writable input
  to the ownership claim the callback later honours
- ``TikTokOAuthStartResult`` — the ``authorize_url`` + ``state_expires_in`` response
  model (``schemas.py``). The state is never echoed as a separate field; a second
  copy is a second place for it to leak
- ``resolve_seller_connect_owner(state_user_id) -> UUID`` — the fail-closed owner
  resolver. It MUST NEVER fall back to the shared app-review row (a real user,
  default 00000000-0000-4000-8000-000000000001). The line it replaced bound every
  stateless connect to that one row, so with several trial sellers one seller's shop
  landed under another's owner — and provisioning then locks the rightful owner out
  permanently with "already connected to another account". Raises ``Unauthorized``
  rather than inventing an owner: an unbound connect is retryable, a mis-bound one
  is not
- ``tiktok_redirect_uri() -> str`` — the single reader of TIKTOK_REDIRECT_URI, shared
  by the authorize URL and the callback facade. TikTok rejects the code exchange if
  the two disagree

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
