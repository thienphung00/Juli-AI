# P15 contract — content analysis of seller-uploaded videos / LIVE recordings (D24.19, D24.20)

Backend and UI build against this file. Same auth as every `/v1/demo` route (demo
session bearer + `X-Shop-Id`, `get_active_shop` sets the tenant scope); errors are
`{detail: {code, message (VI), …}}`. Ops: `docs/runbooks/content-analysis-runbook.md`.

## 0. Why upload

D24.19 2B: no compliant TikTok API returns the seller's video or LIVE replay file,
nor transcripts, nor per-product pin times (A-26 per-minute LIVE metrics are
shop-level; A-27 has no timing). So the seller uploads the file (2C); Juli keeps only
derived data and deletes the file.

## 1. Storage — migration `082_content_analysis` (onto 081; deferred phone cleanup re-parented, still last)

`content_analyses` (tenant_direct; RLS per verb via `app_current_shop_id()`;
`juli_app` SELECT / INSERT / UPDATE, no DELETE): `kind` (`video`|`live`),
`content_ref` (`video:<tiktok video id>` / `live:<live id>` — the Phân tích row, or
null from a content run), `tiktok_product_id`, `workflow_run_id`, `status`,
`file_name` (text only), `content_type`, `size_bytes`, `received_bytes`,
`storage_key` (relative path; null once deleted), `upload_expires_at`,
`duration_s`, `signals` JSON, `result` JSON, `usage` JSON, `cost_usd`,
`error_code`, `error_message` (VI), `attempts`, timestamps, `file_deleted_at`.
**No media in the database.**

File: `<CONTENT_ANALYSIS_UPLOAD_DIR>/<shop_id>/<analysis_id>.upload`, dir 0700, file
0600 (`O_NOFOLLOW`), never web-served, deleted when the analysis ends (done / failed
for good / refused); a transient provider error keeps it for the retry; the hourly
`content_analysis_sweep` (minute 47) deletes anything older than 24 h.

## 2. Upload API

| | Request | Answer |
|---|---|---|
| Open a slot | `POST /v1/demo/content-analysis` `{kind, content_ref?, tiktok_product_id?, run_id?, file_name, content_type: video/mp4 \| video/quicktime, size_bytes}` | 201 `{data: {analysis, upload: {url, token, chunk_bytes, expires_at}}}` |
| Send bytes | `PUT {url}?offset=N&token=…`, raw body (`application/octet-stream`), ≤ `chunk_bytes` (32 MB) | 200 `{data: analysis}`; the chunk that completes `size_bytes` → `queued` + enqueue |
| List | `GET /v1/demo/content-analysis?tiktok_product_id=&content_ref=&run_id=` | `{data: [analysis]}` newest first, ≤ 20 |
| One | `GET /v1/demo/content-analysis/{id}` | `{data: analysis}`; another shop's → 404 |

Refusals: 415 `unsupported_type` (not .mp4/.mov), 413 `too_large` (video > 500 MB,
LIVE > 4 GB) / `chunk_too_large` / `size_mismatch`, 422 `bad_kind` /
`bad_content_ref` / `bad_product`, 404 `run_not_found`, 409 `too_many_uploads` (2 in
flight per shop), 402 `cost_cap_reached`, 409 `offset_mismatch` with
`expected_offset` (client resumes there), 410 `upload_expired` (6 h), 403 `bad_token`,
415 `not_a_video` (first chunk is not an MP4/MOV box → slot failed, file deleted).
The token = HMAC(analysis id, shop id, expiry) with `CONTENT_UPLOAD_SIGNING_SECRET`
(else `SUPABASE_JWT_SECRET`, domain-separated) — required in addition to the session.
With `run_id` and no product, the run's product is used.

Duration limits (video ≤ 10 min, LIVE ≤ 3 h, +2 s tolerance) are checked by ffprobe
in the pipeline → `failed` / `too_long_video` | `too_long_live`.

## 3. `analysis` (view)

```json
{"id": "…", "kind": "video", "content_ref": "video:73…", "tiktok_product_id": "17…",
 "run_id": null, "file_name": "clip.mp4",
 "status": "done", "status_label": "Đã phân tích",            // (VI) Đang tải lên · Đang chờ phân tích · Juli đang phân tích · Chưa phân tích được · Đã đạt hạn mức tháng · Tải lên chưa xong
 "upload": {"received_bytes": 1, "size_bytes": 1}, "duration_s": 32.0,
 "error": null,                                               // {code, message (VI)}
 "result": {                                                  // only when done
   "kind": "video", "analysed_s": 32.0,
   "hook": {"verdict": "weak", "label": "Yếu", "from_s": 0, "to_s": 3, "reason": "…"},  // LIVE: 30 s from the first mention
   "product_first_s": 6.0, "product_line": "Sản phẩm xuất hiện lần đầu ở giây 6,0",
   "cta": {"present": true, "at_s": 29.0, "text": "…", "line": "Có lời kêu gọi mua ở giây 29,0"},
   "pacing": {"cuts": 4, "cuts_per_10s": 1.3, "line": "4 lần cắt · 1,3 lần / 10 giây"},
   "issues": [{"code": "product_late", "text": "…"}],         // ≤ 6
   "suggestions": ["…"],                                      // ≤ 5, banned words removed
   "suggestions_dropped": 0,
   "windows": [{"from_s": 1140, "to_s": 1560, "mention_s": 1260, "source": "asr_mention"}],  // LIVE only
   "prompt_version": "p15-content-analysis-v1"},
 "cost_usd": 0.004, "file_deleted": true, "created_at": "…Z", "completed_at": "…Z"}
```
Issue codes: `hook_weak product_late no_cta cta_late slow_pacing fast_pacing no_speech
no_text_on_screen banned_claim off_tone other`.

