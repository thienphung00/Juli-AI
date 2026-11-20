# Hướng dẫn chỉ số cho đội ngũ Juli Ops

Tài liệu nội bộ. Giải thích mọi con số và nhãn trên màn hình Shopee của Juli (Tổng quan, Phân tích, Quyết định, Dữ liệu shop,
Cài đặt, Ops): nghĩa là gì, tính thế nào, lấy từ bảng nào, và trả lời người bán ra sao.

Quy ước: **một bộ từ cho cả hệ thống**. Nhãn trên màn hình được viết **đúng nguyên văn**; khi nói với người bán, dùng đúng nhãn
đó. Từ của đội (tên bảng, tên trường, mã nội bộ…) chỉ dùng trong tài liệu này và khi nói chuyện nội bộ. Tài liệu gửi người bán là
`docs/chi-so/nguoi-ban-huong-dan-chi-so.md`; hai tài liệu dùng chung bảng thuật ngữ bên dưới (cùng hàng, cùng cột nhãn; test
`tests/unit/test_chi_so_docs_vocabulary.py` kiểm tra). Phần TikTok Shop nằm ở **Phụ lục** cuối tài liệu.

Nguồn đã đối chiếu khi viết (cập nhật 2026-11-20): `services/metrics/{registry,components,compute,allocation}.py`;
`services/shopee_analytics/{channel_split,metric_view,data_through,margins,loaders,shared}.py`; `services/shopee_profit/*`
(lợi nhuận, VAT); `services/shopee_recommendations/{forecast,prediction,learning,measure,running,execution_state,config,month_plan,stale}.py`;
`services/card_events/verification.py`; `services/exports/{tong_quan_xlsx,ke_hoach_xlsx,collect,profit_bridge}.py` (bản F8, PR #2342);
`services/planned_changes/external_rows.py`; `services/shop_inputs/importer.py`; `services/ingest/status.py`; giao diện
`apps/demo/src/components/{shopee-analytics,shopee-decisions,connector,ops,shop-inputs}/*`; Connector
`apps/connector/src/platforms/shopee/{config.ts,background/scheduler.ts,popup/guide.ts}`.

## Bảng thuật ngữ

| Nhãn trên màn hình | Ý nghĩa | Cách tính |
|---|---|---|
| **Tổng quan** | Màn hình đầu: số tổng của shop (hoặc một sản phẩm) trong kỳ đã chọn, kèm thay đổi so với kỳ trước cùng độ dài. | `channel_split.channel_split`: `kpis`, `kpis_prev` (cùng số của `Window.previous()`), `rows`, `plan`, `data_through`. |
| **Phân tích** | Xem từng chỉ số một: theo luồng và theo sản phẩm, kèm bước tiếp theo (Đề xuất hoặc Tự tạo). | `metric_view`: mỗi hàng `now`, `prev`, `change`, `impact`; đếm thẻ mở theo chỉ số (`METRIC_OF_KPI`). |
| **Quyết định** | Nơi Juli đề xuất việc cần làm và theo dõi kết quả, qua ba bước Đề xuất, Thực hiện, Đo lường. | Nhãn dùng chung `ACTIONS_DESTINATION_LABEL`; ba tab `TABS` (`de-xuat`, `thuc-hien`, `do-luong`). |
| **Dữ liệu shop** | Số liệu gốc theo loại: Sản phẩm, Từ khóa, Dịch vụ hiển thị, Đơn hàng, Luồng. | Một mục điều hướng với năm tab con (`DATA_SHOP_TABS`); shop mẫu chỉ có Sản phẩm. |
| **Đề xuất** | Các thẻ Juli (hoặc bạn) đề xuất, chưa làm gì trên Shopee. | `reco.list` (hàng chờ thẻ mở; người bán thấy thẻ đã xuất bản, Ops thấy cả nháp). |
| **Thực hiện** | Các thẻ đã duyệt: Connector điền, bạn lưu, Juli xác minh. | `execution_state.derive_state` từ sự kiện `executed` / `verified` / `mismatch` / `not_seen` và lệnh điền `shopee_fill_jobs`. |
| **Đo lường** | Kết quả thật của từng thẻ đã thực hiện, đo từng ngày. | `running.build_actual` (Thực tế, hiện tại, Δ) và `execution_state.measurement_row` (nhãn kết luận). |
| **Kế hoạch** | Mục tiêu GMV và Lợi nhuận của kỳ, từ các thẻ đang chạy: nền cộng phần tăng thêm dự kiến. | `month_plan.range_plans`: `goal = baseline + uplift`; baseline = mức 30 ngày đã đóng băng của kế hoạch chạy sớm nhất ÷ `HORIZON_DAYS` (30) × số ngày; uplift = tổng P50 Δ của thẻ đang chạy, trải đều trên ngày của thẻ và chỉ tính ngày trong kỳ. Không có thẻ chạy → `goal = None`. |
| **Kế hoạch nháp** | Các thẻ bạn gom lại để xem tổng chênh lệch và duyệt một lượt. | Kế hoạch `draft` của shop (`plans.get_plan(None)`); thêm thẻ không chạy gì, chỉ `Duyệt kế hoạch` mới duyệt. |
| **Cả kế hoạch** | Kỳ xem lấy theo ngày bắt đầu đến ngày kết thúc của các thẻ đang chạy. | `period = plan`: `month_plan.running_range`, cắt ở ngày dữ liệu mới nhất; không có thẻ chạy thì về 30 ngày. |
| **Tùy chọn** | Kỳ xem do bạn chọn từ ngày – đến ngày (một tháng lịch cũng là Tùy chọn). | `period = custom` với `from`, `to` (GMT+7). |
| **Trung bình / ngày** | Cùng số liệu nhưng chia cho số ngày của kỳ. | `inMode`: `total ÷ days` cho số cộng được; các tỷ lệ không chia. |
| **Số liệu đến** | Ngày cuối cùng mà số liệu của khối đó đã đủ (hiện dạng "Số liệu đến dd/mm"). | `data_through`: ngày **cũ nhất** trong các bộ số liệu của khối (`SECTION_DATASETS`), không quá ngày cuối của kỳ; mỗi bộ lấy ngày mới nhất có hàng (`load_freshness`). |
| **Cập nhật** | Lần gần nhất Juli nhận số liệu từ shop của bạn. | `max(coalesce(last_captured_at, last_ingest_at))` của mọi bộ số liệu (`ingest_dataset_status`). |
| **Tải Excel** | Tải số liệu đang xem về tệp Excel. | `exports.tong_quan_xlsx` (Tổng quan) và `exports.ke_hoach_xlsx` (Kế hoạch nháp); mục 12. |
| **GMV** | Doanh số của shop theo Seller Centre. | Tổng của Seller Centre (`shop_overview.gmv`), không tự tính từ dòng đơn (owner T8). Mỗi nơi chỉ có một nguồn GMV. |
| **Đơn hàng** | Số đơn theo Seller Centre. | `shop_overview.orders`. Hoàn tiền không tính (GLOSSARY D2). |
| **AOV** | Giá trị trung bình của một đơn. | `gmv ÷ orders` (tính từ tổng). |
| **Lượt xem** | Số lần khách thấy sản phẩm. | `traffic_overview.views` theo nguồn; Tiếp thị liên kết không có. |
| **Lượt nhấp** | Số lần khách bấm vào sản phẩm. | `traffic_overview.product_clicks` theo nguồn. |
| **CTR** | Trong 100 lượt xem có bao nhiêu lượt nhấp. | `clicks ÷ views` (cộng cả kỳ rồi chia). Dòng DVHT: trên những ngày có đủ cả hai số. |
| **CTOR** | Trong 100 lượt nhấp có bao nhiêu thành đơn. | `orders ÷ clicks`. Dòng DVHT: đơn đã đặt ÷ clicks. |
| **Lợi nhuận** | Tiền còn lại sau giá vốn, phí sàn, đóng gói, vận chuyển, quảng cáo, tiếp thị liên kết (ưu đãi đã trừ trong doanh thu), theo thiết lập VAT của shop. | `known_cost_profit`: Σ (doanh thu thực − giá vốn − đóng gói − phí sàn − vận chuyển − hoa hồng AFF) trên đơn có chi phí − quảng cáo tính vào − chi phí marketing khác; mục 3.1. |
| **Tổng chi phí** | Quảng cáo + Tiếp thị liên kết + Ưu đãi của kỳ. | `kpis_of`: `cost_ads + cost_affiliate + cost_offers`; `None` nếu không khoản nào biết. (Excel Tổng quan chỉ cộng QC + AFF: mục 3.2.) |
| **Ưu đãi** | Khuyến mãi, voucher của shop và combo đã áp dụng cho đơn; đã được trừ sẵn vào số tiền khách trả. | `promo_discount + voucher + bundle` của các dòng đơn (`_offers_cost`); không trừ lần hai trong lợi nhuận. |
| **ROI** | Lợi nhuận chia cho Tổng chi phí; một số lần, không phải phần trăm. | `profit ÷ cost_total` (màn hình, `kpis_of`); `None` khi chi phí = 0. Hiện một chữ số thập phân. |
| **Biên lợi nhuận** | Phần lợi nhuận trong doanh thu thực của kỳ. | `margin = profit ÷ net_revenue_known` (đơn có chi phí). Excel Tổng quan chia cho GMV. |
| **Biên ở giá bán** | Biên của một đơn vị ở giá bán hiện tại, chỉ cần giá bán và giá vốn. | `(price_after_vat − fees − cogs − packaging) ÷ price_after_vat` (`variations.margin_pct`); thiếu giá vốn → "chưa tính". |
| **Biên cuối** | Biên ở giá bán trừ phần voucher, hoa hồng và quảng cáo thật của 30 ngày gần nhất. | `margins.final_margin = Biên ở giá bán − 100 × (voucher + hoa hồng + quảng cáo)` theo tỷ lệ đo 30 ngày; `final_margin_basis` = variation \| product. |
| **GMV ảnh hưởng** | Số tiền GMV mà riêng thay đổi của chỉ số này giải thích được (âm là đã mất). | `metric_view.impact_of`: GMV: Δ; Đơn: Δđơn × AOV trước; AOV: ΔAOV × đơn nay; Lượt xem: Δviews × GMV/lượt trước; CTR: ΔCTR × views nay × CTOR trước × AOV trước; CTOR: ΔCTOR × clicks nay × AOV trước; Biên: Δbiên × GMV nay. |
| **Thay đổi** | Tăng hay giảm so với kỳ liền trước có cùng số ngày (▲ / ▼). | `(now − prev) ÷ prev`, `None` khi `prev ≤ 0` hoặc thiếu (`change_of`). |
| **Kỳ này** | Giá trị trong kỳ đang xem. | Cột `now` của `metric_view`. |
| **Kỳ trước** | Giá trị trong kỳ liền trước cùng độ dài. | Cột `prev`: cùng chỉ số trên `Window.previous()`. |
| **Organic** | GMV không đến từ quảng cáo hay tiếp thị liên kết: Thẻ sản phẩm, Trang shop, Video, Live. | Tổng bốn dòng con (mục 2); cấp Sản phẩm: phần dư của GMV sản phẩm sau quảng cáo và liên kết. |
| **Quảng cáo** | GMV đến từ quảng cáo (phần "trong đó Quảng cáo" của Thẻ sản phẩm) và chi phí quảng cáo. | GMV: lớp phủ `traffic_overview.ads_overlay`, đơn đã xác nhận; chi phí: `ads_report.expense` (một trình giải: `ads_days`). |
| **Tiếp thị liên kết** | GMV, đơn và hoa hồng của các KOL. | GMV: nguồn `lien_ket`; chi phí = hoa hồng `affiliate_lines.commission`; không có Lượt xem. |
| **Thẻ sản phẩm** | Khách thấy sản phẩm dạng thẻ (tìm kiếm, gợi ý) ngoài Trang shop. | Organic: `the_san_pham_khac` + phần dư − "trong đó Quảng cáo", mỗi ô ≥ 0. |
| **Trang shop** | Khách vào trang cửa hàng của bạn (Tab cửa hàng của Shopee). | Nguồn `trang_shop`. |
| **Video** | Video bạn đăng có gắn sản phẩm. | Nguồn `video`. |
| **Live** | Phiên Live bạn phát. | Nguồn `live`. |
| **DVHT Sản phẩm** | Dịch vụ hiển thị Sản phẩm: quảng cáo sản phẩm, rơi vào Thẻ sản phẩm. | Báo cáo quảng cáo, mọi loại trừ Shop+ (`is_shop_plus`); đơn đã đặt. |
| **DVHT Shop+** | Dịch vụ hiển thị Shop+: quảng cáo shop, rơi vào Trang shop (cùng thực thể với Trang shop). | Báo cáo quảng cáo, loại `ads_shop` (tệp) hoặc `shop_*` (Connector); đơn đã đặt. Cấp Sản phẩm không có. |
| **% GMV** | Phần GMV của luồng trong GMV cả shop. | `share = gmv_dòng ÷ gmv_tổng`; `None` ở dòng `ads_report`. |
| **Lưu lượng** | Nhãn nhỏ: số của dòng lấy từ báo cáo lưu lượng (cơ sở đơn đã xác nhận). | `ad_base = traffic_overview`. |
| **Báo cáo DVHT** | Nhãn nhỏ: số của dòng lấy từ báo cáo quảng cáo (cơ sở đơn đã đặt). Không cộng với Lưu lượng. | `ad_base = ads_report`. |
| **CPA** | Chi phí quảng cáo cho mỗi đơn quảng cáo. | `spend ÷ orders` (đơn trực tiếp điều chỉnh theo tỷ lệ huỷ; thẻ: `AdsEvaluation.cpa_now / cpa_after`). |
| **CPA hoà vốn** | CPA tối đa để quảng cáo không lỗ: lợi nhuận mỗi đơn trước quảng cáo. | `profit_per_order_before_ads` của sản phẩm trong chiến dịch (`break_even_cpa`); thiếu giá vốn → "chưa tính". |
| **ROAS Shopee** | GMV quảng cáo chia cho chi phí quảng cáo, chỉ để tham khảo. | `ads_gmv_platform ÷ cost_ads` (đơn đã đặt, "broad"); `roas_direct` = GMV trực tiếp ÷ chi phí. |
| **ROAS hoà vốn** | Mức ROAS cần đạt để quảng cáo không lỗ. | `roas_break_even = net_revenue_known ÷ contribution`, `contribution = profit + ads_spend`. |
| **ΔGMV / chi phí** | Mỗi đồng chi phí của thẻ mang lại bao nhiêu GMV tăng thêm. | `card_return = card_delta_gmv ÷ card_cost` (nhãn `CARD_RETURN_LABEL`). |
| **Duyệt** | Bạn đồng ý để Juli chuẩn bị thực hiện thẻ; thẻ chuyển sang Thực hiện. | `approve(chosenVersion, acknowledgeBreaches)`; chỉ người bán duyệt, Ops không duyệt thay. |
| **Duyệt kế hoạch** | Duyệt một lượt mọi thẻ trong Kế hoạch nháp. | `plans.confirm`; vi phạm sàn / trần ghi lại xác nhận kèm giờ. |
| **Tự tạo** | Thẻ do chính bạn tạo bằng "Tự tạo phương án". | `origin = manual`; Excel Nguồn = Tự tạo; chỉ số học riêng, không đổi hệ số của engine. |
| **Lợi nhuận dự kiến** | Lợi nhuận nếu thẻ chạy đủ số ngày: một con số, kèm số ngày. | `forecast.metrics.profit.du_kien = hien_tai + delta` (delta = P50 của engine), trên N ngày của thẻ. |
| **GMV dự kiến** | GMV nếu thẻ chạy đủ số ngày. | `forecast.metrics.gmv.du_kien`. |
| **Đơn dự kiến** | Số đơn nếu thẻ chạy đủ số ngày. | `forecast.metrics.orders.du_kien`. |
| **AOV dự kiến** | AOV nếu thẻ chạy đủ số ngày. | `forecast.metrics.aov.du_kien` (GMV ÷ đơn của kịch bản `likely`). |
| **hiện tại** | Mức nền của chính phạm vi thẻ, quy ra cùng số ngày của thẻ (dòng xám: "hiện tại: … · ±Δ"). | Thẻ: `result.before` = số mỗi ngày trên 30 ngày × N. Đo lường: tổng k ngày ngay trước ngày bắt đầu. |
| **Thực tế** | Con số thật của các ngày đã đo ("Thực tế: A đ · hiện tại: B đ · +Δ"). | `running.totals` trên các ngày đã đo (`product_metrics_daily` / `shop_metrics_daily`); Δ = thực tế − hiện tại; ngày thiếu dữ liệu không tính. |
| **Đã đo** | Số ngày đã đo trên tổng số ngày của thẻ ("Đã đo k/N ngày"). | `label = f"Đã đo {k}/{n} ngày"`; `k` = số ngày từ ngày bắt đầu tới ngày có dữ liệu đơn mới nhất. |
| **đo chung với** | Các thẻ khác của cùng sản phẩm (hoặc cả shop) chạy chồng lên, được đo thành một nhóm. | `running.group_sets`: cùng phạm vi + sản phẩm, cửa sổ chồng hoặc `cut_by_change_set`; kết quả nhóm không sạch (không học). Excel: Đo chung với. |
| **Đo trong bao lâu** | Số ngày đo của kế hoạch (trong Kế hoạch nháp). | `window_days`: Tự động theo sản phẩm (ngắn nhất có MDE ≤ 30 %) \| 7 / 14 / 28 \| Tuỳ chọn 3–90 (`WINDOW_MIN_DAYS`, `WINDOW_MAX_DAYS`). |
| **Chờ điền** | Đã duyệt, Connector chưa điền. | `cho_dien`: chưa có lệnh điền `filled`. |
| **Đã điền · chờ bạn lưu** | Connector đã điền form trên Shopee; việc còn lại là của bạn. | `da_dien`, `completed = 2`; lệnh `filled` / `saved` / `captured` với `progress.filled == total`, hoặc người bấm Đã làm. |
| **Đã lưu · chờ xác minh** | Bạn đã báo đã làm; Juli chờ đọc lại Seller Centre. | `da_dien` có `executed_at` hoặc `completed ≥ 3`; `not_seen` → "Chưa thấy thay đổi". |
| **Khớp Seller Centre** | Seller Centre đang đúng như thẻ; đồng hồ đo bắt đầu. | `khop`: sự kiện `verified` (lần đọc đầu tiên sau `executed_at` thấy đúng giá trị); `measure_start` = lúc đó. |
| **Lệch Seller Centre** | Seller Centre hiện giá trị khác thẻ. | `lech`: `mismatch` ở hạn `VERIFY_WINDOW` = 48 h; kèm trường, giá trị đọc được và giá trị thẻ. |
| **Mở Seller Centre** | Mở trang Shopee cần sửa để Connector điền sẵn; bạn tự kiểm tra và bấm Lưu. | `fillJobHref(open_job)`: `#juli-fill=<job id>`; Connector không bấm nút nào trên Shopee. |
| **Đã làm** | Bạn báo đã lưu thay đổi trên Shopee. | `reco.executed(card, { voucherId? })` → sự kiện `executed`; voucher cần mã Seller Centre để đọc lại. |
| **Hoàn tác** | Các bước đưa nội dung cũ trở lại; Juli không bao giờ tự hoàn tác. | `RevertBlock`: `revertFill` xếp lệnh điền cho giá trị cũ; `Đã hoàn tác` cần lệnh `ready`. |
| **Đã hoàn tác** | Bạn đã đưa nội dung về như cũ; thẻ dừng đo. | `state = hoan_tac`: ghi người + giờ, dừng đo, loại khỏi dữ liệu học. |
| **Đối chiếu ngay** | Bảo Juli Connector đọc lại để xác minh các thẻ đang chờ. | `POST …/execution/reconcile` → `connector_state.request_reconcile`; không mở được chặn `traffic_check` trước `until`. |
| **Đang đo** | Thẻ còn trong thời gian đo. | `VERDICT_RUNNING = dang_do` (chưa đủ N ngày). |
| **Trong khoảng** | Đo đủ ngày: lợi nhuận thật nằm trong khoảng Juli dự kiến lúc duyệt. | `Δ lợi nhuận` giữa P10 và P90 của dải lúc duyệt (`running.verdict_of`) hoặc thay đổi tương đối trong P10–P90 lift (`execution_state.verdict_of`). |
| **Dưới khoảng** | Đo đủ ngày: lợi nhuận thật thấp hơn khoảng dự kiến. | `Δ < P10` của dải. |
| **Vượt khoảng** | Đo đủ ngày: lợi nhuận thật cao hơn khoảng dự kiến. | `Δ > P90` của dải. |
| **Nhập thẻ đã làm ngoài Juli** | Nhập từ tệp .xlsx các thay đổi bạn đã làm ngoài Juli để Juli đo kết quả. | `planned_changes.external_rows` + `import_job`; mục 11.1. Thẻ có `origin = external`, Nguồn = Làm ngoài Juli. |
| **Juli Connector** | Tiện ích Chrome đọc báo cáo Seller Centre (chỉ đọc) và điền sẵn form khi bạn duyệt thẻ. | `apps/connector`: reader + scheduler (mục 10); hạn mức `DAILY_REQUEST_BUDGET = 800` / ngày. |
| **Đồng bộ hôm qua** | Nút trong tiện ích: đọc ngay số liệu của ngày vừa kết thúc và thử lại các trang đang bị chặn. | `tick({ manual })`: nâng chặn đăng nhập / CAPTCHA, đọc lại trang chưa gửi; không nâng `traffic_check`. |
| **Juli đã nhận gì** | Bảng cho thấy từng loại số liệu: đến ngày nào, nhận lúc nào. | `GET /v1/ingest/status` (`ingest/status.dataset_status`): `last_period_end`, `last_ingest_at`, `drift`. |
| **Máy cũ** | Các máy tính đã kết nối nhưng quá 14 ngày không thấy; có thể gỡ cùng lúc. | `splitMachines`: `last_seen_at` (hoặc `last_used_at`, `created_at`) cách đây ≥ `INACTIVE_DAYS = 14`; `Gỡ tất cả máy cũ` thu hồi token. |
| **Thông số shop** | Giá vốn, đóng gói, tồn kho, VAT và mục tiêu bạn nhập bằng tệp .xlsx. | Quy tắc theo SKU / tháng (`shop_rules`) có phiên bản; mục 11.2. |

## 1. Tab, kỳ xem và chế độ xem số

- Thanh điều hướng Shopee: **Tổng quan**, **Phân tích**, **Quyết định**, **Dữ liệu shop** (và tab Juli khi shop được bật:
  `/v1/demo/juli/enabled`). Cài đặt ở menu ảnh đại diện shop. Tab Juli là batch riêng, chưa có trong nhánh này; kiểm tra lại
  khi nó được gộp.
- Kỳ xem: 7 / 30 / 90 ngày, **Tùy chọn** (từ – đến), **Cả kế hoạch** (`period = plan`: khoảng ngày của các thẻ đang chạy, cắt ở
  ngày dữ liệu mới nhất; không có thẻ chạy thì chuyển về 30 ngày và nút mờ). Không có nút đổi kỳ so sánh: kỳ trước luôn là
  khoảng liền kề trước, cùng độ dài (`Window.previous()`).
- **Tổng** | **Trung bình / ngày** (`cach=tb` trên URL): tổng chia cho số ngày của kỳ cho các số cộng được (GMV, đơn, lượt xem, tiền);
  các tỷ lệ (CTR, CTOR, AOV, biên, % GMV) giữ nguyên.
- **Thay đổi** = (kỳ này − kỳ trước) ÷ |kỳ trước|; `None` khi kỳ trước bằng 0 hoặc thiếu. Hiển thị `▲ 12 %`, một chữ số thập phân khi < 10 %.
- ROI hiện là số lần một chữ số thập phân ("5,4"), không bao giờ là %.

## 2. Phễu, luồng và hai cơ sở quảng cáo

Phễu: `GMV = Lượt xem × CTR × CTOR × AOV`. Các tỷ lệ luôn là tỷ lệ của tổng (cộng tử, cộng mẫu, rồi chia).

**Nguồn luồng** (Seller Centre, bảng `traffic_overview`): `the_san_pham_khac` (Thẻ sản phẩm), `trang_shop`, `live`, `video`,
`lien_ket` (Tiếp thị liên kết) và phần dư `chenh_lech_nguon`. Một dòng bảng luồng của Tổng quan (`channel_split.split_rows`):

| Dòng | Lượt xem / Lượt nhấp / Đơn / GMV |
|---|---|
| **Organic** | tổng bốn dòng con (không để con thiếu số làm trống cha nếu Thẻ sản phẩm có số) |
| ↳ **Thẻ sản phẩm** | (Thẻ sản phẩm + phần dư) − phần "trong đó Quảng cáo", mỗi ô kẹp ≥ 0 |
| ↳ **Trang shop**, **Video**, **Live** | số của nguồn tương ứng |
| **Quảng cáo** (tag **Lưu lượng**) | "trong đó Quảng cáo" của Thẻ sản phẩm (xem dưới) |
| ↳ **DVHT Sản phẩm**, **DVHT Shop+** (tag **Báo cáo DVHT**) | báo cáo quảng cáo, đơn đã đặt; DVHT Shop+ = `is_shop_plus` (tệp `ads_shop`, Connector `shop_*`); DVHT Sản phẩm = mọi loại còn lại |
| **Tiếp thị liên kết** | chỉ lượt nhấp, đơn, GMV; Lượt xem = `None` |

**Hai cơ sở quảng cáo không bao giờ cộng với nhau:** "trong đó Quảng cáo" của báo cáo lưu lượng (đơn đã xác nhận, một cơ sở đơn
với các nguồn) và báo cáo quảng cáo (đơn đã đặt). Quy tắc chọn ô (B.4a): nếu lớp phủ có lượt nhấp thì **Quảng cáo** lấy lượt xem /
lượt nhấp từ lớp phủ; không có thì lấy impressions / clicks của báo cáo quảng cáo (mọi loại trừ Shop+). Đơn và GMV của Quảng cáo luôn từ
lớp phủ (cơ sở xác nhận; nếu chỉ có hàng đã đặt thì nhân với tỷ lệ xác nhận ÷ đặt của chính Thẻ sản phẩm: `materialize.ads_overlay`).
Dòng DVHT: CTR = clicks ÷ impressions, CTOR = đơn ÷ clicks, cả hai trên những ngày có đủ cả hai số (`ad_rate_basis`).

**`share`** (% GMV) = GMV dòng ÷ GMV tổng (`base.total("gmv")`); `None` ở dòng `ad_base = ads_report` hoặc khi tổng bằng 0.

**Ở cấp Sản phẩm** (`_partition_product_rows`, C4): ba kênh cộng lại bằng GMV sản phẩm: Quảng cáo kẹp ở tổng, Tiếp thị liên kết lấy phần còn
lại, Organic = phần dư; Thẻ sản phẩm (con) là phần dư của Organic sau Trang shop / Video / Live. Giá trị Quảng cáo gốc giữ ở `overlay_gmv`.
Không có nguồn nào cho sản phẩm thì Organic = GMV sản phẩm − quảng cáo − liên kết, không âm.

## 3. Lợi nhuận, chi phí, ROI và các mức biên

### 3.1 Lợi nhuận (`shop_profit_of` = `known_cost_profit`)

Một đơn "có chi phí" khi **mọi** dòng được tính của đơn đó có đủ giá vốn, phí, đóng gói, hoa hồng; đơn khác bị bỏ khỏi lợi nhuận,
khỏi mẫu số của biên, khỏi phần chia quảng cáo, và tính vào độ phủ (`cost_coverage = cogs_known_gmv ÷ line_gmv`). Không có đơn nào có
chi phí thì Lợi nhuận là `None` ("—"), không phải 0.

```
profit = Σ doanh thu thực (đơn có chi phí)
       − giá vốn − đóng gói − phí sàn − vận chuyển shop chịu (shipping_net) − hoa hồng AFF
       − quảng cáo tính vào − chi phí marketing khác (other_marketing_costs, Thông số shop)
net_revenue (buyer_paid) = giá bán × SL − voucher shop − combo − VAT đầu ra   # 0 với hoàn tiền "accepted"
```

- Phí sàn: phí thật (`order_income`: income / actual) thắng; không có thì tính theo biểu phí (`fee_table`).
- Giá vốn: `sku_cost × pack_count` (hoặc `pack_components`), trừ phần VAT đầu vào khi `cost_includes_vat` (mục 4).
- Đóng gói: `packaging_cost`; không có quy tắc = 0 và gắn cờ "chưa nhập chi phí đóng gói".
- Quảng cáo (R11, `ADS_SHARE_DAILY`): chi phí từng ngày (một trình giải duy nhất: `ads_days`) × (GMV đơn có chi phí ÷ GMV mọi đơn của ngày đó);
  ngày có chi phí nhưng **không có đơn nào**, trong số ngày mà dữ liệu đơn nói được (`order_data_days`), tính nguyên vào dòng riêng
  `NO_ORDER_DAYS_ADS_LABEL`; ngày ngoài dữ liệu đơn không tính (thiếu ≠ 0). Chi phí marketing khác chia theo tỷ trọng cả kỳ.
- Đơn huỷ / đang giao: ngoài lợi nhuận (vẫn nằm trong GMV theo Seller Centre). Hoàn tiền (`returned`, `refunded_accepted`,
  `refunded_not_received`): doanh thu 0, không tính vào số đơn / GMV / AOV; chi phí hoàn = `max(0, −payout)` của dòng đối soát
  (chưa có dòng đối soát = chưa có chi phí) — quy tắc D2 của GLOSSARY.
- Ưu đãi (`promo + voucher + combo`): đã nằm trong số tiền khách trả; hiện ở Tổng quan nhưng không trừ lần hai khi tính lợi nhuận.

Bảng **Lợi nhuận** của tệp Excel (`profit_bridge`) cộng được đúng bằng số này (tới từng đồng, cộng sai số làm tròn theo dòng) và ghi từng
khoản là "Thật" hay "Giả định" theo `real_pct`.

### 3.2 Tổng chi phí và ROI (hai nơi hai cách)

| Nơi | Tổng chi phí | ROI |
|---|---|---|
| Màn hình Tổng quan (`kpis_of`) | Quảng cáo + Tiếp thị liên kết + Ưu đãi (cộng các khoản biết được; `None` nếu không khoản nào biết) | Lợi nhuận ÷ Tổng chi phí; `None` khi chi phí = 0 hoặc thiếu |
| Tệp Excel Tổng quan (`cost_of`) | Quảng cáo + Tiếp thị liên kết; Ưu đãi chỉ hiện, không cộng ("đã trừ trong doanh thu") | `ROI (lợi nhuận ÷ chi phí QC + AFF)` |
| Registry `roi` | `cost_marketing` = `cost_ads + cost_affiliate + cost_offers` | `profit ÷ cost_marketing` |
| Registry `cost_total` (chưa nối vào màn hình) | tám khoản gồm giá vốn, đóng gói, phí sàn, vận chuyển, quảng cáo, liên kết, ưu đãi, chi phí khác | — |

Màn hình và registry giống nhau; Excel và GLOSSARY ("Ưu đãi is deducted from revenue, never a cost", chủ 2026-11-18, phương án A) khác.
Nếu người bán so ROI trên màn hình với ROI trong Excel mà lệch, đây là nguyên nhân (mục 13).

### 3.3 Các mức biên

| Nhãn | Cách tính | Nơi hiện |
|---|---|---|
| **Biên lợi nhuận** (màn hình) | `margin = profit ÷ net_revenue_known` (đơn có chi phí) | Phân tích (chip), trang sản phẩm, thẻ ("Biên lợi nhuận a % → b %") |
| **Biên lợi nhuận** (Excel Tổng quan) | Lợi nhuận ÷ **GMV** ("Biên lợi nhuận (% GMV)") | Tệp Excel |
| **Biên ở giá bán** | `margin_sale = (price_after_vat − fees − cogs − packaging) ÷ price_after_vat`, một đơn vị ở giá bán hiện tại (`variations.margin_pct`); không có giá vốn → `None` / "chưa tính" (không bao giờ dùng 1/3 giá) | Trang sản phẩm, so sánh phân loại, combo |
| **Biên cuối** | `Biên ở giá bán − 100 × (voucher + hoa hồng + quảng cáo)`, các tỷ lệ đo 30 ngày trên số tiền khách trả (`margins.final_margin`); quảng cáo chia cho các SKU của sản phẩm theo doanh thu; `final_margin_basis` = `variation` hoặc `product` | cùng nơi |

Ghi chú tên: GLOSSARY còn ghi hai biên là "Biên cuối ở giá hiện tại" và "Biên thực hiện 30 ngày"; trên màn hình hiện là **Biên ở giá
bán** (chắc chắn) và **Biên cuối** (ước tính). Dùng nhãn trên màn hình khi nói với người bán.

### 3.4 Các chỉ số khác trong registry

`aov = gmv ÷ orders`; `ctr = clicks ÷ views`; `ctor = orders ÷ clicks`; `roas = ads_gmv_platform ÷ cost_ads` (đơn đã đặt, gọi là
**ROAS Shopee** ở thẻ quảng cáo); `roas_direct = ads_gmv_direct ÷ cost_ads` (ROAS trực tiếp); `roas_break_even = net_revenue_known ÷ contribution` với
`contribution = profit + ads_spend` (lợi nhuận trước quảng cáo; nhãn **ROAS hoà vốn**); `card_return = card_delta_gmv ÷ card_cost`
(nhãn **ΔGMV / chi phí**, đo trên các đơn tăng thêm). CPA: xem mục 5.3. Mọi tỷ lệ cộng thành phần trước rồi chia; thành phần thiếu → `None`.
Làm tròn: đồng nửa lên, % và x một chữ số (`shopee_profit/money.py`). Đổi công thức = nâng `DERIVATION_VERSION`
(hiện `2026-11-15.1`) và sinh lại `registry.generated.ts`.

## 4. Thuế VAT (mặc định và theo sản phẩm)

Màn hình: Ops › Cài đặt shop › **Thuế VAT** (`ops-vat.tsx`, chỉ Vận hành+ ghi, Xem chỉ đọc).

- **Mặc định** (`vat_rate_default`): 0 / 5 / 8 / 10 % hoặc **Chưa đặt** (xoá dòng quy tắc). Ghi qua `PUT /rules/vat_rate_default`.
- **Theo sản phẩm** (`vat_rate`): tìm sản phẩm, bấm 0 / 5 / 8 / 10 %. Giao diện ghi thuế suất cho `item_id` **và** cho từng biến thể
  (`item_id:variation_id`) để dòng đơn có hay không có biến thể đều đọc được; **Bỏ** xoá tất cả các dòng đó.
- Thứ tự tra thuế suất cho một dòng đơn (`engine.py`): quy tắc của biến thể → của SKU gốc → thuế suất của cả sản phẩm (các biến thể
  đồng ý) → `vat_rate_default`. Không có cả bốn: lợi nhuận của dòng `None` (lý do `vat_rate` thiếu), **không bao giờ tính 0 %**.
- Hai cờ cho cả shop, `prices_include_vat` ("Giá bán đã gồm VAT") và `cost_includes_vat` ("Giá vốn đã gồm VAT"), ngầm định **chưa đặt** (người bán
  khai trong tệp Thông số shop). Chưa đặt `prices_include_vat` thì không trừ VAT đầu ra khỏi doanh thu:
  - `prices_include_vat = true`: `VAT đầu ra = round(buyer_paid − buyer_paid ÷ (1 + r))`, doanh thu thực = buyer_paid − VAT đầu ra.
  - `cost_includes_vat = true`: giá vốn tính = giá vốn − `round(giá vốn − giá vốn ÷ (1 + r))` (VAT đầu vào được khấu trừ).
  - Cờ `false` hoặc chưa đặt: không điều chỉnh.
- Phí Shopee không điều chỉnh. Không tính thuế khấu trừ (GTGT, TNCN) — quy tắc chủ 2026-11-15.
- Đổi thuế suất, cờ VAT, giá vốn, đóng gói, loại trừ, biểu phí, mục tiêu hay trần chi tiêu làm đổi **dấu vân tay đầu vào** của thẻ (`freshness.fingerprint`), nên thẻ liên quan thành cũ (`inputs_changed`) và job làm mới tự tính lại; muốn ngay, bấm **Tính lại thẻ cũ** (mục 8).

## 5. Thẻ: hiện tại, dự kiến, thực tế

### 5.1 Khối `forecast` của một thẻ (`forecast.py`, F7)

Mỗi chỉ số (`profit`, `gmv`, `orders`, `aov`, `margin_pct`) có `{hien_tai, du_kien, delta, delta_pct, low, high, days}` trên **N ngày của chính thẻ**:

- `hien_tai` = `result.before`: số mỗi ngày của shop (hoặc sản phẩm) trên cơ sở 30 ngày (`HISTORY_DAYS`) nhân N. Thẻ 7 ngày mang 7 ngày, không phải 30.
- `delta` = tác động P50 của engine (cột `likely` − `before`); `du_kien = hien_tai + delta`.
- `low` / `high` = hiện tại + tác động P10 / P90. **Chúng đi cùng dữ liệu nhưng màn hình không bao giờ hiện**: một con số, không khoảng, không chú
  thích. (Chúng vẫn dùng để chấm nhãn kết luận ở Đo lường — mục 6.)
- `margin_pct` = lợi nhuận ÷ doanh thu thực (%), `delta` tính bằng điểm.
- Không ước tính được: mọi `du_kien` là `None`, kèm `reason_code` / `reason_text` ("Chưa ước tính được" khi hover "—").
- `data_through`: ngày dữ liệu mới nhất mà con số dựa vào ("Số liệu đến dd/mm").

Nhãn hiển thị: "Lợi nhuận dự kiến (N ngày)", "GMV dự kiến", "Đơn dự kiến", "AOV dự kiến"; dòng xám "hiện tại: Y đ · ±Z đ (±p %)". Lợi nhuận dự kiến < 0 hiện
"Lỗ X đ" đỏ; chênh lệch âm không tô đỏ.

### 5.2 Cách chọn Δ (`prediction.predict_lift`)

Lift tương đối của chỉ số mục tiêu = prior của loại thay đổi × hệ số hiệu chỉnh × thang khoảng (coverage). Thứ tự bậc (`Lift.source`):

1. `product_history`: chỉ loại thay đổi theo kích cỡ giá (`price_scaled`): phản ứng đơn của **chính sản phẩm** khi từng giảm giá (`env.response_by_item`).
2. `shop` (loại giá): phản ứng của **các sản phẩm khác** trong shop (`env.response_shop`). Cả hai bậc này thay luôn prior + hiệu chỉnh.
3. `shop` (hiệu chỉnh): khi shop có `n_results ≥ MIN_SHOP_RESULTS = 5` kết quả **sạch** của cùng (`change_kind`, `metric`). Hệ số
   `1 + n/(n+K)·(ratio−1)` với `K = SHRINKAGE_K = 5`, `ratio` = tỷ lệ đo ÷ dự kiến gộp theo nghịch phương sai, kẹp `[0,25; 2,0]`; `n` đếm theo trọng số
   (`MULTI_CARD_WEIGHT = 0,25` cho thẻ chạy chung).
4. `pooled`: cùng cách trên, gộp từ **các shop Shopee thật** (`kind = real`; không TikTok, không mẫu / sandbox), cũng cần ≥ 5 kết quả.
5. `prior`: mức chung của Juli, theo nhóm khoảng cách tới mức tham chiếu (`GAP_BUCKET_SCALE`), có sàn `MIN_PRIOR_LIFT` (owner 2026-11-15/16);
   thẻ gắn `basis_weak` và hiện nhãn "chung".
   Không có gì để dự báo → `not_estimable` (`insufficient`): Δ thay bằng chỉ chi phí và hoà vốn.

Brief ban đầu ghi "≥ 3 kết quả sạch"; **code là 5** (`config.MIN_SHOP_RESULTS`; bậc `pooled` cũng đi qua `factor_from` nên cùng ngưỡng 5). Trong nhãn cơ sở của kết quả
(`outcome.BASIS_LABELS`) bậc `pooled` hiện chung với `prior` là "ước tính chung" (`_SOURCE_BASIS` chưa có khoá `pooled`), nhưng số thì khác.

**Chỉ thẻ do engine (`origin = engine`) mới làm đổi hệ số.** Thẻ **Tự tạo** (`manual`) và **Làm ngoài Juli** (`external`) được lưu quan sát nhưng
`calibrate(…, "engine")` loại chúng; chỉ `coverage_report` riêng ("calibration_manual") đếm chúng.

**Một quan sát "sạch"** (`measure.clean_reasons`, `Observation.calibrates`):
- không `partial` (đo bị cắt); không `other_change` (thẻ khác của sản phẩm, thay đổi cả shop, combo trùng ngày: `stacked`);
- không ngày sale hợp đồng (`contract_excluded_days`) trong khoảng trước hoặc sau;
- mỗi khoảng trước / sau có ≥ `CLEAN_MIN_TRAFFIC_DAYS = 5` ngày có lượt xem hoặc nhấp;
- `controlled` (có chuỗi đối chứng) và `tier` ∈ {`cao`, `trung_binh`} và số liệu tươi (`fresh`); nhóm đo chung không bao giờ sạch.

### 5.3 CPA, CPA hoà vốn, ROAS Shopee (thẻ Dịch vụ hiển thị)

`AdsEvaluation`: `cpa = spend ÷ orders` (đơn trực tiếp của chiến dịch, điều chỉnh theo tỷ lệ huỷ của shop; trong `ads_edit`: `direct_orders × keep`);
`break_even_cpa` = lợi nhuận mỗi đơn **trước quảng cáo** của các sản phẩm trong chiến dịch (`profit_per_order_before_ads`);
`profit_after_ads = orders × break_even_cpa − spend`; verdict "có lãi" khi `cpa < break_even_cpa`, ngược lại "lỗ";
`ROAS Shopee = gmv_placed ÷ spend` (chỉ tham khảo). Tác động Δ lợi nhuận / ROI của thẻ dùng riêng phần đơn **tăng thêm** (`incremental_share`,
cần ≥ `MIN_MEASURE_DAYS` ngày bật và tắt; không có thì thẻ chỉ có chi phí + hoà vốn). Thiếu giá vốn: CPA hoà vốn "chưa tính (thiếu giá vốn)".

## 6. Đo lường

### 6.1 Thực tế (`running.build_actual`, F7.5)

Với một change set bắt đầu `start`, cửa sổ N ngày: `k` = số ngày từ `start` tới ngày mới nhất **có dữ liệu đơn** (`k ≤ N`, ngày thiếu không tính). Thực tế =
tổng `k` ngày đó; **hiện tại** = `k` ngày ngay trước `start`; `delta = thực tế − hiện tại`, `delta_pct = delta ÷ |hiện tại|`. Năm chỉ số: `profit`
(sản phẩm: lợi nhuận trước quảng cáo − `ads_spend`; shop đã mang quảng cáo), `gmv`, `orders`, `aov`, `margin_pct`. Không ước tính gì: là tổng các ngày đã lưu
(`product_metrics_daily` / `shop_metrics_daily`). Nhãn "Đã đo k/N ngày".

Khi `k ≥ N` (`final`), lợi nhuận Δ được so với **dải lợi nhuận P10–P90 lúc duyệt** (`profit_band`: dải của kết quả đã lưu trong `result_store`; nếu không có thì
`forecast.metrics.profit` low/high trừ hiện tại; tổng các thẻ của nhóm): `Vượt khoảng` nếu Δ > P90, `Dưới khoảng` nếu Δ < P10, còn lại `Trong khoảng`.
Đo lường dùng nhãn này khi `actual.final`; trước đó hoặc khi không đủ dữ liệu dùng verdict của `execution_state.verdict_of` (so `impact_pct` với P10–P90 lift của chỉ số
thẻ): `Đang đo` / `Trong khoảng` / `Dưới khoảng` / `Vượt khoảng` / `chua_ket_luan` (thẻ chưa có kết luận; nhãn cũ này đã bị loại khỏi hai tài liệu, nói "chưa có kết luận" với người bán).

### 6.2 Nhóm đo chung (F7.6, `group_sets`)

Một thay đổi bắt đầu khi thay đổi khác của **cùng sản phẩm** (hoặc cùng cả shop) đang đo: các set vào **một nhóm**, đo từ ngày bắt đầu đầu tiên tới ngày kết thúc cuối cùng,
liệt kê thành viên ("đo chung với …", Excel **Đo chung với**). Nhóm được suy ra từ các set (cùng phạm vi + sản phẩm, cửa sổ chồng, hoặc `cut_by_change_set`), nên
set cũ bị cắt vẫn thành nhóm (`regroup`, không cần thao tác tay). Kết quả nhóm không sạch, không học. Thực hiện trên sản phẩm đang đo: nếu đã đo ≥ `CUT_MIN_DAYS = 3` ngày kết
quả được giữ ("đo được N ngày"), ít hơn thì "không kết luận".

### 6.3 Độ dài đo

Kế hoạch: **Đo trong bao lâu** — **Tự động theo sản phẩm** (ngày khuyến nghị = ngắn nhất có MDE ≤ `MDE_MAX = 30 %`, ngày hợp lệ 7 / 14 / 28), 7 / 14 / 28 cho cả kế hoạch, hoặc **Tuỳ chọn** 3–90 ngày. Thẻ không có kế hoạch: 14 ngày
(`QUEUE_DEFAULT_PLAN_DAYS`). Khung ngày hiện "Khó kết luận" khi lượng đơn quá ít (không có ngày nào đạt MDE).

## 7. Thực hiện: điền, lưu, xác minh, hoàn tác

`execution_state.derive_state` (không lưu thêm gì, suy ra từ các sự kiện và lệnh điền):

| Trạng thái | Điều kiện |
|---|---|
| `cho_dien` — **Chờ điền** | đã duyệt, chưa có lệnh điền nào `filled` |
| `da_dien` — **Đã điền · chờ bạn lưu** (hoặc **Đã lưu · chờ xác minh** khi đã có `executed_at` hoặc ≥ 3 bước) | Connector báo điền đủ mọi trường của lệnh (`progress.filled == total`) hoặc người bấm **Đã làm** |
| `khop` — **Khớp Seller Centre** | sự kiện `verified`: một lần đọc sau `executed_at` thấy đúng giá trị; **đồng hồ đo bắt đầu từ lúc này** (`measure_start`) |
| `lech` — **Lệch Seller Centre** | `mismatch`: đến hạn `VERIFY_WINDOW = 48 h` sau `executed_at`, đã đọc nhưng không khớp (giá trị đọc được cuối cùng được báo); `not_seen` ("Chưa thấy thay đổi") khi chưa có lần đọc nào |
| `hoan_tac` — **Đã hoàn tác** | người bấm **Đã hoàn tác** (hoặc **Đã hoàn tác thủ công**) |

- Tiến độ theo **lệnh điền** (một trang của thẻ), không theo trường: Connector báo trạng thái lệnh, không báo "3/4 trường". Chữ "3/4 tiêu đề đã điền" đếm lệnh theo loại (`NOUN`).
- Connector **không bao giờ lưu hay bấm nút trên Shopee** (từ 0.3.28 điền có hướng dẫn; trước đó bấm chuột không tin cậy làm Shopee chặn ngày 19/11). Người bán xem, bấm **Lưu**, rồi **Đã làm**.
- Thanh Connector: kết nối (`connected`), `seller_centre_open`, `last_check_at`, `reader_blocks` (một dòng mỗi trang bị chặn: "Đăng nhập lại …", "Xác nhận mật khẩu …", "Cần quyền Tài chính …", "Shopee tạm chặn — Juli dừng đến HH:mm"),
  `upgrade_required` / `min_version` ("Cập nhật Juli Connector lên …"). **Đối chiếu ngay** = `POST …/execution/reconcile` (`connector_state.request_reconcile`: một lệnh bảo Connector đọc lại để xác minh); không mở được chặn `traffic_check` trước `until`.
- **Hoàn tác** (`RevertBlock`): các bước ngược; **Mở và điền** xếp lệnh điền cho giá trị cũ (`revertFill`); **Đã hoàn tác** cần lệnh đã `ready`, còn
  **Đã hoàn tác thủ công** bỏ qua. Ghi người + giờ, dừng đo của thẻ, loại khỏi những gì Juli học.

## 8. Việc của Ops trên Quyết định (thanh "Việc của Ops")

Chỉ nhân viên (Vận hành+), hiện ở đầu tab Đề xuất khi xem như nhân viên. Mỗi nút được ghi nhật ký (`reco_*`):

| Nút | Làm gì |
|---|---|
| **Tạo đề xuất** | sinh thẻ từ số liệu mới nhất, lưu thành **nháp** (`topN = 10`); trả "N thẻ nháp" |
| **Gửi tất cả nháp cho shop** | xuất bản mọi nháp (`publish`); trả "N thẻ đã gửi" |
| **Tính lại thẻ cũ** (`rerun-stale`, `reco_rerun_stale`) | tính lại **chỉ** các thẻ đã bị đánh cờ cũ: người bán áp dụng Thông số shop (SKU / mục tiêu đổi → `mark_stale_for`), hoặc `stale_reason` = `engine_version_changed` (`ENGINE_VERSION` đổi, hiện `2026-11-20.1`), `inputs_changed` (dấu vân tay đầu vào đổi, mục 4), `never_stamped`. Nháp thì thay; thẻ đã gửi / yêu cầu sửa thì `revise` (bản cũ giữ như người bán đã thấy); thẻ **đã duyệt giữ nguyên** và vẫn gắn cờ để người xem lại. Trả đếm theo loại. Một ngày đơn mới **không** làm thẻ cũ: mỗi sáng kết quả / dự kiến của thẻ được làm mới (`data_advanced`) mà thẻ không bị đánh cũ hay gửi lại. |
| **Đo lại** (`learning/run`, `reco_learning_run`, F8.6) | chạy **ngay** vòng học của shop (`measure.run_learning`): dựng lại các hàng cũ theo luật mới (`rebuild_outdated`), **làm mới Thực tế đang chạy** của mọi change set và nhóm (F7.5 / F7.6), đọc kết quả các thẻ và set đã xong, đọc lại quảng cáo của chiến dịch mới (`ads_readback`), rồi tính lại hiệu chỉnh theo (`change_kind`, `metric`) và độ phủ của shop, và xếp lại hàng chờ thẻ của sản phẩm. Trả "N số đo từ M thẻ" (`readings` / `cards_considered`). Dùng khi người bán hỏi vì sao Đo lường chưa cập nhật, hoặc ngay sau khi sửa dữ liệu. Ghi theo mã quan sát nên chạy lại không nhân đôi; thẻ đã bị Xoá bảng không bao giờ được học. Chỉ quan sát **sạch** mới làm đổi hệ số (mục 5.2). |

Khác: `learning/backfill` (`reco_backfill`) = nạp một lần "thí nghiệm tự nhiên" từ nhật ký quảng cáo và lịch sử voucher; `sim-priors` nhập kết quả mô phỏng có kiểm tra cổng.

## 9. Dữ liệu shop: "Số liệu đến" và lần nhận cuối

Hai khái niệm khác nhau; người bán hay nhầm:

| Hiện ở | Ý nghĩa | Nguồn |
|---|---|---|
| **Số liệu đến** dd/mm (mỗi khối) | **ngày mới nhất mà dữ liệu ĐANG GIỮ** của khối đó đã đủ | `data_through`: với mỗi khối lấy **ngày cũ nhất** trong các bộ số liệu của khối (`min`), không quá ngày cuối của kỳ. Bộ số liệu → ngày mới nhất có hàng: dữ liệu theo ngày → `day`; theo kỳ → `period_end`; dòng đơn → ngày đơn cuối; ảnh chụp → ngày chụp (`load_freshness`) |
| **Cập nhật** dd/mm/yyyy hh:mm (đầu Tổng quan) | **lần nhận gần nhất**: `max(coalesce(last_captured_at, last_ingest_at))` mọi bộ số liệu của shop | `ingest_dataset_status` |
| **Số liệu đến ngày** / **Trạng thái** ("Nhận lúc …") ở Cài đặt › Juli Connector › **Juli đã nhận gì** | `last_period_end` và `last_ingest_at` của **lần gửi cuối** của từng bộ số liệu | `ingest/status.py` (`last_*` chỉ đi tới, một lần gửi muộn của dữ liệu cũ không làm lùi) |

Khối → bộ số liệu (`SECTION_DATASETS`): `kpis` ← `shop_overview` (GMV, đơn: chỉ tổng của Shopee — owner T8, đơn lẻ muộn không được làm GMV lùi ngày); `profit` ←
`shop_overview` + `order_lines` + quảng cáo (`ads_last_day`: ngày cuối có số quảng cáo trong kỳ); `channels` ← `shop_overview` + `traffic_overview` + quảng cáo; `plan` ←
`shop_overview` + `order_lines`; `products` ← `shop_overview` + `order_lines`. Một bộ số liệu shop chưa có hàng thì bị bỏ khỏi phép `min`; khối không có bộ nào thì "—".
Khi ngày của Lợi nhuận / Tổng chi phí cũ hơn ngày của GMV, ô đó hiện thêm dòng "Số liệu đến" riêng.

Cách đọc khi người bán nói "số cũ": (1) xem **Cập nhật** — nếu cũ, Connector không gửi (xem thanh Juli Connector ở Thực hiện và danh sách **Reader lỗi** ở Ops);
(2) nếu **Cập nhật** mới mà **Số liệu đến** cũ, Connector có gửi nhưng bộ số liệu chậm nhất của khối đó chưa có ngày mới (`last_period_end` có thể là ngày không có hàng nào — so với "ngày mới nhất đang giữ");
(3) bộ nào có `drift` thì tạm dừng cho tới khi Connector mới hơn gửi thành công (409 `dataset_in_drift`).

## 10. Juli Connector (Ops)

- **Kết nối dữ liệu** trên trang shop: **Tạo mã kết nối** (mã một lần, 10 phút, tối đa 5 mã chưa dùng → 429; 409 "Shop chưa có đồng ý xử lý dữ liệu"). Nguồn đang kết nối liệt kê "thấy lần cuối"; **Thu hồi** ngắt một nguồn.
- **Máy cũ (N)** = token đang hoạt động mà `last_seen_at` (hoặc `last_used_at`, `created_at`) cách đây **≥ 14 ngày** (`INACTIVE_DAYS`); **Gỡ tất cả máy cũ**
  thu hồi chúng một lượt (`revokeInactiveIngestTokens`). Token đã thu hồi không hiện. Người bán có cùng nút ở Cài đặt › Juli Connector.
- **Reader lỗi**: mỗi trang có kết quả hôm nay khác "đã đọc / còn mới / bỏ qua" hiện nhãn ngắn: Cần đăng nhập, Cần nhập lại mật khẩu, Không có quyền, Cần xác minh, Lỗi, Quá thời gian, Chưa có mẫu, Không mở được trang, Chờ hạn mức, Đọc chưa đủ.
- Hằng số nên nhớ (`config.ts`): hạn mức `DAILY_REQUEST_BUDGET = 800` yêu cầu / ngày GMT+7 chung cho reader, đồng bộ và nạp 30 ngày (`TODAY_REQUEST_RESERVE = 250` cho hôm nay, `BACKFILL_REQUEST_SHARE = 150`
  khi nạp lịch sử, `FILL_REQUEST_RESERVE = 60` cho điền / đọc lại; mỗi tab mở tính `READER_PAGE_LOAD_COST = 10`); mỗi trang cách nhau 20 s + tối đa 25 s ngẫu nhiên; một trang quá 4 phút bị đóng (quảng cáo 8 phút);
  chặn: đăng nhập / CAPTCHA / `traffic_check` (6 giờ, không gì mở sớm) / `password_recheck` (người bán nhập một lần; Connector không bao giờ gõ mật khẩu).
- **Thứ tự đọc** (`READER_IDS`): sản phẩm → đơn → thu nhập từng đơn → voucher → quảng cáo → chi tiết chiến dịch → quảng cáo theo sản phẩm → sức khỏe tài khoản → các trang `/datacenter` (tổng shop, truy cập, hiệu quả
  sản phẩm 30 ngày) → Tiếp thị liên kết (8 trang) → nguồn truy cập từng sản phẩm. Đơn và thu nhập chạy **trước** mọi trang `/datacenter` vì hộp thoại mật khẩu của Phân tích bán hàng chỉ chặn các trang đó. Tồn kho đọc riêng lúc 06:30 GMT+7.
- **Đọc bù** (0.3.29, `catchup.ts`): backend nêu từng bộ số liệu theo ngày những ngày trong 30 ngày qua chưa có hàng nào được nhận (`GET /v1/connector/shopee/read-days`); Connector đọc **ngày vừa kết thúc trước**, rồi ngày thiếu **cũ nhất trước**,
  vài ngày mỗi lượt (`CATCHUP_DAYS_PER_JOB`: traffic 5, ads 5, item_traffic 2, shop_totals 30, ads_products 10), chỉ khi hạn mức còn chỗ.
- **Đồng bộ hôm qua** (popup) nâng chặn đăng nhập / CAPTCHA và đọc lại các trang hôm nay chưa gửi được; không nâng `traffic_check`.

## 11. Nhập file và kết quả từng dòng

### 11.1 "Nhập thẻ đã làm ngoài Juli" (Thực hiện)

`planned_changes/external_rows.py` + `import_job.py`: trang tính **Tổng hợp đề xuất**, tìm hàng tiêu đề trong 12 hàng đầu, chỉ đọc các cột trong danh sách trắng (STT, Mã, Hạng mục, Mã SP, Phương án,
Dữ liệu cụ thể, Ngày thực hiện, Trạng thái, Thời gian đo ngày, Chi tiết trạng thái), dừng ở hàng trống đầu tiên hoặc 500 hàng. **Bắt buộc**: Mã, Hạng mục, Mã SP, Phương án, Ngày thực hiện, Trạng thái, Thời gian đo ngày (1–365).
Tệp không tin cậy: kiểm kích thước / zip, từ chối DTD / entity.

- Hạng mục → loại thẻ: Tiêu đề sản phẩm → `title`; Ảnh bìa + Tiêu đề → `cover_image` + `title`; Ảnh bìa; Voucher → `min_spend_voucher`; Quảng cáo → `ads_roas_target`; Giá → `price`; Combo khuyến mãi → `bundle_deal`; Mua kèm deal sốc → `add_on` + `gift`;
  Mua quà tặng kèm → `gift`; Tiếp thị liên kết → `affiliate_commission` (+ `affiliate_target_campaign` nếu kế hoạch bắt đầu bằng "Chiến dịch mục tiêu").
- Trạng thái đọc: Đã thực hiện / Đang thử nghiệm (đã chạy, tạo thẻ đã thực hiện), Đề xuất, Đã huỷ (bỏ qua), Không rõ.
- **Xem trước** từng dòng: `N dòng · M thẻ mới · K đã có · J bỏ qua`; mỗi dòng bỏ qua ghi **Bỏ qua: <lý do>**. Lý do (`SKIP_LABELS`): Không có gì để đo; Đã huỷ; Hạng mục chưa có loại thẻ trong Juli; Không đọc được trạng thái; Cần một mã sản phẩm;
  Thiếu ngày thực hiện; Ngày thực hiện chưa tới; Không có tiêu đề mới (dòng 'Sau:'); Không đọc được mức voucher / ROAS mục tiêu / giá mới / bậc combo / chi phí quà / % hoa hồng; Không tìm thấy chiến dịch quảng cáo của dòng này;
  Không xác định được phân loại; Cần sản phẩm chính và sản phẩm mua kèm; Các giá trị không hợp lệ; Mã bị trùng trong tệp; Đã nhập trước đó; Không tạo được thẻ. Dòng bỏ qua theo `EXTERNAL_IMPORT_SKIP_REFS` (NH-1, XM-1, VC-R, KOC-2) và cụm
  mở đầu (nghiên cứu, báo cáo, trao đổi, tạo listing, bật tính năng) là ghi chú, không nhập.
- **Kết quả sau khi Nhập** (`ImportResult`): tóm tắt "Đã nhập N thẻ · K đã có · J không nhập được" và bảng **Dòng · Mã · Loại · Kết quả** với từng thẻ: **Đã tạo**, **Đã có**, **Không nhập được: <lý do>**.
  Chạy lại cùng tệp không tạo trùng (cùng `external_ref` + loại → "Đã có"). **Xoá bảng** rút mọi thẻ khỏi bảng Thực hiện (một bước xác nhận).
- Thẻ nhập về có `origin = external` (Nguồn **Làm ngoài Juli**), `external_ref` giữ **Mã gốc** (cột Mã gốc trong Excel); không có kế hoạch (`plan_id` rỗng), vẫn được đo, **được tính vào mục tiêu Kế hoạch** (F8.5), và không làm đổi hệ số của engine.

### 11.2 Thông số shop

Bước: 1 · Mẫu và tải lên → 2 · Kiểm tra → 3 · So sánh → 4 · Áp dụng → Phiên bản → Mục tiêu. Kiểm tra liệt kê dòng bị từ chối với cột **Dòng · SKU · Cột · Giá trị · Vì sao bị từ chối · Loại**. Loại (`KIND_LABELS`): SKU lạ, Giá vốn ≥ giá, Giá vốn trống, Ngoài khoảng, Ngày sai, Trùng SKU, Giá trị sai, Tháng sai,
Thiếu KOL, Số món sai, VAT sai, Thành phần lạ, Thành phần trùng chính nó, Số lượng sai, Trùng thành phần. Trường: Giá vốn, Đóng gói, Giảm tối đa (%), Tồn kho, Ngày nhập lại, Nhóm, Trạng thái, Số món / phân loại, VAT (%), Loại trừ,
Lý do loại trừ, Thành phần combo, Giá bán đã gồm VAT, Giá vốn đã gồm VAT; trang Mục tiêu: GMV, Đơn, AOV, Biên mục tiêu (%), Trần chi marketing/ngày. Áp dụng bắt buộc một lý do; mỗi lần là một phiên bản theo SKU có **Khôi phục**.
Chỉ các thẻ của sản phẩm có SKU đổi bị đánh cờ cũ (mục 8).

### 11.3 Thứ tự ưu tiên nguồn (`models.ingest.SOURCE_RANK`, chủ 2026-11-18)

`api 4 > extension (Connector) 3 > file 2 > vendor 1`. Trên `order_lines`, `affiliate_lines`, `order_settlements`: một lần ghi cùng hoặc cao hơn thay bằng các giá trị không rỗng (NULL không bao giờ xoá giá trị đã có); một lần ghi
**thấp hơn** (tệp dưới Connector) **chỉ điền các cột đang NULL**, còn nguồn / bậc / phiên bản / payload của hàng vẫn thuộc nguồn cao (mỗi lần điền ghi một dòng log `ingest_gap_fill`). Đơn mà không nguồn cao hơn nào ghi thì lấy nguyên từ tệp (nạp lịch sử).
Quy tắc cũ P90 D-5 (tệp trên Connector) đã bị thay thế.

## 12. Excel (F8)

`exports/tong_quan_xlsx.py`, `ke_hoach_xlsx.py`, `collect.py`. Các tỷ lệ và tổng là **công thức Excel** (`fullCalcOnLoad`, chỉ hàm Excel-2007); số liệu thiếu là ô **trống**, không 0.

**Tổng quan**: trang `Tổng quan`, `Lợi nhuận`, `Theo kênh`, `Theo ngày`, `Theo sản phẩm`, `Theo SKU`. Trang `Tổng quan` có cột `Chỉ số · Kỳ này · % doanh thu · Kỳ trước · Thay đổi · Mục tiêu (Kế hoạch) · So với mục tiêu`;
Mục tiêu chỉ có cho GMV, Lợi nhuận và biên. Trang `Theo kênh`: `Chi phí (đ)`, `ROI (lợi nhuận ÷ chi phí QC + AFF)`, `Chi phí / doanh thu`, `Lợi nhuận kênh (đ)` = GMV kênh × ((lợi nhuận + tổng chi phí) ÷ GMV) − chi phí kênh
(dòng cộng lại bằng lợi nhuận shop); `Thay đổi` = "—" khi kỳ trước tính Quảng cáo trên cơ sở khác (`basis_differs`: overlay vs report). `Theo SKU`: `Cần nhập = bán/ngày × (7 + 14) − tồn kho`, ≥ 0 (`LEAD_DAYS` + `COVER_DAYS`);
dòng "Chênh lệch: doanh thu dòng đơn khác Doanh số Shopee" đưa Σ doanh thu về GMV kỳ.

**Kế hoạch** (khoảng Từ ngày – Đến ngày; thẻ có hoạt động trong khoảng: đề xuất, chạy hoặc đo): trang `Lịch sử thẻ`, `Mục tiêu`, một trang cho mỗi nhóm loại (`KIND_SHEETS`: Quảng cáo, Voucher, Combo - Deal Sốc, Giá - Chương trình - Flash, Phân loại, Listing, Liên kết - KOL, Thẻ khác), `KOL`.
- Dẫn đầu: STT, Mã thẻ, Mã gốc, **Nguồn** (`SOURCE_LABELS`: engine → Juli, manual → Tự tạo, external → Làm ngoài Juli), Shop, Nền tảng, Trạng thái (Đang chạy / Trong nháp / Đang đo / Đã đo), Nhóm, Phương án, Phiên bản, Sản phẩm, Đề xuất, Bắt đầu, Kết thúc, Số ngày chạy (công thức).
- Mỗi chỉ số Lợi nhuận, GMV, Đơn, AOV: `hiện tại · dự kiến · thực tế · chênh lệch` (F7: dự kiến lưu trong thẻ và Thực tế đang chạy, **trên các ngày đã đo**, một số, không khoảng); `chênh lệch = IF(OR(dự kiến="",thực tế=""),"",thực tế − dự kiến)`.
  Khác màn hình Đo lường: ở đó **Δ = thực tế − hiện tại**; Excel là **thực tế − dự kiến**. Cộng thêm `Chi phí`, `Đã đo` ("k/N ngày"), `Đo chung với` (Mã gốc của thẻ kia nếu có, không thì Mã thẻ), `Kết luận` (`Đang đo` / `Trong khoảng` / `Dưới khoảng` / `Vượt khoảng`; trạng thái chưa có kết luận để trống).
- Khi mới đo k trên N ngày (`0 < k < N`), `hiện tại` và `dự kiến` của Lợi nhuận, GMV, Đơn (`ADDITIVE`) được quy theo k ÷ N để ba số phủ cùng k ngày; AOV giữ nguyên.
- `Mục tiêu`: mỗi shop `GMV nền / mục tiêu / thực tế / % đạt` rồi cùng bốn số cho Lợi nhuận; dòng **Tổng** chỉ khi **mọi** shop đều có mục tiêu đó (G23); bảng "Theo ngày" trải nền đều và phần tăng đúng ngày rơi vào.
  `goal = baseline + uplift`: baseline = mức 30 ngày "hôm nay" đã đóng băng của **kế hoạch đã chạy sớm nhất** (`aggregate.today`) ÷ `HORIZON_DAYS = 30` × số ngày; uplift = tổng P50 Δ của các thẻ đang chạy, mỗi thẻ trải đều trên số ngày của chính nó và chỉ tính ngày nằm trong khoảng;
  thẻ **ngoài kế hoạch** (Làm ngoài Juli / Tự tạo đã thực hiện, `plan_id` rỗng) tính như thẻ trong kế hoạch; nếu không có kế hoạch nào đã chạy, baseline là mức 30 ngày của shop trước thẻ sớm nhất. Không thẻ nào chạy → `goal = None` (không phải 0). `ahead` = thực tế ≥ mục tiêu chia theo tỷ lệ thời gian đã qua.
- Trang Quảng cáo: `CPA`, `ROAS`, `CPA hoà vốn`, `ROAS hoà vốn` mỗi cái hai cột (dự kiến / thực tế); thực tế CPA = chi ÷ đơn của lần đọc lại (`ads_readback`), CPA hoà vốn và ROAS hoà vốn không có số thực tế. Trang KOL: `ROI KOL` là công thức **`Lợi nhuận ÷ Hoa hồng`** (`=H/G`: cột Lợi nhuận chia cột Hoa hồng) của dòng.

## 13. Các khác biệt đã biết (nói đúng khi người bán hỏi)

1. **ROI và Tổng chi phí**: màn hình tính **cả Ưu đãi**; tệp Excel Tổng quan không (mục 3.2). GLOSSARY nói Ưu đãi không là chi phí. Chưa thống nhất.
2. **Biên lợi nhuận**: màn hình = lợi nhuận ÷ doanh thu thực (đơn có chi phí); Excel Tổng quan = lợi nhuận ÷ GMV.
3. **ROI KOL**: registry (`roi_kol`) = `(kol_net − samples_cost) ÷ (kol_commission + samples_cost)` kèm khoảng tin cậy 90 % → ba trạng thái (`kol_status`); Excel trang KOL hiện `Lợi nhuận ÷ Hoa hồng`. Màn hình Phân tích chưa hiện ROI KOL.
4. **Thứ tự chia kênh**: `metrics/allocation.channel_partition` (registry; "chưa nối màn hình") ưu tiên Tiếp thị liên kết rồi Quảng cáo; màn hình cấp Sản phẩm (`partition_channels`) ưu tiên **Quảng cáo** rồi Tiếp thị liên kết;
   cấp Shop không chia mà lấy nguồn Seller Centre trực tiếp (mục 2).
5. **Nhãn Đo lường**: hai cách chấm (mục 6.1) cùng dùng nhãn "Trong khoảng / Dưới khoảng / Vượt khoảng" nhưng so **Δ lợi nhuận** với dải lợi nhuận (khi đã đủ N ngày) hoặc **thay đổi tương đối** của chỉ số mục tiêu với P10–P90 lift (verdict trước đó).
6. **Ngưỡng hiệu chỉnh**: 5 kết quả sạch, không phải 3 (mục 5.2).
7. **Tên biên** trong GLOSSARY (Biên cuối ở giá hiện tại / Biên thực hiện 30 ngày) khác nhãn màn hình (Biên ở giá bán / Biên cuối).
8. **Juli tab** (hỏi đáp số liệu) thuộc batch chưa gộp; tài liệu người bán mô tả ngắn, cần kiểm lại khi gộp.

## Phụ lục: TikTok Shop

Phần này giữ lại hướng dẫn chỉ số của **màn hình TikTok Shop** (Mô phỏng, Trang chủ, Phân tích TikTok, Quyết định TikTok) từ bản hướng dẫn trước, để đội ngũ vẫn tra được.
Nó **không** áp dụng cho shop Shopee. Các mã D25–D55 là mã quyết định nội bộ cũ; nhãn trong bảng này là nhãn của màn hình TikTok, một số nhãn (Tab cửa hàng, LIVE, Lượt hiển thị/ngày, Dao động…)
không có trên màn hình Shopee. Nội dung được chuyển nguyên văn (chỉ đánh số lại thành A1–A7) và **chưa được đối chiếu lại với code trong lần viết này**: kiểm tra với mã nguồn trước khi trích cho người bán.

### A0. Bảng thuật ngữ TikTok


| Nhãn trên màn hình | Ý nghĩa | Cách tính |
|---|---|---|
| **Thẻ sản phẩm** | Luồng 1: khách thấy sản phẩm dạng thẻ (tìm kiếm, gợi ý, trang For You…) | Số liệu TikTok của nguồn "product card"; TikTok tính kênh này là **phần còn lại** sau LIVE và video (mục A5.5) |
| **Tab cửa hàng** | Luồng 2: khách vào trang cửa hàng của shop | Số liệu nguồn "shop tab"; đơn SKU ở luồng này là ước tính (CTOR × lượt nhấp) vì TikTok không trả |
| **Video** | Luồng 3: video do chính shop đăng; tên dài "Video của người bán" chỉ hiện khi rê chuột | Số liệu nguồn "seller video" |
| **LIVE** | Luồng 4: phiên LIVE do chính shop phát; tên dài "LIVE của người bán" chỉ hiện khi rê chuột | Số liệu nguồn "seller live" |
| **Lượt hiển thị/ngày** | Trung bình mỗi ngày có bao nhiêu lượt khách thấy sản phẩm/nội dung | Tổng lượt hiển thị trong N ngày ÷ số ngày có dữ liệu |
| **Lượt nhấp** | Số lần khách bấm vào sản phẩm (TikTok gọi là click) | Tổng trong khoảng |
| **CTR** | Trong 100 lượt hiển thị, bao nhiêu lượt nhấp | Tổng lượt nhấp ÷ tổng lượt hiển thị (cộng cả khoảng rồi mới chia) |
| **CTOR** | Trong 100 lượt nhấp, bao nhiêu thành đơn | Tổng đơn SKU ÷ tổng lượt nhấp; **không phải** "tỷ lệ chuyển đổi" của TikTok (người mua ÷ lượt xem trang, mục A5.5) |
| **AOV** | Giá trị trung bình một đơn | Tổng GMV ÷ tổng đơn SKU; GMV của TikTok gồm cả đơn sau đó bị huỷ/hoàn (mục A5.5) |
| **GMV/ngày** | Doanh thu trung bình mỗi ngày | Tổng GMV ÷ số ngày; = Lượt hiển thị/ngày × CTR × CTOR × AOV; GMV theo TikTok, chưa trừ đơn huỷ/hoàn (mục A5.5) |
| **▲▼** | Hướng thay đổi so với khoảng trước đó cùng độ dài | (N ngày gần nhất − N ngày trước đó) ÷ N ngày trước đó; xám khi \|Δ\| < 0,5 %; cần 2 × N ngày lịch sử |
| **Dao động TB N ngày** | Con số trung bình N ngày tự nó lên xuống bao nhiêu chỉ vì ngẫu nhiên | ±1,2816 × độ lệch chuẩn các ngày ÷ √(số ngày) ÷ trung bình (khoảng 80 % của trung bình) |
| **Dao động mỗi ngày** | Một ngày bình thường lệch khỏi trung bình bao nhiêu | max(p90 − TB, TB − p10) ÷ TB, trên các giá trị từng ngày trong N ngày |
| **Ít dữ liệu** | Quá ít lượt nhấp/đơn để tin vào tỷ lệ | < 30 lượt nhấp (CTR) hoặc < 30 đơn (CTOR, AOV) trong khoảng; Lượt hiển thị không bao giờ "Ít dữ liệu" |
| **Trong dao động** | Mức thay đổi nằm trong mức lên xuống thường ngày — không nói được gì | Mô phỏng: \|mục tiêu %\| ≤ Dao động TB N ngày. D31.7: \|thay đổi\| < 1 × dao động gộp |
| **Vượt dao động · đo được** | Mục tiêu đặt trong Mô phỏng đủ lớn để đo được | \|mục tiêu %\| > Dao động TB N ngày của ô |
| **Thay đổi rõ** | Thay đổi gần như chắc chắn không phải ngẫu nhiên | \|thay đổi\| ≥ 2 × √(a² + b²), a, b = dao động trung bình của hai khoảng |
| **Có thể thay đổi** | Có dấu hiệu thay đổi nhưng chưa chắc | 1 × ≤ \|thay đổi\| < 2 × √(a² + b²) |
| **Lưu lượng ổn định** | Lượt hiển thị đều đặn từng ngày (luồng hoặc sản phẩm); nên đặt mục tiêu ở đây | Hệ số biến thiên lượt hiển thị (CV) < 15 %; 15–30 % "Dao động vừa", ≥ 30 % "Dao động cao" |
| **Độ tin cậy** | Juli chắc đến đâu về mục tiêu trên thẻ: Cao / Vừa / Thấp (thẻ quét nhanh: "Tham khảo") | Thấp: ít dữ liệu hoặc CV lượt hiển thị > Ngưỡng lưu lượng ổn định (mặc định 30 %); Cao: CV < 15 % và ≥ 3 × Dữ liệu tối thiểu; còn lại Vừa |
| **Đề xuất nhanh · dựa trên 14 ngày** | Thẻ tạo ngay sau khi kết nối shop, chỉ dựa trên 14 ngày | Quét nhanh D26; độ tin cậy luôn "Tham khảo" |
| **Chỉ số chính** | Chỉ số mục tiêu của thẻ, dạng "hiện tại → mục tiêu · 30 ngày" (ví dụ "3,22 % → 3,8–4,4 %") | Mục tiêu = mức tham chiếu, kẹp trong [hiện tại + 1 × dao động, hiện tại + 3 × dao động]; sản phẩm dao động cao → hiện dạng khoảng |
| **GMV dự kiến** | GMV có thể lấy lại mỗi tháng nếu đạt mục tiêu | GMV lấy lại được/ngày × 30 (ước tính theo quy tắc), hoặc khoảng từ dự đoán hiệu quả, nhân hệ số hiệu chỉnh của shop |
| **N thay đổi cho CTR** | Nhóm thẻ cùng sản phẩm, cùng một chỉ số mục tiêu (ví dụ "2 thay đổi cho CTR") | Một sản phẩm chỉ có một chỉ số mục tiêu tại một thời điểm (D29.4) |
| **Duyệt** | Người bán đồng ý cho Juli thực hiện thẻ; "Duyệt N thẻ" duyệt cả nhóm | Chỉ người bán duyệt; Ops không duyệt thay |
| **Kết quả nhóm** | Một câu trên thẻ về nhóm sản phẩm cùng chỉ số × thay đổi × kênh, khi nhóm đã đo xong ngày 14 (ví dụ "Nhóm 6 sản phẩm đổi ảnh bìa: lượt nhấp tăng khoảng 7 % so với các sản phẩm chưa đổi") | D34: trung vị thay đổi nhóm áp dụng − trung vị nhóm đối chứng (chọn ngẫu nhiên, nhận thẻ sau 14 ngày); không hiện khi "Chưa đủ cơ sở" (mục A5.2) |
| **Ngày 7 · kiểm tra** | Mốc đo sơ bộ, 7 ngày sau khi áp dụng | Trung bình 7 ngày sau so với 14 ngày trước ngày áp dụng |
| **Đang lên** | Ngày 7: chỉ số mục tiêu đã tăng rõ hơn dao động, GMV giữ được | Mục tiêu tăng > 1 × dao động VÀ GMV không giảm quá dao động của GMV |
| **Chưa rõ** | Ngày 7: chưa thấy tăng vượt dao động | Ngược lại với "Đang lên" |
| **Ngày 14 · chốt** | Mốc chốt kết quả, 14 ngày sau khi áp dụng | Trung bình 14 ngày sau so với 14 ngày trước |
| **Đạt** | Ngày 14: chỉ số mục tiêu tăng rõ, chạm mục tiêu, GMV giữ được | Tăng > 1 × dao động, ≥ mục tiêu, GMV không giảm quá dao động (sau D31.7: tăng ≥ 2 × dao động gộp) |
| **Đạt · chưa chắc chắn** | Ngày 14: đạt các điều kiện nhưng mức tăng chỉ ở mức "Có thể thay đổi" | D31.7: chạm mục tiêu, GMV giữ được, nhưng 1 × ≤ mức tăng < 2 × dao động gộp |
| **Một phần** | Ngày 14: tăng rõ HOẶC chạm mục tiêu, không đủ cả hai cùng GMV giữ được; thẻ cũ "gan_dat"/"chua_ket_luan" cũng hiện nhãn này | moved OR reached, không phải "Đạt" |
| **Không đạt** | Ngày 14: không tăng vượt dao động và không chạm mục tiêu | Không moved, không reached |
| **Bị ảnh hưởng bởi thay đổi khác** | Trong lúc đo có thay đổi không do Juli (sửa ngoài Juli, khuyến mãi bắt đầu/kết thúc, đổi giá) | Thay đổi bên ngoài (webhook sản phẩm/khuyến mãi + đối soát `update_time` hằng ngày) chồng lên khoảng đo |
| **Ngưỡng giữ ổn định** | Các chỉ số KHÔNG phải mục tiêu được lệch tối đa bao nhiêu (± %) trước khi Juli hỏi hoàn tác | Mặc định = Ngưỡng giữ ổn định (Ops, 1 ×) × dao động trung bình 14 ngày trước khi áp dụng của từng chỉ số; giá trị người bán đặt trong Quy tắc thắng |
| **Bạn đặt** | Nhãn nguồn: ngưỡng do người bán đặt | `bands[].source = "seller"` |
| **Juli gợi ý** | Nhãn nguồn: ngưỡng mặc định của Juli | `bands[].source = "default"` (từ `stability_band_defaults`) |
| **Giữ ổn định** | Đánh giá của một chỉ số giữ: vẫn trong Ngưỡng giữ ổn định | trước × (1 − ngưỡng %) ≤ thực tế ≤ trước × (1 + ngưỡng %); ngoài thì "Ngoài khoảng" |
| **Hoàn tác?** | Ngày 7 có chỉ số vượt Ngưỡng giữ ổn định — Juli hỏi người bán; Juli không tự hoàn tác | Bất kỳ chỉ số giữ nào ra ngoài khoảng trên |
| **Giữ thay đổi** | Người bán chọn giữ; Juli đo tiếp đến ngày 14 | — |
| **Đã hủy** | Hàng chờ thẻ tối ưu: người bán dừng lượt chạy ("Không thực hiện" khi Juli chờ, hoặc huỷ) trước khi Juli ghi gì | `status = cancelled`, `stop_reason = cancelled_by_seller`; hàng chờ chỉ giữ lượt đã kết thúc trong 14 ngày, mỗi thẻ một lượt mới nhất |
| **Sự cố** | Hàng chờ thẻ tối ưu: lượt chạy mất worker (không ai xử lý) và bị dừng; không ghi gì lên TikTok | `status = failed`, `stop_reason = worker_lost` — bộ dọn (reaper, mỗi 5 phút) đóng lượt không có sự kiện quá thời hạn của playbook |
| **Quy tắc** | Trang người bán đặt giới hạn cho Juli (Ngưỡng giữ ổn định, giá vốn, trần giảm giá, số thẻ mở…) | Đội ngũ đặt trước từ Cài đặt shop; người bán chỉnh sau |


### A1. Bốn luồng và bốn chỉ số

GMV của mỗi luồng được tách thành bốn thừa số:

> **GMV/ngày** = **Lượt hiển thị/ngày** × **CTR** × **CTOR** × **AOV**

- Bốn luồng, cùng tên ở Mô phỏng, Phân tích và Trang chủ: **Thẻ sản phẩm**, **Tab cửa hàng** (nhóm
  "Sản phẩm"), **Video**, **LIVE** (nhóm "Nội dung"). Tên dài "Video của người bán" / "LIVE của người
  bán" chỉ là tooltip. Liên kết (affiliate) chỉ theo dõi ở Trang chủ, không phải một luồng phân tích.
- Tỷ lệ luôn là **tỷ lệ của tổng** (cộng lượt nhấp, cộng lượt hiển thị, rồi chia), không phải trung bình
  của các tỷ lệ từng ngày. Lượt hiển thị và GMV là trung bình mỗi ngày.
- **Lượt hiển thị** là chỉ số gián tiếp (thuật toán TikTok quyết định): chỉ tác động được qua quảng cáo,
  chiến dịch, nội dung. Mô phỏng ghi "gián tiếp ⚠".
- Ô khoá trong Mô phỏng: Video CTOR, Video AOV, LIVE AOV ("Khoá · phụ thuộc trang sản phẩm").

### A2. Đọc một ô Mô phỏng

Ô Mô phỏng có: giá trị, chip **▲▼**, dòng **Dao động TB N ngày: ±X %**, khi bấm/rê chuột thì thêm
**Dao động mỗi ngày: ±Y %**, và khi bạn bấm ± thì có nhãn đánh giá mục tiêu.

Thanh chọn khoảng: 7 / 14 / 30 / 90 ngày (mặc định 30). Dòng chú thích:
"Gốc: trung bình N ngày · ▲▼ so với N ngày trước đó · dao động trong N ngày".

#### A2.1. Ví dụ có số

Thẻ sản phẩm của shop, khoảng 30 ngày:

| Trên màn hình | Đọc là |
|---|---|
| Lượt hiển thị/ngày **2.393** | 30 ngày qua trung bình mỗi ngày 2.393 lượt hiển thị |
| **▼ 24,6 %** | Trung bình 30 ngày này thấp hơn 24,6 % so với 30 ngày trước đó (≈ 3.174/ngày) |
| **Dao động TB 30 ngày: ±4,1 %** | Chỉ do ngẫu nhiên, con số trung bình 2.393 có thể lệch khoảng ±4,1 % (≈ ±98 lượt) |
| **Dao động mỗi ngày: ±25 %** | Một ngày bình thường dao động khoảng ±25 % quanh trung bình (≈ 1.800–3.000 lượt) |

**Vì sao ±25 % mỗi ngày nhưng chỉ ±4,1 % cho trung bình?** Khi lấy trung bình 30 ngày, ngày cao bù
ngày thấp. Độ lệch của trung bình nhỏ hơn độ lệch từng ngày khoảng √30 ≈ 5,5 lần:
±25 % ÷ 5,5 ≈ ±4,6 %. Con số thật ±4,1 % hơi khác vì "Dao động mỗi ngày" lấy p10–p90 thực tế (không giả
định phân phối chuẩn), còn "Dao động TB" dùng độ lệch chuẩn. Hệ quả: khoảng càng dài, dao động trung
bình càng hẹp (7 → 14 → 30 ngày), nên mục tiêu nhỏ có thể "Trong dao động" ở 7 ngày nhưng "Vượt dao
động · đo được" ở 30 ngày.

**Dao động gộp khi so hai khoảng (D31.7).** ▼ 24,6 % là hiệu của HAI trung bình, mỗi cái đều có sai số
riêng. Giả sử 30 ngày trước đó có Dao động TB ±4,3 %. Dao động gộp:

> √(a² + b²) = √(4,1² + 4,3²) = √35,3 ≈ ±5,9 %

24,6 % ÷ 5,9 % ≈ 4,2 lần ≥ 2 → **Thay đổi rõ**. Nếu chỉ giảm 8 % (≈ 1,4 lần) → **Có thể thay đổi**;
giảm 4 % (< 1 lần) → **Trong dao động**.

Vì sao ngưỡng là 2 lần chứ không 1: các ngày không độc lập với nhau (hiệu ứng thứ trong tuần, chuỗi
ngày tốt/xấu liền nhau), nên dao động tính ra lạc quan hơn thực tế. Ngưỡng 2 lần bù cho điều đó.
Một quy tắc dùng chung cho mọi phép so sánh: chip ▲▼, kết quả đo thẻ, và khi nói với người bán.

#### A2.2. "Không ngẫu nhiên" ≠ "do Juli"

**Thay đổi rõ** chỉ nói: con số đã thật sự thay đổi. Nó KHÔNG nói vì sao. Lượt hiển thị giảm 24,6 % có
thể do TikTok đổi thuật toán, hết chiến dịch sàn, đối thủ giảm giá, hết hàng… Một kết quả ngày 14 chỉ
được coi là của Juli khi đồng thời:

1. thay đổi đủ mạnh (theo quy tắc trên),
2. không có thay đổi bên ngoài chồng lên khoảng đo (nếu có → **Bị ảnh hưởng bởi thay đổi khác**),
3. các chỉ số giữ ở trạng thái **Giữ ổn định** và GMV không giảm quá dao động của nó.

#### A2.3. Ô "Ít dữ liệu"

Dưới 30 lượt nhấp (CTR) hoặc 30 đơn (CTOR, AOV) trong khoảng: giá trị vẫn hiện nhưng màu xám, có dấu
"*", viền đứt, chip xu hướng xám "~ 3,1 %" thay cho ▲▼, dòng "Ít dữ liệu · N đơn" (hoặc "N lượt nhấp").
Mục tiêu đặt trên ô này đánh giá là "Ít dữ liệu". Cách xử lý: chọn khoảng dài hơn.

#### A2.4. Đánh giá mục tiêu trong Mô phỏng

Mỗi lần bấm ± đổi 1 %. Nhãn dưới ô:

- **Trong dao động** — |mục tiêu| ≤ Dao động TB N ngày: dù đạt cũng không phân biệt được với ngẫu
  nhiên. Đừng đặt mục tiêu này cho shop.
- **Vượt dao động · đo được** — lớn hơn dao động: đo được.
- **Ít dữ liệu** — ô ít dữ liệu.

Lưu ý: Mô phỏng so mục tiêu với dao động của MỘT khoảng (dao động trung bình N ngày). Kết quả đo thẻ
(sau D31.7) dùng dao động GỘP của hai khoảng và ngưỡng 2 lần — chặt hơn. Một mục tiêu "đo được" vừa
đủ trong Mô phỏng có thể chỉ ra "Có thể thay đổi" khi đo thật.

#### A2.5. Lưu lượng ổn định và bảng "Độ dao động"

- Nhãn luồng: **Lưu lượng ổn định** (CV lượt hiển thị < 15 %), **Dao động vừa** (< 30 %), **Dao động
  cao** (≥ 30 %), "Chưa đủ dữ liệu". Dưới tên luồng: "Dao động mỗi ngày (lượt hiển thị): ±X %".
- Bảng "Độ dao động · {luồng}": từng sản phẩm, khoảng thấp – cao (p10–p90 từng ngày) của Lượt hiển
  thị/ngày, CTR, CTOR, cột "Dao động mỗi ngày (lượt hiển thị)"; nút sắp xếp "Lưu lượng ổn định trước";
  "Lưu lượng ổn định · nên chọn" là dòng nên đặt mục tiêu (KPI chính xác hơn).
- GMV cả shop sau mô phỏng = tổng GMV/ngày các luồng; "≈ X tr ₫ mỗi tháng" = chênh lệch × 30. Đây là
  phép nhân công thức, không phải dự báo của mô hình.

### A3. Juli chọn sản phẩm và đặt mục tiêu thế nào (D29, D30)

1. **Khoảng thích ứng.** Với từng sản phẩm và từng chỉ số, Juli lấy khoảng ngắn nhất trong
   Cửa sổ chẩn đoán (mặc định 14 → 30 → 60 ngày) có ≥ Dữ liệu tối thiểu (mặc định 30 lượt nhấp / 30
   đơn). Không khoảng nào đủ → "Ít dữ liệu", không chẩn đoán. Khoảng này hiện trên thẻ: "· 30 ngày".
2. **Bắt đầu từ một chỉ số (D39.1, mặc định từ P30).** Sản phẩm thành ứng viên khi **bất kỳ** chỉ số
   nào trong Lượt hiển thị/ngày, CTR, CTOR, AOV giảm **nhiều hơn dao động gộp** √(a² + b²) của chính
   nó (khoảng hiện tại so với khoảng liền trước cùng độ dài, khoảng trước có ít nhất nửa số ngày có dữ
   liệu), **kể cả khi GMV giữ được**. Mỗi chỉ số đọc trên kênh của nó (D32): Lượt hiển thị và CTR trên
   Thẻ sản phẩm khi kênh đủ dữ liệu, CTOR và AOV trên tất cả kênh. Chỉ số "Ít dữ liệu" không bao giờ mở
   thẻ. Sản phẩm bán chạy cũng được xét.
3. **Chỉ số mục tiêu = chỉ số tốn GMV nhiều nhất.** Tách: ln(GMV nay / GMV trước) = Σ ln(chỉ số nay /
   chỉ số trước). Phần GMV chỉ riêng chỉ số đó làm mất mỗi ngày = GMV/ngày hiện tại × (e^(−c) − 1),
   với c = ln(chỉ số nay / chỉ số trước) trên kênh của nó (GMV của kênh khi có, không thì của sản
   phẩm). Một sản phẩm chỉ có một chỉ số mục tiêu (D29.4): chỉ số giảm tốn GMV nhiều nhất. Thẻ được
   **xếp hạng theo phần GMV này** (nhân hệ số hiệu chỉnh và lý do của người bán như trước); Lưu lượng
   ổn định chỉ còn để phân định khi bằng nhau. Lý do trên thẻ nói chỉ số nào giảm và GMV có giữ được
   không, ví dụ "CTOR giảm 20 % so với 30 ngày trước nhưng doanh thu được giữ nhờ lượt hiển thị tăng;
   nếu cải thiện CTOR, doanh thu có thể tăng thêm khoảng 1.200.000 ₫/tháng" (GMV giảm: "… và kéo
   doanh thu giảm 12 %; nếu cải thiện CTR, doanh thu có thể lấy lại khoảng …"). Ops thấy chi tiết
   (các chỉ số giảm, dao động gộp, phần GMV, chỉ số giữ GMV) trong `diagnosis.metric_trigger` của thẻ.
   **Lọc nhiễu CTR / CTOR (D41.2, mặc định Bật):** trước khi so với dao động, CTR và CTOR của sản
   phẩm được kéo về mức chung của ngành hàng trong shop, càng ít dữ liệu càng kéo mạnh (beta-binomial
   thực nghiệm: tỉ lệ = (lượt thành công + α) ÷ (lượt thử + α + β), α và β ước lượng từ các sản phẩm
   cùng ngành hàng trong cùng khoảng ngày; ngành hàng dưới 5 sản phẩm dùng mức chung của cả shop).
   Sản phẩm 70 lượt hiển thị/ngày "giảm" CTR 4 % → 3 % không còn mở thẻ; sản phẩm nhiều dữ liệu gần
   như không đổi. Chỉ ảnh hưởng việc mở thẻ: KPI, dao động, GMV mất và câu cho người bán vẫn dùng số
   thô. Chi tiết trong `diagnosis.metric_trigger.drops[].shrinkage`.
   **Cách cũ (GMV trước, D29.2)** vẫn chọn được cho từng shop ở "Điều kiện mở thẻ" (mục A5): sản phẩm
   chỉ thành ứng viên khi GMV/ngày giảm nhiều hơn dao động gộp của GMV, rồi chỉ số kéo xuống nhiều
   nhất là chỉ số mục tiêu, xếp hạng theo Lưu lượng ổn định trước. Sản phẩm không có chỉ số nào giảm
   chỉ có thẻ "tăng trưởng" khi mô phỏng người mua tìm được phương án thắng rõ (D38) — chưa xây trong
   hệ thống.
4. **Mức tham chiếu** = cao nhất trong: trung vị của shop, mức ổn định trước đây của chính sản phẩm,
   chuẩn ngành hàng (khi có).
5. **Mục tiêu (Chỉ số chính)** = mức tham chiếu, kẹp vào [hiện tại + KPI tối thiểu × dao động,
   hiện tại + KPI tối đa × dao động] (mặc định 1× và 3×). Dưới 1 lần không đo được; trên 3 lần là hứa
   quá. Dự đoán hiệu quả (D30.3) chỉ được thu hẹp khoảng này, không nới rộng.
6. **Sản phẩm dao động cao** (CV lượt hiển thị > Ngưỡng lưu lượng ổn định, mặc định 30 %): vẫn có thẻ,
   mục tiêu hiện dạng khoảng, Độ tin cậy Thấp, chỉ chốt ở ngày 14.
7. **Lưu lượng ổn định** được ưu tiên khi hai thẻ tốn GMV như nhau (cách cũ "GMV giảm": ưu tiên trước
   hết); Quality Score và dự đoán hiệu quả là thuật toán nội bộ, chỉ lộ ra qua thứ hạng thẻ, Độ tin
   cậy và khoảng mục tiêu.
8. **Kênh đo (D32).** Chỉ số mục tiêu, khoảng thích ứng, dao động trung bình, mức kẹp KPI, Độ tin
   cậy, mức tham chiếu, GMV dự kiến và kết quả ngày 7 / ngày 14 đều tính trên **kênh mà thay đổi tác
   động**: Ảnh bìa, Tiêu đề, Mô tả → Thẻ sản phẩm (gồm tab Cửa hàng); Giảm giá, Flash sale, Giảm phí vận
   chuyển, Mua nhiều giảm nhiều → tất cả kênh. Dữ liệu theo kênh là lượt hiển thị + CTR (và GMV) mỗi
   ngày của TikTok theo loại nội dung; TikTok không trả đơn hàng theo kênh, nên CTOR và AOV luôn tính
   trên tất cả kênh. Khi kênh có ít hơn Dữ liệu tối thiểu lượt nhấp trên khoảng dài nhất (hoặc ngày đó
   không có số theo kênh), Juli dùng tất cả kênh và thẻ ghi "đo trên tất cả kênh"; ngược lại thẻ ghi
   "đo trên kênh Thẻ sản phẩm". Trên một kênh, mức tham chiếu là trung vị của shop **trên kênh đó** và
   mức trước đây của sản phẩm trên kênh đó (chuẩn ngành hàng là số tất cả kênh nên không dùng); Độ tin
   cậy theo lượt nhấp và CV lượt hiển thị của kênh. GMV/ngày của sản phẩm vẫn phải giữ trong dao động
   (kiểm tra trên tất cả kênh). Video và LIVE là thẻ nội dung riêng, đo trên luồng của chúng.

**Ví dụ kênh đo (số giả lập):** một sản phẩm bán qua Thẻ sản phẩm (đều) và Video (CTR mỗi ngày nhảy
0,5–4,5 %). Thẻ Ảnh bìa: trên tất cả kênh CTR 2,55 %, dao động ±7,2 % → mục tiêu kẹp 2,74–3,10 %; trên
Thẻ sản phẩm CTR 2,96 %, dao động ±1,6 % → mục tiêu kẹp 3,00–3,10 %. Khoảng hẹp hơn nên một thay đổi
nhỏ của ảnh bìa đã đo được, và lượt nhấp video không che mất kết quả.

**Ví dụ khoảng mục tiêu "3,22 % → 3,8–4,4 %":** CTR hiện tại 3,22 %, dao động trung bình ±18 %
(= ±0,58 điểm). Khoảng cho phép: 3,22 + 0,58 = 3,80 % đến 3,22 + 3 × 0,58 = 4,96 %. Dự đoán hiệu quả
của thay đổi (ví dụ ảnh bìa mới) cho 3,7–4,4 % → giao nhau 3,8–4,4 %. Sản phẩm dao động cao nên hiện
khoảng, kèm chip "▲ 18–37 %" và "· 30 ngày".

**GMV dự kiến** (ví dụ "+0,5–1,2 tr ₫/tháng"): phần GMV/ngày lấy lại được nếu chỉ số mục tiêu về mức
tham chiếu, × 30, nhân hệ số hiệu chỉnh của loại thay đổi (khởi đầu 0,5; sau mỗi lần chốt ngày 14
dịch ¼ quãng về tỷ lệ thực tế ÷ dự kiến, kẹp 0–2). Trên thẻ ghi "ước tính".

**Nhóm "N thay đổi cho CTR":** nhiều thẻ của cùng một sản phẩm chỉ được cùng nhắm MỘT chỉ số (ví dụ
Ảnh bìa + Tiêu đề cùng cho CTR), không bao giờ CTR và CTOR cùng lúc — để kết quả quy được về đúng
thay đổi. Mỗi thẻ vẫn **Duyệt** riêng.

### A4. Đọc một thẻ đã đo (Đo lường)

Mốc: **Ngày 0** (ngày Juli ghi thành công, hoặc ngày khuyến mãi bắt đầu), **Ngày 7 · kiểm tra**,
**Ngày 14 · chốt**. Khối "Mục tiêu và Ngưỡng giữ ổn định": "Trung bình mỗi ngày · so với 14 ngày trước
khi áp dụng". Cột "Ngưỡng giữ ổn định" ghi giá trị kèm nguồn: "±3 % · Juli gợi ý" hoặc "±5 % · Bạn đặt".

Bảng kết quả: Chỉ số · Trước · Mục tiêu / khoảng cho phép · Thực tế · Đánh giá. Dòng đầu là chỉ số
mục tiêu (ngày 7: Đang lên / Chưa rõ), các dòng sau là chỉ số giữ (**Giữ ổn định** / Ngoài khoảng),
dòng cuối GMV/ngày (Sơ bộ, rồi nhãn chốt).

| Mốc | Nhãn | Điều kiện (dao động = Dao động TB của 14 ngày trước, tối thiểu 1 %) |
|---|---|---|
| Ngày 7 | **Đang lên** | mục tiêu tăng > 1 × dao động và GMV không giảm quá dao động GMV |
| Ngày 7 | **Chưa rõ** | còn lại |
| Ngày 7 | "Ngày 7 · cần bạn quyết" + **Hoàn tác?** | một chỉ số giữ ra ngoài Ngưỡng giữ ổn định |
| Ngày 14 | **Đạt** | tăng > 1 × dao động, ≥ mục tiêu, GMV giữ được |
| Ngày 14 | **Đạt · chưa chắc chắn** | (D31.7) như Đạt nhưng mức tăng chỉ 1–2 × dao động gộp |
| Ngày 14 | **Một phần** | tăng rõ hoặc chạm mục tiêu, không đủ cả hai |
| Ngày 14 | **Không đạt** | không tăng rõ, không chạm mục tiêu |
| bất kỳ | **Bị ảnh hưởng bởi thay đổi khác** | có thay đổi bên ngoài trong khoảng đo; liệt kê "Tiêu đề sửa ngoài Juli · 12/10", "Flash sale bắt đầu · 14/10"… |

Thẻ đo trước D29 có mã cũ trong dữ liệu: `gan_dat` (70–99 % GMV dự kiến) và `chua_ket_luan` (dữ liệu
quá ít hoặc có thay đổi khác). Cả hai nay hiện là **Một phần** (với `chua_ket_luan` tiêu đề ghi "chưa
đủ dữ liệu để chốt rõ"); `chua_ket_luan` vẫn không dùng để chỉnh hệ số hiệu chỉnh.

Cách đọc nhanh: (1) nhãn chốt; (2) nếu có "Bị ảnh hưởng bởi thay đổi khác" → không tính công cho Juli,
dù số tăng; (3) xem các chỉ số giữ — một chỉ số "Ngoài khoảng" nghĩa là thay đổi có thể đã đánh đổi
chỉ số khác; (4) GMV/ngày thực tế so với GMV dự kiến.

**Ngưỡng giữ ổn định:** mặc định (**Juli gợi ý**) mỗi chỉ số giữ = Ngưỡng giữ ổn định (Ops, mặc định
1 ×) × dao động trung bình 14 ngày trước khi áp dụng của chỉ số đó. Không còn mức ±3 % cố định: khi chưa
có mặc định, Quy tắc để trống ("—"). Người bán đặt riêng trong Quy tắc thì giá trị của người bán thắng
(**Bạn đặt**). Juli không bao giờ tự hoàn tác; **Hoàn tác** tạo một lượt chạy mới khôi phục nội dung cũ,
cũng qua bước xác nhận; với khuyến mãi, Hoàn tác = Juli hướng dẫn người bán tắt khuyến mãi.

### A5. Cài đặt shop → "Chẩn đoán & KPI" (Admin)

Mỗi hàng là một bản nháp, lưu qua hộp xác nhận trước → sau, ghi Nhật ký. "Về mặc định" bỏ giá trị riêng.

| Nhãn | Mặc định | Giới hạn | Tác dụng |
|---|---|---|---|
| Cửa sổ chẩn đoán | 14 · 30 · 60 ngày | 1–5 khoảng, mỗi khoảng 7–90 ngày | Ngắn nhất đủ dữ liệu được dùng. Bỏ 14 → thẻ chậm phản ứng nhưng ổn định hơn |
| Dữ liệu tối thiểu | 30 lượt nhấp/đơn | 5–1000 | Dưới mức này chỉ số là "Ít dữ liệu", không chẩn đoán. Cao hơn → ít thẻ hơn nhưng chắc hơn; cũng là mốc Độ tin cậy Cao (≥ 3 ×) |
| Điều kiện mở thẻ | Một chỉ số giảm | Một chỉ số giảm / GMV giảm (cũ) | Một chỉ số giảm (D39.1): mở thẻ khi bất kỳ chỉ số nào giảm quá dao động, kể cả khi GMV giữ được, xếp theo GMV chỉ số đó làm mất. GMV giảm (cũ, D29.2): chỉ khi GMV giảm quá dao động — để quay lại cách cũ cho một shop |
| Lọc nhiễu CTR / CTOR | Bật | Bật / Tắt | Bật (D41.2): CTR / CTOR kéo về mức chung của ngành hàng theo lượng dữ liệu trước khi so với dao động — bớt thẻ mở vì may rủi ở sản phẩm ít dữ liệu. Tắt: so số thô như trước |
| KPI tối thiểu | 1 × dao động | 0,5–10 | Mục tiêu ≥ hiện tại + N × dao động. Dưới 1 → mục tiêu có thể không đo được |
| KPI tối đa | 3 × dao động | 0,5–10 (không nhỏ hơn KPI tối thiểu) | Mục tiêu ≤ hiện tại + N × dao động. Cao hơn → hứa nhiều hơn |
| Ngưỡng giữ ổn định | 1 × dao động | 0,5–10 | Ngưỡng mặc định (Juli gợi ý) của chỉ số không phải mục tiêu. Nhỏ hơn → hỏi "Hoàn tác?" thường hơn |
| Ngưỡng lưu lượng ổn định | CV > 30 % | 5–200 % | Lượt hiển thị dao động (CV) trên ngưỡng: KPI dạng khoảng, độ tin cậy Thấp, chỉ chốt ngày 14 |

Ngưỡng "Ít dữ liệu" của Mô phỏng (30) và mốc Lưu lượng ổn định/Dao động vừa của Mô phỏng (15 %/30 %)
là cố định, không theo các tunable này.

Các phần khác của Cài đặt shop: giai đoạn (Thử nghiệm · Tự vận hành · Pilot đặc biệt), luồng và hành
động bật/tắt, API khuyến mãi, model, giới hạn OpenAI riêng (mặc định $5/tháng), và Quy tắc của người bán
(ghi "Đội ngũ Juli đặt"; người bán thấy và sửa tiếp).

#### A5.1. "Nhiều thẻ mỗi ô (thử nghiệm)" (Admin, D33)

Bật cho từng shop (mặc định Tắt; shop khác không đổi). Lưu cùng hàng tunable của "Chẩn đoán & KPI",
qua hộp xác nhận, ghi Nhật ký.

| Nhãn | Mặc định | Giới hạn | Tác dụng |
|---|---|---|---|
| Nhiều thẻ mỗi ô | Tắt | Bật / Tắt | Thay 3 Juli / 1 Seller Center / 1 nội dung mỗi ngày (và giới hạn ngày/tuần mặc định) bằng tối đa N thẻ MỞ cho mỗi ô |
| Thẻ mở mỗi ô | 5 thẻ/ô | 1–20 | N. Ô = chỉ số mục tiêu × kênh đo (CTR · Thẻ sản phẩm, CTOR · tất cả kênh …); Video và LIVE (nội dung) là ô riêng |
| Thẻ mở tối đa (nhiều thẻ) | 40 thẻ mở | 5–100 | Trần chung. "Số thẻ mở cùng lúc" của người bán vẫn thắng; giới hạn ngày/tuần/mở mà Ops đặt riêng vẫn áp dụng |

Khi bật: thời hạn 7 ngày, thời gian chờ 7 ngày, một chỉ số mỗi sản phẩm (D29.4), luồng/hành động tắt
và loại trừ quà tặng giữ nguyên; thẻ bị chặn vì ô đầy có lý do `cell_cap`. Trang Cài đặt shop hiện
"Thẻ đang mở theo ô" (ví dụ "CTR · Thẻ sản phẩm: 5/5"). Cũng chỉ khi bật:

- **Giảm giá** được đề xuất khi shop có Quy tắc mức giảm giá tối đa (mặc định hoặc theo SKU); không đề
  xuất khi sản phẩm đang có giảm giá / flash sale đang chạy (bảng khuyến mãi đã lưu); Mua nhiều giảm
  nhiều không đề xuất khi đang chạy. Flash sale và Giảm phí vận chuyển vẫn tắt (chưa có dữ liệu cho
  điều kiện của chúng).
- **Thấp hơn mức shop (S28B):** sản phẩm có GMV không giảm (`no_gmv_drop`) và (với "Một chỉ số giảm")
  không chỉ số nào giảm quá dao động, nhưng CTR / CTOR / AOV thấp
  hơn trung vị của shop quá 1 × dao động (đủ dữ liệu), và cũng thấp hơn trung vị trên kênh của thay đổi,
  nhận thẻ: mục tiêu = KPI tối thiểu (1 ×) thôi, Độ tin cậy Thấp, xếp sau mọi thẻ GMV giảm, mã
  `reason_code = below_shop_level`. Lý do hiện cho người bán: "CTR của sản phẩm trên kênh Thẻ sản phẩm
  thấp hơn mức chung của shop (x so với y); doanh thu không giảm, đây là cơ hội tăng thêm".
- Trọng số Quality Score theo loại thay đổi (tới 1,5 × cho ảnh bìa / tiêu đề / mô tả) bỏ, nên thay đổi
  giá xếp hạng ngang thay đổi nội dung.

Ô có thể có thẻ với dữ liệu hiện lưu: Lượt hiển thị và CTR (Thẻ sản phẩm hoặc tất cả kênh), CTOR và
AOV (chỉ tất cả kênh), Video, LIVE.

#### A5.2. "Nhóm thử nghiệm (đối chứng chậm)" (Admin, D34 / D39.3)

Vì sao: thẻ được chọn **vì** sản phẩm vừa giảm, nên so trước/sau đơn thuần hay "ăn may" (sản phẩm tự
hồi lại), và thuật toán sàn, mùa vụ, đối thủ đều làm số lên xuống. Chỉ chia ngẫu nhiên mới tách được
hiệu quả thật của một loại thay đổi.

| Nhãn | Mặc định | Giới hạn | Tác dụng |
|---|---|---|---|
| Nhóm thử nghiệm (đối chứng chậm) | Theo Nhiều thẻ mỗi ô | Bật / Tắt | Bật: chia nhóm và giữ đối chứng như dưới đây. Tắt: thẻ ra như trước, không giữ thẻ nào |

- **Nhóm** = chỉ số mục tiêu × thay đổi × kênh đo trong một shop (ví dụ "CTR · Ảnh bìa · Thẻ sản phẩm").
- Khi có **≥ 3 thẻ chờ** của cùng nhóm (3 sản phẩm khác nhau, chưa thuộc nhóm cùng loại nào trong 44 ngày qua — thẻ đối chứng đã trả không
  bao giờ bị giữ lần hai), Juli
  mở một nhóm: xáo trộn các sản phẩm bằng một **seed** ngẫu nhiên (lưu lại — cùng seed cho ra đúng
  cách chia đó), khoảng **1/3** (làm tròn, ít nhất 1) là **đối chứng**. Thẻ đối chứng bị giữ (lý do
  `group_control`) và **trả lại sau 14 ngày** kể từ ngày mở nhóm — không người bán nào mất thẻ hẳn.
  Dưới 3 thẻ: không có nhóm, thẻ ra như bình thường.
- **Nhóm áp dụng** được ưu tiên trong 3 ngày đầu, vẫn theo giới hạn thẻ (3/1/1 mỗi ngày, hoặc số thẻ mỗi ô).
- **Ngày 14** (khi số liệu đã đủ 14 ngày kể từ ngày mở): với từng sản phẩm, chỉ số mục tiêu trên kênh
  của nhóm, trung bình 14 ngày từ ngày mở so với 14 ngày trước đó (%). **Kết quả = trung vị nhóm áp
  dụng − trung vị nhóm đối chứng** (điểm %), khoảng 90 % bằng bootstrap (lặp 2.000 lần, seed của nhóm),
  đọc theo quy tắc D31.7 so với nửa độ rộng khoảng: **Thay đổi rõ / Có thể thay đổi / Trong dao động**.
- **Chặt hơn từ D41.3:** (a) thay đổi của từng sản phẩm được điều chỉnh theo 14 ngày trước đó của chính
  nó (kiểu CUPED, θ chung của nhóm, xem `group_stats.py`) để phần "hồi lại sau khi tụt" không bị tính
  cho thay đổi; (b) khi đối chứng dưới 5 sản phẩm, phải qua thêm kiểm định hoán vị (thử mọi cách chọn
  đối chứng, p ≤ 0,10), không thì là Trong dao động; (c) hệ thống chạy lại quy tắc 500 lần trên số liệu
  không có thay đổi nào của chính nhóm để đo **tỉ lệ báo động giả**: cặp 14 ngày trước-trước / 14 ngày
  trước của mọi sản phẩm, cộng các cặp 14 ngày liền nhau sau ngày mở của sản phẩm đối chứng khi chúng còn
  chưa được duyệt thẻ (đối chứng chưa bị đổi gì). Trên **15 %** (T3.1, chủ shop chốt sau kiểm tra công
  suất v0.3: ở 17 + 9 sản phẩm × 28 ngày, ngưỡng ≈ 11,7 % để 27 % nhóm kẹt "Đang đo", ngưỡng 15 % chỉ
  12 %, báo động giả thật vẫn ≤ 9,6 %) thì nhãn là **"Đang đo"**, không nói mạnh yếu, người bán không
  thấy câu nào. Nhóm "Đang đo" được đo lại mỗi 7 ngày (ngày 21, 28, … đến ngày 56) với số liệu mới nhất:
  khoảng so sánh vẫn là 14 ngày đầu, nhưng số liệu không thay đổi của đối chứng nhiều thêm nên nhóm có
  thể ra khỏi "Đang đo". Con số báo động giả này hiện cạnh kết quả ("báo động giả x %"). Nhóm nhỏ (ví dụ 5 + 3 với trung vị) gần như luôn là
  Trong dao động hoặc Đang đo — đó là chủ ý.
  Tính theo **cách chia** (cả thẻ người bán không duyệt); "Chỉ thẻ đã duyệt" là số phụ.
- Nhãn: ≥ 3 áp dụng + ≥ 2 đối chứng có số liệu → **"Sơ bộ"**; ≥ 5 + ≥ 3 → không nhãn; ít hơn →
  **"Chưa đủ cơ sở"** (không có con số, người bán không thấy câu nào); báo động giả trên 15 % →
  **"Đang đo"** (có con số cho Ops, không có độ mạnh, người bán không thấy câu nào).
- Trang Cài đặt shop hiện **"Nhóm thử nghiệm (đối chứng chậm)"**: từng nhóm, trạng thái (Đang chạy /
  Đã đo), ngày bắt đầu, ngày trả thẻ đối chứng, số áp dụng · đối chứng, kết quả ngày 14 với khoảng,
  số "Chỉ thẻ đã duyệt", câu người bán thấy, seed; bấm vào nhóm để xem từng sản phẩm (nhóm, thẻ đang
  giữ / đã trả / đã hiện / đã duyệt, thay đổi %).
- Người bán chỉ thấy **Kết quả nhóm**: một câu trên các thẻ cùng nhóm (cùng chỉ số × thay đổi × kênh)
  khi nhóm gần nhất đã có kết quả, ví dụ "Nhóm 6 sản phẩm đổi ảnh bìa: lượt nhấp tăng khoảng 7 % so
  với các sản phẩm chưa đổi" (thêm "(sơ bộ)" khi nhãn Sơ bộ).
- Chưa làm: kết quả của các shop tương tự cho shop quá nhỏ (D34.6) và bảng hiệu quả theo loại thay đổi
  thay trọng số xếp hạng (D34.7).

#### A5.3. Nhóm tạo trong Ops, AOV, cảnh báo CTR, sàn trôi tuần (Admin, D45, P36 — chỉ Ops)

Mọi thứ ở mục này chỉ có trong Ops; ứng dụng người bán không đổi.

- **Tạo nhóm thử nghiệm** (nút trong "Nhóm thử nghiệm (đối chứng chậm)", quyền Operator): cho một thay
  đổi Juli không đề xuất thành thẻ, trước hết **"Quy cách mới"** (ví dụ thêm gói 2× giảm 5 % mỗi đơn
  vị). Dán mã sản phẩm TikTok (ít nhất 3, tối đa 60, đều phải thuộc shop, không sản phẩm nào đang ở
  nhóm khác trong 44 ngày). Juli chia ngẫu nhiên như nhóm thẻ (seed lưu lại, khoảng 1/3 đối chứng),
  không tạo thẻ, không ghi gì lên TikTok: **chủ shop tự tạo SKU trên TikTok cho nhóm áp dụng**. Người
  bán không thấy nhóm này (không câu "Kết quả nhóm"). Sản phẩm trong nhóm Ops không bị rút vào nhóm thẻ.
  Nhóm Ops vẫn được đo ngày 14 khi "Nhóm thử nghiệm (đối chứng chậm)" đang tắt.
- **Chia tầng theo số đơn 30 ngày** (ô chọn khi tạo, D45.8): sản phẩm xếp theo số đơn mọi kênh 30 ngày
  qua, nửa nhiều đơn (làm tròn lên) là tầng "nhiều đơn", còn lại "ít đơn"; chia ngẫu nhiên trong từng
  tầng (3 sản phẩm → 2 áp dụng + 1 đối chứng). Cần ít nhất 6 sản phẩm. Ví dụ nhóm quy cách D45.8: tầng
  nhiều đơn = Ion Kiềm 300 mL, 1250 mL, Tinh Khiết 450 mL; tầng ít đơn = ba sản phẩm còn lại. Chủ shop
  đối chiếu với nhóm băng giá đang chạy trước khi tạo.
- **Chỉ số chính và cảnh báo CTR** (D45.2): nhóm quy cách đọc **AOV mọi kênh** là chỉ số chính, kèm
  **Số món mỗi đơn** mọi kênh; mọi nhóm (kể cả nhóm thẻ) có thêm hai số này, cùng cách đọc: khoảng 90 %,
  báo động giả, điều chỉnh tiền kỳ. CTR thẻ sản phẩm là **chỉ số canh**: khi nhóm áp dụng giảm hơn
  **15 %** so với đối chứng (chỉnh ở "Nhóm thử nghiệm: cảnh báo CTR giảm quá") Ops hiện dòng đỏ "Cảnh
  báo: … dù AOV tăng …". Đây là lời nhắc xem lại, không phải kết luận.
- **Điều chỉnh tiền kỳ theo cỡ nhóm** (D45.6, sửa bởi D47.1): dưới **15** sản phẩm có số liệu, giữ
  cách P31 (một cửa sổ, θ tự khớp của nhóm) — kiểm tra công suất P36 thấy θ = 1 làm nhóm nhỏ yếu đi
  (4 + 2 · 28 ngày ở +40 %: 35 → 25 %), ngược với nghiên cứu §4a, nên sẽ kiểm lại trên các nhóm D34
  thật đầu tiên; từ 15 sản phẩm, điều chỉnh theo **hai cửa sổ 14 ngày
  trước** (ngày −28…−15 và −14…−1); lần chạy lại báo động giả dùng đúng cách này. Dòng "Cách tính" ghi
  cách nào đã chạy. Nhóm thẻ: kết quả chính (câu người bán thấy) **giữ cách P31** cho tới khi chủ shop
  quyết định; cách mới hiện ngay dưới, dòng "Theo cách tính mới (…, chỉ Ops)". Chỉnh ngưỡng 15 ở "Nhóm
  thử nghiệm: hai cửa sổ tiền kỳ từ".
- **Sàn trôi tuần** (D45.4): mỗi nhóm hiện sàn của nửa độ rộng khoảng 90 % do số liệu tự trôi tuần
  qua tuần (σ 0,15 mỗi tuần, chỉnh ở "Nhóm thử nghiệm: trôi tuần (σ)"): z · √(2σ² / số tuần / số sản
  phẩm), và cho hiệu áp dụng − đối chứng z · √(2σ² / số tuần · (1/n áp dụng + 1/n đối chứng)). Ví dụ:
  6 sản phẩm × 2 tuần ±10,1 %, 26 × 2 tuần ±4,8 %, 4 + 2 cửa sổ 2 tuần ±21,4 %, 4 tuần ±15,1 %. Cạnh đó
  là lượng cần mỗi nhánh cho ±10 % (lượt hiển thị với CTR / CTOR, đơn với AOV) có và không tính trôi,
  và lượng có trong 14 ngày trước khi bắt đầu. Không nhãn, không chặn gì.
- **Lý do chọn thử nghiệm** (D45.3): một dòng tự gõ (tối đa 200 ký tự), sửa được trên mọi nhóm; mỗi lần
  sửa vào Nhật ký. Chọn thử nghiệm tự động (knowledge gradient) chưa làm: chỉ sau khi 2–3 nhóm D34 có
  kết quả.

#### A5.4. Lift đã co (EB) (D52, P45 — chỉ Ops)

Một nhóm được chú ý vì kết quả trông rất tốt thường may mắn hơn thực tế ("lời nguyền người thắng").
Cạnh mỗi kết quả nhóm (chỉ số chính, cách tính mới, AOV, số món mỗi đơn) Ops hiện thêm một dòng:
**"Lift đã co (EB): +x % [thấp; cao] · lift thô +y % · …"**. Rê chuột vào dòng sẽ thấy: "Điều chỉnh
theo các nhóm cùng loại để tránh tin nhầm kết quả may mắn".

- **Cách tính.** Lift thô đổi sang thang log: y = ln(1 + chênh lệch / (100 + thay đổi của đối chứng)),
  sai số se lấy từ khoảng 90 % của chênh lệch. Lift đã co = w · y + (1 − w) · μ với w = τ² / (τ² + se²):
  nhóm càng nhiễu (se lớn) càng được kéo về μ; nhóm đo chắc (se nhỏ) gần như giữ lift thô. Khoảng
  [thấp; cao] là khoảng 90 % của lift đã co.
- **Mốc so sánh (μ, τ) theo loại đòn bẩy** (cùng đòn bẩy × chỉ số × kênh). Khi đã có ít nhất **3** nhóm
  cùng loại được đo ở các shop (mỗi shop tính là một; nhiều nhóm của một shop được gộp trước; không tính
  chính nhóm đang xem), Juli ước lượng μ và τ từ các nhóm đó (DerSimonian–Laird); dòng ghi "theo n nhóm
  cùng loại". Chưa đủ thì dùng mức mặc định μ = 0, τ = 0,15 (khoảng ±15 %); dòng ghi "mức mặc định".
  Chỉnh ở "Nhóm thử nghiệm: độ lệch mặc định khi co lift (EB)" và "Nhóm thử nghiệm: số nhóm cùng loại
  tối thiểu để co lift".
- **Dữ liệu shop khác.** Chỉ Ops đọc kết quả nhóm của các shop khác, và chỉ hiện con số tổng hợp
  (μ, τ, số nhóm); không hiện tên, mã hay số liệu riêng của shop nào.
- **Shop nào góp, shop nào dùng (D11, D14, D17 — 2026-10-27).** Chỉ shop đã đồng ý gộp dữ liệu
  (`pooled_training`) góp kết quả nhóm vào mốc so sánh và chỉ những shop đó dùng mốc chung; shop
  chưa đồng ý không góp cũng không dùng ("chỉ dữ liệu của shop này"). Quyền này chỉ cấp cho shop của
  chính Juli (shop sandbox của Juli): điều khoản TikTok Shop (Developer ToS §2.7(g), Partner Center ToS
  §3.8(e)) cấm gộp dữ liệu API của người bán cho mục đích riêng của Juli; Shopee (ToS §6.2(c)) cần
  Shopee đồng ý bằng văn bản cho số liệu tổng hợp về hiệu quả người bán. Thêm một lớp bảo vệ: một ô
  gộp chỉ được dùng khi có **ít nhất 5 shop đã đồng ý** góp vào và **không shop nào chiếm quá 50 %**
  số kết quả nhóm trong ô; không đủ thì lùi sang ô rộng hơn — mọi loại thay đổi cùng chỉ số × kênh
  (dòng ghi "theo n shop, mọi loại thay đổi cùng chỉ số") — vẫn không đủ thì dùng mức mặc định. Hiện
  chỉ shop của Juli đồng ý, nên mọi dòng đều đang ở mức mặc định. Hệ số hiệu chỉnh cấp "fleet" của Dự
  đoán hiệu quả (D30.3) theo cùng quy tắc: ô theo đòn bẩy, rồi mọi đòn bẩy.

#### A5.5. GMV, "tỷ lệ chuyển đổi" và kênh Thẻ sản phẩm: định nghĩa của TikTok (D55.1, P47 — chỉ Ops)

Ba điểm dễ nhầm khi so số của Juli với Seller Center (nguồn: TikTok Seller University, tổng hợp ở
`~/juli-sim-pilot/research/metric_definitions.md`, 2026-10-17):

1. **GMV của TikTok gồm đơn huỷ và đơn hoàn.** TikTok định nghĩa GMV là tổng tiền của các đơn trong
   khoảng, *kể cả đơn sau đó bị huỷ hoặc hoàn tiền*. Mọi số GMV, GMV/ngày và AOV Juli lấy từ số liệu
   TikTok đều theo nghĩa này. Câu người bán thấy không đổi (D55.1).
   - **Nhóm thử nghiệm (chỉ Ops):** khi đơn hàng của shop (đồng bộ mỗi chu kỳ: trạng thái đơn, dòng
     sản phẩm, yêu cầu hoàn/huỷ) phủ đủ mọi ngày nhóm đọc (ngày −42 đến ngày 13), **AOV** và **Số món
     mỗi đơn** mọi kênh được đọc **đã trừ huỷ/hoàn**: mỗi ngày của từng sản phẩm, đơn SKU × (1 − tỷ lệ
     đơn bị huỷ/hoàn hết), số món × (1 − tỷ lệ món bị huỷ/hoàn), GMV × (1 − tỷ lệ giá trị bị huỷ/hoàn;
     hoàn một phần chỉ trừ số tiền hoàn). Đơn hoàn tính vào ngày đặt đơn. Ngày không có đơn của sản
     phẩm giữ nguyên số TikTok. Chỉ tính yêu cầu hoàn/huỷ đã xong (không tính đang chờ, bị từ chối
     hay đổi hàng). Khoảng 90 %, báo động giả, cảnh báo CTR ("… dù AOV tăng …") và Lift đã co (EB)
     đều chạy trên số đã trừ.
   - Ops hiện cả hai: nhãn **"AOV (đã trừ huỷ/hoàn) · tất cả kênh"** và ngay dưới **"AOV (gồm đơn
     huỷ/hoàn, theo TikTok) · tất cả kênh"**; dòng 14 ngày trước khi bắt đầu ghi **"Doanh thu (đã trừ
     huỷ/hoàn)"** cạnh **"GMV TikTok (gồm huỷ/hoàn)"**. Nhóm thẻ: kết quả chính (sau câu "Kết quả nhóm"
     của người bán) vẫn theo GMV TikTok; số đã trừ hiện ở dòng "AOV (đã trừ huỷ/hoàn) · tất cả kênh
     (chỉ Ops)".
   - Khi đơn hàng chưa phủ đủ (shop mới kết nối, chưa đồng bộ đơn), nhãn ghi **"gồm đơn huỷ/hoàn, theo
     TikTok"** và dòng 14 ngày ghi **"GMV (gồm đơn huỷ/hoàn, theo TikTok)"**.
   - Giới hạn: đơn hoàn về sau (sau ngày đo) chưa bị trừ, nên số đã trừ của 14 ngày sau có thể còn
     giảm nhẹ; hai nhánh cùng chịu nên chênh lệch áp dụng − đối chứng ít bị ảnh hưởng.
