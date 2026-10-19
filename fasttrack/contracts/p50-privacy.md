# P50 — privacy API contract (D68)

Backend (P50-B) and demo (P50-U) build against this. Change it here first, then both sides.

## Current legal text date

`LEGAL_TERMS_DATE = "2026-10-18"` — the date of the D68 `/terms` + `/privacy` text.
- Backend: `juli_backend/services/privacy/terms.py` constant.
- Demo: `apps/demo/src/lib/privacy/legal.ts` constant (same value; a test in each side pins it).
When the legal text changes, bump both.

## Endpoints (all under `/v1`, authenticated seller; scoped by `users.id`)

### `GET /v1/me/privacy` → 200

```json
{
  "marketing_opt_out": false,
  "ad_measurement_opt_out": false,
  "case_study_opt_in": false,
  "terms_date_accepted": "2026-10-18",        // null if never accepted
  "terms_accepted_at": "2026-10-18T03:00:00Z", // null
  "liability_clause_accepted_at": "…",         // null
  "current_terms_date": "2026-10-18",
  "needs_terms_acceptance": false,             // terms_date_accepted != current_terms_date or liability null
  "deletion_scheduled_for": null               // ISO datetime when a deletion is pending
}
```

### `PATCH /v1/me/privacy` → 200 (same body as GET)

Body: any subset of `{"marketing_opt_out": bool, "ad_measurement_opt_out": bool, "case_study_opt_in": bool}`.
Unknown keys → 422.

### `POST /v1/me/consents` → 200 (same body as GET)

Body: `{"terms_date": "2026-10-18", "liability_clause": true}`.
- `terms_date` must equal `current_terms_date`, else 409.
- `liability_clause` must be `true`, else 422 (the separate Điều 11 acceptance, D68.4).
Records `terms_date_accepted`, `terms_accepted_at = now()`, `liability_clause_accepted_at = now()`.

### `GET /v1/me/export` → 200 `application/json`, `Content-Disposition: attachment; filename="juli-du-lieu-<yyyy-mm-dd>.json"`

The seller's own account row (no internal ids beyond the user id), privacy prefs, their shops
(name, platform, connected_at), and the shop data Juli stores for them that the seller can
already see in the product. No buyer contact data (Juli does not store it), no tokens, no
secrets, no staff/audit rows.

### `POST /v1/me/deletion` → 200 (same body as GET, `deletion_scheduled_for` = now + 30 days)

Starts the 30-day export window (D68.10). The account stays usable read-only for export; shop
sync for the user's shops stops. Idempotent.

### `DELETE /v1/me/deletion` → 200

Cancels a pending deletion inside the window.

## Purge

Nightly Celery task `privacy_account_purge` (pattern: `workers/tasks/ops_audit_retention.py`):
deletes users whose `deletion_scheduled_for <= now()` together with their shops and shop data,
keeping invoices / payment records (10 years, D68.10), then deletes the Supabase Auth user.
Logs counts only, never PII.

## Demo behaviour

- Settings: tab **"Quyền riêng tư"** with three switches (Không nhận email tiếp thị / Không đo lường
  quảng cáo / Cho phép Juli nêu tên shop làm ví dụ khách hàng), "Tải dữ liệu của tôi" (export),
  "Xoá tài khoản" (confirm dialog explaining 30 days to export, then deletion; cancel button
  while pending), and the e-mail lienhe@app-juli.com.
- Strip (pattern: `components/app-shell/term-strip.tsx`, mounted in `demo-shell.tsx`) when
  `needs_terms_acceptance`: short notice that the terms changed on 18/10/2026, links to /terms and
  /privacy, a required checkbox "Tôi đã đọc và đồng ý riêng với Điều 11 (Giới hạn trách nhiệm)
  của Điều khoản dịch vụ", button "Đồng ý" → `POST /v1/me/consents`.
- TikTok pixel in the demo does not load and sends no event when `ad_measurement_opt_out` is true.
