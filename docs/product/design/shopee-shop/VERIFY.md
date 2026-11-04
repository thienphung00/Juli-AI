# VERIFY — Shopee shop artboards vs `fasttrack/contracts/p90-metrics.md`

Ngày chạy 2026-11-03. Tất cả số trong các artboard là số minh hoạ từ **một bộ dữ liệu tổng hợp** (block `SHARED DATASET v1`, giống hệt từng byte trong cả chín file `.dc.html`). Kiểm tra chạy bằng Playwright trên runtime thay thế `support.js` (không nằm trong repo): mở từng artboard, đọc `renderVals()` và DOM đã render, bấm và kéo thật. Script kiểm tra và runtime không được commit; kết quả dưới đây sinh từ lần chạy đó.

Quy tắc contract §9 (cập nhật 2026-11-03) đã áp dụng: (1) giới hạn mỗi người là input, ghi “không kiểm được từ dữ liệu”, không đổi số nào; (2) trên thẻ, ② chỉ nằm ở lớp “Dự kiến”, lớp “Chắc chắn” hiện số đơn hoà vốn, không bao giờ hiện “0đ / 1đ” đỏ; (3) coverage < 100 % thì biên ghi “trên X % doanh thu có giá vốn” và lợi nhuận shop bằng đồng chỉ hiện ở 100 % (trạng thái thiếu giá vốn là mặc định của Tổng quan, cảnh `full` là 100 %); (4) chi cho trần/ngày là cùng chi với ② (quảng cáo + voucher + khuyến mãi + combo + hoa hồng); (5) đóng gói tính theo từng dòng sản phẩm (SKU), nằm trong giá vốn + đóng gói của công thức sàn.

## 1. Render, không lỗi console

54 trạng thái đã mở (9 artboard, mọi cảnh `#scene=`, mọi tab, mọi thẻ, các bước Cài đặt, các cú bấm cảnh của thẻ và của Tổng quan): **0 trạng thái có lỗi console hoặc lỗi template**.


## 2. Một bộ dữ liệu, định nghĩa giống hệt

| File | Block dữ liệu chung giống hệt | Ký tự |
|---|---|---|
| `CaiDatImport.dc.html` | đạt | 45250 |
| `CardWhatIf.dc.html` | đạt | 45250 |
| `PhanTich.dc.html` | đạt | 45250 |
| `Ranking.dc.html` | đạt | 45250 |
| `RankingMobile.dc.html` | đạt | 45250 |
| `SanPham.dc.html` | đạt | 45250 |
| `SanPhamMobile.dc.html` | đạt | 45250 |
| `TongQuan.dc.html` | đạt | 45250 |
| `TongQuanMobile.dc.html` | đạt | 45250 |

Đẳng thức và ràng buộc kiểm trên dữ liệu: 257/257 đạt.