2. **"Tỷ lệ chuyển đổi" của TikTok không phải CTOR của Juli.** Trong Product Analytics, TikTok tính
   tỷ lệ chuyển đổi = số người mua duy nhất ÷ số lượt xem trang duy nhất (theo người). **CTOR** của
   Juli = đơn SKU ÷ lượt nhấp (theo lượt), khớp chỉ số "CTOR (SKU Order)" mới của Seller Analytics.
   Người bán so với ô "tỷ lệ chuyển đổi" cũ sẽ thấy hai số khác nhau: cả hai đều đúng, chỉ khác định
   nghĩa. Trả lời: "CTOR của Juli là số đơn trên mỗi lượt nhấp, giống CTOR (SKU Order) trong Seller
   Center."
3. **Kênh "Thẻ sản phẩm" là phần còn lại.** TikTok: doanh thu không đến từ LIVE và không đến từ video
   được tính là doanh thu thẻ sản phẩm. Vậy **Thẻ sản phẩm** là mọi nguồn không phải LIVE hay video
   (tìm kiếm, gợi ý…), không phải một kênh thuần; khi LIVE hoặc video đo thiếu, phần thiếu dồn vào
   Thẻ sản phẩm. Đọc thay đổi của Thẻ sản phẩm cùng với LIVE và video.

