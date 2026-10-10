# Content analysis (fast track P15) — VPS requirements and operation

Contract: `fasttrack/contracts/p15-content-analysis.md`. Code:
`backend/src/juli_backend/services/content_analysis/`, task
`workers/tasks/content_analysis.py` (queue `content_analysis`).

## What the box needs

| Need | Value | Why |
|---|---|---|
| ffmpeg / ffprobe | **≥ 4.4** (Ubuntu 22.04 ships 4.4.2, 24.04 ships 6.1; tested locally with 9.0). `apt install ffmpeg`. Uses only built-ins: `mov` demuxer, `aac` encoder, `ipod` muxer, `fps`/`scale`/`format` filters, `mjpeg` | probe, audio, keyframes, luma frames for cuts |
| CPU | 2 vCPU minimum. One analysis decodes the video twice at reduced rate (10 fps 64×36 for cuts, 0.5 fps 384 px for keyframes). Measured on an M2: a 6 s / 30 s 320×240 fixture → 0.3–0.4 s of ffmpeg work. Expect roughly 0.05–0.2× real time for 1080p H.264 per pass on a VPS core; a 10-min 1080p video ≈ 1–3 min, a 3 h LIVE with 3 windows ≈ 2–5 min (audio extraction of the whole file dominates) | |
| RAM | +300 MB per running analysis (ffmpeg decode + ≤ 14 MB of luma frames per 10-min window + the chunk buffer of 32 MB per upload request in the API) | |
| Disk | Uploads ≤ 500 MB (video) / ≤ 4 GB (LIVE) each, at most 2 in flight per shop (`CONTENT_ANALYSIS_MAX_IN_FLIGHT`), deleted after analysis and by the hourly sweep after 24 h at most. Plan **10 GB free** on the upload volume (47 GB free today, `vps-wiring-runbook.md`) | |
| Directory | `CONTENT_ANALYSIS_UPLOAD_DIR` (default `/var/lib/juli/content-uploads`), owned by the API/worker user, mode 0700. Never under nginx `root`/`alias` | |
| Worker | `juli-celery-worker.service` now consumes `content_analysis` (its `-Q`). Redeploy the unit with this release (deploy.sh verifies the queues) | |
| nginx | `location ~ ^/v1/demo/content-analysis/[^/]+/file$` with `client_max_body_size 40m`, `proxy_request_buffering off` (both vhosts) | 32 MB chunks under Cloudflare's 100 MB request cap |
| OpenAI | `OPENAI_API_KEY` (already required); the key must be allowed to call `/v1/audio/transcriptions` and image input on `gpt-5.4-nano` | |

No new Python dependency: cuts are pure numpy/PIL (port of the content engine's
`reference_analyze.py`), OCR and product-on-screen use `gpt-5.4-nano` vision on
keyframes (EasyOCR / PaddleOCR / OpenCLIP all need torch or paddle — several
hundred MB — not worth it on this VPS at today's volume).

## Operating

- Status per upload: `content_analyses.status` (`awaiting_upload` → `queued` →
  `processing` → `done` | `failed` | `refused` | `expired`), cost in `cost_usd`,
  per-stage usage and timings in `usage`.
- Logs: `content_analysis_upload_opened`, `content_analysis_upload_complete`,
  `content_analysis_finished` (outcome, cost, usage), `content_analysis_error`,
  `content_analysis_sweep`.
- A shop over its monthly cap gets `refused` with a Vietnamese message; raise the
  cap with a `shop_rules` row `openai_monthly_cap_usd` (P16's Ops console owns the UI).
- Stuck `queued` (enqueue failed): re-enqueue with
  `celery call juli_backend.analyze_content_upload --args='["<id>","<shop_id>"]'`.
- Disk check: `du -sh /var/lib/juli/content-uploads` should stay near zero between uploads.
