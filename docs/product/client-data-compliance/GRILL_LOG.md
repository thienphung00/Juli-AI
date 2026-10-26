# Grill (ĐÃ CHỐT 2026-10-26 → ADR-116, fast-track D76) — backend đạt chuẩn bảo mật NDA Ory (P0 + T7)

Nguồn: `juli-client-ops/clients/ory/compliance/backend_handoff_nda_zdr.md` (T1–T14, C1–C12), `juli-client-ops/clients/ory/contract/phu_luc_02_nda.md (NDA hiện hành, gửi 26/10)`. Phạm vi session này: chỉ backend + code; tài liệu khách hàng do session client-ops cập nhật.
Nhánh thực hiện: `fasttrack/optimize-product` (backend), `~/juli-sim-pilot` (mô hình nghiên cứu). Quyết định chuẩn hoá: [ADR-116](../../adr/116-client-data-lanes-consent-and-model-split.md); ADR trích số dòng theo nhánh fast-track (mục Hiện trạng dưới đây ghi theo `main`).

## Mục tiêu (yêu cầu tối thiểu)
1. Khi ISV Shopee được duyệt (mốc bắt đầu giai đoạn 2), backend không vi phạm C1, C2, C3, C8 ngay từ lần đồng bộ đầu.
2. Dữ liệu công khai (scrape) và dữ liệu khách hàng (API sàn) tách được, chứng minh được bằng manifest + test.
3. Dữ liệu khách hàng chỉ vào mô hình chung khi khách đồng ý bằng văn bản; đồng ý ghi nhận được và thu hồi được.
4. Mỗi quyết định có tiêu chí chấp nhận kiểm thử được.