### A6. Các màn hình Ops khác

- **Tổng quan**: Đã kết nối / Đang hoạt động / Mất kết nối (Token hết hạn); từng shop: Giai đoạn, Kết
  nối, Lấy dữ liệu (lần lấy gần nhất), Thẻ mở / duyệt / từ chối, Tỷ lệ duyệt (30 ngày), OpenAI tháng này,
  GMV 30 ngày, Chạy lỗi. "Huỷ kết nối" chỉ Admin, bắt buộc lý do và gõ tên shop.
- Dòng "Số liệu đến hết DD/MM · cập nhật lúc HH:MM" + **Làm mới**: số liệu tính một lần mỗi ngày;
  Làm mới chỉ tính lại shop đang xem.
- **Chi phí**: giới hạn OpenAI hệ thống (mặc định $50/tháng) và từng shop ("· riêng"). Trạng thái:
  Bình thường, Cảnh báo 80 %, Dừng (hệ thống), Dừng (riêng). Khi dừng: không soạn nội dung mới, thẻ đề
  xuất vẫn tạo; người bán thấy "Juli tạm dừng soạn nội dung mới".
- **Thời hạn**: gia hạn theo gói 30 hoặc 365 ngày (Hợp đồng / Thanh toán). Trạng thái: còn N ngày,
  Sắp hết hạn (≤ 14 ngày), Ân hạn (7 ngày, Juli vẫn chạy), Chỉ xem (không thẻ mới, không chạy; dữ liệu
  vẫn đồng bộ), Chưa đặt (không bị giới hạn).
