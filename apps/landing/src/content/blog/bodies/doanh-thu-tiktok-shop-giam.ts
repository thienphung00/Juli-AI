/**
 * Post (D48 additions 6, P39-B): "Doanh thu TikTok Shop giảm" checklist.
 * Target queries: "doanh thu tiktok shop giảm", "phân tích doanh thu tiktok
 * shop". Metric facts are from TikTok Academy VN, "Lưu lượng truy cập sản phẩm"
 * (17/06/2026: GMV incl. cancelled and refunded orders, GMV variants, refund
 * timing, channel dimensions, Tỷ lệ thêm vào giỏ hàng); settlement from "Tài
 * Chính cho Người Mới Bắt Đầu: Hướng Dẫn về Phương Thức và Thời Điểm Bạn Được
 * Thanh Toán" (01/12/2023); product statuses from "Quản lý Sản phẩm"
 * (27/08/2026); recommendation threshold and shop operations from "Chẩn Đoán
 * Thẻ Sản Phẩm hoạt động như thế nào 1"; product card scope from "Thẻ Sản
 * Phẩm"; price states from "Chẩn đoán giá"; BMSM from "Mua Sỉ Giá Hời". The
 * per-metric reading is plain percentage change, with no numeric data floor
 * (D61); reach tier, D59: no Juli. Every number in a "Ví dụ giả định" is hypothetical.
 */
