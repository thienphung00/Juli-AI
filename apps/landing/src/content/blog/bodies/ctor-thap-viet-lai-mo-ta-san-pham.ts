/**
 * Conversion problem post C8 (D59 additions 5, P49-A2): "CTOR thấp: Juli đề xuất mô tả sản phẩm".
 * Main keyword "viết lại mô tả sản phẩm tiktok shop khi ctor thấp" (long tail; "ctor thấp tiktok
 * shop" stays an H2 / FAQ term of the reach post `khach-xem-nhung-khong-mua-tiktok-shop`, and "mô tả
 * sản phẩm tiktok shop" belongs to `mo-ta-san-pham-tiktok-shop`). This post covers only Juli's CTOR
 * flow. Facts: D22.2 (CTOR = SKU orders ÷ clicks; CTOR-stage GMV = clicks × Δ × AOV),
 * `/san-pham/phan-tich-shop` (before / after cart split, Khuyến mãi "giảm thật", voucher threshold
 * share), `/san-pham/de-xuat-va-thuc-thi` (description drafted after approval, checked, confirmed;
 * price never written; promotions on Seller Center within the margin rule and only with a cost),
 * D13 / D24.5 (price recommendation only, promotion API later), D22 (competitor price optional
 * third-party data), `/san-pham/do-luong-gmv` (CTOR measured on all channels, day 7 / 14 labels,
 * Juli asks, never reverts by itself). No AOV lever, no simulation, no control groups. Worked
 * numbers are hypothetical and say so; screenshot numbers are the sample shop's.
 */