| Kiểm tra | Kết quả |
|---|---|
| Σ năm luồng + chênh lệch nguồn = GMV shop | đạt (2 lần kiểm) |
| Σ lượt xem năm luồng = lượt xem shop | đạt (2 lần kiểm) |
| Σ sáu nguồn con = Thẻ sản phẩm · v | đạt (2 lần kiểm) |
| Σ sáu nguồn con = Thẻ sản phẩm · orders | đạt (2 lần kiểm) |
| Σ sáu nguồn con = Thẻ sản phẩm · gmv | đạt (2 lần kiểm) |
| Σ bốn ưu đãi = GMV shop | đạt (2 lần kiểm) |
| Σ bốn ưu đãi = số đơn shop | đạt (2 lần kiểm) |
| Σ QC sản phẩm + QC không gắn sản phẩm = tổng chi QC | đạt (2 lần kiểm) |
| lợi nhuận shop = Σ lợi nhuận sản phẩm − QC không gắn SP − chi khác | đạt (2 lần kiểm) |
| chi = QC + voucher + khuyến mãi + combo + hoa hồng | đạt (2 lần kiểm) |
| GMV = lượt xem×CTR×CTOR×AOV | đạt (14 lần kiểm) |
| Σ luồng = GMV×(1+e) | đạt (14 lần kiểm) |
| GMV luồng = xem×CTR×CTOR×AOV | đạt (70 lần kiểm) |
| Σ ưu đãi = GMV | đạt (14 lần kiểm) |
| buyer_paid = GMV − voucher − combo | đạt (14 lần kiểm) |
| QC ≤ luồng (GMV) | đạt (70 lần kiểm) |
| thẻ c_bep_voucher: kind min_spend_voucher hợp lệ cho chỉ số aov (§8) | đạt (1 lần kiểm) |
| thẻ c_bep_title: kind title hợp lệ cho chỉ số views (§8) | đạt (1 lần kiểm) |
| thẻ c_bep_cover: kind cover_image hợp lệ cho chỉ số ctr (§8) | đạt (1 lần kiểm) |
| thẻ c_bep_ads: kind ads_budget hợp lệ cho chỉ số views (§8) | đạt (1 lần kiểm) |
| thẻ c_gl_bundle: kind bundle_deal hợp lệ cho chỉ số aov (§8) | đạt (1 lần kiểm) |
| thẻ c_nr_vcap: kind voucher_cap hợp lệ cho chỉ số bien (§8) | đạt (1 lần kiểm) |
| thẻ c_xm_disc: kind product_discount hợp lệ cho chỉ số ctor (§8) | đạt (1 lần kiểm) |
| thẻ c_xm_title: kind title hợp lệ cho chỉ số views (§8) | đạt (1 lần kiểm) |
| thẻ c_tu_price: kind price hợp lệ cho chỉ số bien (§8) | đạt (1 lần kiểm) |
| thẻ c_gn_kw: kind keyword hợp lệ cho chỉ số views (§8) | đạt (1 lần kiểm) |
| thẻ c_gl_title: kind title hợp lệ cho chỉ số views (§8) | đạt (1 lần kiểm) |
| thẻ c_nr_ads: kind ads_roas_target hợp lệ cho chỉ số roas (§8) | đạt (1 lần kiểm) |
| thẻ c_tu_pause: kind ads_pause hợp lệ cho chỉ số roas (§8) | đạt (1 lần kiểm) |
| thẻ c_gn_adb: kind ads_budget hợp lệ cho chỉ số views (§8) | đạt (1 lần kiểm) |
| thẻ c_kol_o1: kind affiliate_commission hợp lệ cho chỉ số lien_ket (§8) | đạt (1 lần kiểm) |
| thẻ c_kol_o3: kind affiliate_commission hợp lệ cho chỉ số lien_ket (§8) | đạt (1 lần kiểm) |
| thẻ c_bep_voucher → Xếp hạng aov×voucher có dòng BEP-S5 | đạt (1 lần kiểm) |
| thẻ c_bep_title → Xếp hạng views×the_san_pham/search có dòng k6 | đạt (1 lần kiểm) |
| thẻ c_bep_cover → Xếp hạng ctr×the_san_pham/de_xuat có dòng BEP-S5 | đạt (1 lần kiểm) |
| thẻ c_bep_ads → Xếp hạng gmv×ads có dòng a7 | đạt (1 lần kiểm) |
| thẻ c_gl_bundle → Xếp hạng aov×lien_ket có dòng GL-001 | đạt (1 lần kiểm) |
| thẻ c_nr_vcap → Xếp hạng bien×voucher có dòng v1 | đạt (1 lần kiểm) |
| thẻ c_xm_disc → Xếp hạng ctor×the_san_pham/de_xuat có dòng XM-003 | đạt (1 lần kiểm) |
| thẻ c_xm_title → Xếp hạng views×the_san_pham/search có dòng k4 | đạt (1 lần kiểm) |
| thẻ c_tu_price → Xếp hạng bien×all có dòng TU-004 | đạt (1 lần kiểm) |
| thẻ c_gn_kw → Xếp hạng views×the_san_pham/search có dòng k3 | đạt (1 lần kiểm) |
| thẻ c_gl_title → Xếp hạng views×the_san_pham/search có dòng k1 | đạt (1 lần kiểm) |
| thẻ c_nr_ads → Xếp hạng gmv×ads có dòng a1 | đạt (1 lần kiểm) |
| thẻ c_tu_pause → Xếp hạng gmv×ads có dòng a2 | đạt (1 lần kiểm) |
| thẻ c_gn_adb → Xếp hạng gmv×ads có dòng a6 | đạt (1 lần kiểm) |
| thẻ c_kol_o1 → Xếp hạng gmv×lien_ket có dòng o1 | đạt (1 lần kiểm) |
| thẻ c_kol_o3 → Xếp hạng gmv×lien_ket có dòng o3 | đạt (1 lần kiểm) |
| giá sàn tuyệt đối BEP-S5-CB = 121.176 | đạt (1 lần kiểm) |
| giá sàn vận hành BEP-S5-CB = 181.979 | đạt (1 lần kiểm) |
| giảm tối đa 18.000đ (9,0%) | đạt (1 lần kiểm) |
| thẻ "trước" (A) = dòng SKU BEP-S5-CB: lợi nhuận | đạt (1 lần kiểm) |
| thẻ "trước": GMV = GMV SKU | đạt (1 lần kiểm) |
| thẻ "trước": số đơn = 30 = đơn SKU | đạt (1 lần kiểm) |
| Σ GMV các SKU = GMV sản phẩm BEP-S5 | đạt (1 lần kiểm) |
| Σ đơn các SKU = đơn sản phẩm | đạt (1 lần kiểm) |
| trần chi/ngày (Cài đặt › Mục tiêu) = trần ở Tổng quan | đạt (1 lần kiểm) |

## 3. Cùng một con số ở mọi nơi

