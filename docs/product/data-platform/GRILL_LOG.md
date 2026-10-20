# Grill (ĐÃ CHỐT 2026-10-20) — nền tảng dữ liệu đa shop / đa sàn cho gợi ý cold-start và huấn luyện (mở 2026-10-20)

## Mục tiêu (yêu cầu tối thiểu)
1. Thu thập tự động cho MỌI shop kết nối: hiệu suất sản phẩm theo ngày (impressions, clicks, CTR, CTOR, đơn, GMV) theo kênh; đơn + trả; lịch sử sản phẩm (tiêu đề, giá, ảnh bìa, SKU) có phiên bản; khuyến mãi; video / live. Kết nối → Backfill → Poll, không script tay.
2. Vòng hành động có bản ghi: gợi ý cold-start → duyệt / sửa / bỏ → thực thi → theo dõi → kết quả; có khoá, có thời điểm, nối được với hiệu suất.
3. Dữ liệu huấn luyện tái tạo được, không rò rỉ: raw append-only phát lại được, feature snapshot có phiên bản + mốc thời gian, lịch can thiệp là thông tin thiết kế; mô hình chỉ bật cho shop khi qua cổng đánh giá.
4. Mức production: rate limit, RLS, idempotent, verdict + bản ghi mỗi chu kỳ (ADR-105), test đúng tầng CI (Postgres thật), runbook.
5. Bảng chia theo cách dùng: bronze append-only, silver chuẩn hoá, gold / feature đọc nhanh; bảng thời gian lớn phân vùng + index theo (shop, ngày).
6. Backfill cold-start nhanh và đầy đủ nhất: ưu tiên dữ liệu cần cho gợi ý đầu tiên, rồi chảy liên tục tới khi đủ, không chạm rate limit (bộ điều phối hạn mức chung mọi shop), resumable.
7. Lớp ingestion + chuẩn hoá dùng chung nhiều shop và 2 sàn: TikTok trước, Shopee sau, không khoá vào TikTok.

## Nguyên tắc
Một câu mỗi lượt, kèm khuyến nghị; xây trên ADR hiện có (046, 104/105, 106, 107…); không ghi gì lên TikTok khi grill; production chỉ đọc, chủ shop tự chạy; quyết định → D-n → ADR + issue, mỗi phase một nhánh / PR, chủ shop merge.

## Checklist
1. [x] Hiện trạng (khảo sát 2026-10-20; truy vấn DB `juli-sim-pilot/research/db_check/fujiwa_db_coverage.sql` chờ chạy)
2. [x] Ranh giới nền tảng (D1)
3. [x] Backfill cold-start + bộ điều phối hạn mức (D2, D3)
4. [x] Phạm vi dữ liệu + lịch sử (D4, D5, D6)
5. [x] Mô hình bảng (D5 index, D7, D8)
6. [x] Vòng hành động (D9, D10, D11)
7. [x] Dữ liệu huấn luyện + cổng bật mô hình theo shop (D12, D13)
8. [x] Production (D14, D15)
9. [x] Chốt ADR / issue / phase (D16)

