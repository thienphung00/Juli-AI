# Hướng dẫn chỉ số cho đội ngũ Juli Ops

Tài liệu nội bộ. Giải thích mọi con số và nhãn trên màn hình Juli Ops và trên thẻ của người bán:
nghĩa là gì, tính thế nào, đọc ra sao, và trả lời người bán thế nào.

Quy ước (D31.8): **một bộ từ cho cả hệ thống**. Nhãn trên màn hình được viết **đúng nguyên văn**
(in đậm hoặc trong ngoặc kép) — khi nói với người bán, dùng đúng nhãn đó. Từ của đội (band,
window-mean, p10–p90, CV, D29…) chỉ dùng trong tài liệu này và khi nói chuyện nội bộ, không bao giờ
nói với người bán. Tài liệu gửi người bán là `docs/chi-so/nguoi-ban-huong-dan-chi-so.md`; hai tài liệu
dùng chung bảng thuật ngữ bên dưới (cùng hàng, cùng cột nhãn — có test
`tests/unit/test_chi_so_docs_vocabulary.py` kiểm tra).

Nguồn: `fasttrack/DECISIONS.md` D25–D31; `services/ops/simulation.py`;
`services/optimize_product/volatility.py`, `tunables.py`; `services/lever_flows/measurement.py`;
`services/run_changes/default_bands.py`; giao diện `apps/demo/src/components/ops/*`,
`components/quyet-dinh/*`, `lib/quyet-dinh/*`, `components/phan-tich/*`.

## Bảng thuật ngữ

| Nhãn trên màn hình | Ý nghĩa | Cách tính |
|---|---|---|
| **Thẻ sản phẩm** | Luồng 1: khách thấy sản phẩm dạng thẻ (tìm kiếm, gợi ý, trang For You…) | Số liệu TikTok của nguồn "product card"; TikTok tính kênh này là **phần còn lại** sau LIVE và video (mục 5.5) |
| **Tab cửa hàng** | Luồng 2: khách vào trang cửa hàng của shop | Số liệu nguồn "shop tab"; đơn SKU ở luồng này là ước tính (CTOR × lượt nhấp) vì TikTok không trả |
| **Video** | Luồng 3: video do chính shop đăng; tên dài "Video của người bán" chỉ hiện khi rê chuột | Số liệu nguồn "seller video" |
| **LIVE** | Luồng 4: phiên LIVE do chính shop phát; tên dài "LIVE của người bán" chỉ hiện khi rê chuột | Số liệu nguồn "seller live" |
| **Lượt hiển thị/ngày** | Trung bình mỗi ngày có bao nhiêu lượt khách thấy sản phẩm/nội dung | Tổng lượt hiển thị trong N ngày ÷ số ngày có dữ liệu |
| **Lượt nhấp** | Số lần khách bấm vào sản phẩm (TikTok gọi là click) | Tổng trong khoảng |
| **CTR** | Trong 100 lượt hiển thị, bao nhiêu lượt nhấp | Tổng lượt nhấp ÷ tổng lượt hiển thị (cộng cả khoảng rồi mới chia) |
| **CTOR** | Trong 100 lượt nhấp, bao nhiêu thành đơn | Tổng đơn SKU ÷ tổng lượt nhấp; **không phải** "tỷ lệ chuyển đổi" của TikTok (người mua ÷ lượt xem trang, mục 5.5) |
| **AOV** | Giá trị trung bình một đơn | Tổng GMV ÷ tổng đơn SKU; GMV của TikTok gồm cả đơn sau đó bị huỷ/hoàn (mục 5.5) |
| **GMV/ngày** | Doanh thu trung bình mỗi ngày | Tổng GMV ÷ số ngày; = Lượt hiển thị/ngày × CTR × CTOR × AOV; GMV theo TikTok, chưa trừ đơn huỷ/hoàn (mục 5.5) |
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
| **Kết quả nhóm** | Một câu trên thẻ về nhóm sản phẩm cùng chỉ số × thay đổi × kênh, khi nhóm đã đo xong ngày 14 (ví dụ "Nhóm 6 sản phẩm đổi ảnh bìa: lượt nhấp tăng khoảng 7 % so với các sản phẩm chưa đổi") | D34: trung vị thay đổi nhóm áp dụng − trung vị nhóm đối chứng (chọn ngẫu nhiên, nhận thẻ sau 14 ngày); không hiện khi "Chưa đủ cơ sở" (mục 5.2) |
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

