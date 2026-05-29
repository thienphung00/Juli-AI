# Module: web

## Responsibility
Next.js web dashboard for the Juli platform. Provides Vietnamese-language UI
for TikTok Shop sellers: phone-OTP login, homepage with GMV/livestream/AI
modules, orders management with filtering and shipment confirmation.

## Public Interface
- `/login` — Phone-OTP login screen (Vietnamese phone format)
- `/mode-select` — Post-login workspace gate (Seller vs Affiliate); skipped when mode is persisted
- `/` — Homepage dashboard (GMV counter, livestream feed, AI recommendations, inventory risk)
- `/trends` — Trends discovery hub (MVP placeholder; full UI in later issues)
- `/operation` — Operations hub (MVP placeholder)
- `/ai-chat` — Juli AI chat tab (MVP placeholder)
- `/alerts` — Legacy; 301 → `/` (alerts in header drawer + Home cards)
- `/orders` — Legacy; 301 → `/operation`
- `/products` — Legacy; 301 → `/trends`
- `/inventory` — Inventory depletion forecasts, reorder recommendations per SKU
- `/livestreams` — Livestream session list with metrics summary and 0–100 performance grade
- `/creators` — Creator GMV attribution and commission efficiency scorecards
- `/recommendations` — Recommendations feed with Vietnamese message + confidence + one-tap CTA

## Dependencies
- `api` (read-only) — consumes `GET /v1/shops`, `GET /v1/shops/me`, orders endpoints
- `auth` (read-only) — login uses Supabase phone-OTP flow via API endpoints (not direct Supabase client calls from browser)

## Stack
- Next.js 14 (App Router)
- TypeScript
- Tailwind CSS
- Vietnamese locale (VND ₫ formatting, diacritics, ICT timezone)

## Invariants
- Workspace mode (`seller` | `affiliate`) is persisted in `localStorage` (`juli_workspace_mode`) and drives the `dark` class on `<html>` (Seller=dark, Affiliate=light)
- Auth MUST go through the API layer — no direct Supabase client calls from the browser
- All UI text in Vietnamese with proper diacritics
- Currency formatted as VND (₫) with thousands separators
- Mobile-responsive with single-thumb operation patterns
- Empty states rendered gracefully when API returns no data
- Pages load within 2 seconds (measured via Core Web Vitals)

## Owners
- domain: web
- code: web/