export const body = `
CTOR thấp nghĩa là khách đã bấm vào sản phẩm mà không đặt hàng. Juli tách tiếp thành hai trường hợp: khách rời đi trước khi thêm vào giỏ, hay đã thêm vào giỏ rồi không đặt. Khi vấn đề nằm trước giỏ hàng và trang sản phẩm chưa trả lời được câu hỏi của khách, Juli đề xuất viết lại mô tả: Juli soạn bản mới sau khi bạn duyệt, bạn đọc, sửa và xác nhận, rồi Juli mới ghi lên TikTok Shop. Khi vấn đề nằm sau giỏ hàng, như phí vận chuyển hay một đợt giảm giá quá nông, Juli hướng dẫn và bạn làm trên Seller Center.

Bài này đi qua một thẻ CTOR từ lúc Juli phát hiện đến lúc đo xong ở ngày 14. Nếu bạn muốn tự chẩn đoán vì sao khách xem mà không mua bằng số liệu Seller Center, đọc bài [khách xem nhưng không mua](/blog/khach-xem-nhung-khong-mua-tiktok-shop); cách tự viết mô tả theo chính sách của TikTok nằm ở bài [mô tả sản phẩm TikTok Shop](/blog/mo-ta-san-pham-tiktok-shop). Ảnh màn hình dưới đây lấy từ "Cửa hàng Mẫu Hoa Mai", shop minh hoạ của Juli.

## CTOR thấp: khách bấm vào mà không đặt

Theo bài "Lưu lượng truy cập sản phẩm" của Học viện TikTok Shop, CTOR là tỷ lệ từ nhấp đến đặt hàng:

> CTOR = Đơn hàng SKU ÷ Lượt nhấp vào sản phẩm

Ở bước này, khách đã thấy sản phẩm và đủ quan tâm để mở trang. Họ rời đi vì thứ gặp sau đó: thông tin trên trang, hình ảnh, đánh giá, giá, hoặc phí và ưu đãi lúc thanh toán. Đổi ảnh bìa hay tiêu đề không giúp gì ở đây, vì người cần thuyết phục đã ở trong trang rồi.

{{hinh:ctor-mo-ta-o-va-bang}}

Trong trang Phân tích của Juli, CTOR là một ô trong phễu của từng luồng, với số đồng mỗi ngày mà thay đổi của nó kéo GMV xuống. Juli đánh dấu "Juli gợi ý" khi CTOR là chỉ số lấy đi nhiều GMV nhất của luồng, và bảng bên dưới chia con số đó cho từng sản phẩm. Ví dụ của shop mẫu: CTOR của Thẻ sản phẩm giảm, và ba sản phẩm đầu bảng giảm rõ nhất. Cách đọc bảng này ở bài [tìm sản phẩm kéo GMV xuống](/blog/tim-san-pham-keo-gmv-xuong-tiktok-shop).

Một mức giảm chỉ được tính khi nó lớn hơn mức dao động bình thường của chính CTOR trên luồng đó, và khi có đủ dữ liệu, khoảng 30 đơn trở lên trong khoảng thời gian xét.

## Trước giỏ hàng hay sau giỏ hàng

Khi CTOR là chỉ số nghẽn, Juli nhìn thêm tỷ lệ thêm vào giỏ hàng:

- **Tỷ lệ thêm vào giỏ giảm**: vấn đề nằm trước giỏ hàng. Trang sản phẩm chưa thuyết phục: mô tả thiếu thông tin, hình ảnh chưa rõ, đánh giá ít, hoặc giá chưa hợp.
- **Khách vẫn thêm vào giỏ nhưng ít đặt hơn**: vấn đề nằm sau giỏ hàng. Phí vận chuyển hiện ra ở bước cuối, voucher không đạt được ngưỡng, hoặc khách đang chờ một đợt flash sale.

Hai trường hợp dẫn đến hai loại thẻ rất khác nhau. Viết lại mô tả cho một sản phẩm mà khách bỏ ở bước thanh toán là sửa sai chỗ; giảm giá cho một sản phẩm mà khách không hiểu dùng thế nào là bỏ tiền ra mà vấn đề vẫn còn. Cách Juli đọc từng luồng được giải thích ở trang [Phân tích shop](/san-pham/phan-tich-shop).

## Khi vấn đề nằm trước giỏ hàng: thẻ mô tả

{{hinh:ctor-mo-ta-the}}

Thẻ trên nhắm CTOR của một mặt nạ đất sét, từ 5,4 % lên mục tiêu 5,9 %. Lý do ngắn là "Mô tả quá ngắn"; lý do đầy đủ cho biết mô tả hiện chỉ có 180 ký tự trong một đoạn, và TikTok cũng báo "Mô tả quá ngắn". Thay đổi đề xuất là Mô tả. Dưới cùng là cách tính GMV dự kiến.

Lý do của một thẻ mô tả đến từ hai nguồn. Thứ nhất là chẩn đoán mà TikTok trả về cho sản phẩm, hiện trong lý do đầy đủ đúng như TikTok ghi. Thứ hai là những gì Juli kiểm tra được trên chính trang: mô tả quá ngắn, chỉ một đoạn, không có hình minh hoạ. Chính sách của TikTok yêu cầu mô tả không dưới 30 từ, nhưng một mô tả đủ dài vẫn có thể chưa trả lời câu khách hay hỏi.

Có một nguồn thứ ba nhưng không phải lúc nào cũng có: khi có dữ liệu giá của các sản phẩm tương tự trên thị trường, lý do có thể nhắc đến chênh lệch giá. Đây là dữ liệu bên ngoài và tuỳ chọn, nên không có nó thì thẻ vẫn dựa trên hai nguồn đầu.

## Juli soạn mô tả thế nào, bạn xác nhận gì

Juli chưa gọi mô hình AI nào khi tạo thẻ: chọn sản phẩm, chọn thay đổi và tính con số đều do quy tắc và phép tính. Chỉ sau khi bạn bấm **Duyệt**, Juli tạo một lượt chạy:

1. Đọc chẩn đoán của TikTok và thông tin sản phẩm, kể cả mô tả hiện tại.
2. Phân tích từ khoá liên quan đến sản phẩm.
3. Soạn mô tả mới theo giọng văn bạn đặt trong Quy tắc, chia đoạn rõ ràng để khách đọc nhanh trên điện thoại.
4. Kiểm tra bản soạn: độ dài, danh sách từ không được dùng, và đối chiếu với thông tin của chính sản phẩm, để mô tả không thêm công dụng hay thành phần sản phẩm không có.
5. Dừng ở bước **Xác nhận một lần**: bạn thấy mô tả cũ và mô tả mới, sửa được trước khi áp dụng, rồi bấm Xác nhận hoặc Không thực hiện.

Chỉ khi bạn xác nhận, Juli mới ghi mô tả mới lên TikTok Shop qua Open API và lưu lại mô tả cũ. Quyền ghi được cấp cho đúng một sản phẩm và một loại thao tác, có thời hạn và chỉ dùng một lần. Sau khi ghi, TikTok duyệt lại trang sản phẩm, và Juli đặt lịch đo.

Bước kiểm tra giúp loại những lỗi dễ thấy, nhưng bạn vẫn là người hiểu sản phẩm nhất. Ở bước xác nhận, đọc kỹ những câu nói về thành phần, công dụng, kích thước và cách dùng. Một mô tả sai còn tệ hơn mô tả ngắn: khách nhận hàng thấy khác mô tả thì trả hàng.

## Khi vấn đề nằm sau giỏ hàng: bạn làm trên Seller Center

Juli không đổi giá sản phẩm và không tạo khuyến mãi. Với giảm giá sản phẩm, flash sale hay giảm phí vận chuyển, thẻ ghi "Bạn thực hiện trên Seller Center". Sau khi duyệt, Juli đưa hướng dẫn từng bước với mức giảm cụ thể. Bạn tạo khuyến mãi, bấm "Đã áp dụng", Juli kiểm tra lại trên TikTok bằng quyền chỉ đọc và bắt đầu đo.

Một đề xuất giảm giá chỉ xuất hiện khi Juli biết giá vốn của sản phẩm, và luôn nằm trong biên lợi nhuận bạn đặt trong Quy tắc. Nếu chưa nhập giá vốn, Juli không đề xuất giảm giá cho sản phẩm đó.

{{hinh:ctor-mo-ta-khuyen-mai}}

Trước khi nghĩ đến một đợt giảm mới, xem khối Khuyến mãi trong trang Phân tích. Juli tính **giảm thật**: giá khuyến mãi so với giá đang bán ngay trước đó, không so với giá niêm yết. Trong ví dụ của shop mẫu, Son môi số 12 có giảm giá sản phẩm chỉ 2 % so với giá đang bán, và Juli đánh dấu "quá nông": một mức giảm như vậy gần như không tạo khác biệt cho người mua. Khối này cũng cho biết tỷ lệ đơn đạt ngưỡng voucher, để bạn thấy voucher đang chạy có thực sự được dùng hay không.

## GMV dự kiến của thẻ CTOR

Với thẻ nhắm CTOR, GMV có thể lấy lại mỗi ngày theo đúng phép tách GMV của TikTok là:

> Lượt nhấp × (CTOR mục tiêu − CTOR hiện tại) × AOV

Một ví dụ giả định: sản phẩm có 300 lượt nhấp mỗi ngày, CTOR từ 4,0 % lên mục tiêu 4,6 %, AOV 180.000đ.

- Đơn thêm mỗi ngày: 300 × 0,6 % = 1,8.
- GMV thêm mỗi ngày: 1,8 × 180.000đ = 324.000đ.
- Quy ra 30 ngày: khoảng 9,7 triệu đồng.

Số liệu trên thẻ là trung bình 30 ngày. Mục tiêu phải cao hơn mức dao động bình thường của CTOR, để còn đo được, nhưng không vượt quá vài lần mức đó, để không hứa quá tay. Với sản phẩm có số liệu dao động mạnh, mục tiêu hiện dưới dạng một khoảng và độ tin cậy là Thấp. Thẻ ghi rõ GMV dự kiến là ước tính theo quy tắc, không phải lời hứa; kết quả thật được đo sau khi áp dụng.

## Đo ở ngày 7 và ngày 14, trên mọi kênh

Trước khi áp dụng, Juli chụp lại mốc so sánh: chuỗi số liệu 14 ngày, giá, khuyến mãi đang chạy và nội dung trang sản phẩm. Mọi con số khi đo là trung bình mỗi ngày, so với mốc này.

TikTok không tách đơn hàng SKU theo từng luồng cho từng sản phẩm, nên CTOR của một thay đổi được đo trên tất cả các kênh, kể cả khi vấn đề được phát hiện trên luồng Thẻ sản phẩm. Lượt hiển thị, CTR và AOV là các chỉ số giữ ổn định, mỗi chỉ số có một khoảng được phép dao động mà bạn chỉnh được trong Quy tắc.

- **Ngày 7**: Juli so 7 ngày sau thay đổi với 14 ngày trước. CTOR ghi **Đang lên** nếu đang tiến về mục tiêu, hoặc **Chưa rõ**. Kết quả này là sơ bộ.
- **Ngày 14**: kết quả chốt, một trong bốn nhãn **Đạt**, **Đạt · chưa chắc chắn**, **Một phần** hoặc **Không đạt**, đặt cạnh GMV dự kiến ban đầu.

Nếu trong thời gian đo bạn mở hay tắt một khuyến mãi, đổi giá hay tự sửa mô tả, kết quả ghi "Bị ảnh hưởng bởi thay đổi khác", kèm thay đổi đó và ngày xảy ra. Vì vậy, nếu vừa duyệt một thẻ mô tả, đừng mở thêm flash sale cho cùng sản phẩm trong 14 ngày đo, nếu bạn muốn biết mô tả có tác dụng hay không. Cách đo chi tiết ở trang [Đo lường GMV](/san-pham/do-luong-gmv).

## Khi nào nên hoàn tác mô tả

Mô tả cũ luôn được lưu. Nút **Hoàn tác** có ở lượt chạy đã áp dụng và trong phần Đo lường. Khi bấm, bạn chọn một lý do, Juli tạo một lượt chạy khôi phục mô tả cũ, và lượt đó cũng dừng ở bước xác nhận trước khi ghi. Nếu mô tả đã bị sửa bên ngoài Juli sau lần thay đổi, Juli không ghi đè và báo cho bạn.

Ba tình huống nên cân nhắc hoàn tác:

1. **Nội dung sai thông tin sản phẩm.** Hoàn tác ngay, không cần chờ ngày 7.
2. **Ngày 7, một chỉ số giữ ổn định ra ngoài ngưỡng.** Juli hỏi bạn có muốn hoàn tác không, kèm số liệu cụ thể. Bạn chọn Hoàn tác hoặc Giữ thay đổi; nếu giữ, Juli đo tiếp đến ngày 14 và ghi chú lại.
3. **Khách phản hồi không tốt** về cách viết, hoặc mô tả không hợp giọng thương hiệu.

Ngoài các trường hợp đó, một kết quả "Chưa rõ" ở ngày 7 không phải lý do để hoàn tác: đợi đến ngày 14. Juli không bao giờ tự hoàn tác. Lý do bạn chọn làm loại thay đổi đó được ưu tiên thấp hơn cho shop trong thời gian sau, nhạt dần trong khoảng 60 ngày.

## Chuẩn bị trước khi duyệt thẻ CTOR đầu tiên

Ba việc trong Quy tắc giúp thẻ CTOR hợp với shop của bạn hơn:

- **Giọng văn**: cách shop xưng hô và nói chuyện với khách. Mô tả Juli soạn theo giọng này.
- **Từ không được dùng**: những từ hay cam kết bạn không muốn xuất hiện trên trang sản phẩm.
- **Giá vốn hoặc biên lợi nhuận tối thiểu**: cần cho mọi đề xuất giảm giá. Không có, Juli chỉ đề xuất mô tả.

Toàn bộ các loại thẻ, phần Juli làm và phần bạn làm được mô tả ở trang [Đề xuất và thực thi](/san-pham/de-xuat-va-thuc-thi). Khi CTOR ổn mà ít người bấm vào sản phẩm, vấn đề nằm trước cú nhấp: đọc bài [CTR Thẻ sản phẩm thấp](/blog/ctr-the-san-pham-thap-doi-tieu-de-anh-bia). Định nghĩa các chỉ số có ở bài [các chỉ số TikTok Shop](/blog/chi-so-tiktok-shop-ctr-ctor-aov).

Muốn thấy thẻ CTOR cho sản phẩm của chính shop mình, kết nối shop ở trang [Kết nối TikTok Shop](/ket-noi/tiktok-shop) hoặc xem [Tổng quan sản phẩm](/san-pham) trước; tài khoản mới được [dùng thử miễn phí 3 tháng](/dang-ky).
`;