## Nguyên tắc
- Một câu hỏi mỗi lượt, kèm đề xuất; quyết định ghi ngay vào đây (D#, ngày).
- Xác minh trong code trước khi hỏi; trích `file:dòng`.
- Allowlist thay vì blocklist cho mọi dữ liệu rời khỏi ranh giới (DB thô, OpenAI).
- Không gửi Ory chi tiết mô hình / mã nguồn (NDA Điều 4).

## Các bước
1. Chốt phạm vi chặn go-live.  2. Chốt ranh giới dữ liệu.  3. Đi từng việc P0 + T7 → quyết định + tiêu chí.
4. Chốt nơi ghi (ADR / issue / PR) và thứ tự.  5. Báo lại client-ops (mục 5 của handoff).

## Checklist
1. [x] Phạm vi chặn go-live (D0)
2. [x] Ranh giới làn công khai / làn khách hàng (D1)
3. [x] (D2) Dữ liệu không công khai lấy ngoài API (tài khoản phụ giai đoạn 1, file xuất Seller Center như Fujiwa)
4. [x] (D3, D4) Đồng ý: hình thức, phạm vi (xử lý LLM / huấn luyện chung), thu hồi và mô hình đã huấn luyện
5. [x] (D5) T1 — allowlist trường đơn / hoàn, dọn dữ liệu cũ
6. [x] (D6) T3 + T4 — tối thiểu hoá payload OpenAI, project riêng, hàng rào ZDR
7. [x] (D6) T5 — `llm_call_log`
8. [x] (D7) T7 — phê duyệt trước khi ghi lên shop, tổng quát hoá theo sàn
9. [x] (D9) Nơi ghi + thứ tự (ADR / issue / PR)

## Hiện trạng (kiểm 2026-10-26, juli main `886c922c`)
- **Quan trọng:** production chạy nhánh `fasttrack/optimize-product` (`~/juli-fasttrack`, cùng repo GitHub, hơn `main` 963 commit). Các file trích dưới đây đều có trên nhánh đó nhưng số dòng có thể lệch (vd. `openai_adapter.py` `require_env` ở :192). Việc backend của grill này nhắm nhánh fast-track, không phải `main`.
- Fast-track có Juli Ops (`apps/demo` → `ops.app-juli.com`, `/v1/ops/`, Hetzner) và **cổng ingest + tiện ích Juli Connector** (migration 088, `models/ingest.py`): tiện ích đọc Kênh Người Bán (Shopee VN) và POST lên Supabase; `ingest_raw_payloads` lưu nguyên body.
- Webhook thô đã redact (`services/tiktok/webhook_raw_log.py:124`). Đơn / hoàn bronze lưu nguyên payload (`services/etl/bronze_append.py:52`, `:87`).
- Danh sách khoá PII có sẵn nhưng chỉ dùng cho demo (`services/analytics_kpi_masking/mask.py:12`).
- Chưa có: đồng ý theo shop, `llm_call_log`, `data_access_log`, offboarding, Shopee.
- Grill nền tảng dữ liệu 2026-10-20 (`juli/docs/product/data-platform/GRILL_LOG.md`) D12/D13 không có cổng đồng ý / nguồn gốc dữ liệu.
- sim-pilot: pool Shopee chung có 1 sản phẩm Ory (scrape công khai, `funnel/ml_pipeline/01_eda.py:101`); Fujiwa từ file xuất TikTok Shop (`v0/features.py:39`).

## Quyết định
- **D0 (2026-10-26) — phạm vi.** Giai đoạn 2 bắt đầu khi ISV Shopee được duyệt (không có ngày cố định). Chặn go-live: P0 (T1–T5) + T7. P1 còn lại (T6, T8, T9) sau; P2 là việc vận hành.
- **D1 (2026-10-26) — ranh giới dữ liệu.** Làn khách hàng = **chỉ dữ liệu lấy qua API sàn** (TikTok Shop, Shopee), có `shop_id`, RLS. Làn công khai = mọi dữ liệu scrape công khai (FastMoss, Apify, Metric.vn, Chrome), **kể cả listing công khai của shop khách hàng** — dùng tự do cho mô hình chung (NDA Điều 1 loại trừ thông tin đã công khai hợp pháp). Dữ liệu làn khách hàng được dùng cho mô hình chung **sau khi xin và có đồng ý bằng văn bản** của khách (cổng `pooled_training_allowed`, T2). Hệ quả: sản phẩm Ory trong pool sim-pilot giữ nguyên.
- **D2 (2026-10-26) — dữ liệu không công khai ngoài API = làn khách hàng.** Sửa D1: làn khách hàng = mọi dữ liệu không công khai của khách, bất kể cách lấy (API sàn, file xuất qua tài khoản phụ giai đoạn 1, file khách gửi). Loader file xuất Seller Center của sim-pilot (khi làm) đi qua cùng cổng đồng ý. **Fujiwa** = trường hợp đặc biệt phục vụ phát triển: `pooled_training_allowed = true`; dữ liệu Fujiwa hiện có dùng để dựng và kiểm thử việc tách làn cho khách TikTok Shop.
- **D3 (2026-10-26) — tách mô hình: nền công khai + lớp riêng theo khách (thay câu hỏi "thu hồi thì huấn luyện lại mô hình chung").**
  1. **Mô hình nền** chỉ huấn luyện từ làn công khai + shop có `pooled_training_allowed = true` (hiện chỉ Fujiwa). Không bao giờ đọc dữ liệu làn khách hàng khác → thu hồi của một khách **không bao giờ** buộc huấn luyện lại mô hình nền. Khớp `subprocessors.md` mục D ("Mô hình chung").
  2. **Lớp riêng theo khách** = mô hình nền (phiên bản cố định) làm điểm xuất phát / offset + phần hiệu chỉnh chỉ ước lượng từ dữ liệu của chính shop đó. Lưu trong bảng có `shop_id` (`tenant_direct`) kèm `base_model_version` + manifest dữ liệu; chỉ phục vụ shop đó (khớp mục D "Tham số riêng").
  3. **Phục vụ:** khách mới → mô hình nền. Có quyền + lớp riêng qua cổng D13 → lớp riêng. Thu hồi → cờ tắt, phục vụ **lùi ngay** về mô hình nền; lớp riêng + đặc trưng + dự báo của shop bị xoá theo T8 trong 30 ngày, biên bản xoá ghi phiên bản lớp riêng đã xoá.
  4. Khi mô hình nền lên phiên bản mới: lớp riêng giữ `base_model_version` cũ cho tới khi ước lượng lại (rẻ, từng shop), không tự trộn.
  5. Test: bộ dựng mô hình nền từ chối mọi `shop_id` không có `pooled_training_allowed`; xoá lớp riêng của shop → phục vụ shop đó trả kết quả từ mô hình nền.
- **D4 (2026-10-26) — mô hình quyền (theo cách SaaS doanh nghiệp làm).** Một bảng `data_use_consents` (`tenant_direct`, append-only trừ `revoked_at`), một dòng / shop / phạm vi: `scope` ∈ {`service`, `llm_processing`, `pooled_training`}, `method` ∈ {`contract_paper`, `in_app_click`, `email`}, `terms_version`, `evidence_ref` (+ SHA-256 bản scan), `granted_by`, `granted_at`, `revoked_at`.
  - `service` (lớp riêng theo khách D3, phân tích KPI): quyền nằm trong hợp đồng / điều khoản sử dụng — không có bước đồng ý riêng.
  - `llm_processing` (OpenAI): theo hợp đồng + danh sách nhà xử lý phụ đã duyệt.
  - `pooled_training` (dữ liệu khách vào mô hình nền): đồng ý riêng, mặc định **tắt**; bật qua nút trong app hoặc giấy. Có hợp đồng giấy → nút trong app khoá "theo hợp đồng".
  - Ory: `service` = hợp đồng giấy (Phụ lục 03 + `subprocessors.md` mục D); `llm_processing` = khi Ory duyệt danh sách giai đoạn 2; `pooled_training` = false. Fujiwa: `pooled_training` = true (D2).
  - Cần xác minh: chính sách dữ liệu nhà phát triển Shopee / TikTok Shop (dùng dữ liệu seller cho seller khác) — reviewer ISV có thể hỏi.
- **D5 (2026-10-26) — T1 `buyer_id` = HMAC theo shop.** Lớp allowlist theo `platform` + `endpoint` tại `services/cdp_speed/targeted_fetch_bronze_handoff.py` (trước `bronze_append`), bỏ mọi trường ngoài danh sách ở mọi độ sâu. `buyer_id` lưu dạng `HMAC-SHA256(khoá_shop, buyer_id)`, khoá theo shop trong AWS Secrets Manager; áp dụng cả silver (`integrations/tiktok/mapping.py:30`, `:226` — `user_id` → `buyer_id`) để `orders` / `returns` khớp nhau. Đếm khách mua lại trong shop vẫn chạy (`ai/anomaly/train.py:40` nối theo `buyer_id` + `shop_id`); không nối được giữa các shop. Offboarding (T8) xoá khoá → mã vĩnh viễn ẩn danh. Migration dọn: xoá trường PII trong payload đã lưu + băm `buyer_id` cũ; ghi số dòng.
  - Ghi chú cho T2: `ai/anomaly/train.py`, `ai/dataset/assembler.py` dựng dữ liệu huấn luyện từ đơn / hoàn của shop → phải đi qua cổng D3/D4 (mô hình nền chỉ đọc shop có `pooled_training`).
- **D6 (2026-10-26) — OpenAI: 2 project cố định, không key theo khách (T3, T4, T5).**
  1. Đúng **hai** project OpenAI, mỗi project **một** khoá service-account (không gắn người): `juli-internal` (nghiên cứu, nội bộ) và `juli-client-data` (mọi lời gọi có `shop_id`; xin ZDR cho project này). Thêm khách mới **không** tạo khoá mới — chỉ thêm dòng `data_use_consents` (D4).
  2. Khoá nằm trong AWS Secrets Manager (`juli/api/production`, hai trường), adapter đọc qua bộ nạp bí mật có TTL (thay `require_env("OPENAI_API_KEY")`, `services/agent/llm/openai_adapter.py:121`) → xoay khoá (định kỳ / khi sự cố) = cập nhật secret, không deploy.
  3. Một cửa duy nhất trong adapter: request có `shop_id` → bắt buộc project `juli-client-data` + `llm_processing` đã cấp + payload qua allowlist T3 + `store=false`, không `previous_response_id` / `background`; thiếu điều kiện nào → từ chối (không lùi về khoá nội bộ). Cùng chỗ đó ghi `llm_call_log` (T5: shop, mục đích, model, token, `request_id`, project; không nội dung) → chi phí theo khách lấy từ log, không cần khoá theo khách.
  4. Mở rộng sau (không làm bây giờ): khách doanh nghiệp đòi project riêng (ZDR / residency riêng) → bảng định tuyến `shop → project`, mặc định `juli-client-data`.
  5. CI: cấm gọi `files`, `vector_stores`, `assistants`, `threads`, `conversations`, `batches`, `fine_tuning`, `evals`; test: shop request chỉ có khoá nội bộ → 0 HTTP call.
  - Việc của chủ (ngoài code): tạo project `juli-client-data` + khoá service-account, đưa vào secret; gửi đơn ZDR cho project đó.
- **D7 (2026-10-26) — T7 phê duyệt = chỉ người dùng Ory bấm trong app (giai đoạn 2).**
  1. Không có đường "operator ghi hộ": `action_card_approvals.approved_by_user_id` giữ NOT NULL, user đó phải là thành viên của shop (RLS + kiểm ở service). Executor chỉ ghi lên shop khi có phê duyệt khớp đúng thông số card (trước / sau, mã băm `card_snapshot`), còn hạn, và đọc lại trường ngay trước khi ghi (D11-1) vẫn bằng giá trị "trước"; lệch → từ chối + ghi `production_write_audit`.
  2. Tổng quát hoá `production_write_authorizations` / `production_write_audit`: `tiktok_product_id` → `platform` + `platform_product_id`.
  3. Hạn phê duyệt mặc định 72 giờ (đề xuất, chủ chưa phản đối); hết hạn → card quay lại chờ duyệt.
  4. **Giai đoạn 1:** Juli không ghi lên shop. Thiên phân tích dữ liệu Ory, nhập thông số đề xuất vào "Juli Ops"; người dùng Ory tự thực hiện trên Kênh Người Bán. Juli Ops = `ops.app-juli.com` (sửa 2026-10-26: trước đó ghi nhầm "chưa tồn tại" vì chỉ kiểm `main`). Thay đổi do Ory tự làm được quy nguồn `seller_change` (D11 của grill nền tảng dữ liệu).
- **D8 (2026-10-26) — production chưa có dữ liệu Ory không công khai.** Chủ xác nhận: Juli Ops và Connector hiện chỉ có dữ liệu công khai; giai đoạn 1 chưa bắt đầu (chờ tài khoản phụ). Quy tắc: không đưa dữ liệu không công khai của Ory vào Juli Ops / Connector / Supabase / Hetzner cho tới khi danh sách nhà xử lý phụ v2 (thêm Supabase + Hetzner Singapore + Cloudflare cho giai đoạn 1) được Ory duyệt; trước đó giai đoạn 1 chạy trên máy nội bộ như v1. Cổng ingest (`ingest_raw_payloads`) nhận allowlist trường kiểu D5 + kiểm `data_use_consents` trước khi bất kỳ shop khách hàng nào ghép Connector — thêm vào P0.
- **D9 (2026-10-26) — nơi ghi + thứ tự.** Nhánh đích `fasttrack/optimize-product`; mỗi PR một nhánh `fasttrack/nda-*` từ `origin/fasttrack/optimize-product`, worktree riêng. Giấy tờ: ADR-116 "Làn dữ liệu khách hàng, đồng ý và tách mô hình" (D1–D4, D8; sửa ADR-115) + mục DECISIONS fast-track. PR: (1) docs ADR-116 + grill log → (2) `data_use_consents` + helper → song song (3) allowlist + HMAC đơn / hoàn / ingest + migration dọn, (4) cửa OpenAI + `llm_call_log`, (5) phê duyệt T7 → (6) bộ dựng huấn luyện + lớp riêng. Xong trước khi ISV duyệt; P1 (T6, T8) đợt sau.
  - Kiểm đồng bộ nhánh (2026-10-26): không có PR mở vào nhánh fast-track; mọi checkout `~/juli-fasttrack*` sạch và đã nằm trong nhánh; `~/juli-fasttrack` chậm 15 commit (sạch, chỉ cần fast-forward); 2 nhánh P68 còn trên remote đã squash-merge (#2187, #2188); `main` có 1 commit không có trong fast-track (#2149, chỉ CI uptime). **P68 đã merge nhưng chưa deploy** (migration 102) → không merge PR nào của đợt này trước khi chủ deploy P68; migration mới nối sau 102.
- **D6 sửa (2026-10-26) — một key cho backend; ZDR hoãn.** Kiểm code: cả bốn đường gọi OpenAI của backend (agent, `vision.py`, `content_analysis/openai_media.py`, chấm điểm / soạn content card) đều mang dữ liệu shop, không có đường nội bộ. → Backend dùng **một** project `juli-client-data`, key nằm trong trường `OPENAI_API_KEY` hiện có của `juli/api/production` (nạp qua `fetch-secrets.sh` / `refresh-secrets.sh`, xoay khoá = sửa secret); bỏ bộ nạp TTL và định tuyến key. Project cũ chỉ cho nghiên cứu (`~/.juli-sim.env`). Key: chỉ quyền Model capabilities; danh sách model `gpt-5.4-nano`, `whisper-1`. Chi phí theo khách lấy từ `llm_call_log` + giá trong code, đối chiếu tổng token với số của OpenAI cho project. **ZDR hoãn** (chủ): trong lúc chờ, OpenAI lưu nhật ký giám sát tối đa 30 ngày — đúng như danh sách nhà xử lý phụ đã gửi. Chủ đã tạo project, key, hạn chế quyền và đưa key vào Secrets Manager.
- **D4 bổ sung (2026-10-26, từ session client-ops) — quyền OpenAI tách theo loại đầu vào.** Danh sách v1 Ory đã nhận chỉ cho phép gửi OpenAI nội dung listing (văn bản) + chỉ số tổng hợp; chính sách quyền riêng tư cho người bán tự đăng ký nêu thêm hình ảnh sản phẩm và khung hình video. → `llm_processing` (văn bản + chỉ số), `llm_images` (ảnh sản phẩm, `vision.py`), `llm_media` (khung hình / âm thanh video, `content_analysis/openai_media.py`, whisper-1); cổng OpenAI kiểm từng loại. Ory: chỉ `llm_processing` khi duyệt danh sách giai đoạn 2; ảnh / video bị chặn cho tới khi danh sách mới nêu rõ và Ory duyệt.
- **D10 (2026-10-26) — người bán tự đăng ký: chấp nhận Điều khoản = cấp quyền.** Khi người dùng chấp nhận Điều khoản trong app (`users.terms_accepted_at`, `services/privacy/prefs.py`), ghi `service`, `llm_processing`, `llm_images`, `llm_media` (`method = in_app_click`, `terms_version` = phiên bản Điều khoản) cho các shop của họ — chính sách quyền riêng tư công khai nêu OpenAI, ảnh sản phẩm và khung hình video. Backfill một lần cho người đã chấp nhận (lệnh vận hành, không phải migration). `pooled_training` tắt, trừ Fujiwa (lệnh seed vận hành). Khách hợp đồng giấy (Ory) chỉ nhận đúng phạm vi danh sách đã ký. Key OpenAI của backend nằm trong trường `OPENAI_API_KEY` (chủ xác nhận).

