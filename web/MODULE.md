# Module: web

## Responsibility
Next.js web dashboard for the Juli platform. Provides Vietnamese-language UI
for TikTok Shop sellers: phone-OTP login, homepage with GMV/livestream/AI
modules, orders management with filtering and shipment confirmation.

## Public Interface
- `/login` — Phone-OTP login screen (Vietnamese phone format)
- `/` — Homepage dashboard (GMV counter, livestream feed, AI recommendations, inventory risk)
- `/orders` — Orders list with status filtering, date range picker, one-tap shipment confirmation
- `/products` — Product revenue ranking with velocity indicators (acceleration/deceleration)
- `/inventory` — Inventory depletion forecasts, reorder recommendations per SKU
- `/livestreams` — Livestream session list with metrics summary and 0–100 performance grade
- `/creators` — Creator GMV attribution and commission efficiency scorecards

## Dependencies
- `api` (read-only) — consumes `GET /v1/shops`, `GET /v1/shops/me`, orders endpoints
- `auth` (read-only) — login uses Supabase phone-OTP flow via API endpoints (not direct Supabase client calls from browser)

## Stack
- Next.js 14 (App Router)
- TypeScript
- Tailwind CSS
- Vietnamese locale (VND ₫ formatting, diacritics, ICT timezone)

## Invariants
- Auth MUST go through the API layer — no direct Supabase client calls from the browser
- All UI text in Vietnamese with proper diacritics
- Currency formatted as VND (₫) with thousands separators
- Mobile-responsive with single-thumb operation patterns
- Empty states rendered gracefully when API returns no data
- Pages load within 2 seconds (measured via Core Web Vitals)

## Owners
- domain: web
- code: web/
