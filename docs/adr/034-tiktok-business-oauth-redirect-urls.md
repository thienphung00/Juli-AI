# ADR 034: TikTok Business OAuth redirect URL pair

**Status:** Accepted  
**Date:** 2026-07-23  
**Deciders:** grill-with-docs (Architect)  
**Related:** Shop OAuth at `/v1/auth/tiktok/callback`; Marketing API host in
`CONTEXT.md` (**Action executor**)

## Context

Juli already registers a TikTok **Shop Partner** OAuth redirect at
`https://api.app-juli.com/v1/auth/tiktok/callback`. Integrating the TikTok
**Marketing API** (`business-api.tiktok.com`) requires registering redirect URIs
in the TikTok for Business developer app. The portal exposes two distinct fields:

1. **Advertiser redirect URL** — ad account / Business Center consent.
2. **TikTok account holder redirect URL** — personal TikTok account consent
   (identity / posts scopes).

Options: (1) reuse the Shop callback for both Business fields; (2) one shared
Business callback for Advertiser + account holder; (3) two dedicated Business
paths under `/v1/auth/tiktok/business/…`.

## Decision

1. **Do not reuse** Shop `…/v1/auth/tiktok/callback` for Business OAuth (different
   app, host, and token exchange).
2. Register **two** production HTTPS callbacks on `api.app-juli.com`:
   - Advertiser:
     `https://api.app-juli.com/v1/auth/tiktok/business/callback`
   - Account holder:
     `https://api.app-juli.com/v1/auth/tiktok/business/account-holder/callback`
3. Prefer separate handlers and env vars
   (`TIKTOK_BUSINESS_REDIRECT_URI`,
   `TIKTOK_BUSINESS_ACCOUNT_HOLDER_REDIRECT_URI`) when implementation lands.

## Consequences

- Portal registration can proceed before route handlers exist; URLs are stable
  contracts.
- Changing a registered URI later requires TikTok app config updates and can
  break in-flight authorizations.
- Implementation must mount public (non-JWT) GET callbacks matching these paths
  exactly (no query/fragment in the registered URI).