Cột “Ở đâu” liệt kê nơi giá trị xuất hiện; “Bằng nhau” là so sánh chuỗi hiển thị đã render. Kỳ 30 ngày, đơn đã xác nhận. Xếp hạng đọc cột “trước → nay” (giá trị nay); Sản phẩm đọc chuỗi chỉ số của kỳ 30 ngày và dải “5 con số chính”.

| Sản phẩm | Chỉ số | Giá trị | Ở đâu | Bằng nhau |
|---|---|---|---|---|
| GL-001 | Lượt xem | 412.000 | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| GL-001 | CTR | 3,10% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| GL-001 | CTOR | 6,20% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| GL-001 | AOV | 74.000đ | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| GL-001 | GMV | 58.597.936đ | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| GL-001 | Biên cuối | 21,4% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| GL-001 | Số đơn | 792 | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| GL-001 | % giảm giá | 7,8% | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| GL-001 | AOV (5 số) | 74.000đ | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| GL-001 | Biên (5 số) | 21,4% | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| NR-002 | Lượt xem | 655.000 | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| NR-002 | CTR | 2,40% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| NR-002 | CTOR | 5,10% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| NR-002 | AOV | 96.000đ | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| NR-002 | GMV | 76.965.120đ | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| NR-002 | Biên cuối | 9,8% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| NR-002 | Số đơn | 802 | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| NR-002 | % giảm giá | 13,3% | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| NR-002 | AOV (5 số) | 96.000đ | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| NR-002 | Biên (5 số) | 9,8% | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| XM-003 | Lượt xem | 268.000 | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| XM-003 | CTR | 3,60% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| XM-003 | CTOR | 3,90% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| XM-003 | AOV | 42.000đ | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| XM-003 | GMV | 15.803.424đ | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| XM-003 | Biên cuối | 24,0% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| XM-003 | Số đơn | 376 | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| XM-003 | % giảm giá | 4,9% | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| XM-003 | AOV (5 số) | 42.000đ | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| XM-003 | Biên (5 số) | 24,0% | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| TU-004 | Lượt xem | 190.000 | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| TU-004 | CTR | 2,90% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| TU-004 | CTOR | 4,80% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| TU-004 | AOV | 118.000đ | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| TU-004 | GMV | 31.208.640đ | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| TU-004 | Biên cuối | 6,2% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| TU-004 | Số đơn | 264 | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| TU-004 | % giảm giá | 15,7% | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| TU-004 | AOV (5 số) | 118.000đ | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| TU-004 | Biên (5 số) | 6,2% | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| GN-005 | Lượt xem | 224.000 | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| GN-005 | CTR | 2,20% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| GN-005 | CTOR | 5,60% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| GN-005 | AOV | 88.000đ | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| GN-005 | GMV | 24.285.184đ | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| GN-005 | Biên cuối | 15,3% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| GN-005 | Số đơn | 276 | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| GN-005 | % giảm giá | 5,8% | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| GN-005 | AOV (5 số) | 88.000đ | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| GN-005 | Biên (5 số) | 15,3% | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| BEP-S5 | Lượt xem | 15.000 | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| BEP-S5 | CTR | 4,40% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| BEP-S5 | CTOR | 10,00% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| BEP-S5 | AOV | 198.242đ | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| BEP-S5 | GMV | 13.084.000đ | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| BEP-S5 | Biên cuối | 26,0% | TongQuan, TongQuanMobile, Ranking, SanPham chain, SanPhamMobile chain | đạt |
| BEP-S5 | Số đơn | 66 | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| BEP-S5 | % giảm giá | 3,8% | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| BEP-S5 | AOV (5 số) | 198.242đ | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| BEP-S5 | Biên (5 số) | 26,0% | TongQuan, Ranking, SanPham 5 số, SanPhamMobile 5 số | đạt |
| SHOP | GMV shop | 243.542.304đ | a, b, c | đạt |
| SHOP | Biên shop (tile vs 5 số) | 14,5% | a, b, c | đạt |
| SHOP | AOV shop (tile vs 5 số) | 83.453đ | a, b, c | đạt |
| SHOP | Số đơn shop (5 số desk vs mobile) | 2.918 đơn | a, b, c | đạt |
| SHOP | % giảm shop | 9,9% | a, b, c | đạt |
| SHOP | ② shop | 1,32đ / 1đ chi | a, b, c | đạt |
| SHOP | Chi/ngày vs trần | 1.110.211đ/ngày | a, b, c | đạt |

**67/67 so sánh bằng nhau.**

Thẻ “trước” (A) so với dòng SKU BEP-S5-CB và giá sàn: phạm vi thẻ là **SKU BEP-S5-CB** (30 trong 66 đơn của sản phẩm BEP-S5), không phải cả sản phẩm; lợi nhuận, GMV, số đơn của A bằng dòng SKU trong dữ liệu chung, giá sàn 121.176đ / 181.979đ giống ở Sản phẩm (khối Giá, bảng phiên bản, tab Chi phí & giá sàn) và ở thẻ. Xem mục 2 (các dòng “thẻ trước”).