## 1. Bốn luồng và bốn chỉ số

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

## 2. Đọc một ô Mô phỏng

Ô Mô phỏng có: giá trị, chip **▲▼**, dòng **Dao động TB N ngày: ±X %**, khi bấm/rê chuột thì thêm
**Dao động mỗi ngày: ±Y %**, và khi bạn bấm ± thì có nhãn đánh giá mục tiêu.

Thanh chọn khoảng: 7 / 14 / 30 / 90 ngày (mặc định 30). Dòng chú thích:
"Gốc: trung bình N ngày · ▲▼ so với N ngày trước đó · dao động trong N ngày".

### 2.1 Ví dụ có số

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

### 2.2 "Không ngẫu nhiên" ≠ "do Juli"

**Thay đổi rõ** chỉ nói: con số đã thật sự thay đổi. Nó KHÔNG nói vì sao. Lượt hiển thị giảm 24,6 % có
thể do TikTok đổi thuật toán, hết chiến dịch sàn, đối thủ giảm giá, hết hàng… Một kết quả ngày 14 chỉ
được coi là của Juli khi đồng thời:

1. thay đổi đủ mạnh (theo quy tắc trên),
2. không có thay đổi bên ngoài chồng lên khoảng đo (nếu có → **Bị ảnh hưởng bởi thay đổi khác**),
3. các chỉ số giữ ở trạng thái **Giữ ổn định** và GMV không giảm quá dao động của nó.

### 2.3 Ô "Ít dữ liệu"

Dưới 30 lượt nhấp (CTR) hoặc 30 đơn (CTOR, AOV) trong khoảng: giá trị vẫn hiện nhưng màu xám, có dấu
"*", viền đứt, chip xu hướng xám "~ 3,1 %" thay cho ▲▼, dòng "Ít dữ liệu · N đơn" (hoặc "N lượt nhấp").
Mục tiêu đặt trên ô này đánh giá là "Ít dữ liệu". Cách xử lý: chọn khoảng dài hơn.

### 2.4 Đánh giá mục tiêu trong Mô phỏng

Mỗi lần bấm ± đổi 1 %. Nhãn dưới ô:

- **Trong dao động** — |mục tiêu| ≤ Dao động TB N ngày: dù đạt cũng không phân biệt được với ngẫu
  nhiên. Đừng đặt mục tiêu này cho shop.
- **Vượt dao động · đo được** — lớn hơn dao động: đo được.
- **Ít dữ liệu** — ô ít dữ liệu.

Lưu ý: Mô phỏng so mục tiêu với dao động của MỘT khoảng (dao động trung bình N ngày). Kết quả đo thẻ
(sau D31.7) dùng dao động GỘP của hai khoảng và ngưỡng 2 lần — chặt hơn. Một mục tiêu "đo được" vừa
đủ trong Mô phỏng có thể chỉ ra "Có thể thay đổi" khi đo thật.

### 2.5 Lưu lượng ổn định và bảng "Độ dao động"

- Nhãn luồng: **Lưu lượng ổn định** (CV lượt hiển thị < 15 %), **Dao động vừa** (< 30 %), **Dao động
  cao** (≥ 30 %), "Chưa đủ dữ liệu". Dưới tên luồng: "Dao động mỗi ngày (lượt hiển thị): ±X %".
- Bảng "Độ dao động · {luồng}": từng sản phẩm, khoảng thấp – cao (p10–p90 từng ngày) của Lượt hiển
  thị/ngày, CTR, CTOR, cột "Dao động mỗi ngày (lượt hiển thị)"; nút sắp xếp "Lưu lượng ổn định trước";
  "Lưu lượng ổn định · nên chọn" là dòng nên đặt mục tiêu (KPI chính xác hơn).
