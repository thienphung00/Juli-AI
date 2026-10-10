# P14 contract — "Juli soạn · bạn làm" content cards (D24.4, D24.18, D24.19)

Backend and UI build against this file. Additive to `p10-quyet-dinh.md`: same auth,
`X-Shop-Id`, tenant guards, reason dialog and codes. Vietnamese strings marked (VI)
come from the backend; everything else is UI copy from the artboards
`docs/product/design/quyet-dinh-flows/ContentCards.dc.html` and `ContentRun.dc.html`.

## 0. Identity

| | Video | LIVE |
|---|---|---|
| `action_cards.workflow_key` / `workflow_runs.workflow_key` | `content_video` | `content_live` |
| lever code (cooldown, calibration, measurement final) | `video_script` | `live_script` |
| source ranking (ADR-109 d.5, `shop_metric_rankings`) | `seller_video` × `ctr` | `seller_live` × `ctor` |
| main KPI key / label (VI) | `video_ctr` / "CTR - Video của người bán" | `live_ctor` / "CTOR - LIVE của người bán" |

`executor` = `"juli_drafts"`. Both keys are exported as
`juli_backend.services.content_cards.CONTENT_WORKFLOW_KEYS`; emission counts a card as a
content card by that key (or by the payload's `card_executor == "juli_drafts"`).

## 1. Card — `GET /v1/demo/decisions` item `recommendation.card`

Same shape as P10 §1, plus `content`. The item has **no** `recommendation.diagnosis`.

```json
"card": {
  "seller_sku": "MN-015", "seller_sku_more": 0,
  "product_title": "Mặt nạ đất sét 100g",
  "workflow_label": "Tối ưu nội dung · Video",          // (VI) "… · LIVE" for LIVE
  "updated_at": "2026-10-10T02:00:00Z",
  "status": "pending",                                   // pending | running | applied | rejected | expired
  "main_kpi": {"key": "video_ctr", "label": "CTR - Video của người bán",
               "current": 0.019, "target": 0.032, "unit": "ratio"},
  "expected_gmv_per_month": 1700000,                     // D22-style recoverable GMV/day × 30, VND
  "reason_short": "Video có lượt xem nhưng ít bấm vào sản phẩm",       // (VI)
  "reason_full": "Video \"…\" có 118k lượt hiển thị, CTR 1,9 % so với 3,2 % …", // (VI)
  "tiktok_codes": [],
  "lever": {"code": "video_script", "label": "Kịch bản video mới", "executor": "juli_drafts"},
  "change_fields": [{"field": "video_script", "label": "Kịch bản video mới"}],
  "before_after": [],
  "gmv_method": "lượt hiển thị × (CTR mục tiêu − CTR hiện tại) × CTOR × AOV, …", // (VI)
  "content": {
    "kind": "video",                                     // video | live
    "action_label": "Kịch bản video mới",                // (VI) the "Hành động" chip
    "chip": "Juli soạn · bạn làm",                       // (VI)
    "will_draft": ["Hook 3 giây và 2 phương án mở đầu", "…"],   // (VI) "Juli sẽ soạn", one line each
    "measure": "CTR trên các video mới gắn MN-015 trong 7 và 14 ngày, so với video cũ."  // (VI)
  }
}
```

LIVE: `reason_short` "Người xem bấm vào nhưng ít chốt đơn", lever `live_script` /
"Kịch bản host + thứ tự giỏ", KPI `live_ctor`.
`status`: `expired` once the card is older than **7 days** (D24.17); it then returns no
earlier than 7 days later.

Từ chối: the existing `POST /v1/demo/decisions/{id}/reject` (same reason codes); the
cooldown is keyed on (product, `video_script` | `live_script`), 7 days.

## 2. Run — after Phê duyệt

The existing approve endpoint creates an ordinary `workflow_runs` row
(`workflow_key` = the card's). Timeline events are the ordinary `tool.*`,
`assistant.text`, `workflow.status`, `workflow.completed` SSE events:

1. `tool.*` `get_content_performance` (video list + per-video metrics for the product /
   LIVE sessions + products incl. basket position when TikTok reports one)
2. `tool.*` `get_product_information`, then `get_seo_keywords` (video) or
   `find_product_promotions` (`flash_sale`, LIVE); then `assistant.text` with the
   seller's rules read from the database ("Quy tắc của bạn: Trần giảm giá 10 % · …") —
   the rules are not a TikTok tool, so they are narrated, not a `tool.*` pair
3. `assistant.text` "Đã soạn kịch bản (bản 1) · gpt-5.4-nano · đầu ra JSON schema · đã kiểm tra" (VI)
4. `workflow.status` "Đang chờ bạn xem kịch bản" (VI) — `awaiting = "content_choice"`
5. after Dùng kịch bản này: `workflow.status` "Đang chờ bạn đăng video" /
   "Đang chờ phiên LIVE kế tiếp" (VI) — `awaiting = "content_publish"`
6. after "Tôi đã đăng video" / "Tôi đã LIVE xong" or auto-detect: `tool.*`
   `find_new_content`, then `workflow.completed` (`final_response`): measurement starts.

Soạn lại: one more model call (bản 2) — events 3–4 again. At most 2 versions.
Không thực hiện at either wait: the existing `POST /v1/demo/runs/{id}/decline` (reason
codes of P10 §2 decline) → run `cancelled` / `cancelled_by_seller`, 7-day cooldown.
**No Hoàn tác**: the run writes nothing to TikTok, so `GET /runs/{id}/changes` has no
changes and the revert route refuses it with the existing "nothing written" answer; the
UI never shows the button for a content run.
`tool.completed.summary` of the two content tools is their own VI sentence
(`summary_vi`, e.g. "3 video gắn sản phẩm · CTR 1,9 %", "Tìm thấy 1 video mới").
A version that fails the guardrails is not shown: `assistant.text` "Bản 1 chưa đạt kiểm
tra nên Juli không hiển thị. Bạn bấm Soạn lại …"; if bản 2 fails too the run ends
(`final_response`, nothing to measure).

`awaiting` (runs list and run detail) gains `content_choice` and `content_publish`.
The choice wait lasts 3 days, the publish wait 7 days (then `timed_out`).

### 2.1 `GET /v1/demo/runs/{id}` → `data.content` (null for other runs)

```json
"content": {
  "kind": "video",
  "stage": "drafting",          // drafting | choice | publish | measuring | declined | ended
  "title": "MN-015 · Mặt nạ đất sét 100g · kịch bản video",              // (VI)
  "headline": "Juli đã soạn kịch bản video, bạn quay và đăng",             // (VI)
  "steps": [                    // always 6, in order (ContentRun.dc.html)
    {"key": "read_content", "label": "Đọc số liệu video và sản phẩm",
     "result": "3 video gắn MN-015 · CTR 1,9 % · giỏ hàng xuất hiện giây 20", "at": "2026-10-10T02:01:00Z"},
    {"key": "read_product", "label": "Đọc thông tin sản phẩm, từ khoá", "result": "…", "at": "…"},
    {"key": "draft", "label": "Soạn kịch bản", "result": "gpt-5.4-nano · đầu ra JSON schema · đã kiểm tra", "at": "…"},
    {"key": "choose", "label": "Bạn xem, sửa và chọn", "result": null, "at": null},
    {"key": "publish", "label": "Bạn quay và đăng video gắn MN-015", "result": null, "at": null},
    {"key": "measure", "label": "Đo CTR trên video mới · ngày 7, ngày 14", "result": null, "at": null}
  ],
  "script": {                   // the shown version, null while drafting
    "version": 1,
    "title": "Kịch bản video 25–35 giây",                                  // (VI)
    "blocks": [{"key": "hook", "label": "Hook (0–3 giây)", "text": "…"}],    // (VI) labels; 4 blocks
    "checks": [{"key": "banned", "label": "không có từ cấm", "ok": true}],    // (VI)
    "checks_line": "Đã kiểm tra: không có từ cấm, giữ từ bảo vệ của bạn, đúng thông tin sản phẩm, trong trần giảm giá.", // (VI)
    "plain_text": "…",          // what Sao chép copies
    "raw": { … }                // the validated JSON (§3)
  },
  "versions": 1, "can_redraft": true,
  "chosen_version": null, "edited": false,
  "wait": {"title": "Đang chờ bạn đăng video", "body": "…", "done_label": "Tôi đã đăng video",
           "detect_what": "video mới gắn MN-015"},                      // (VI), null unless stage=publish
  "measure_body": "…",          // (VI), null unless stage=measuring
  "published_at": null, "detected": null
}
```
LIVE labels: "Đọc số liệu các phiên LIVE", "Đọc sản phẩm, giá, khuyến mãi, Quy tắc",
"Soạn kịch bản host và thứ tự giỏ", "Bạn xem, sửa và chọn", "Bạn LIVE theo kịch bản",
"Đo CTOR ở 3 phiên kế tiếp"; script title "Kịch bản host cho SM-012 + thứ tự giỏ";
blocks "Mở (A · Attention)", "Trình diễn (S · Show)", "Chốt (B · Benefit + C · Close)",
"Thứ tự giỏ"; wait "Đang chờ phiên LIVE kế tiếp" / "Tôi đã LIVE xong" /
"phiên LIVE mới có SM-012".

### 2.2 Seller actions (all 202 `{status, celery_task_id}`; 409 `{code, message (VI)}` when the run is not waiting for that step)

| Button | Endpoint | Body |
|---|---|---|
| Dùng kịch bản này | `POST /v1/demo/runs/{id}/content/use` | `{"version": 1, "edited_blocks": {"hook": "…"}?}` |
| Soạn lại | `POST /v1/demo/runs/{id}/content/redraft` | — (409 `redraft_used` after bản 2) |
| Tôi đã đăng video / Tôi đã LIVE xong | `POST /v1/demo/runs/{id}/content/published` | — |
| Sao chép | client only (`script.plain_text`) | — |
| Không thực hiện | existing `POST /v1/demo/runs/{id}/decline` | `{reason_code, note?}` |

Edited blocks are validated with the same guardrails (422 `{code:"rule_violation",
message, field}`) and stored as the seller's final text (D24.8 training target).

## 3. Model output (structured output, JSON schema, `gpt-5.4-nano`)

Video: `{hook_options: [str, str], scenes: [{t_from, t_to, visual, voiceover, on_screen}],
cta, hashtags: [str], music_hint, product_on_screen_by_s}`.
LIVE: `{opening, show, close, offer: {type, discount_pct|null, text}, basket_order:
[{position, sku, pin_at}]}`. Validated before the seller sees it: banned patterns and
the seller's banned words, protected terms kept, length, no number/fact not in the
product data, discount ≤ the seller's cap (`max_discount_pct`), product on screen by 3 s.
A version that fails validation is never shown; the run says so and offers Soạn lại.

## 4. Measurement — `GET /v1/demo/runs/{id}/measurement`

P10 §6 shape. Video: day 0 = the new video's post date (or the "Tôi đã đăng video"
day); `rows` = CTR of new videos tagging the product vs the old videos' CTR; stage
`waiting` → `day7` → `final` (day 14). LIVE: CTOR of the product over the **next 3
sessions** selling it vs the prior session(s); `stage` `waiting` (0 sessions) → `day7`
(1–2 sessions) → `final` (3 sessions); `dates` are the session dates when known.
Final labels and calibration (per lever `video_script` / `live_script`) as P10.
Adds `content: {kind, sessions_done, sessions_needed, new_videos}`.
Readings are collected by the hourly `content_runs_poll` beat (TikTok reads), never in
the request.

## 5. Signed-out / no-shop sample

Two sample cards (MN-015 video, SM-012 LIVE) in the in-memory sample, with a canned
script for each (no network, no model call), playing the run states above.