## 4. Năm con số: một định nghĩa, một bộ nhãn

Tiêu đề khối là “5 con số chính” (không có tên người) và nhãn trùng với `DS.LABELS`:

| Artboard | Nhãn trùng bộ chung | Nhãn đọc được |
|---|---|---|
| TongQuan | đạt | ① % giảm giá · ② Doanh thu thêm / chi thêm · ③ Biên lợi nhuận cuối · ④ Số đơn · ⑤ AOV |
| TongQuanMobile | đạt | ① % giảm giá · ② Doanh thu thêm / chi thêm · ③ Biên lợi nhuận cuối · ④ Số đơn · ⑤ AOV |
| SanPham | đạt | ① % giảm giá · ② Doanh thu thêm / chi thêm · ③ Biên lợi nhuận cuối · ④ Số đơn · ⑤ AOV |
| SanPhamMobile | đạt | ① % giảm giá · ② Doanh thu thêm / chi thêm · ③ Biên lợi nhuận cuối · ④ Số đơn · ⑤ AOV |
| CardWhatIf | đạt | ① % giảm giá · ② Doanh thu thêm / chi thêm · ③ Biên lợi nhuận cuối · ④ Số đơn · ⑤ AOV |

Tiêu đề “5 con số chính” có trong Tổng quan, Tổng quan mobile, Sản phẩm, Sản phẩm mobile: TongQuan: có, TongQuanMobile: có, SanPham: có, SanPhamMobile: có. Còn tên người trong file: không.

## 5. Bảng liên kết (contract §8)

Thu từ DOM đã render ở mọi trạng thái (mở hết các dòng gập): **282 liên kết duy nhất giữa các artboard**, gom thành 44 nhóm (từ → tới, tham số). Mỗi liên kết được mở thật; trang đích phải đọc đúng tham số (chỉ số, nguồn, nguồn con, sản phẩm, tab, thẻ, dòng được đánh dấu, banner quay về) và không lỗi console.