- GMV cả shop sau mô phỏng = tổng GMV/ngày các luồng; "≈ X tr ₫ mỗi tháng" = chênh lệch × 30. Đây là
  phép nhân công thức, không phải dự báo của mô hình.

## 3. Juli chọn sản phẩm và đặt mục tiêu thế nào (D29, D30)

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
   **Cách cũ (GMV trước, D29.2)** vẫn chọn được cho từng shop ở "Điều kiện mở thẻ" (mục 5): sản phẩm
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

## 4. Đọc một thẻ đã đo (Đo lường)

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

## 5. Cài đặt shop → "Chẩn đoán & KPI" (Admin)

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

### 5.1 "Nhiều thẻ mỗi ô (thử nghiệm)" (Admin, D33)

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

### 5.2 "Nhóm thử nghiệm (đối chứng chậm)" (Admin, D34 / D39.3)

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

### 5.3 Nhóm tạo trong Ops, AOV, cảnh báo CTR, sàn trôi tuần (Admin, D45, P36 — chỉ Ops)

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

### 5.4 Lift đã co (EB) (D52, P45 — chỉ Ops)

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
  chính Juli (Fujiwa, shop sandbox): điều khoản TikTok Shop (Developer ToS §2.7(g), Partner Center ToS
  §3.8(e)) cấm gộp dữ liệu API của người bán cho mục đích riêng của Juli; Shopee (ToS §6.2(c)) cần
  Shopee đồng ý bằng văn bản cho số liệu tổng hợp về hiệu quả người bán. Thêm một lớp bảo vệ: một ô
  gộp chỉ được dùng khi có **ít nhất 5 shop đã đồng ý** góp vào và **không shop nào chiếm quá 50 %**
  số kết quả nhóm trong ô; không đủ thì lùi sang ô rộng hơn — mọi loại thay đổi cùng chỉ số × kênh
  (dòng ghi "theo n shop, mọi loại thay đổi cùng chỉ số") — vẫn không đủ thì dùng mức mặc định. Hiện
  chỉ shop của Juli đồng ý, nên mọi dòng đều đang ở mức mặc định. Hệ số hiệu chỉnh cấp "fleet" của Dự
  đoán hiệu quả (D30.3) theo cùng quy tắc: ô theo đòn bẩy, rồi mọi đòn bẩy.

### 5.5 GMV, "tỷ lệ chuyển đổi" và kênh Thẻ sản phẩm: định nghĩa của TikTok (D55.1, P47 — chỉ Ops)

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

## 6. Các màn hình Ops khác

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

## 7. Câu hỏi thường gặp

**"Sao Phân tích báo lượt hiển thị giảm 24,6 % mà Juli không đề xuất gì?"**
Nội bộ (D39.1): một chỉ số giảm quá dao động gộp của chính nó là đủ mở thẻ, kể cả khi GMV giữ được.
Không có thẻ khi: con số trên Phân tích là của cả shop hoặc cả luồng chứ không của từng sản phẩm; từng
sản phẩm giảm chưa quá dao động của nó; chỉ số đó "Ít dữ liệu"; sản phẩm đã có thẻ cho chỉ số khác
(D29.4) hoặc đang trong thời gian chờ; hoặc chỉ có thay đổi Tiêu đề mới tác động được lượt hiển thị mà
không có lỗi tiêu đề nào. Shop đặt "GMV giảm (cũ)" thì vẫn chỉ mở thẻ khi GMV giảm. Trả lời: "Lượt
hiển thị của shop giảm thật, nhưng ở từng sản phẩm mức giảm chưa vượt mức lên xuống thường ngày (hoặc
Juli chưa có thay đổi phù hợp), nên Juli chưa đề xuất. Khi một sản phẩm giảm rõ, Juli sẽ đề xuất."

**"Sao sản phẩm của tôi nhận thẻ muộn hơn các sản phẩm khác?"**
Nội bộ: sản phẩm rơi vào nhóm đối chứng (D34, mục 5.2). Trả lời: "Juli thử thay đổi này trên một nhóm
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
