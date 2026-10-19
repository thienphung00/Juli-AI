/**
 * Pain post (D56, P46-C1, week 2 #5): "Nhiều người bấm xem nhưng không ai mua".
 * Main keyword "khách xem nhưng không mua tiktok shop" (content plan; Google
 * autocomplete VN 2026-10-17 empty for it and every close pain phrasing, kept
 * per the brief: the SERP is buyer-side app errors and agency pages). Scope is
 * only the step after the click (CTOR, add to cart, checkout): definitions stay
 * in `chi-so-tiktok-shop-ctr-ctor-aov`, the whole-funnel diagnosis in
 * `tiktok-shop-khong-ra-don`, order value in
 * `tang-gia-tri-don-hang-trung-binh-tiktok-shop`. Facts re-opened on
 * 2026-10-17 in TikTok Academy VN (title + date in the text and `sources`):
 * Lưu lượng truy cập sản phẩm (17/06/2026), Tinh chỉnh GMV (11/05/2026),
 * Voucher Thông Thường Của Nhà Bán Hàng (13/06/2025), Cách Tính Khuyến Mãi Cộng
 * Dồn (29/10/2025), Chiết Khấu Phí Vận Chuyển của Nhà Bán Hàng (24/01/2025),
 * Chẩn đoán giá (24/07/2026), Chẩn Đoán Thẻ Sản Phẩm 4 (15/12/2023). No
 * official CTOR benchmark exists; none is given. D59 reach post (P48-C): no
 * Juli, no product links; the last how-to section is a weekly self-check sheet
 * built from the Seller Center pages above. Numbers in examples are
 * hypothetical and say so.
 */