- **Nhật ký**: Cấu hình (365 ngày), Xem như shop và Hệ thống (90 ngày). Cùng người, cùng shop, cùng
  trường trong 10 phút → gộp một dòng.
- **Xem như shop**: luôn chỉ xem ("Đang xem như {shop} · chỉ xem, không ghi được"); thấy Trang chủ,
  Phân tích, Quyết định, Quy tắc đúng như người bán. Muốn thay đổi → Cài đặt shop.

### A7. Câu hỏi thường gặp

**"Sao Phân tích báo lượt hiển thị giảm 24,6 % mà Juli không đề xuất gì?"**
Nội bộ (D39.1): một chỉ số giảm quá dao động gộp của chính nó là đủ mở thẻ, kể cả khi GMV giữ được.
Không có thẻ khi: con số trên Phân tích là của cả shop hoặc cả luồng chứ không của từng sản phẩm; từng
sản phẩm giảm chưa quá dao động của nó; chỉ số đó "Ít dữ liệu"; sản phẩm đã có thẻ cho chỉ số khác
(D29.4) hoặc đang trong thời gian chờ; hoặc chỉ có thay đổi Tiêu đề mới tác động được lượt hiển thị mà
không có lỗi tiêu đề nào. Shop đặt "GMV giảm (cũ)" thì vẫn chỉ mở thẻ khi GMV giảm. Trả lời: "Lượt
hiển thị của shop giảm thật, nhưng ở từng sản phẩm mức giảm chưa vượt mức lên xuống thường ngày (hoặc
Juli chưa có thay đổi phù hợp), nên Juli chưa đề xuất. Khi một sản phẩm giảm rõ, Juli sẽ đề xuất."

