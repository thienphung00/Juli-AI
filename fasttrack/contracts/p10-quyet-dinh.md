# P10 contract — Quyết định card and flows (ADR-109 Amendment 1)

Backend (P10-A, P10-B) and UI (P10-C) build against this file in parallel. Additive to the
existing `/v1/demo/*` API; same auth + `X-Shop-Id` guards; Vietnamese user-facing strings
come from the backend only where marked (VI); everything else is UI copy from the
artboards in `docs/product/design/quyet-dinh-flows/`. Changing a shape here needs the
orchestrator.

## 1. Card — `GET /v1/demo/decisions` item, new `recommendation.card` (P10-A)

```json
"card": {
  "seller_sku": "SM-012",            // first seller SKU of the product, null if none
  "seller_sku_more": 0,              // count of other SKUs → UI shows "+N"
  "product_title": "Son môi số 12",
  "workflow_label": "Tối ưu sản phẩm",   // (VI)
  "updated_at": "2026-10-09T02:00:00Z",
  "status": "pending",               // pending | running | applied | rejected | expired
  "main_kpi": {
    "key": "ctor", "label": "CTOR - Thẻ sản phẩm",   // (VI) label
    "current": 0.054, "target": 0.059, "unit": "ratio"  // ratio | vnd ; target = reference_rate
  },
  "expected_gmv_per_month": 2100000,   // D22 recoverable GMV/day × 30, VND
  "reason_short": "Khách thêm giỏ rồi bỏ",            // (VI) ≤ 6 words
  "reason_full": "Đơn/thêm giỏ của sản phẩm thấp hơn 31 % …",  // (VI)
  "tiktok_codes": ["Mô tả quá ngắn"],                  // (VI) labels
  "lever": { "code": "description", "label": "Mô tả",
             "executor": "juli" },     // juli | juli_with_photo | seller_center
  "change_fields": [ { "field": "title", "label": "Tiêu đề" }, { "field": "description", "label": "Mô tả" } ],
  "before_after": [ { "field": "title", "label": "Tiêu đề", "before": "…", "after": "…" } ],
  "gmv_method": "lượt bấm × (CTOR mục tiêu − CTOR hiện tại) × AOV, trung bình 30 ngày, ước tính theo quy tắc"  // (VI)
}
```
Lever codes: `cover_image` (juli_with_photo), `title`, `description` (juli),
`product_discount`, `flash_sale`, `shipping_discount`, `buy_more_save_more` (seller_center).
`expired` = proposal older than its validity or the product changed since.

## 2. Reasons and cooldown (P10-A)

Exactly one reason is required (`reason_code`), plus optional `note` (≤ 300 chars).
After any of the three actions the same lever is not proposed again for that product for
**7 days** unless its data changes clearly.

| Action | Endpoint | reason_code values |
|---|---|---|
| Từ chối a card | `POST /v1/demo/decisions/{id}/reject` → 200 `{status:"rejected", cooldown_until}` | `brand_mismatch`, `not_convincing`, `editing_myself`, `discontinued`, `other_campaign`, `other` |
| Không thực hiện (consent step) | `POST /v1/demo/runs/{id}/decline` → 200 `{status:"declined", cooldown_until}` | `wrong_info`, `tone`, `too_much_change`, `changed_mind`, `other` |
| Hoàn tác | `POST /v1/demo/runs/{id}/revert` (existing) now requires `{reason_code, note?}` | `metrics_dropped`, `bad_feedback`, `wrong_info`, `off_brand`, `tiktok_warning`, `other` |

422 when `reason_code` is missing/unknown. Reasons are stored with the card/run.

## 3. Consent with edits (P10-A)

Existing `POST /v1/demo/runs/{id}/confirmations/{tool_call_id}` accepts optional
`edited_values: {"title"?: str, "description"?: str}`. The backend validates against the
shop's rules (length limits, protected terms) and writes exactly the edited values;
422 `{detail:{code:"rule_violation", message (VI), field}}` otherwise. The run's
before/after record stores the edited value; `tool.completed.summary` mentions
"theo bản bạn sửa".

## 4. Cover-image flow (P10-B)

- The run pauses with `run.awaiting = "photo"` (exposed on `GET /v1/demo/runs/{id}` and the
  runs list); SSE: `workflow.status` with `phase_narration` "Đang chờ ảnh từ bạn".
  Request expires after 3 days (run ends `timed_out`).
- `POST /v1/demo/runs/{id}/photo` (multipart `file`, JPG/PNG ≤ 5 MB) → 202
  `{checks:[{key, label (VI), ok}]}`; failing checks → 422 with the same list.
  Checks: 1:1, ≥ 800 px, plain background, product ≥ 70 % of frame (best effort; record
  which checks are heuristic).
- Then the normal consent step (before/after images as URLs) → `upload_product_image`.

## 5. Promotion flow (P10-B)

- Approving a `seller_center` card creates a run that reads data, checks rules, and then
  pauses with `run.awaiting = "seller_action"`.
- `GET /v1/demo/runs/{id}/instructions` → `{steps:[str (VI)], deep_link, summary (VI)}`.
- `POST /v1/demo/runs/{id}/applied` → 202; the run verifies on TikTok (promotion read
  tools) emitting `tool.*` events; not found → `workflow.status` narration
  "Chưa tìm thấy trên TikTok" and stays awaiting; found → measurement clock starts at the
  promotion's start date.
- No revert for these runs (`revert.available=false`, reason_code `seller_center`).

## 6. Measurement — `GET /v1/demo/runs/{id}/measurement` (P10-B)

```json
{
  "stage": "waiting",                 // waiting | day7 | final
  "dates": {"day7": "2026-10-16", "day14": "2026-10-23"},
  "target": {"label": "CTOR Thẻ sản phẩm", "current": 0.054, "target": 0.059,
             "progress_from": 0.055, "unit": "ratio"},
  "expected_gmv_per_day": 70000,
  "bands": [ {"key":"impressions","label":"Lượt hiển thị/ngày","before":9910,
              "band_pct":3,"low":9613,"high":10207,"unit":"count"} ],
  "rows": [ {"key":"ctor","label":"CTOR (chỉ số chính)","before":0.054,
             "expected":"5,9 %","actual":0.057,"verdict":"Đang tăng","tone":"ok"} ],
  "day7": {"within_band": true, "question_id": null},
  "final": {"label": "gan_dat", "gmv_actual_per_day": 57000, "pct_of_expected": 82,
            "calibration": {"lever": "description", "from": 0.50, "to": 0.58}}
}
```
Final labels: `dat` (≥ target and ≥ 100 % expected GMV) · `gan_dat` (70–99 %) ·
`khong_dat` (< 70 %) · `chua_ket_luan` (too little data or another change on the
product; no calibration update). `tone`: ok | warn | muted. Before day 7: `rows=[]`.