export const body = `
Doanh thu giảm là lúc nhà bán TikTok Shop dễ đưa ra quyết định vội nhất. Thấy GMV tuần này thấp hơn tuần trước, nhiều người lập tức giảm giá, đổi ảnh, đăng thêm video hay tăng ngân sách quảng cáo, rồi một tuần sau không biết việc nào đã giúp, việc nào đã làm tệ hơn. Trong khi đó, nguyên nhân thật có thể nằm ở một luồng truy cập duy nhất, ở hai ba sản phẩm, hoặc thậm chí ở cách so sánh hai kỳ.

Bài viết này là một danh sách kiểm tra để phân tích doanh thu TikTok Shop khi nó giảm, theo đúng thứ tự: kiểm tra xem doanh thu có giảm thật không, tách mức giảm theo năm luồng truy cập, tách luồng giảm nhiều nhất thành bốn chỉ số của phễu, rồi đi qua danh sách nguyên nhân cho từng luồng và từng chỉ số. Mọi ví dụ có số trong bài là ví dụ giả định, chỉ để minh họa cách tính.

## Doanh thu giảm thật, hay chỉ là cách so sánh

Trước khi tìm nguyên nhân, hãy chắc rằng bạn đang so sánh đúng. Một nửa số lần "doanh thu giảm" mà người bán lo lắng thực ra đến từ cách chọn kỳ, chọn loại số hoặc cách tính trung bình.

### Doanh thu ở đây là GMV hay tiền về

Trên La bàn dữ liệu, con số doanh thu bạn thấy là GMV. Theo trang "Lưu lượng truy cập sản phẩm" của Học viện TikTok Shop (cập nhật 17/06/2026), GMV là "tổng số tiền thanh toán cho các đơn hàng trong khoảng thời gian đã chọn, bao gồm cả đơn đã hủy và hoàn tiền". Còn số tiền về tài khoản là số tiền quyết toán: theo bài "Tài Chính cho Người Mới Bắt Đầu: Hướng Dẫn về Phương Thức và Thời Điểm Bạn Được Thanh Toán", khoản thu "sau khi trừ tất cả các khoản phí" được chuyển vào Số dư Nhà bán hàng, với chu kỳ tiêu chuẩn (D+6)+1 tính từ ngày giao hàng.

Hai con số này giảm vì những lý do khác nhau:

- **GMV giảm**: ít đơn hơn hoặc đơn có giá trị thấp hơn. Đây là vấn đề của phễu, và là chủ đề chính của bài.
- **Tiền về giảm trong khi GMV không giảm**: nhiều đơn hủy hơn, nhiều hoàn tiền hơn, phí thay đổi, hoặc đơn của kỳ trước chưa đến hạn quyết toán. Đây là vấn đề của vận hành và tài chính, không phải của phễu.

Bài [GMV là gì? Cách tính và cách tăng GMV TikTok Shop](/blog/gmv-la-gi-tiktok-shop) giải thích chi tiết đường đi từ GMV đến tiền về.

### So sánh hai kỳ cho công bằng

- **Hai kỳ dài bằng nhau.** 30 ngày so với 30 ngày, 7 ngày so với 7 ngày. So tháng 2 với tháng 3 đã lệch vài ngày.
- **Cùng cơ cấu thứ trong tuần.** Nếu shop bán khác nhau giữa ngày thường và cuối tuần, kỳ 7 ngày nên bắt đầu cùng một thứ.
- **Đánh dấu ngày sale lớn.** Các ngày như 9.9, 10.10, 11.11 có traffic và tỷ lệ đặt hàng khác hẳn ngày thường. So 30 ngày có 10.10 với 30 ngày không có 10.10 gần như chắc chắn cho thấy một mức "giảm" ở kỳ sau. Cách đọc số liệu trước, trong và sau một đợt sale có trong bài [trước và sau 11.11](/blog/doanh-thu-sau-sale-tiktok-shop).
- **Không đưa ngày hôm nay vào so sánh.** Một ngày chưa kết thúc luôn thấp hơn một ngày trọn vẹn.
- **Cùng một loại GMV.** TikTok có các biến thể như GMV bao gồm thuế và GMV có đồng tài trợ của TTS (TikTok Shop). So hai loại khác nhau tạo ra một mức chênh không có thật.

{{hinh:so-sanh-hai-ky}}

### Tổng trước, chia sau

Nếu bạn xuất dữ liệu theo ngày và tự tính, hãy cộng tổng các đại lượng đếm được của cả kỳ (Lượt hiển thị sản phẩm, Lượt nhấp vào sản phẩm, Đơn hàng SKU, GMV) rồi mới chia để ra tỷ lệ. Lấy trung bình cộng của 30 tỷ lệ theo ngày sẽ tính ngày có 50 lượt hiển thị nặng như ngày có 5.000 lượt hiển thị, và cho ra một con số khác với con số TikTok hiển thị.

### Mức giảm có vượt khỏi dao động bình thường không

Với shop vài đơn mỗi ngày, GMV giữa hai tuần có thể chênh nhau đáng kể chỉ vì ngẫu nhiên. Trước khi kết luận, hãy xem mức giảm có lớn hơn mức dao động thường thấy của shop trong vài kỳ gần đây không. Một cách đọc đơn giản để tự áp dụng: chỉ coi một so sánh là "rõ" khi mỗi kỳ có số đơn đủ nhiều để không bị nhiễu và mức giảm lớn hơn mức chênh thường thấy giữa các kỳ gần đây; dưới mức đó, coi chênh lệch là "dấu hiệu" để theo dõi tiếp. TikTok không đưa ra ngưỡng chính thức cho việc này.

## Phân tích doanh thu TikTok Shop theo năm luồng

Khi đã chắc doanh thu giảm thật, bước đầu tiên là tìm xem nó giảm ở đâu. Trang "Lưu lượng truy cập sản phẩm" cho phép xem GMV, Lượt nhấp, CTR và CTOR theo các khía cạnh: Tất cả, LIVE của người bán, video của người bán, thẻ sản phẩm của người bán, Liên kết (gồm LIVE liên kết và video liên kết) và Tab Cửa hàng. Bài này gom thành năm luồng: **Thẻ sản phẩm**, **Tab cửa hàng**, **Video**, **LIVE** và **Liên kết**.

### Ví dụ giả định: GMV hai kỳ theo luồng

Giả sử một shop có GMV 30 ngày giảm từ 45 triệu xuống 42 triệu, tức giảm 6,7 %. Tách theo luồng (toàn bộ là số giả định):

| Luồng | Kỳ trước | Kỳ này | Thay đổi |
|---|---|---|---|
| Thẻ sản phẩm | 9.000.000 ₫ | 6.300.000 ₫ | −2.700.000 ₫ |
| Tab cửa hàng | 4.000.000 ₫ | 3.800.000 ₫ | −200.000 ₫ |
| Video | 6.000.000 ₫ | 6.200.000 ₫ | +200.000 ₫ |
| LIVE | 12.000.000 ₫ | 12.400.000 ₫ | +400.000 ₫ |
| Liên kết | 14.000.000 ₫ | 13.300.000 ₫ | −700.000 ₫ |
| **Toàn shop** | **45.000.000 ₫** | **42.000.000 ₫** | **−3.000.000 ₫** |

{{hinh:giam-theo-luong}}

### Đọc bảng theo số tuyệt đối

Mức giảm 3 triệu của shop gần như nằm gọn ở một luồng: thẻ sản phẩm giảm 2,7 triệu, tức 90 % mức giảm. Liên kết giảm 0,7 triệu, nhưng video và LIVE tăng bù gần hết. Nếu chỉ nhìn GMV toàn shop giảm 6,7 %, bạn có thể nghĩ "cả shop đang chậm lại" và giảm giá mọi thứ. Bảng theo luồng cho thấy câu chuyện cụ thể hơn: khách tự tìm đến qua tìm kiếm và đề xuất đang mua ít đi, còn nội dung vẫn ổn.

Hãy đọc theo số tuyệt đối trước, phần trăm sau. Một luồng nhỏ giảm 50 % có thể chỉ mất vài trăm nghìn đồng; một luồng lớn giảm 10 % có thể mất vài triệu.

### Vì sao luồng thẻ sản phẩm đáng xem kỹ nhất

Theo bài "Thẻ Sản Phẩm" của Học viện TikTok Shop, doanh thu không đến từ LIVE hay video được tính là doanh thu từ thẻ sản phẩm. Đây là luồng mà kết quả phụ thuộc chủ yếu vào chính trang sản phẩm của bạn: ảnh bìa, tiêu đề, mô tả, giá, đánh giá. Khi luồng này giảm, nguyên nhân thường nằm ở những thứ bạn sửa được. Khi các luồng nội dung giảm, nguyên nhân thường nằm ở nội dung, người dẫn hay nhà sáng tạo.

## Tách luồng giảm nhiều nhất thành bốn chỉ số

Biết luồng nào giảm, bước tiếp theo là biết bước nào trong phễu của luồng đó giảm. Bốn chỉ số TikTok định nghĩa trên trang "Lưu lượng truy cập sản phẩm" ghép thành một đẳng thức:

> GMV = Lượt hiển thị sản phẩm × CTR × CTOR × AOV (SKU)

Trong đó **Lượt hiển thị sản phẩm** là số lần sản phẩm xuất hiện trước người dùng; **CTR (Tỷ lệ nhấp)** là Lượt nhấp vào sản phẩm chia cho Lượt hiển thị; **CTOR (Tỷ lệ từ nhấp đến đặt hàng)** là Đơn hàng SKU chia cho Lượt nhấp, tên mới năm 2026 của chỉ số trước đây gọi là Tỷ lệ chuyển đổi; **AOV (SKU)** là giá trị trung bình của mỗi đơn hàng SKU, tức GMV chia cho Đơn hàng SKU. Đơn hàng SKU đếm đơn theo từng phiên bản sản phẩm. Bài [Các chỉ số TikTok Shop: Lượt hiển thị, CTR, CTOR, AOV và cách đọc đúng](/blog/chi-so-tiktok-shop-ctr-ctor-aov) giải thích chi tiết từng chỉ số.

### Ví dụ giả định: luồng thẻ sản phẩm

Tiếp ví dụ trên, luồng thẻ sản phẩm của shop có (số giả định):

| Chỉ số | Kỳ trước | Kỳ này | Thay đổi |
|---|---|---|---|
| Lượt hiển thị sản phẩm | 50.000 | 48.000 | −4 % |
| CTR | 3 % | 2,5 % | −17 % |
| Lượt nhấp vào sản phẩm | 1.500 | 1.200 | −20 % |
| CTOR | 4 % | 3,75 % | −6 % |
| Đơn hàng SKU | 60 | 45 | −25 % |
| AOV (SKU) | 150.000 ₫ | 140.000 ₫ | −7 % |
| GMV | 9.000.000 ₫ | 6.300.000 ₫ | −30 % |

Cả bốn chỉ số đều giảm, nhưng không giảm như nhau. CTR giảm mạnh nhất.

### Chia mức giảm cho từng chỉ số

Vì GMV là tích của bốn chỉ số, chỉ số nào giảm nhiều nhất theo tỷ lệ là chỉ số kéo GMV xuống nhiều nhất. Trong ví dụ trên, CTR giảm 17 %, gần bằng ba chỉ số còn lại cộng lại: AOV giảm 7 %, CTOR giảm 6 %, Lượt hiển thị giảm 4 %.

Câu chuyện chính là CTR: khoảng một nửa mức giảm của luồng đến từ việc người xem ít nhấp vào sản phẩm hơn. Lượt hiển thị gần như giữ nguyên, nên đây không phải chuyện sản phẩm bị ít người thấy, cũng không phải traffic loãng. Câu hỏi tiếp theo đã rất cụ thể: điều gì trên thẻ sản phẩm thay đổi trong kỳ này?

Nếu GMV gần như không đổi giữa hai kỳ, vẫn nên so tỷ lệ thay đổi của từng chỉ số: một chỉ số tăng và một chỉ số giảm có thể triệt tiêu nhau, và GMV đứng yên che mất cả hai câu chuyện.

### Lưu ý với Tab cửa hàng

Trong bảng khía cạnh của TikTok, Tab Cửa hàng có Lượt nhấp, CTR và CTOR nhưng không nằm trong danh sách khía cạnh của Lượt hiển thị sản phẩm. Với luồng này, hãy tách GMV thành ba phần: Lượt nhấp × CTOR × AOV.

## Danh sách kiểm tra theo từng luồng

Khi đã biết luồng nào giảm, đây là các câu hỏi nên đi qua cho luồng đó.

### Thẻ sản phẩm

- Các sản phẩm bán chạy có còn ở trạng thái **Trực tuyến** không? Trang "Quản lý Sản phẩm" của Học viện TikTok Shop (cập nhật 27/08/2026) phân biệt sản phẩm Trực tuyến, Đã vô hiệu hóa, Đã tạm ngưng và Bản nháp; chỉ sản phẩm Trực tuyến là khách mua được.
- Các biến thể chính có còn hàng không?
- Có ai sửa ảnh bìa, tiêu đề hay giá của sản phẩm bán chạy trong kỳ không?
- Một chương trình chiết khấu hay voucher có vừa kết thúc không? Giá hiển thị trên thẻ đổi ngay khi chương trình kết thúc.
- Công cụ Chẩn đoán giá có chuyển sản phẩm sang "Giá không cạnh tranh" không?
- Vận hành có xấu đi không? Bài "Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 1" nêu giao hàng đúng hạn và phản hồi nhanh đơn hàng mới là điều kiện để thẻ sản phẩm giữ được vị trí trong nhóm đề xuất.
- Đánh giá mới gần đây có nhiều đánh giá thấp không?

### Tab cửa hàng

- Khách vào trang shop ít đi (Lượt nhấp giảm) hay vào nhưng ít mua (CTOR giảm)?
- Sản phẩm được ghim hoặc trưng bày đầu trang shop có thay đổi không, có còn hàng không?
- Lượt nhấp từ Tab cửa hàng thường đi cùng các luồng nội dung: khi video và LIVE giảm, khách tìm vào trang shop cũng có thể giảm.

### Video

- Số video đăng trong kỳ có ít hơn không?
- Lượt hiển thị sản phẩm từ video giảm (video ít được phân phối) hay CTR giảm (video vẫn được xem nhưng ít người nhấp vào sản phẩm)?
- Sản phẩm trong các video bán chạy cũ có còn được gắn đúng, còn hàng, còn cùng mức giá không?

### LIVE

- Số buổi LIVE, thời lượng và khung giờ có thay đổi không?
- Ưu đãi trong phiên có nhỏ hơn kỳ trước không?
- Sản phẩm chủ lực của buổi LIVE có hết hàng giữa chừng không?

Một buổi LIVE lớn có thể làm thay đổi rõ GMV cả kỳ. Nếu kỳ trước có một buổi LIVE đặc biệt mà kỳ này không có, đó là nguyên nhân, không phải dấu hiệu shop đi xuống.

### Liên kết

- Một nhà sáng tạo từng mang về nhiều đơn có ngừng đăng nội dung về sản phẩm của bạn không?
- Mức hoa hồng hoặc điều kiện hợp tác có thay đổi không?
- Lượt hiển thị từ Liên kết giảm, hay vẫn nhiều nhưng ít đơn?

Kết quả của luồng Liên kết phụ thuộc chủ yếu vào nhà sáng tạo và khán giả của họ, nên nó không nên là căn cứ để kết luận về trang sản phẩm của bạn.

## Danh sách kiểm tra theo từng chỉ số

Trong luồng đã khoanh vùng, chỉ số giảm nhiều nhất cho biết nên tìm nguyên nhân ở đâu.

### Khi Lượt hiển thị sản phẩm giảm

- Sản phẩm có bị chuyển trạng thái, hết hàng, hay bị sửa tiêu đề làm mất từ khóa không?
- Số video, số buổi LIVE, số nhà sáng tạo gắn sản phẩm có ít đi không?
- Kỳ trước có một chương trình khuyến mãi của nền tảng hay ngày sale mà kỳ này không có không?
- Vận hành có xấu đi khiến thẻ sản phẩm tụt khỏi nhóm đề xuất không?

### Khi CTR giảm

- **Kiểm tra traffic loãng trước.** Nếu lượt hiển thị của luồng đó tăng mạnh cùng lúc CTR giảm, phần traffic mới có thể là người ít quan tâm. So CTR theo từng luồng: nếu CTR chỉ giảm ở đúng luồng vừa có lượt hiển thị tăng, đó là traffic loãng.
- Ảnh bìa, tiêu đề hay giá hiển thị có thay đổi trong kỳ không?
- Một chiết khấu hay nhãn khuyến mãi trên thẻ có vừa hết không?
- Có sản phẩm cạnh tranh mới với giá thấp hơn trên cùng trang tìm kiếm không? Hãy tự tìm từ khóa chính trên ứng dụng TikTok và xem thẻ của bạn nằm giữa các thẻ khác.

### Khi CTOR giảm

Tách CTOR làm hai nửa bằng **Tỷ lệ thêm vào giỏ hàng**, mà TikTok định nghĩa lại năm 2026 là số lượt nhấp nút Thêm vào giỏ hàng chia cho số lượt nhấp vào sản phẩm.

- **Tỷ lệ thêm vào giỏ hàng giảm**: khách vào trang nhưng chưa bị thuyết phục. Xem giá, bộ ảnh chi tiết, mô tả, đánh giá mới.
- **Tỷ lệ thêm vào giỏ hàng giữ nguyên nhưng ít đơn hơn**: khách thêm vào giỏ rồi không thanh toán. Xem phí vận chuyển, voucher đã hết hạn chưa, hoặc khách đang chờ một đợt ưu đãi chớp nhoáng mà họ đoán sẽ đến.

### Khi AOV giảm

- Một chương trình **Mua Sỉ Giá Hời**, mà Học viện TikTok Shop mô tả là công cụ "để tăng giá trị đơn hàng trung bình", có vừa kết thúc không?
- Cơ cấu biến thể có chuyển sang loại rẻ hơn không, ví dụ quy cách lớn hết hàng nên khách mua quy cách nhỏ?
- Bạn có vừa giảm giá sâu hơn không? GMV có thể giảm dù số đơn tăng.
- Một ưu đãi theo gói hay quà tặng kèm có vừa tắt không?

{{hinh:kiem-tra-theo-chi-so}}

## Nguyên nhân nằm ngoài phễu

Không phải mọi mức giảm đều do khách mua ít đi. Hãy kiểm tra thêm:

- **Mùa vụ**: nhiều ngành hàng có tháng cao điểm và tháng thấp điểm. So với cùng kỳ năm trước (nếu shop đã đủ lâu) giúp tách mùa vụ khỏi vấn đề thật.
- **Đơn hủy và hoàn tiền tăng**: GMV vẫn tính chúng, nhưng tiền về thì không. Nếu tiền về giảm mạnh hơn GMV, hãy xem lý do hủy và hoàn.
- **Hoàn tiền đến muộn**: theo trang "Lưu lượng truy cập sản phẩm", khoản hoàn tiền được ghi vào thời điểm yêu cầu được xử lý, có thể muộn hơn ngày mua. Vì vậy tỷ lệ hoàn tiền của tuần gần nhất thường trông thấp hơn thực tế, và một kỳ cũ có thể trông "xấu đi" khi các khoản hoàn của nó dần được ghi nhận.
- **Một sản phẩm chủ lực ngừng bán**: hết hàng dài ngày, ngừng nhập, hoặc bị tạm ngưng.

{{hinh:ngoai-pheu}}

## Một vài sản phẩm hay cả shop

Sau khi biết luồng và chỉ số, hãy lặp lại phép tách cho từng sản phẩm. Thường chỉ một vài sản phẩm giải thích phần lớn mức giảm.

### Cách làm

1. Lấy danh sách sản phẩm có GMV cao nhất ở kỳ trước trên luồng đã khoanh vùng.
2. Với mỗi sản phẩm, tính mức thay đổi GMV giữa hai kỳ.
3. Sắp xếp theo mức giảm tuyệt đối. Thường năm sản phẩm đầu đã giải thích phần lớn mức giảm của luồng.
4. Với từng sản phẩm đó, tách thành bốn chỉ số như ở trên.

### Hai kiểu kết quả

- **Mức giảm tập trung ở vài sản phẩm**: nguyên nhân thường nằm ở chính các sản phẩm đó, như hết hàng, đổi giá, đánh giá mới, chương trình kết thúc. Đây là trường hợp dễ xử lý nhất.
- **Mức giảm rải đều trên mọi sản phẩm**: nguyên nhân thường nằm ở cấp shop hoặc thị trường, như mùa vụ, vận hành, một thay đổi chung về giá hay voucher toàn shop. Sửa từng sản phẩm sẽ không giải quyết được.

Để biết một sản phẩm có thật sự yếu đi hay không, hãy so nó với chính nó ở kỳ trước và với các sản phẩm khác trong shop trên cùng luồng. Nếu cả shop cùng giảm 10 % và sản phẩm đó cũng giảm 10 %, sản phẩm đó không có vấn đề riêng.

## Quy trình 30 phút khi doanh thu giảm

Khi thấy doanh thu giảm, đây là thứ tự nên làm:

1. **Kiểm tra cách so sánh**: hai kỳ dài bằng nhau, cùng loại GMV, đánh dấu ngày sale, không tính ngày hôm nay.
2. **Tách GMV theo năm luồng** và tìm luồng có mức giảm tuyệt đối lớn nhất.
3. **Tách luồng đó thành Lượt hiển thị, CTR, CTOR và AOV**, chia mức giảm cho từng chỉ số.
4. **Đi qua danh sách kiểm tra** của luồng và chỉ số tương ứng.
5. **Tìm năm sản phẩm** giải thích nhiều nhất mức giảm, tách từng sản phẩm.
6. **Kiểm tra nguyên nhân ngoài phễu**: mùa vụ, hủy, hoàn, sản phẩm ngừng bán.
7. **Ghi lại một kết luận và một hành động** cho mỗi sản phẩm, kèm ngày bắt đầu, để kỳ sau đo lại.

{{hinh:quy-trinh-30-phut}}

Bước 7 thường bị bỏ qua nhất nhưng lại quan trọng nhất. Không có ngày bắt đầu, bạn không biết thay đổi nào gây ra kết quả nào.

## Những phản ứng nên tránh khi doanh thu giảm

- **Giảm giá toàn shop ngay lập tức.** Nếu mức giảm nằm ở CTR của vài sản phẩm do ảnh bìa, giảm giá toàn shop chỉ lấy đi biên lợi nhuận của mọi đơn.
- **Tăng ngân sách quảng cáo khi chưa biết bước nào yếu.** Quảng cáo đưa thêm người xem đến sản phẩm, nhưng không sửa được CTOR thấp. Kiểm tra CTR và CTOR trước, rồi mới quyết định mua thêm traffic. Bài [TikTok Shop không ra đơn: đọc phễu để tìm nguyên nhân](/blog/tiktok-shop-khong-ra-don) có một ví dụ về thứ tự này.
- **Sửa nhiều thứ cùng lúc.** Đổi ảnh, giá và mô tả trong một ngày khiến bạn không đo được việc nào có tác dụng.
- **Kết luận sau hai ba ngày.** Chỉ số theo ngày dao động mạnh. Hãy đọc sơ bộ một thay đổi sau 7 ngày và chỉ kết luận sau 14 ngày.
- **Sửa trang sản phẩm vì CTOR toàn shop giảm.** CTOR toàn shop thay đổi theo tỷ trọng giữa các luồng. Nếu lượt nhấp từ LIVE (thường có CTOR cao) giảm, CTOR toàn shop giảm dù không trang nào kém đi.

## Bảng theo dõi doanh thu mỗi tuần

Phân tích ở trên nhanh hơn nhiều khi bạn đã có sẵn số của các tuần trước. Một bảng tính cập nhật mỗi thứ Hai, từ trang Lưu lượng truy cập sản phẩm trong La bàn dữ liệu, là đủ:

1. **Một dòng cho mỗi luồng**: Thẻ sản phẩm, Tab cửa hàng, Video, LIVE, Liên kết, và một dòng toàn shop.
2. **Ba cột cho mỗi dòng**: GMV tuần vừa rồi, GMV tuần trước đó, và mức thay đổi tính bằng đồng. Đọc số đồng trước phần trăm, vì luồng nhỏ dễ có phần trăm lớn mà không đáng kể.
3. **Với luồng giảm nhiều nhất**, thêm bốn cột: Lượt hiển thị sản phẩm (với Tab cửa hàng là Lượt nhấp), CTR, CTOR, AOV, mỗi chỉ số của hai tuần.
4. **Cột ghi chú**: ngày sale, đợt khuyến mãi bắt đầu hay kết thúc, sản phẩm hết hàng, thay đổi bạn đã làm.

Ví dụ giả định cho một tuần:

| Luồng | Tuần trước | Tuần này | Thay đổi | Ghi chú |
|---|---|---|---|---|
| Thẻ sản phẩm | 2.100.000 ₫ | 1.500.000 ₫ | −600.000 ₫ | Voucher hết hạn thứ Tư |
| Tab cửa hàng | 300.000 ₫ | 300.000 ₫ | 0 ₫ | Không có |
| Video | 1.000.000 ₫ | 1.100.000 ₫ | +100.000 ₫ | Hai video mới |
| LIVE | 800.000 ₫ | 750.000 ₫ | −50.000 ₫ | Không có |
| Liên kết | 200.000 ₫ | 200.000 ₫ | 0 ₫ | Không có |
| Toàn shop | 4.400.000 ₫ | 3.850.000 ₫ | −550.000 ₫ | Không có |

Ở đây gần như toàn bộ mức giảm nằm ở Thẻ sản phẩm và trùng với ngày voucher hết hạn, nên câu hỏi đầu tiên là CTOR hay AOV của luồng đó đã đổi chưa. Sau bốn đến sáu tuần, bảng còn cho bạn mức dao động thường thấy của shop, thứ cần có để biết một mức giảm có vượt khỏi dao động bình thường không.

Để xem một chỉ số đổi thì GMV đổi bao nhiêu, nhập số của luồng vào [công cụ tính GMV miễn phí](/cong-cu/tinh-gmv). Nếu mức giảm nằm ở luồng thẻ sản phẩm, đọc tiếp bài [Tối ưu thẻ sản phẩm TikTok Shop từ A–Z](/blog/toi-uu-the-san-pham-tiktok-shop); nếu doanh thu tụt ngay sau một đợt sale, xem bài [Doanh thu sau sale TikTok Shop](/blog/doanh-thu-sau-sale-tiktok-shop).

## Tóm tắt

- **Kiểm tra cách so sánh trước**: hai kỳ bằng nhau, cùng loại GMV, đánh dấu ngày sale, tổng trước chia sau, và mức giảm có vượt khỏi dao động bình thường.
- **GMV khác tiền về**: GMV giảm là chuyện phễu; tiền về giảm trong khi GMV giữ nguyên là chuyện hủy, hoàn và quyết toán.
- **Tách theo năm luồng**, đọc số tuyệt đối, rồi tách luồng giảm nhiều nhất thành Lượt hiển thị × CTR × CTOR × AOV.
- **Đi qua danh sách kiểm tra** của đúng luồng và đúng chỉ số, rồi tìm vài sản phẩm giải thích phần lớn mức giảm.
- **Một hành động, một ngày bắt đầu**, đo lại sau 7 và 14 ngày.

Nếu tiền về giảm mạnh hơn GMV, bài [Tỷ lệ hoàn hàng TikTok Shop](/blog/ty-le-hoan-hang-tiktok-shop) tách đơn hủy, giao không thành công và trả hàng, còn bài [Phí sàn TikTok Shop 2026](/blog/phi-san-tiktok-shop-2026) cho thấy một đơn còn lại bao nhiêu sau phí.
`;