| Từ | Tới | Tham số | Số href | Ví dụ | Trạng thái | Đích đọc được |
|---|---|---|---|---|---|---|
| CaiDatImport | CardWhatIf.html | card,cogs,from,recalc | 1 | `CardWhatIf.html#card=c_bep_voucher&recalc=1&cogs=104000&from=cai-dat` | đạt | thẻ c_bep_voucher; banner tính lại + giá vốn 104000 |
| CardWhatIf | CardWhatIf.html | card | 1 | `CardWhatIf.html#card=c_bep_voucher` | đạt | thẻ c_bep_voucher |
| CardWhatIf | Ranking.html | card,focus,from,kpi,src | 2 | `Ranking.html#kpi=aov&src=lien_ket&focus=GL-001&from=card&card=c_gl_bundle` | đạt | kpi=aov; src=lien_ket; dòng GL-001 có; banner “Vừa quay về từ thẻ” |
| CardWhatIf | SanPham.html | card,id,tab | 2 | `SanPham.html#id=BEP-S5&tab=ng&card=c_bep_voucher` | đạt | sản phẩm BEP-S5; tab ng |
| PhanTich | CardWhatIf.html | — | 1 | `CardWhatIf.html` | đạt |  |
| PhanTich | CardWhatIf.html | card,from,row | 5 | `CardWhatIf.html#card=c_gn_kw&from=phan-tich&row=i5` | đạt | thẻ c_gn_kw |
| PhanTich | CardWhatIf.html | card,from | 1 | `CardWhatIf.html#card=c_nr_vcap&from=phan-tich` | đạt | thẻ c_nr_vcap |
| PhanTich | Ranking.html | card,focus,from,kpi,src | 3 | `Ranking.html#kpi=bien&src=all&focus=TU-004&from=phan-tich&card=c_tu_price` | đạt | kpi=bien; src=all; dòng TU-004 có |
| PhanTich | Ranking.html | card,focus,from,kpi,src,sub | 2 | `Ranking.html#kpi=ctor&src=the_san_pham&sub=de_xuat&focus=XM-003&from=phan-tich&card=c_xm_disc` | đạt | kpi=ctor; src=the_san_pham; dòng XM-003 có |
| PhanTich | SanPham.html | — | 1 | `SanPham.html` | đạt |  |
| PhanTich | TongQuan.html | — | 1 | `TongQuan.html` | đạt | cảnh default |
| Ranking | CardWhatIf.html | card,from,row | 10 | `CardWhatIf.html#card=c_bep_ads&from=ranking&row=a7` | đạt | thẻ c_bep_ads |
| Ranking | CardWhatIf.html | card | 1 | `CardWhatIf.html#card=c_xm_disc` | đạt | thẻ c_xm_disc |
| Ranking | SanPham.html | from,id,kpi,row,src,tab | 16 | `SanPham.html#id=BEP-S5&tab=ng&kpi=bien&src=voucher&row=v5&from=ranking` | đạt | sản phẩm BEP-S5; tab ng; banner Mở từ Xếp hạng · Biên cuối × Voucher · dòng v5; dòng nguồn |
| Ranking | SanPham.html | from,id,kpi,row,src,sub,tab | 5 | `SanPham.html#id=GL-001&tab=ng&kpi=ctor&src=the_san_pham&sub=de_xuat&row=GL-001&from=ranking` | đạt | sản phẩm GL-001; tab ng; banner Mở từ Xếp hạng · CTOR × Đề xuất · dòng GL-001; dòng nguồn  |
| Ranking | TongQuan.html | — | 1 | `TongQuan.html` | đạt | cảnh default |
| Ranking | TongQuan.html | scene | 1 | `TongQuan.html#scene=default` | đạt | cảnh default |
| RankingMobile | CardWhatIf.html | card,from,row | 4 | `CardWhatIf.html#card=c_gl_bundle&from=ranking&row=GL-001` | đạt | thẻ c_gl_bundle |
| RankingMobile | CardWhatIf.html | card | 1 | `CardWhatIf.html#card=c_xm_disc` | đạt | thẻ c_xm_disc |
| RankingMobile | SanPham.html | from,id,kpi,row,src,sub,tab | 3 | `SanPham.html#id=GL-001&tab=ng&kpi=ctor&src=the_san_pham&sub=de_xuat&row=GL-001&from=ranking` | đạt | sản phẩm GL-001; tab ng; banner Mở từ Xếp hạng · CTOR × Đề xuất · dòng GL-001; dòng nguồn  |
| RankingMobile | SanPham.html | from,id,kpi,row,src,tab | 2 | `SanPham.html#id=GN-005&tab=ng&kpi=ctr&src=all&row=GN-005&from=ranking` | đạt | sản phẩm GN-005; tab ng; banner Mở từ Xếp hạng · CTR × Tất cả · dòng GN-005 |
| RankingMobile | TongQuan.html | — | 1 | `TongQuan.html` | đạt | cảnh default |
| SanPham | CaiDatImport.html | from,sku,step | 1 | `CaiDatImport.html#step=tai&sku=BEP-S3&from=san-pham` | đạt | bước tai; SKU BEP-S3 |
| SanPham | CardWhatIf.html | card,from | 5 | `CardWhatIf.html#card=c_bep_ads&from=san-pham` | đạt | thẻ c_bep_ads |
| SanPham | Ranking.html | focus,kpi,src | 1 | `Ranking.html#kpi=ctr&src=live&focus=GL-001` | đạt | kpi=ctr; src=live; dòng GL-001 có |
| SanPham | Ranking.html | focus,from,kpi,src | 1 | `Ranking.html#kpi=gmv&src=all&focus=BEP-S5&from=san-pham` | đạt | kpi=gmv; src=all; dòng BEP-S5 có |
| SanPham | TongQuan.html | — | 1 | `TongQuan.html` | đạt | cảnh default |
| SanPhamMobile | CaiDatImport.html | from,sku,step | 1 | `CaiDatImport.html#step=tai&sku=BEP-S3&from=san-pham` | đạt | bước tai; SKU BEP-S3 |
| SanPhamMobile | CardWhatIf.html | card,from | 3 | `CardWhatIf.html#card=c_bep_ads&from=san-pham` | đạt | thẻ c_bep_ads |
| SanPhamMobile | Ranking.html | focus,from,kpi,src | 1 | `Ranking.html#kpi=gmv&src=all&focus=BEP-S5&from=san-pham` | đạt | kpi=gmv; src=all; dòng BEP-S5 có |
| SanPhamMobile | TongQuan.html | — | 1 | `TongQuan.html` | đạt | cảnh default |
| TongQuan | CaiDatImport.html | from,sku,step | 1 | `CaiDatImport.html#step=tai&sku=BEP-S3&from=tong-quan` | đạt | bước tai; SKU BEP-S3 |
| TongQuan | CardWhatIf.html | — | 1 | `CardWhatIf.html` | đạt |  |
| TongQuan | CardWhatIf.html | card,from | 12 | `CardWhatIf.html#card=c_bep_ads&from=tong-quan` | đạt | thẻ c_bep_ads |
| TongQuan | PhanTich.html | — | 1 | `PhanTich.html` | đạt |  |
| TongQuan | Ranking.html | from,kpi,src | 50 | `Ranking.html#kpi=aov&src=ads&from=tong-quan` | đạt | kpi=aov; src=ads |
| TongQuan | Ranking.html | from,kpi,src,sub | 36 | `Ranking.html#kpi=aov&src=the_san_pham&sub=de_xuat&from=tong-quan` | đạt | kpi=aov; src=the_san_pham |
| TongQuan | SanPham.html | — | 1 | `SanPham.html` | đạt |  |
| TongQuan | SanPham.html | from,id,tab | 6 | `SanPham.html#id=BEP-S5&tab=ng&from=tong-quan` | đạt | sản phẩm BEP-S5; tab ng |
| TongQuanMobile | CaiDatImport.html | from,sku,step | 1 | `CaiDatImport.html#step=tai&sku=BEP-S3&from=tong-quan` | đạt | bước tai; SKU BEP-S3 |
| TongQuanMobile | CardWhatIf.html | card,from | 6 | `CardWhatIf.html#card=c_gl_bundle&from=tong-quan` | đạt | thẻ c_gl_bundle |
| TongQuanMobile | Ranking.html | from,kpi,src | 50 | `Ranking.html#kpi=aov&src=ads&from=tong-quan` | đạt | kpi=aov; src=ads |
| TongQuanMobile | Ranking.html | from,kpi,src,sub | 36 | `Ranking.html#kpi=aov&src=the_san_pham&sub=de_xuat&from=tong-quan` | đạt | kpi=aov; src=the_san_pham |
| TongQuanMobile | SanPham.html | from,id,tab | 1 | `SanPham.html#id=XM-003&tab=ng&from=tong-quan` | đạt | sản phẩm XM-003; tab ng |