export const body = `
Khi nhiều người đã bấm vào sản phẩm mà gần như không ai đặt hàng, chỗ đứt nằm ở bước từ cú nhấp đến đơn hàng (CTOR), không phải ở lượt xem hay ở nội dung. Ở bước này khách đã thấy sản phẩm và đủ quan tâm để mở trang, nên lý do họ rời đi thường là thứ họ gặp sau đó: thông tin trên trang sản phẩm, đánh giá, giá, voucher hoặc phí vận chuyển lúc thanh toán. Bài này chỉ cách tách từng nguyên nhân bằng số liệu của chính shop, sửa đúng một chỗ và đo lại sau 7, 14 ngày.

Bài này chỉ nói về điều xảy ra sau cú nhấp. Nếu bạn cần định nghĩa CTR, CTOR, AOV và cách TikTok tính chúng, hãy đọc bài [các chỉ số TikTok Shop](/blog/chi-so-tiktok-shop-ctr-ctor-aov). Nếu shop không có đơn và bạn chưa biết phễu gãy ở bước nào, bài [TikTok Shop không ra đơn](/blog/tiktok-shop-khong-ra-don) đi qua cả phễu từ lượt hiển thị. Mọi con số trong các ví dụ dưới đây là ví dụ giả định.

## Nhiều người bấm vào sản phẩm mà không mua: có đúng là CTOR thấp không

"Bấm vào nhiều mà đơn thì không có": trước khi sửa gì, hãy chắc đây đúng là vấn đề của bước sau cú nhấp. Theo bài "Lưu lượng truy cập sản phẩm" của Học viện TikTok Shop (cập nhật 17/06/2026), CTOR là Tỷ lệ từ nhấp đến đặt hàng, tức phần trăm số lượt nhấp vào liên kết sản phẩm dẫn đến đơn hàng SKU:

> CTOR = Đơn hàng SKU ÷ Lượt nhấp vào sản phẩm

Trang này nằm trong Trung tâm nhà bán hàng, mục La bàn dữ liệu, Số liệu phân tích sản phẩm. Phễu của từng sản phẩm hiển thị Lượt hiển thị sản phẩm, Lượt nhấp vào sản phẩm, Đơn hàng SKU, CTR và CTOR.

### So với chính shop, không so với một con số chung

TikTok không công bố một mức CTOR chuẩn. Mốc so sánh có ý nghĩa là:

- **Chính sản phẩm đó ở kỳ trước**: 28 ngày gần nhất với 28 ngày trước đó, cộng tổng lượt nhấp và đơn hàng SKU của cả kỳ rồi mới chia.
- **Các sản phẩm khác của shop trên cùng nguồn**: CTOR bằng một nửa các sản phẩm cùng ngành trong shop là tín hiệu rõ hơn mọi ngưỡng chung.
- **Đủ dữ liệu**: với vài chục lượt nhấp, một hai đơn đã làm CTOR nhảy mạnh. Chờ đến khi lượt nhấp đủ nhiều để không bị nhiễu, hoặc gộp một khoảng thời gian dài hơn.

## Xem video, LIVE khác với bấm vào sản phẩm

Nhiều người bán nói "khách xem nhiều mà không mua" khi thật ra khách mới chỉ xem video hay ở trong phòng LIVE, chưa bấm vào sản phẩm. Đó là chuyện của các bước trước: Lượt hiển thị sản phẩm và CTR. Bài [video nhiều view nhưng không ra đơn](/blog/video-tiktok-nhieu-view-khong-ra-don) và bài [LIVE đông người xem mà ít đơn](/blog/live-tiktok-shop-khong-ra-don) đọc riêng phễu của hai luồng này. Nếu sản phẩm gần như không có ai thấy, hãy bắt đầu từ bài [sản phẩm không có lượt hiển thị](/blog/san-pham-tiktok-shop-khong-co-luot-hien-thi).

Phần còn lại của bài dành cho trường hợp khách **đã bấm vào sản phẩm**: Lượt nhấp vào sản phẩm khá, mà Đơn hàng SKU thấp.

## Đọc CTOR theo nguồn: thẻ sản phẩm, tab cửa hàng, video, LIVE

Cùng một sản phẩm, mọi lượt nhấp đều dẫn về cùng một trang sản phẩm. Nhưng khách đến từ những nơi khác nhau mang theo kỳ vọng khác nhau. Trên trang Lưu lượng truy cập sản phẩm, bạn chọn loại nội dung ở đầu trang (LIVE cá nhân, Video cá nhân, Nội dung liên kết) và TikTok cho xem CTOR theo các khía cạnh: thẻ sản phẩm của người bán, video, LIVE, Liên kết và Tab cửa hàng.

Câu hỏi cần trả lời: vấn đề nằm ở trang, hay ở lời hứa của nội dung dẫn khách đến trang?

- **CTOR thấp ở mọi nguồn**: trang sản phẩm là nghi phạm chính. Khách tự tìm đến cũng không mua.
- **CTOR ổn ở Thẻ sản phẩm, thấp ở Video hoặc LIVE**: trang vẫn thuyết phục được người tự tìm đến. Người đến từ nội dung có thể đã nghe một mức giá, một ưu đãi hay một biến thể mà trang không có.
- **CTOR thấp ở Liên kết**: nhà sáng tạo có thể đã nhắc đến một ưu đãi đã hết hạn.

{{hinh:ctor-hai-luong}}

Trong ví dụ giả định ở trên, CTOR gộp 3,4 % trông bình thường, trong khi khách từ video gần như không mua. Sửa mô tả lúc này là sửa nhầm chỗ: hãy xem lại video đã nói gì về giá và ưu đãi.

## Khách rời đi ở trang sản phẩm hay ở bước thanh toán

Sau cú nhấp, khách đi qua ba chỗ: trang sản phẩm, giỏ hàng, và bước thanh toán. Chỉ số giúp tách chúng là **Tỷ lệ thêm vào giỏ hàng**, mà bài "Lưu lượng truy cập sản phẩm" định nghĩa là số lượt nhấp nút Thêm vào giỏ hàng chia cho tổng số lượt nhấp vào sản phẩm.

- **Tỷ lệ thêm vào giỏ hàng thấp**: khách xem trang rồi đi. Họ chưa bị thuyết phục bởi ảnh, mô tả, đánh giá hay giá.
- **Tỷ lệ thêm vào giỏ hàng ổn, nhưng ít đơn**: khách đã muốn mua, rồi dừng lại ở giỏ hoặc ở bước thanh toán. Nghi phạm là voucher, mức chi tối thiểu, phí vận chuyển và tổng tiền cuối cùng.

{{hinh:sau-cu-nhap}}

Người xem video hay LIVE có thể đặt ngay mà không qua giỏ hàng, nên cách tách này rõ nhất ở luồng Thẻ sản phẩm và Tab cửa hàng.

## Trang sản phẩm chưa trả lời câu hỏi của khách

Khách xem trang rồi rời đi thường vì trang thiếu một câu trả lời họ cần. Bài "Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 4" của Học viện TikTok Shop xếp các yếu tố tác động đến quyết định đặt hàng thành ba nhóm: Hiển thị (ảnh chính, trang chi tiết, thông tin cơ bản), Lợi ích (hiệu quả chi phí, lợi thế giá, hoạt động khuyến mãi, thanh toán khi giao hàng) và Sự tin cậy (thương hiệu, đánh giá, tỷ lệ trả hàng).

### Kích thước, chất liệu, cách dùng, biến thể

"Khách hỏi size rồi im lặng": những câu hỏi lặp lại trong tin nhắn là danh sách những gì trang đang thiếu. Kiểm tra:

- **Ảnh có cho thấy sản phẩm thật không**: kích thước so với vật quen thuộc, chi tiết chất liệu, màu thật của từng biến thể. Bài chẩn đoán của TikTok gợi ý có ít nhất 3 ảnh, có video và thêm ảnh khác nhau cho từng SKU.
- **Mô tả có trả lời 5 câu khách hay hỏi nhất không**: kích thước, thành phần, cách dùng, trong hộp có gì, bảo quản thế nào.
- **Biến thể khách cần có còn hàng không**: khách vào để mua màu đen size M, thấy hết hàng thì rời đi.

### Đánh giá và điểm xếp hạng

Ít đánh giá, hoặc vài đánh giá thấp mới nhất nằm ngay đầu, đủ làm khách ngần ngại. Tìm lý do lặp lại trong đánh giá gần đây: hàng không giống ảnh, giao chậm, đóng gói kém. Nếu nguyên nhân là chất lượng hay vận hành, sửa trang không giúp được.

## Giá, voucher và phí vận chuyển lúc thanh toán

Khi khách đã thêm vào giỏ mà không thanh toán, họ thường dừng lại vì một con số họ không ngờ tới.

### Voucher: mức chi tối thiểu và một voucher mỗi đơn

Theo bài "Voucher Thông Thường Của Nhà Bán Hàng" (13/06/2025), voucher của nhà bán hàng có mức chi tối thiểu, và các loại voucher của nhà bán hàng không dùng chung được trong cùng một đơn: khi thanh toán, voucher có mức giảm cao nhất được áp dụng. Bài "Cách Tính Khuyến Mãi Cộng Dồn" (29/10/2025) thêm một chi tiết dễ bị bỏ qua: nếu voucher yêu cầu mức chi tối thiểu, hệ thống xét điều kiện trên giá **sau khi** áp dụng giảm giá sản phẩm.

Hệ quả: khách thấy voucher "giảm 20.000 ₫ cho đơn từ 200.000 ₫", nhẩm theo giá gốc 110.000 ₫ và thêm vào giỏ hai món, nhưng sản phẩm đang giảm còn 95.000 ₫ nên giỏ chỉ còn 190.000 ₫ và voucher không áp dụng (ví dụ giả định). Khách thấy thiếu voucher ở bước cuối và bỏ giỏ. Cũng theo bài voucher, tỷ lệ đổi thấp có thể cho thấy mức chi tối thiểu quá cao so với giá bán trung bình của sản phẩm.

### Phí vận chuyển hiện ra ở bước cuối

Với sản phẩm giá thấp, phí vận chuyển có thể chiếm một phần lớn tổng tiền khách thấy ở bước cuối. Trang Lưu lượng truy cập sản phẩm có chỉ số Phí vận chuyển (tổng phí vận chuyển khách đã trả trong kỳ) để bạn xem mức phí khách đang gặp. Theo bài "Chiết Khấu Phí Vận Chuyển của Nhà Bán Hàng" (24/01/2025), nhà bán hàng có thể tự chịu toàn bộ hoặc một phần phí vận chuyển, cho sản phẩm được chọn, cho đơn đạt mức chi tối thiểu hoặc toàn cửa hàng; công cụ này cần số dư tài khoản dương và tài khoản đã qua giai đoạn thử thách.

### Giá so với sản phẩm tương tự

Công cụ Chẩn đoán giá của TikTok (bài cập nhật 24/07/2026) cho xem sản phẩm tương tự có giá cạnh tranh hơn và cho đặt lại giá bằng Giảm giá sản phẩm hoặc Voucher của nhà bán hàng. Bài này cũng ghi rõ không có hình phạt nào nếu bạn không đổi giá theo đề xuất. Giảm giá là một quyết định về biên lợi nhuận, không phải việc làm mặc định mỗi khi CTOR giảm.

{{hinh:ctor-trieu-chung}}

## Khách chưa mua ngay có thể mua sau: GMV gián tiếp

Không phải ai bấm vào mà chưa mua đều là khách đã mất. Theo bài "Tinh chỉnh GMV" của Học viện TikTok Shop (cập nhật 11/05/2026), từ giữa tháng 4/2026 doanh số chia thành Trực tiếp và Gián tiếp. Ví dụ trong bài: người dùng xem video có link sản phẩm, nhấp vào sản phẩm nhưng không mua ngay, sau đó tự tìm sản phẩm trong TikTok Shop và mua; đơn đó được ghi vào GMV video gián tiếp. Bài cũng ghi CTOR thuộc nhóm chỉ số áp dụng cách ghi nhận này, và một đơn có thể được ghi cho video khách đã xem trong vòng 7 ngày.

Vì vậy đừng kết luận sau một hai ngày, và đừng so CTOR của 3 ngày gần nhất với 28 ngày trước: đơn muộn của 3 ngày đó chưa về, nên mức giảm có thể không có thật.

## Sửa gì trước, đo thế nào sau 7 và 14 ngày

Thứ tự gợi ý khi CTOR của một sản phẩm thấp:

1. **Tồn kho và biến thể**: lỗi rẻ nhất để sửa.
2. **Nguồn**: CTOR thấp ở mọi nguồn hay chỉ một nguồn.
3. **Trước giỏ hay sau giỏ**, bằng Tỷ lệ thêm vào giỏ hàng.
4. **Chọn một thay đổi**: mô tả và ảnh nếu trước giỏ thấp; voucher, mức chi tối thiểu hay phí vận chuyển nếu sau giỏ thấp; nội dung nếu chỉ một nguồn thấp.
5. **Ghi ngày bắt đầu, đọc sơ bộ ở ngày 7, chốt ở ngày 14**, so với 14 ngày trước khi đổi.

Trong lúc đo, để ý các chỉ số còn lại: một voucher có thể tăng CTOR mà kéo giá trị mỗi đơn xuống. Thay đổi chỉ đáng giữ khi chỉ số mục tiêu lên mà các chỉ số khác vẫn trong mức dao động bình thường.

## Những điều không nên làm khi chưa biết CTOR thấp ở nguồn nào

- **Giảm giá hàng loạt.** Nếu khách rời đi vì trang thiếu thông tin hay vì video hứa một ưu đãi không còn, giảm giá chỉ lấy đi biên lợi nhuận. Muốn hiểu tác động của giảm giá lên giá trị mỗi đơn, đọc bài [bán nhiều đơn mà vẫn ít tiền](/blog/tang-gia-tri-don-hang-trung-binh-tiktok-shop).
- **Xóa sản phẩm rồi đăng lại.** Bạn mất đánh giá và lịch sử số liệu để so sánh, và không có trang chính thức nào nói việc này giúp tăng đơn.
- **Đổi giá, ảnh, mô tả và voucher trong cùng một tuần.** Khi số liệu thay đổi, bạn sẽ không biết điều gì có tác dụng.

## Tự theo dõi CTOR mỗi tuần bằng một bảng đơn giản

Mỗi tuần một lần, mở trang Lưu lượng truy cập sản phẩm trong La bàn dữ liệu, chọn 28 ngày gần nhất và chép vào một bảng tính cho 10 đến 20 sản phẩm có nhiều lượt nhấp nhất:

| Cột | Lấy ở đâu |
|---|---|
| Sản phẩm, nguồn | Tên sản phẩm; khía cạnh thẻ sản phẩm, video, LIVE, Liên kết hoặc Tab cửa hàng |
| Lượt nhấp, Đơn hàng SKU | Phễu của sản phẩm trên trang Lưu lượng truy cập sản phẩm |
| CTOR, Tỷ lệ thêm vào giỏ hàng | Cùng trang, cùng khoảng thời gian |
| Thay đổi đã làm, ngày bắt đầu | Bạn tự ghi: sửa gì, sửa ngày nào |

Rồi làm ba việc theo thứ tự:

1. **Đưa sản phẩm nhiều lượt nhấp lên trước.** Một sản phẩm được bấm nhiều mà CTOR thấp hơn hẳn các sản phẩm khác cùng nguồn thường đang để lỡ nhiều đơn hơn một sản phẩm có CTOR thấp nhất nhưng ít ai bấm vào. Ví dụ giả định: sản phẩm có 600 lượt nhấp và CTOR 2 % đáng xem trước sản phẩm chỉ có 40 lượt nhấp và CTOR 1 %.
2. **Ghi một nghi phạm cho mỗi sản phẩm đầu bảng**: trước giỏ hay sau giỏ, một nguồn hay mọi nguồn, theo các mục ở trên.
3. **Chọn một sản phẩm, một thay đổi**, ghi ngày bắt đầu vào bảng, và chưa đụng đến sản phẩm đó cho đến ngày 14.

Dòng nào còn quá ít lượt nhấp trong kỳ thì chưa kết luận. Cách tách GMV theo luồng có trong bài [GMV là gì](/blog/gmv-la-gi-tiktok-shop), và [công cụ tính GMV miễn phí](/cong-cu/tinh-gmv) cho ước tính GMV đổi ra sao khi CTOR đổi.

## Ghi nhớ nhanh

- Khách đã bấm vào mà không mua là chuyện của CTOR, không phải lượt xem. So với chính shop, không so với ngưỡng chung.
- Đọc CTOR theo nguồn: thấp ở mọi nguồn thì sửa trang, thấp ở một nguồn thì xem nội dung dẫn khách đến.
- Tách trước giỏ và sau giỏ bằng Tỷ lệ thêm vào giỏ hàng: trang sản phẩm hay voucher, phí vận chuyển.
- Đơn có thể đến muộn trong 7 ngày. Sửa một chỗ, đọc ở ngày 7, chốt ở ngày 14.

Muốn so CTOR với các bước còn lại của phễu, bài [TikTok Shop không ra đơn](/blog/tiktok-shop-khong-ra-don) đi qua từng bước từ lượt hiển thị đến đơn hàng.
`;