## Hiện trạng (tóm tắt khảo sát)
- Poll 15 phút (orders, products, returns, inventory, analytics A-31..A-39) chỉ cho shop production đã cấu hình (`shop_id=None`); shop khác chỉ qua nút làm mới thẻ. Backfill / reconcile hardcode `DEMO_REFERENCE_SHOP_ID` → impact reader `suppressed` cho shop khác.
- `products` chỉ trạng thái hiện tại; không có bronze cho sản phẩm / khuyến mãi / video.
- `analytics_performance_intervals`: không có clicks / add-to-cart, không tách kênh A-34.
- `card_events` (ADR-107) chưa xây; `gold.ml_feature_snapshots` không ai ghi; không có bảng lịch can thiệp.
- Không phân vùng, không retention; `persisted` đếm cả dòng DLQ (#1950).
- Rate limiter: Redis đếm theo cửa sổ cố định, khoá (app, shop, endpoint) (`integrations/tiktok/rate_limiter.py`).

## Quyết định
- **D1 (2026-10-20) — ranh giới nền tảng = A.** Adapter riêng từng sàn (xác thực, gọi API, phân trang, hạn mức) ghi bronze có `platform` + `endpoint` + `shop_id`; từ silver trở lên dùng chung: thực thể chuẩn ADR-009 khoá `(shop_id, platform_object_id)`, chỉ số tên trung tính + cột `channel`; bảng hạ tầng chuyển dần sang dạng chung (`platform_credentials`, `sync_state` có `platform`). Mô hình / đo tác động chỉ đọc silver.
- **D2 (2026-10-20) — điều phối = A.** Mọi lệnh gọi là một việc nhỏ `(platform, shop, endpoint, phân vùng ngày)` trong bảng `ops` (trạng thái, số lần thử, con trỏ trang → resumable). Ưu tiên P0 (danh mục + chi tiết / ảnh + hiệu suất sản phẩm 30 ngày) → P1 (lịch sử sâu, đơn, khuyến mãi, video / live) → P2 (poll định kỳ). Bộ điều phối token bucket theo (sàn, app, shop, nhóm endpoint), hạn mức từ cấu hình và tự hạ khi gặp mã rate limit; worker lấy việc ưu tiên cao nhất có token; round-robin giữa shop, luôn giữ phần cho P2. Dùng lại bộ đếm Redis + phân vùng ADR-029.
- **D3 (2026-10-20) — sẵn sàng dữ liệu = A.** Mức 1: P0 xong (danh mục + 30 ngày) → gợi ý đầu tiên nhãn "sơ bộ", chỉ đòn bẩy đủ đo trong 30 ngày. Mức 2: 90 ngày + đơn + khuyến mãi → bỏ nhãn sơ bộ, mở đòn bẩy cần nền dài (ADR-077: tiền kỳ 14 ngày + đối chứng). Mức 3: độ sâu tối đa từng endpoint (đo thật bằng lệnh đọc trên Fujiwa, ghi vào cấu hình adapter) → dữ liệu huấn luyện. Mức sẵn sàng lưu theo shop, một nguồn cho màn hình / bộ gợi ý / mô hình.
- **D4 (2026-10-20) — lịch sử sản phẩm = A.** Silver giữ phiên bản theo thay đổi (`valid_from` / `valid_to`), so mã băm các trường có ý nghĩa (tiêu đề, mô tả, URI ảnh theo thứ tự, giá / tồn từng SKU, trạng thái, danh mục) mỗi lần poll / backfill; bảng "hiện tại" để đọc nhanh; mỗi phiên bản ghi nguồn thay đổi (Juli thực thi ↔ `production_write_audit`, hay người bán tự sửa). Lịch sử trước ngày kết nối không có (API không trả lịch sử sửa).
- **D5 (2026-10-20) — hiệu suất = A, index hợp lý (chủ shop).** Silver mới khoá `(shop_id, product_id, ngày, channel)` (tổng / thẻ sản phẩm / video / live / affiliate / trang shop, tên trung tính); chỉ số đếm (impressions, clicks, add-to-cart, orders, units, gmv, visitors), tỷ lệ tính khi đọc; bảng phụ SKU × ngày, shop × ngày; kéo lại 7 ngày gần nhất mỗi ngày, silver cập nhật + `last_revised_at`, bronze giữ mọi bản; bảng cũ cutover theo domain (ADR-046). Index đề xuất (chốt ở bước mô hình bảng): PK `(shop_id, product_id, channel, ngày)` phục vụ chuỗi một sản phẩm (impact reader, panel); `(shop_id, ngày)` cho quét cả shop / ngày; covering INCLUDE các số đếm chính cho reader; BRIN theo ngày nếu phân vùng theo tháng.
- **D6 (2026-10-20) — phạm vi bản đầu = A.** Thu: khuyến mãi (dòng thời gian: loại, % giảm, SKU tham gia, bắt đầu / kết thúc), video + live (danh sách, ngày đăng, sản phẩm gắn, số liệu ngày), tồn kho theo ngày, đánh giá (số lượng + phân bố sao; nội dung để sau). Để sau: quảng cáo (scope riêng, ADR-029 đã loại), creator / affiliate chi tiết. Dữ liệu thị trường / đối thủ (FastMoss, Metric.vn) đi đường nghiên cứu riêng, không qua adapter shop.
- **D7 (2026-10-20) — phân vùng / giữ = A.** Phân vùng range theo tháng (Postgres gốc) cho hiệu suất sản phẩm / SKU / shop × ngày, lịch sử tồn kho, mọi bảng bronze; tác vụ `ops` hằng ngày tạo trước phân vùng tháng tới (không extension; chạy trên Supabase + Postgres 16 CI). Silver giữ vô thời hạn. Bronze giữ 13 tháng trong Postgres, rồi xuất phân vùng cũ ra kho lưu trữ (Parquet + mã băm + manifest) trước khi gỡ; phát lại được từ kho.
- **D8 (2026-10-20) — chuẩn hoá = A.** Worker ghi bronze + commit, rồi chạy bộ ánh xạ `(platform, endpoint)` idempotent sang silver; mỗi dòng silver có `bronze_id` + `mapper_version`; sửa ánh xạ → tăng version, phát lại từ bronze / kho (D7) qua hàng việc D2 ở ưu tiên thấp; payload ánh xạ lỗi nằm ở bronze với trạng thái lỗi, không tính "persisted" (đóng #1950); mỗi bộ ánh xạ có test bằng fixture thật đã ẩn thông tin (ADR-101). Shopee = thêm adapter + bộ ánh xạ + fixture.
- **D9 (2026-10-20) — nhật ký hành động = A.** Xây `card_events` (ADR-107) append-only nối theo `card_id`: đề xuất → hiển thị → duyệt / sửa / bỏ (lý do cố định) / hết hạn → thực thi → đọc tác động sơ bộ / cuối. Lúc đề xuất đóng băng thêm: phiên bản mô hình, mức sẵn sàng dữ liệu (D3), feature snapshot đã dùng. Sửa = ghi phần khác so với gốc. Thay đổi người bán tự làm ngoài Juli (từ lịch sử phiên bản D4) = sự kiện `seller_change`. Bảng hiện có giữ vai trò; view ADR-107 đọc từ `card_events`.
- **D10 (2026-10-20) — thử nghiệm = A, chỉ khi người bán đồng ý.** `experiments` (giả thuyết, đòn bẩy, chỉ số chính, cỡ mẫu / MDE, ngày, dự báo đăng ký trước khi kết thúc — luật D51.6) + `experiment_assignments` (sản phẩm, nhóm, seed, ảnh chụp điều kiện đủ, ngày áp dụng thật từ `card_events`). Người bán chọn tập sản phẩm "cho Juli thử"; Juli chia ngẫu nhiên trong tập; thực thi nhóm can thiệp sau khi duyệt (D9). Impact reader dùng đối chứng ngẫu nhiên khi có, không thì DiD; mô hình đọc lịch can thiệp để loại ngày bị can thiệp khỏi dữ liệu quan sát.
- Câu hỏi mở từ chủ shop (2026-10-20): hoàn tác; hành động ngoài gợi ý; theo dõi thay đổi người bán làm trên Seller Center → Câu hỏi 11.
- **D11 (2026-10-20) — hoàn tác / thay đổi ngoài Juli = A.** (1) Juli ghi: lưu ảnh trước (đọc lại ngay trước khi ghi) + ảnh sau của đúng các trường đổi + mã băm vào bản ghi thực thi. (2) Phát hiện: webhook sản phẩm (nếu TikTok có — CẦN XÁC MINH trong tài liệu API) → fetch có mục tiêu ưu tiên cao (D2); poll gia tăng theo `update_time` là lưới an toàn; khác biệt → phiên bản D4. (3) Quy nguồn theo trường: khớp ảnh sau Juli → `juli`; khớp ảnh trước → `seller_revert`; không khớp → `seller_change`; ghi `card_events` (D9). (4) Hoàn tác = lần ghi mới qua ủy quyền + audit, kiểm ba chiều: chỉ hoàn tác trường còn bằng ảnh sau Juli, khác thì dừng và hỏi. (5) Đo tác động: hoàn tác / sửa trong cửa sổ → cắt tại ngày đó, nhãn `reverted` / `confounded` (mở rộng ADR-077); thay đổi ngoài gợi ý đo như "hành động tự nhiên". (6) Khuyến mãi / giá cùng cách qua dòng thời gian D6.
- **D12 (2026-10-20) — dữ liệu huấn luyện = A.** (1) Mỗi dòng silver mang mốc "biết được lúc nào" (bronze `received_at`, phiên bản D4, `last_revised_at` D5); bộ dựng chỉ lấy dữ liệu đã biết trước mốc dự báo. (2) Feature snapshot lúc gợi ý ghi vào `gold.ml_feature_snapshots` + `feature_version`, nối `card_events` (D9). (3) Manifest mỗi bộ dữ liệu (shop, khoảng ngày, mapper / feature version, mã băm) → tái tạo được. (4) Sổ đăng ký cửa sổ kiểm tra trong Juli (theo ngày / shop / nhóm D10), bộ dựng + chọn mô hình từ chối đọc, chấm một lần (kỷ luật `ml_guard`). (5) Danh mục vai trò biến (đầu vào / hệ quả / rủi ro rò rỉ) có test tự động.
- **D13 (2026-10-20) — cổng bật mô hình = A.** (1) Offline: thắng cách hiện hành > 2 SE trên cửa sổ kiểm tra đã đăng ký (D12) + độ phủ khoảng đúng (luật Gate C). (2) Chạy ẩn trên shop thật: dự báo / gợi ý ghi `card_events` dạng `shadow`, không hiển thị, N tuần theo cỡ mẫu. (3) Bật theo nhóm shop / ngành đạt yêu cầu; nhóm thiếu dữ liệu giữ luật; chủ shop duyệt từng lần nâng bậc. (4) Giám sát tỷ lệ duyệt, tác động đo (ADR-077 / D10), độ phủ khoảng; tụt ngưỡng → tự lùi về phiên bản trước / luật, cảnh báo, ghi sự kiện.
- **D14 (2026-10-20) — chuyển đổi = A.** (1) Ghi song song lớp mới trên Fujiwa, phần đang chạy vẫn đọc bảng cũ, chung bộ điều phối hạn mức (D2). (2) Đối chiếu tự động hằng ngày: silver mới ↔ bảng cũ ↔ file A-34 script (bản chụp sim-pilot 08/10), ngưỡng chênh cho phép, đạt N ngày liên tục mới chuyển. (3) Chuyển từng domain (đơn → sản phẩm → hiệu suất → khuyến mãi / nội dung), mỗi domain một PR + cờ, lùi được; không ghi song song lâu dài (ADR-046). (4) Shop thứ hai trở đi chỉ sau khi Fujiwa chuyển xong ít nhất hiệu suất; mở theo danh sách cho phép rồi toàn bộ. (5) Bỏ hardcode `DEMO_REFERENCE_SHOP_ID`, thay `shop_id=None` bằng hàng việc theo shop.
- **D15 (2026-10-20) — mức production = A.** Test: (1) bộ ánh xạ trên fixture thật đã ẩn thông tin + phát lại (cùng bronze → cùng silver); (2) Postgres thật: phân vùng tạo / gỡ, upsert idempotent, phiên bản D4, kiểm ba chiều hoàn tác D11, RLS hai tenant cho mọi bảng mới; (3) bộ điều phối ~50 shop với API giả có rate limit: 429 dưới ngưỡng, P0 shop mới trong thời hạn, P2 shop cũ không trễ; (4) chịu lỗi: giết worker giữa backfill → chạy tiếp từ con trỏ, không mất / trùng; (5) hợp đồng adapter với sandbox TikTok (merge_group); (6) rò rỉ (D12); (7) đối chiếu D14 hằng ngày. Giám sát theo shop: độ tươi, độ đầy đủ so mức D3, tỷ lệ 429, độ trễ hàng việc, payload lỗi ánh xạ, verdict poll (ADR-105) — SLO + cảnh báo. Runbook: shop kẹt backfill, token hết hạn, phát lại ánh xạ, xuất kho bronze, lùi domain.
- **D16 (2026-10-20) — thứ tự = A (bật trước phần không backfill được).**
  - P0 xác minh chỉ đọc: webhook TikTok, độ sâu lịch sử từng endpoint, kết quả truy vấn DB.
  - P1 ghi sớm: `card_events` tối thiểu (D9), ảnh trước / sau khi Juli ghi (D11-1), phiên bản sản phẩm D4 cho Fujiwa trên poll hiện tại + bronze sản phẩm.
  - P2 nền tảng: hàng việc + bộ điều phối hạn mức (D2), bronze chung có `platform`, `sync_state` theo sàn, quản lý phân vùng (D7), khung giám sát (D15).
  - P3 adapter TikTok + ánh xạ: hiệu suất theo kênh (D5), sản phẩm, đơn / trả; ghi song song Fujiwa + đối chiếu (D14).
  - P4 nhóm D6: khuyến mãi, video / live, tồn kho ngày, đánh giá.
  - P5 cold-start nhiều shop: mức sẵn sàng (D3), bỏ hardcode, mở shop thứ hai trở đi.
  - P6 vòng hành động đầy đủ: quy nguồn + hoàn tác (D11), thử nghiệm (D10), impact reader.
  - P7 huấn luyện: bộ dựng theo mốc, sổ cửa sổ kiểm tra (D12), cổng mô hình (D13).
  - P8 adapter Shopee.
  - ADR: mới — nền tảng thu thập (D1–D3, D7, D8, D14, D15); mới — dữ liệu shop (D4–D6); sửa ADR-107 (D9, D11); mới — thử nghiệm (D10); mới — huấn luyện + cổng mô hình (D12, D13); ghi chú sửa ADR-029, 046, 077, 104.

## Việc cần xác minh
- [ ] TikTok webhook: có sự kiện khi người bán sửa tiêu đề / giá / ảnh / SKU / khuyến mãi không (tài liệu Partner Center) — D11 (2).
- [ ] Độ sâu lịch sử tối đa từng endpoint (đo trên Fujiwa, chỉ đọc) — D3.
- [ ] Kết quả `fujiwa_db_coverage.sql` (chủ shop chạy).