**282/282 đạt.**

Ánh xạ chỉ số → loại thẻ (§8): mọi thẻ trong registry (`DS.CARDS`) mang chỉ số, luồng/đòn bẩy, sản phẩm, loại thẻ, ₫ đang đặt cược; kiểm tra loại thẻ ∈ tập cho phép của chỉ số và “Xem phân tích ›” mở Xếp hạng có dòng được đánh dấu — xem các dòng “thẻ …” ở mục 2.

## 6. What-if quét tham số

Quét bằng cách đặt giá trị cho thanh trượt (sự kiện `input` thật), đọc `#calc` (thuộc tính data của DOM) và chữ hiển thị. Phía Python tính lại độc lập từ công thức contract §7 (không dùng mã của artboard).

| Đầu vào | Dùng (min(Q×u, số lượng)) | Chi voucher | ① % giảm | ③ biên | Đơn hoà vốn | Python khớp |
|---|---|---|---|---|---|---|
| v=10000 s=200000 qty=20 | 20 | 200.000đ | 2.87% | 26.29% | 0 | khớp |
| v=15000 s=200000 qty=20 | 20 | 300.000đ | 4.31% | 25.41% | 0 | khớp |
| v=10000 s=200000 qty=100 | 30 | 300.000đ | 4.31% | 25.41% | 0 | khớp |
| v=15000 s=200000 qty=100 | 30 | 450.000đ | 6.47% | 24.04% | 3 | khớp |
| (thêm) v=15000 s=299000 qty=50 | 6 | 90.000đ | 1.29% | 27.23% | 0 | (không đối chiếu) |
| (thêm) v=15000 s=150000 qty=50 | 30 | 450.000đ | 6.47% | 24.04% | 3 | (không đối chiếu) |
| (thêm) v=25000 s=200000 qty=50 | 30 | 750.000đ | 10.78% | 21.09% | 10 | (không đối chiếu) |

Tính đơn điệu và các ràng buộc:

- đạt: chi voucher tăng khi giá trị 10k → 15k (qty 100)
- đạt: chi voucher tăng khi giá trị 10k → 15k (qty 20)
- đạt: chi voucher không giảm khi số lượng 20 → 100 (v 10k)
- đạt: chi voucher không giảm khi số lượng 20 → 100 (v 15k)
- đạt: ① % giảm tăng cùng chi (v 10k → 15k, qty 100)
- đạt: ③ biên giảm khi chi tăng (v 10k → 15k, qty 100)
- đạt: ③ biên không tăng khi qty 20 → 100 (v 15k)
- đạt: số đơn hoà vốn không giảm khi chi thêm tăng
- đạt: v 15k, qty 100, ≥200k: hoà vốn ≥ 3 đơn và chi thêm 150.000đ
- đạt: qty 20 giới hạn dùng 20 lượt (< Q×u = 30)
- đạt: giới hạn mỗi người 2 → 4 không đổi con số nào (§9.1)
- đạt: số ngày 30 → 21: số đơn đủ điều kiện và chi tính lại theo ngày
- đạt: chế độ %: 10% có trần 18.000đ → mức giảm đơn 200k = 18.000đ

Ví dụ minh hoạ giữ nguyên (đọc từ chữ hiển thị của thẻ):