**"Sao sản phẩm của tôi nhận thẻ muộn hơn các sản phẩm khác?"**
Nội bộ: sản phẩm rơi vào nhóm đối chứng (D34, mục A5.2). Trả lời: "Juli thử thay đổi này trên một nhóm
sản phẩm trước và giữ vài sản phẩm chọn ngẫu nhiên để so sánh, nhờ đó biết thay đổi có thật sự hiệu
quả không. Sản phẩm của bạn nhận đề xuất sau 14 ngày, kèm kết quả của nhóm."

**"Doanh thu không giảm, sao Juli vẫn đề xuất?"**
Một chỉ số của sản phẩm giảm thật nhưng chỉ số khác tăng bù. Trả lời: "CTOR của sản phẩm giảm rõ,
nhưng nhờ lượt hiển thị tăng nên doanh thu chưa giảm. Nếu cải thiện CTOR, doanh thu có thể tăng thêm
— con số trên thẻ là ước tính."

**"Hôm qua giảm 20 %, có sao không?"**
Một ngày dao động ±25 % là bình thường. Trả lời: "Một ngày lên xuống 20–25 % là bình thường với sản
phẩm này. Juli nhìn trung bình nhiều ngày, mức lên xuống của trung bình 30 ngày chỉ khoảng ±4 %."