## 4. Pipeline (Celery `juli_backend.analyze_content_upload`, queue `content_analysis`)

Idempotent (only `queued`/`processing` rows run), per-shop Redis lock
`ingest:content_analysis:{shop}` (locked → retry in 60 s), ≤ 3 attempts on provider
errors (then `failed` / `provider_final`, file deleted), cost stored per stage as spent.

1. **ffprobe** (`-f mov -protocol_whitelist file`, after a first-box sniff) → duration,
   streams. Never executed; argument lists, no shell, timeouts.
2. **Audio** → mono 16 kHz AAC m4a.
3. **ASR** — OpenAI `/v1/audio/transcriptions`, `CONTENT_ANALYSIS_ASR_MODEL`
   (default `whisper-1`: `verbose_json`, segment + word timestamps), `language=vi`,
   prompt = product name, brand, SKU, ≤ 8 TikTok SEO words. 10-min slices
   (30 s for models without timestamps). Cost = minutes × `ASR_USD_PER_MINUTE`
   (whisper-1 $0.006, gpt-4o-mini-transcribe $0.003).
4. **LIVE windows** — TikTok product timing when available (none today), else ASR of
   10-min slices from the start (≤ 60 min) until the product's name (first 2–3 words,
   accent-folded), brand or SKU is said; window = mention −2 min … +5 min, ≤ 3, merged;
   every window fully transcribed. No mention → result with an "other" issue, no vision /
   scoring.
5. **Cuts** — 10 fps 64×36 luma, `max(12, 4 × median)` spike detector (port of the
   content engine's `reference_analyze.py`; PySceneDetect (BSD-3) not used: it needs OpenCV).
6. **Keyframes** — every 2 s, 384 px JPEG, windows only.
7. **On-screen text + product on screen** — `gpt-5.4-nano` vision (`detail: low`), 8
   frames per call with ≤ 2 product listing images (TikTok `get_details`
   `main_images`), JSON schema `{frames: [{index, text, product_visible}]}`;
   near-identical consecutive frames are not resent. (EasyOCR/PaddleOCR/OpenCLIP need
   torch/paddle — too heavy for the VPS; deviation from "OCR library first".)
8. **Scoring** — ONE `gpt-5.4-nano` call, structured output (`SCORING_SCHEMA`), over
   derived signals only (transcript lines, on-screen lines, cut times, product
   timeline, the seller's `content_tone` / `banned_terms`): hook verdict + reason, the
   CTA line by index (`source` speech/screen), issues, suggestions. Every number in the
   result comes from the signals, not the model.
9. **Checks** — rule issues always added (product after 3 s, no CTA, pacing < 1 or > 6
   cuts / 10 s, no speech, legal claims or the seller's banned words in the seller's own
   video); suggestions with a banned claim / banned word are dropped.

**Cost cap**: before ASR (each slice), vision and scoring:
`spent this month (workflow_runs.cost_usd + content_analyses.cost_usd, UTC+7 month) +
estimate ≤ cap`, cap = `shop_rules.openai_monthly_cap_usd` (number, P16 writes it) else
`OPENAI_MONTHLY_COST_CAP_USD` (default $5). Over → `refused`, message "Shop đã dùng hết
hạn mức phân tích bằng AI của tháng này (x / y USD) …". Also checked when a slot opens (402).

## 5. Where it shows (no artboard — deviation, owner review)

- **Content run** (Quyết định › Đang thực hiện, P14-E panel): a "Phân tích video" block
  under the steps (not after Không thực hiện / ended) — upload for the run's product
  (`run_id`), latest result. **Juli soạn uses it**: the drafter's prompt gets
  `phân_tích_video_của_người_bán` = the best and the weakest analysed upload of the
  product by the TikTok rate the run read (video CTR / LIVE CTOR, joined by the
  content tools' 12-char ref), else the latest uploads (≤ 2); prompt version
  `p15-content-prompt-v2` (unchanged text when there is no analysis). Soạn lại after an
  upload uses it.
- **Phân tích › Nội dung row detail** (Video / LIVE rows): the same block, compact,
  for `content_ref = kind:<row id>`, product = the row's first tagged product.
- Block: title "Phân tích video", status chip, Hook, Giây sản phẩm xuất hiện, Lời kêu
  gọi mua (CTA), Nhịp cắt, Vấn đề, Gợi ý, upload button ("Tải video lên" / "Tải bản
  ghi LIVE lên"), progress "Đang tải lên… N %", polling every 5 s while queued /
  processing, the backend's VI error.
- **Signed out / no shop**: canned analyses (video MN-015-style, LIVE SM-012-style),
  badge "Bản minh họa", upload disabled, no request.