- đạt: giá sàn tuyệt đối 121.176đ
- đạt: giá sàn vận hành 181.979đ
- đạt: giảm tối đa 18.000đ
- đạt: A: biên đơn tự nhiên 58.500đ · 30,8%
- đạt: A: đơn QC 21.700đ · 11,4%
- đạt: B: biên đơn tự nhiên 54.250đ · 29,3%
- đạt: B: đơn QC 17.450đ · 9,4% (dưới mục tiêu)
- đạt: B: hoà vốn ≥ 3 đơn (150.000đ ÷ 54.250đ)
- đạt: Chạm giá sàn: khoá phê duyệt (giảm 25.000đ ở đơn tối thiểu 200.000đ)

## 7. Contract §9 trên các artboard

| Quy tắc | Nơi thể hiện | Bằng chứng |
|---|---|---|
| (1) Giới hạn mỗi người: input, “không kiểm được từ dữ liệu”, không đổi số | CardWhatIf, ô “Giới hạn mỗi người” | Mục 6: tăng 2 → 4 lần, mọi số và chữ trên thẻ giữ nguyên |
| (2) ② chỉ từ khoảng “Dự kiến”; “Chắc chắn” hiện đơn hoà vốn | CardWhatIf, hai lớp số | Lớp Chắc chắn: “Hoà vốn khi thêm ≥ N đơn” hoặc “Giảm chi …”; lớp Dự kiến: khoảng ΔGMV ÷ Δchi hoặc “giảm chi”. Không có dòng “0đ / 1đ chi” |
| (3) Coverage < 100 %: biên “trên X % doanh thu có giá vốn”; lợi nhuận shop bằng đồng chỉ ở 100 % | TongQuan, khối “Lợi nhuận shop” (mặc định 99,4 %: dấu “—” thay số đồng; cảnh `full`: 100 %, có số đồng), thẻ “Biên cuối” và ③ ở năm con số; SanPham “trên 88,8 % doanh thu có giá vốn” | `#scene=default` và `#scene=full` mở không lỗi; số liệu ở mục 3 |
| (4) Chi cho trần/ngày = cùng chi với ② | TongQuan, thẻ “Chi marketing / ngày vs trần” (1.110.211đ/ngày so với trần 1.200.000đ, trần lấy từ Cài đặt › Mục tiêu) | Mục 2: “chi = QC + voucher + khuyến mãi + combo + hoa hồng” và so khớp trần ở Tổng quan với Cài đặt |
| (5) Đóng gói theo từng dòng sản phẩm | Giá vốn + đóng gói theo SKU (`DS.SKUS`: BEP-S5-CB 100.000 + 3.000, BEP-S5-QT 128.000 + 6.000), giá sàn tính từng SKU | Mục 6: giá sàn 121.176đ / 181.979đ |

## 8. Còn mở

- **Phạm vi thẻ voucher** là SKU BEP-S5-CB (30 trong 66 đơn của BEP-S5), vì ví dụ minh hoạ của contract (150.000đ ÷ 54.250đ ≥ 3 đơn) cần đúng 30 đơn đủ điều kiện. Con số “trước” của thẻ bằng dòng SKU trong Sản phẩm và Chi phí & giá sàn, không bằng dòng cả sản phẩm ở Tổng quan. Nếu muốn thẻ ở cấp sản phẩm cần đổi ví dụ.
- **Trang Sản phẩm chi tiết** (ảnh, tiêu đề, phiên bản, từ khoá, giá sàn) chỉ vẽ cho BEP-S5; sản phẩm khác mở ra khối 5 con số, chuỗi chỉ số và Nguồn (cùng bộ số) kèm ghi chú.
- **Thẻ không phải voucher** (11 thẻ trong registry) hiện thẻ tóm tắt (loại, chỉ số, luồng, ₫, lý do, kiểm tra §8) và link “Xem phân tích ›”, chưa vẽ phép thử “nếu đổi”.
- **u = 100 %** (voucher A: 30/30 đơn đủ điều kiện đã dùng) là số minh hoạ; u thật lấy từ cột “Tỷ lệ sử dụng” của file voucher.
- **Giai đoạn T+7 và chốt 28 ngày** vẫn là số “thực tế” minh hoạ (tĩnh); phần “trước” và “dự kiến” tính từ dữ liệu.
- **Phân tích**: mục “Găng tay · AOV · Tiếp thị liên kết” (thẻ `c_gl_bundle`) không còn trong danh sách vì AOV của nó không còn thấp hơn kỳ trước ở dữ liệu chung; thẻ vẫn mở được từ Xếp hạng.
- **Bộ chọn kỳ** ở Tổng quan chỉ đổi nhãn (số 30 ngày); ở Sản phẩm kỳ 7 và 90 ngày dùng hệ số cố định, kỳ 30 ngày là số thật của dữ liệu chung.
- **Từ khoá, KOL, voucher** ở Xếp hạng là dữ liệu lá vẽ tay (xuất file riêng); tổng ô và dòng đóng vẫn cộng đúng, nhưng giá trị lá không suy ra từ đơn.
- **Chi marketing khác** (giải thưởng trò chơi) và **QC không gắn sản phẩm** (chiến dịch Lượt vào shop) là hằng số minh hoạ cho khối lợi nhuận.
- Kiểm tra chạy trên runtime thay thế `support.js`, không phải canvas thật; cấu trúc template giữ nguyên các cấu trúc runtime đã hỗ trợ (không `<table>`, không SVG nội tuyến, thanh trượt native).