**"Thẻ ghi Đạt, vậy là nhờ Juli?"**
Đạt = chỉ số đã thật sự tăng, chạm mục tiêu, GMV giữ được, và không có thay đổi bên ngoài được ghi
nhận. Vẫn có yếu tố Juli không thấy (đối thủ, xu hướng). Trả lời: "Kết quả này vượt xa mức lên xuống
thường ngày và trong thời gian đo không có thay đổi nào khác trên sản phẩm, nên nhiều khả năng là nhờ
thay đổi này."

**"Đạt · chưa chắc chắn là sao?"**
Tăng nhưng chỉ 1–2 lần dao động gộp. Trả lời: "Chỉ số đã chạm mục tiêu, nhưng mức tăng chưa đủ lớn để
chắc chắn không phải do ngày tốt ngẫu nhiên. Thay đổi được giữ; Juli tiếp tục theo dõi."

**"Bị ảnh hưởng bởi thay đổi khác — tôi có làm gì đâu?"**
Kiểm tra danh sách dòng dưới nhãn (sửa trên Seller Center, khuyến mãi/flash sale bắt đầu hoặc kết
thúc, đổi giá). Trả lời: "Trong 14 ngày đo, {thay đổi} xảy ra trên sản phẩm này, nên Juli không thể
tách riêng kết quả của thay đổi Juli đề xuất."

