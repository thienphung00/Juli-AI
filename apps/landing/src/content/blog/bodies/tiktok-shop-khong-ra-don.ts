/**
 * Post (D48 additions 6, P39-B): "TikTok Shop không ra đơn". Target queries:
 * "tiktok shop không ra đơn", "vì sao bán hàng trên tiktok shop không ra đơn",
 * "quảng cáo tiktok shop không ra đơn" (funnel angle only: read CTR / CTOR
 * before raising an ad budget; no ad how-to, D48.5). Metric facts are
 * from TikTok Academy VN, "Lưu lượng truy cập sản phẩm" (17/06/2026); product
 * statuses from "Quản lý Sản phẩm" (27/08/2026); recommendation threshold and
 * shop operations from "Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 1"; the
 * three factor groups from "... 4"; product card scope from "Thẻ Sản Phẩm";
 * price states from "Chẩn đoán giá"; listing rules from "Tiêu đề, mô tả, hình ảnh
 * và video về sản phẩm". Nothing here describes TikTok's ad products. Every
 * number in a "Ví dụ giả định" is hypothetical and says so; the data floors are
 * an example the seller sets, not a TikTok rule. Reach tier (D59): no Juli.
 */
export const body = `
"Shop mở mấy tuần rồi mà không ra đơn", "tuần trước còn đều đơn, tuần này im hẳn", "chạy quảng cáo mà vẫn không ra đơn". Đây là những câu than quen thuộc nhất trong các nhóm nhà bán TikTok Shop. Lời khuyên đi kèm thường là một danh sách dài: đổi ảnh, giảm giá, đăng thêm video, chạy thêm quảng cáo, mời nhà sáng tạo. Mỗi lời khuyên có thể đúng với một shop, nhưng làm hết cùng lúc vừa tốn tiền vừa không cho bạn biết điều gì thật sự có tác dụng.

Bài viết này đi theo hướng khác: coi "không ra đơn" là một triệu chứng, rồi đọc phễu bán hàng để tìm xem đơn hàng đang bị chặn ở bước nào. Bạn sẽ có một danh sách kiểm tra theo từng bước, dùng đúng tên chỉ số trên Trung tâm nhà bán hàng, và một phần riêng cho trường hợp quảng cáo TikTok Shop không ra đơn: những gì cần đọc trước khi tăng ngân sách. Mọi ví dụ có số trong bài là ví dụ giả định.

## "Không ra đơn" thực ra đang nghẽn ở đâu

Một đơn hàng trên TikTok Shop chỉ xảy ra khi khách đi qua đủ các bước: nhìn thấy sản phẩm, nhấp vào, rồi đặt hàng. Thiếu bất kỳ bước nào, đơn hàng không đến. Vì vậy câu hỏi "vì sao bán hàng trên TikTok Shop không ra đơn" luôn có thể viết lại thành một trong ba câu hỏi cụ thể hơn:

1. **Không ai nhìn thấy sản phẩm?** Lượt hiển thị sản phẩm quá thấp.
2. **Có người thấy nhưng không ai nhấp?** CTR thấp.
3. **Có người nhấp nhưng không ai mua?** CTOR thấp.

Trên Học viện TikTok Shop, trang "Lưu lượng truy cập sản phẩm" (cập nhật 17/06/2026) định nghĩa đúng các chỉ số này:

- **Lượt hiển thị sản phẩm**: số lần sản phẩm xuất hiện trước người dùng, ở trong video, buổi LIVE, trang tìm kiếm hay trang đề xuất.
- **Lượt nhấp vào sản phẩm**: theo TikTok, chỉ số này "ghi nhận mọi lượt nhấp chủ động vào sản phẩm của bạn trên tất cả các kênh của nhà sáng tạo và người bán".
- **CTR (Tỷ lệ nhấp)**: Lượt nhấp vào sản phẩm chia cho Lượt hiển thị sản phẩm.
- **CTOR (Tỷ lệ từ nhấp đến đặt hàng)**: Đơn hàng SKU chia cho Lượt nhấp vào sản phẩm. Đây là tên mới năm 2026 của chỉ số trước đây gọi là Tỷ lệ chuyển đổi trong phân tích sản phẩm; TikTok cho biết cách tính không đổi.

Đơn hàng SKU là số đơn tính theo từng phiên bản sản phẩm (SKU), nên một đơn có hai sản phẩm khác nhau tạo ra hai đơn hàng SKU. Ba bước này nhân với nhau: Lượt hiển thị × CTR × CTOR = Đơn hàng SKU. Nếu một hệ số gần bằng không, cả tích gần bằng không, dù hai hệ số kia tốt đến đâu.

{{hinh:ba-buoc-nghen}}

### Vì sao phải biết bước nào nghẽn

Mỗi bước có những đòn bẩy riêng, và đòn bẩy của bước này gần như vô dụng ở bước khác. Đổi ảnh bìa giúp khi người ta thấy mà không nhấp, nhưng không giúp khi chẳng ai thấy. Viết lại mô tả giúp khi người ta nhấp vào rồi bỏ đi vì thiếu thông tin, nhưng không giúp khi ảnh bìa không đủ hấp dẫn để ai nhấp vào. Mua thêm traffic giúp khi trang sản phẩm đã chuyển đổi tốt, nhưng chỉ làm tăng số người rời đi khi CTOR đang thấp. Tìm đúng bước trước, rồi mới chọn việc.

## Trước khi đọc phễu: sản phẩm có đang bán được không

Trước khi phân tích chỉ số, hãy loại trừ những nguyên nhân khiến sản phẩm không thể ra đơn dù phễu có tốt đến đâu. Phần này mất năm phút nhưng hay bị bỏ qua nhất.

### Trạng thái sản phẩm

Trang "Quản lý Sản phẩm" của Học viện TikTok Shop (cập nhật 27/08/2026) liệt kê các trạng thái sản phẩm trong Trung tâm nhà bán hàng. Chỉ sản phẩm ở trạng thái **Trực tuyến** là sản phẩm "đang hiển thị trực tuyến và có thể được khách hàng mua". Các trạng thái khác đều không bán được:

- **Đã vô hiệu hóa**: sản phẩm mà nhà bán hàng cho ngừng hiển thị.
- **Đã tạm ngưng**: sản phẩm bị tạm ngưng vì một số lý do, ví dụ bị từ chối khi duyệt.
- **Bản nháp**: đã điền thông tin nhưng chưa gửi đi.

Nếu sản phẩm bán chạy nhất của bạn vừa chuyển sang Đã tạm ngưng, việc "không ra đơn" đã có lời giải. Hãy đọc lý do trong Trung tâm nhà bán hàng, sửa thông tin theo yêu cầu và gửi lại. Trang chính sách "Tiêu đề, mô tả, hình ảnh và video về sản phẩm" của TikTok là nơi đối chiếu những gì tiêu đề, ảnh và mô tả được và không được chứa.

### Tồn kho và biến thể

Một sản phẩm Trực tuyến vẫn có thể không ra đơn nếu các biến thể (SKU) được khách chọn nhiều nhất đã hết hàng. Bài "Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 4" của TikTok khuyên cân nhắc tăng tồn kho cho các SKU nhất định, vì khách chọn đúng biến thể đã hết sẽ không mua được. Hãy kiểm tra tồn kho của từng biến thể, không chỉ tổng tồn kho của sản phẩm.

### Vận hành shop

Bài "Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 1" giải thích rằng thẻ sản phẩm cần đạt ngưỡng tối thiểu để vào nhóm đề xuất, và hoạt động của cửa hàng như vận chuyển đúng hạn, phản hồi nhanh đơn hàng mới ảnh hưởng đến việc giữ được vị trí đó. Nếu gần đây shop giao trễ nhiều hay để đơn mới chờ lâu, đó là điều cần sửa trước khi nghĩ đến ảnh bìa hay giá.

{{hinh:truoc-khi-doc-pheu}}

## Đọc phễu ở đâu và đọc thế nào cho đúng

Phễu của từng sản phẩm nằm tại Trung tâm nhà bán hàng, mục La bàn dữ liệu, phần Số liệu phân tích sản phẩm, trang Lưu lượng truy cập sản phẩm. TikTok mô tả mô-đun này giúp người bán hiểu lưu lượng truy cập đến từ đâu và hiệu quả chuyển đổi của từng giai đoạn trong phễu.

### Chọn luồng truy cập

Các chỉ số trên trang này xem được theo khía cạnh: Tất cả, LIVE của người bán, video của người bán, thẻ sản phẩm của người bán, Liên kết (LIVE và video của nhà sáng tạo tiếp thị liên kết) và Tab Cửa hàng. Bài này gom thành năm luồng: Thẻ sản phẩm, Tab cửa hàng, Video, LIVE và Liên kết.

Khi chẩn đoán vì sao không ra đơn, hãy đọc luồng **thẻ sản phẩm** trước. Theo bài "Thẻ Sản Phẩm" của Học viện TikTok Shop, doanh thu không đến từ LIVE hay video được tính là doanh thu từ thẻ sản phẩm, tức khách tự tìm đến qua tìm kiếm, đề xuất, trang mua sắm. Đây là luồng phản ánh trung thực nhất chất lượng của chính trang sản phẩm, vì không có người dẫn LIVE hay nhà sáng tạo nào bán hộ. Các luồng nội dung được bàn riêng ở phần sau.

### Chọn khoảng thời gian

Với shop mới hoặc shop ít đơn, một ngày hay ba ngày là quá ngắn để đọc tỷ lệ. Hãy chọn ít nhất 14 ngày, tốt hơn là 28 hoặc 30 ngày, và cộng tổng lượt hiển thị, lượt nhấp, đơn hàng SKU của cả kỳ rồi mới tính tỷ lệ. Đừng lấy trung bình của các tỷ lệ theo ngày: ngày có 20 lượt hiển thị và ngày có 2.000 lượt hiển thị sẽ bị tính nặng như nhau.

### Đủ dữ liệu chưa

Với 15 lượt nhấp, CTOR 0 % không có nghĩa là trang sản phẩm hỏng; nó có nghĩa là chưa đủ dữ liệu để kết luận. Chỉ đọc tỷ lệ khi số liệu trên luồng thẻ sản phẩm đủ nhiều để không bị nhiễu, hoặc gộp một cửa sổ đo dài hơn, và giữ cùng một cách đọc cho mọi lần so sánh. TikTok không đưa ra ngưỡng chính thức cho việc này. Khi số liệu còn quá ít, vấn đề gần như luôn nằm ở bước đầu tiên: sản phẩm chưa có đủ người nhìn thấy.

{{hinh:doc-pheu-o-dau}}

## Bước 1: Lượt hiển thị thấp, không ai nhìn thấy sản phẩm

Đây là trường hợp phổ biến nhất ở shop mới. Phễu có hình dạng: vài chục đến vài trăm lượt hiển thị mỗi tuần, một vài lượt nhấp, không có đơn.

### Dấu hiệu lượt hiển thị thấp

- Lượt hiển thị sản phẩm thấp ở mọi luồng, không chỉ một luồng.
- Lượt nhấp quá ít để CTR và CTOR có ý nghĩa.
- Sản phẩm không xuất hiện khi bạn tự tìm từ khóa chính của nó trên ứng dụng TikTok.

### Nguyên nhân khiến ít người thấy sản phẩm

- **Tiêu đề không chứa từ khóa người mua tìm.** Tiêu đề chỉ có tên riêng hoặc mã sản phẩm khiến sản phẩm không xuất hiện trong kết quả tìm kiếm.
- **Thẻ sản phẩm chưa đạt ngưỡng để vào nhóm đề xuất**, như bài chẩn đoán số 1 của TikTok mô tả.
- **Không có nội dung nào đưa sản phẩm đến người xem**: chưa có video, chưa LIVE, chưa có nhà sáng tạo nào gắn sản phẩm.
- **Thuộc tính sản phẩm thiếu hoặc sai ngành hàng**, khiến sản phẩm không vào đúng bộ lọc.

### Việc nên làm khi lượt hiển thị thấp

1. Dùng Trình Tối Ưu Hóa Tiêu Đề Sản Phẩm trong La bàn dữ liệu để tìm từ khóa đúng với sản phẩm, rồi đặt loại sản phẩm và đặc điểm chính lên đầu tiêu đề.
2. Điền đầy đủ thuộc tính và chọn đúng ngành hàng.
3. Tạo một nguồn nội dung đều đặn: video ngắn về sản phẩm, một buổi LIVE nhỏ, hoặc mời nhà sáng tạo tiếp thị liên kết.
4. Giữ vận hành ổn định: giao đúng hạn, xử lý đơn mới nhanh.

Ở bước này, đừng vội giảm giá sâu. Giảm giá không làm sản phẩm được nhìn thấy nhiều hơn nếu nó chưa xuất hiện trong tìm kiếm hay đề xuất.

## Bước 2: Có hiển thị nhưng CTR thấp

Phễu có hình dạng: hàng nghìn lượt hiển thị, rất ít lượt nhấp. Sản phẩm đã được nhìn thấy, nhưng những gì hiện trên thẻ không đủ để người xem dừng lại.

### Dấu hiệu CTR thấp

- Lượt hiển thị ở luồng thẻ sản phẩm đạt ngưỡng, nhưng CTR thấp hơn hẳn các sản phẩm khác của shop trên cùng luồng.
- Hoặc CTR giảm rõ so với chính sản phẩm đó ở kỳ trước.

TikTok không công bố một mức CTR chuẩn chung cho mọi ngành, và CTR khác nhau nhiều giữa các luồng. Vì vậy mốc so sánh đúng là chính sản phẩm đó và các sản phẩm khác trong shop, trên cùng một luồng.

### Kiểm tra traffic loãng trước

CTR thấp không phải lúc nào cũng do thẻ sản phẩm. Khi một video hay một chiến dịch đưa sản phẩm đến rất nhiều người không có nhu cầu, lượt hiển thị tăng vọt nhưng CTR giảm. Hãy so CTR theo từng luồng: nếu CTR chỉ giảm ở đúng luồng vừa có lượt hiển thị tăng mạnh, còn các luồng khác ổn định, đó là traffic loãng, và sửa trang sản phẩm sẽ không giải quyết được gì.

### Nguyên nhân CTR thấp

Những gì người xem thấy trên thẻ trước khi nhấp là ảnh bìa, tiêu đề, giá, nhãn khuyến mãi, số đã bán và điểm đánh giá. Bài "Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 4" xếp hình ảnh chính, tiêu đề và mô tả vào nhóm **Hiển thị**, nhóm tác động mạnh nhất lên quyết định nhấp.

- **Ảnh bìa**: sản phẩm nhỏ trong khung, nền rối, bị chữ hay nhãn dán che, hoặc ảnh không cho thấy đúng quy cách đang bán. Chính sách của TikTok yêu cầu hình ảnh chính hiển thị mặt trước của sản phẩm thực tế, nền đồng nhất (nên là màu trắng), sản phẩm chiếm ít nhất 60 % khung hình.
- **Tiêu đề**: không nói rõ sản phẩm là gì, hoặc phần quan trọng nằm ở cuối và bị cắt trên thẻ nhỏ.
- **Giá hiển thị**: công cụ Chẩn đoán giá cho biết sản phẩm đang ở trạng thái "Giá không cạnh tranh", "Giá cạnh tranh" hay "Giá tốt nhất" so với sản phẩm tương tự.

### Việc nên làm khi CTR thấp

Sửa một thành phần mỗi lần, bắt đầu từ ảnh bìa nếu nó vi phạm yêu cầu hoặc khó nhìn ở kích thước điện thoại, rồi đến tiêu đề. Bài [Tối ưu thẻ sản phẩm TikTok Shop từ A–Z](/blog/toi-uu-the-san-pham-tiktok-shop) trình bày chi tiết quy định và cách làm cho từng thành phần.

## Bước 3: Có lượt nhấp nhưng CTOR thấp

Phễu có hình dạng: khá nhiều lượt nhấp, rất ít đơn hàng SKU. Đây là trường hợp đáng tiếc nhất, vì khách đã quan tâm đủ để vào trang sản phẩm, rồi rời đi.

### Tách làm hai nửa: trước giỏ và sau giỏ

Chỉ số giúp tách CTOR là **Tỷ lệ thêm vào giỏ hàng**, mà TikTok định nghĩa lại năm 2026 là số lượt nhấp nút Thêm vào giỏ hàng chia cho tổng số lượt nhấp vào sản phẩm.

- **Tỷ lệ thêm vào giỏ hàng thấp (trước giỏ)**: khách vào trang nhưng không thêm vào giỏ. Họ chưa bị thuyết phục. Nghi phạm là bộ ảnh chi tiết, mô tả, đánh giá và giá.
- **Tỷ lệ thêm vào giỏ hàng ổn nhưng ít đơn (sau giỏ)**: khách đã thêm vào giỏ nhưng không thanh toán. Nghi phạm là phí vận chuyển, voucher hết hạn, hoặc khách đang chờ một đợt ưu đãi họ đoán sẽ đến.

Lưu ý: người xem video hay LIVE có thể đặt mua ngay mà không qua giỏ hàng, nên cách tách này chính xác nhất ở luồng thẻ sản phẩm và Tab cửa hàng.

{{hinh:truoc-gio-sau-gio}}

### Nguyên nhân thường gặp trước giỏ

Bài chẩn đoán số 4 của TikTok xếp các yếu tố tác động lên quyết định mua vào hai nhóm: **Lợi ích** (giá cạnh tranh, chiết khấu, voucher, ưu đãi chớp nhoáng, mua thêm tiết kiệm nhiều hơn, thanh toán khi giao hàng) và **Sự tin cậy** (thương hiệu, đánh giá, tỷ lệ trả hàng).

- **Mô tả thiếu thông tin**: không có kích thước, thành phần, cách dùng, trong hộp có gì. Chính sách của TikTok yêu cầu mô tả nêu đặc điểm chính và dài không dưới 30 từ.
- **Bộ ảnh phụ không trả lời câu hỏi của khách**: không có ảnh kích thước thật, ảnh chi tiết, ảnh theo từng biến thể.
- **Đánh giá thấp hoặc ít đánh giá**: khách không dám mua.
- **Giá cao hơn hẳn sản phẩm tương tự** mà trang không giải thích được vì sao.

### Nguyên nhân thường gặp sau giỏ

- Phí vận chuyển hiện ra ở bước thanh toán cao hơn khách nghĩ.
- Voucher khách nhìn thấy trước đó đã hết hạn hoặc không áp dụng cho biến thể họ chọn.
- Shop chạy ưu đãi chớp nhoáng gần như liên tục, nên khách quen chờ đợt tiếp theo thay vì mua ở giá thường.

### Việc nên làm khi CTOR thấp

Mở hộp tin nhắn và phần đánh giá, liệt kê 5 câu hỏi khách hay hỏi nhất, rồi trả lời ngay trong mô tả và bộ ảnh. Nếu sản phẩm có điểm đánh giá thấp, hãy xử lý nguyên nhân (chất lượng, mô tả sai lệch, đóng gói) trước khi đẩy thêm khách vào trang; thêm khách cho một sản phẩm bị đánh giá kém chỉ làm tăng số người thất vọng.

## Quảng cáo TikTok Shop không ra đơn: đọc phễu trước khi tăng ngân sách

Nhiều người bán gặp tình huống: đã chạy quảng cáo, có lượt xem, có lượt nhấp, nhưng vẫn không ra đơn. Phản xạ thường gặp là tăng ngân sách, đổi nhóm đối tượng, hoặc đổi sang hình thức quảng cáo khác. Phần này không hướng dẫn cách chạy quảng cáo, chỉ nói về điều cần kiểm tra trên phễu trước khi quyết định chi thêm.

### Quảng cáo mua thêm người xem, không sửa trang sản phẩm

Về bản chất, quảng cáo đưa sản phẩm đến thêm người xem, tức tác động lên bước đầu của phễu. Nó không thay đổi những gì người xem thấy khi vào trang sản phẩm: ảnh, mô tả, giá, đánh giá vẫn như cũ. Nếu CTOR của trang đang thấp, mỗi lượt nhấp mua thêm vẫn chuyển đổi kém như lượt nhấp tự nhiên, và thường kém hơn, vì traffic mua thêm có tỷ lệ người ít quan tâm cao hơn.

### Ví dụ giả định

Một sản phẩm có (số giả định): 10.000 lượt hiển thị mỗi tuần, CTR 1 %, tức 100 lượt nhấp, và CTOR 1 %, tức 1 đơn hàng SKU.

- **Phương án A, gấp đôi traffic**: 20.000 lượt hiển thị. Nếu CTR và CTOR giữ nguyên, được 2 đơn. Thực tế thường ít hơn, vì CTR của phần traffic thêm có thể thấp hơn.
- **Phương án B, sửa trang sản phẩm**: giữ 10.000 lượt hiển thị, nhưng CTOR tăng từ 1 % lên 3 % nhờ bổ sung mô tả, ảnh kích thước và trả lời câu hỏi hay gặp. Được 3 đơn mà không mua thêm traffic.

Nếu sau đó bạn mới tăng traffic, mỗi lượt hiển thị mua thêm sinh ra nhiều đơn gấp ba so với trước khi sửa. Thứ tự đúng thường là sửa phễu trước, rồi mới mua thêm traffic.

{{hinh:quang-cao-ab}}

### Năm câu hỏi trước khi tăng ngân sách quảng cáo

1. **Sản phẩm có đang Trực tuyến và còn hàng ở các biến thể chính không?**
2. **CTOR ở luồng thẻ sản phẩm có đủ dữ liệu và có thấp hơn hẳn các sản phẩm khác của shop không?** Nếu có, sửa trang trước.
3. **Tỷ lệ thêm vào giỏ hàng có thấp không?** Nếu có, vấn đề nằm ở trang sản phẩm. Nếu không, xem phí vận chuyển và voucher.
4. **CTR của phần traffic mới có thấp hơn hẳn traffic cũ không?** Nếu có, người xem mới có thể không phải khách có nhu cầu.
5. **Bạn có đo được kết quả không?** Một thay đổi, một ngày bắt đầu, một cửa sổ đo. Nếu đổi quảng cáo, giá và ảnh cùng lúc, bạn sẽ không biết điều gì có tác dụng.

## Luồng nội dung: video, LIVE và Liên kết không ra đơn

Ở luồng video, LIVE và Liên kết, chỉ số chính là Lượt hiển thị sản phẩm và GMV, còn CTOR chỉ để tham khảo, vì kết quả phụ thuộc nhiều vào nội dung và người bán hàng trong video hay buổi LIVE.

- **Video có lượt xem nhưng ít lượt nhấp vào sản phẩm**: người xem thích nội dung nhưng không thấy lý do để xem sản phẩm. Kiểm tra xem video có cho thấy rõ sản phẩm, công dụng và giá không, và sản phẩm có được gắn đúng không.
- **LIVE có người xem nhưng không ra đơn**: xem lại thời điểm giới thiệu sản phẩm, ưu đãi trong phiên, và sản phẩm được ghim có còn hàng không.
- **Liên kết không ra đơn**: kết quả phụ thuộc chủ yếu vào nhà sáng tạo và khán giả của họ. Một nhà sáng tạo có khán giả không khớp với sản phẩm sẽ tạo lượt hiển thị nhưng ít đơn.

Dù luồng nội dung có vấn đề, trang sản phẩm vẫn là điểm đến cuối cùng của mọi lượt nhấp. Nếu CTOR ở luồng thẻ sản phẩm cũng thấp, hãy sửa trang trước khi đầu tư thêm vào nội dung.

{{hinh:luong-noi-dung}}

## Danh sách kiểm tra khi TikTok Shop không ra đơn

Dùng bảng này cho từng sản phẩm quan trọng, theo thứ tự từ trên xuống:

| Thứ tự | Kiểm tra | Nếu có vấn đề |
|---|---|---|
| 1 | Sản phẩm ở trạng thái Trực tuyến | Đọc lý do tạm ngưng, sửa và gửi lại |
| 2 | Các biến thể chính còn hàng | Bổ sung tồn kho cho đúng SKU |
| 3 | Vận hành: giao đúng hạn, xử lý đơn nhanh | Sửa vận hành trước mọi việc khác |
| 4 | Lượt hiển thị đủ ngưỡng ở luồng thẻ sản phẩm | Tiêu đề, thuộc tính, nội dung |
| 5 | CTR so với chính nó và sản phẩm khác | Ảnh bìa, tiêu đề, giá hiển thị |
| 6 | CTR giảm chỉ ở luồng vừa tăng traffic | Traffic loãng, chưa sửa trang |
| 7 | Tỷ lệ thêm vào giỏ hàng | Mô tả, bộ ảnh, đánh giá, giá |
| 8 | Đơn trên mỗi lượt thêm vào giỏ | Phí vận chuyển, voucher, lịch ưu đãi |
| 9 | Đủ dữ liệu ở mỗi kỳ | Ghi "chưa đủ dữ liệu", đo tiếp |
| 10 | Một thay đổi có ngày bắt đầu | Đo sau 7 và 14 ngày |

## Những hiểu lầm thường gặp

### "Shop mới bị bóp traffic"

Lượt hiển thị thấp ở shop mới thường có lời giải cụ thể hơn: tiêu đề chưa đúng từ khóa, thẻ chưa đạt ngưỡng vào nhóm đề xuất, chưa có nội dung. Hãy kiểm tra các yếu tố bạn kiểm soát được trước khi kết luận về nền tảng.

### "Cứ giảm giá là ra đơn"

Giảm giá tác động lên CTR (giá hiển thị trên thẻ) và CTOR. Nó không giúp sản phẩm được nhìn thấy nhiều hơn nếu sản phẩm chưa xuất hiện trong tìm kiếm, và nó lấy đi biên lợi nhuận của mọi đơn, kể cả đơn mà khách vẫn sẽ mua ở giá cũ.

### "CTOR toàn shop ổn nên trang sản phẩm ổn"

CTOR toàn shop là trung bình của năm luồng có hành vi khác nhau. Một buổi LIVE tốt có thể che việc CTOR ở luồng thẻ sản phẩm đang tụt. Bài [Các chỉ số TikTok Shop: Lượt hiển thị, CTR, CTOR, AOV và cách đọc đúng](/blog/chi-so-tiktok-shop-ctr-ctor-aov) có một ví dụ chi tiết về hiện tượng này.

### "Ba ngày không có đơn là có vấn đề"

Với sản phẩm vài đơn mỗi tuần, ba ngày không có đơn có thể chỉ là ngẫu nhiên. Hãy nhìn cửa sổ 14 đến 30 ngày và kiểm tra ngưỡng dữ liệu trước khi kết luận.

## Tự theo dõi phễu mỗi tuần

Phần chẩn đoán trong bài này làm được bằng một bảng tính và khoảng 20 phút mỗi tuần, với số liệu có sẵn trong Trung tâm nhà bán hàng. Điều quan trọng là làm đều, cùng một cách, để tuần này so được với tuần trước.

1. **Chọn sản phẩm.** Lấy 5 đến 10 sản phẩm mang lại nhiều GMV nhất, cộng các sản phẩm mới đăng chưa có đơn.
2. **Chép số của 7 ngày vừa qua** từ trang Lưu lượng truy cập sản phẩm, khía cạnh thẻ sản phẩm của người bán: Lượt hiển thị sản phẩm, Lượt nhấp vào sản phẩm, Tỷ lệ thêm vào giỏ hàng, Đơn hàng SKU.
3. **Tự tính CTR và CTOR từ tổng cả tuần**, không lấy trung bình các tỷ lệ theo ngày.
4. **Ghi cột "đủ dữ liệu"** theo ngưỡng bạn đã đặt ở phần đọc phễu.
5. **Ghi cột "thay đổi"**: ngày bạn sửa ảnh, tiêu đề, mô tả, giá hay khuyến mãi của sản phẩm đó.

Ví dụ giả định cho một sản phẩm qua hai tuần:

| Tuần | Lượt hiển thị | Lượt nhấp | CTR | Đơn hàng SKU | CTOR | Đủ dữ liệu | Thay đổi |
|---|---|---|---|---|---|---|---|
| 1 | 4.200 | 168 | 4,0 % | 5 | 3,0 % | Có | Không |
| 2 | 4.410 | 150 | 3,4 % | 2 | 1,3 % | Có | Không |

Đọc bảng này theo thứ tự của bài: Lượt hiển thị vẫn vậy, CTR giảm nhẹ, CTOR giảm mạnh. Bước cần xem là sau cú nhấp, và Tỷ lệ thêm vào giỏ hàng cho biết khách rời đi trước giỏ hay sau giỏ. Mỗi tuần chỉ khoanh một sản phẩm và một bước yếu nhất, sửa một thứ, ghi ngày bắt đầu, rồi đọc lại sau 7 và 14 ngày.

Muốn ước tính một bước yếu đang làm mất bao nhiêu GMV, hãy nhập số của sản phẩm vào [công cụ tính GMV miễn phí](/cong-cu/tinh-gmv): công cụ cho thấy phễu từng bước và GMV thay đổi ra sao khi một chỉ số tăng. Bài [GMV là gì? Cách tính và cách tăng GMV TikTok Shop](/blog/gmv-la-gi-tiktok-shop) giải thích đường đi từ GMV đến tiền về, còn bài [Doanh thu TikTok Shop giảm](/blog/doanh-thu-tiktok-shop-giam) đi qua trường hợp shop đang có đơn rồi tụt.

## Tóm tắt

- "Không ra đơn" là triệu chứng. Nguyên nhân nằm ở một trong ba bước: không ai thấy (Lượt hiển thị), thấy mà không nhấp (CTR), nhấp mà không mua (CTOR).
- Trước khi đọc phễu, kiểm tra trạng thái sản phẩm, tồn kho từng biến thể và vận hành shop.
- Đọc luồng thẻ sản phẩm trước, trên cửa sổ 14 đến 30 ngày, và chỉ kết luận khi đủ dữ liệu.
- CTOR thấp thì tách trước giỏ và sau giỏ bằng Tỷ lệ thêm vào giỏ hàng.
- Quảng cáo không ra đơn: kiểm tra CTR và CTOR trước khi tăng ngân sách; sửa phễu trước, mua traffic sau.

Nếu sản phẩm có người nhấp nhưng ít người mua, bài [Khách xem nhưng không mua](/blog/khach-xem-nhung-khong-mua-tiktok-shop) đi sâu vào phần sau cú nhấp; nếu sản phẩm gần như không ai thấy, xem bài [Sản phẩm TikTok Shop không có lượt hiển thị](/blog/san-pham-tiktok-shop-khong-co-luot-hien-thi).
`;