---

# P91 — kiểm tra artboards (2026-11-04)

Chạy bằng runtime thay thế nhỏ (jsdom, không commit): mở từng artboard, render `renderVals()`, bấm các nút chính. Dữ liệu: block `P91 DATASET v1`, giống hệt từng byte trong tám file (`SanPhamDeXuat`, `SanPhamDeXuatMobile`, `CardVersions`, `QuyetDinhHangDoi`, `TuTaoPhuongAn`, `KeHoach`, `KeHoachMobile`, `OpsDeXuat`).

| # | Kiểm tra | Cách xem | Kết quả lần chạy |
|---|---|---|---|
| 1 | Tám file render không lỗi template (mọi `{{...}}` có giá trị) và không có chữ "phương án khác" | mở từng file | đạt |
| 2 | Mỗi thẻ có mã `JC-…`; phiên bản `JC-…-Vn`; thứ tự hàng đợi 1…8 liền nhau | SanPhamDeXuat | đạt |
| 3 | Thẻ voucher ba phiên bản; V3 chạm giá sàn và vượt trần chi: nút Duyệt V3 vẫn bật, mở cảnh báo (thiếu 5.493đ; vượt trần 620.000đ/tháng), "Quay lại" đóng, "Vẫn tiếp tục" ghi "Đã xác nhận vượt giá sàn và trần chi · giờ" lên thẻ; "Đặt về mức tối đa" làm hết chạm sàn | CardVersions `#scene=floor` | đạt |
| 4 | Thanh trượt chỉ đổi cột đang chọn; "Về mặc định" trả lại | CardVersions | đạt |
| 5 | Tiêu đề: 97/100 và 92/100; thêm chữ cho 105/100 thì đỏ, Duyệt khoá | CardVersions `#scene=title` | đạt |
| 6 | Bỏ qua / Thêm vào kế hoạch / Đã thực hiện thay thẻ bằng thẻ kế tiếp ngay; "Sản phẩm đang đo: còn 14 ngày" chỉ ở cảnh `done` | QuyetDinhHangDoi | đạt |
| 7 | Combo 2 sản phẩm: đóng góp = khách trả − giá vốn − phí − chi khác; giá combo cố định 165.000đ chạm giá sàn từng SKU | TuTaoPhuongAn `#scene=breach` | đạt |
| 8 | Ví dụ đánh đổi: P2/P3 so với P1 biên giảm, AOV tăng, GMV tăng, lợi nhuận giảm | TuTaoPhuongAn `#scene=compare` | đạt |
| 9 | Tối đa 4 phương án; không thêm được quá 4; chạm giá sàn thì Lưu mở cảnh báo từng SKU với số thiếu, "Vẫn tiếp tục" mới lưu và ghi xác nhận | TuTaoPhuongAn | đạt |
| 10 | Kế hoạch: voucher V1 + khuyến mãi 8% chồng nhau chạm giá sàn (260.080đ < 275.193đ) dù mỗi thẻ riêng đạt; Xác nhận và Thêm vào kế hoạch không bị khoá, mở cảnh báo, "Vẫn tiếp tục" ghi xác nhận lên kế hoạch (cảnh `breachDone`); bỏ khuyến mãi thì không còn cảnh báo | KeHoach `#scene=breach` → `ok` | đạt |
| 11 | Thêm combo: biên 14,4 % → 14,1 %, AOV +12.000đ, lợi nhuận dự kiến vẫn tăng | KeHoach `#scene=combo` | đạt |
| 12 | Hộp xác nhận liệt kê phép đo bị cắt: Găng tay cao su A (đã đo 8 ngày: giữ "đo được 8 ngày"), Túi rác sinh học B (2 ngày: "không kết luận") | KeHoach `#scene=confirm` | đạt |
| 13 | Cửa sổ đo: 28 ngày được đánh dấu "Đề xuất"; chọn 7 hoặc 14 ngày hiện ghi chú "Khó kết luận" | KeHoach | đạt |
| 14 | Ops: cột mã thẻ, lọc, tìm theo mã; nút Xuất Excel bị khoá, nhãn "Sắp có" | OpsDeXuat | đạt |

Còn mở: số lượt tăng đơn, hệ số chồng thẻ (−0,12) và công thức MDE trong bản vẽ là số minh hoạ; số thật do backend (`combo.py`, `plan.py`) cho. Chưa vẽ mobile cho CardVersions, TuTaoPhuongAn, QuyetDinhHangDoi. Kiểm tra không thay thế việc xem trên canvas thật (runtime `support.js` không nằm trong repo).