**"Sao mục tiêu là một khoảng 3,8–4,4 % chứ không phải một số?"**
Sản phẩm dao động cao. Trả lời: "Sản phẩm này lên xuống nhiều từng ngày, nên Juli đưa mục tiêu dạng
khoảng và chỉ chốt kết quả ở ngày 14."

**"Độ tin cậy Thấp thì có nên duyệt không?"**
Thấp = ít dữ liệu hoặc dao động cao, không phải đề xuất tệ. Trả lời: "Vẫn nên thử nếu thay đổi hợp lý
với bạn; Độ tin cậy Thấp nghĩa là con số dự kiến kém chắc chắn hơn, không phải thay đổi có hại."

**"Hoàn tác? — Juli có tự đổi lại không?"**
Không bao giờ. Trả lời: "Juli chỉ hỏi. Bạn chọn Hoàn tác thì Juli tạo lượt chạy khôi phục nội dung cũ,
bạn xác nhận trước khi Juli ghi; chọn Giữ thay đổi thì Juli đo tiếp đến ngày 14."

**"Ngưỡng giữ ổn định nên đặt bao nhiêu?"**
Để "Juli gợi ý" (theo dao động của từng chỉ số). Đặt quá chặt → hỏi hoàn tác vì dao động bình thường;
quá lỏng → bỏ sót thay đổi xấu.

**"Sao Mô phỏng 7 ngày báo Trong dao động mà 30 ngày lại đo được?"**
Dao động của trung bình hẹp lại khi khoảng dài hơn. Chọn khoảng 30 ngày khi đặt mục tiêu cho shop.

**Không nói với người bán:** band, p10/p90, CV, window, D29/D31, tunable, webhook, API, Ops. Dùng:
"mức lên xuống thường ngày", "trung bình mỗi ngày", "so với 30 ngày trước", và đúng nhãn trên màn hình.
