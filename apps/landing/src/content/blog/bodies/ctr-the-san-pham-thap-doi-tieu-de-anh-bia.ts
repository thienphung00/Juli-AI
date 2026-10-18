/**
 * Conversion problem post C7 (D59 additions 5, P49-A2): "CTR Thẻ sản phẩm thấp". Main keyword
 * "ctr thẻ sản phẩm tiktok shop thấp" (long tail; "thẻ sản phẩm tiktok shop" has autocomplete).
 * The reach posts `dat-ten-san-pham-tiktok-shop` and `anh-bia-san-pham-tiktok-shop` own naming
 * rules and image sizes; this post covers only Juli's flow for a CTR card and its measurement.
 * Facts: D22.2 (CTR = clicks ÷ impressions; CTR-stage GMV includes CTOR), D13 (title executed;
 * cover uploaded only with the seller's photo; price off), D24.1–3 / D24.16 (rules choose, the
 * model writes only after approval, output checked for length, tone, banned words), D29.4 / the
 * product page (one change per product at a time), D32 (measured on Thẻ sản phẩm), D14 + D29.8
 * (day 7 Đang lên / Chưa rõ, Juli asks, never reverts by itself; day 14 labels as on
 * `/san-pham/do-luong-gmv`), `/san-pham/de-xuat-va-thuc-thi` (cover flow, undo guard). The
 * cover-upload run's request is valid 3 days (sample run, D47 external-wait lapse). No simulation
 * or control groups (D34 / D35 not live). Worked numbers are hypothetical and say so.
 */
export const body = `
CTR Thẻ sản phẩm thấp nghĩa là người mua đã thấy sản phẩm của bạn trong kết quả tìm kiếm hay trang gợi ý, nhưng lướt qua mà không bấm. Hai thứ người mua thấy đầu tiên trên Thẻ sản phẩm là ảnh bìa và tiêu đề, nên đó là hai thay đổi Juli đề xuất khi CTR của một sản phẩm giảm. Với tiêu đề, Juli soạn bản mới và chỉ ghi lên TikTok Shop sau khi bạn xác nhận. Với ảnh bìa, Juli phân tích ảnh hiện tại và nói cần đổi gì, còn ảnh mới là ảnh của bạn: bạn tải lên, xác nhận, rồi Juli thay.

Bài này đi qua một thẻ CTR từ đầu đến cuối: khi nào nó xuất hiện, Juli làm phần nào, bạn làm phần nào, và kết quả được đo ra sao. Cách tự viết tiêu đề theo chính sách của TikTok nằm ở bài [đặt tên sản phẩm TikTok Shop](/blog/dat-ten-san-pham-tiktok-shop); kích thước và yêu cầu ảnh nằm ở bài [ảnh bìa sản phẩm TikTok Shop](/blog/anh-bia-san-pham-tiktok-shop). Ảnh màn hình dưới đây lấy từ "Cửa hàng Mẫu Hoa Mai", shop minh hoạ của Juli.

## CTR Thẻ sản phẩm là gì, và vì sao đọc riêng luồng này

Theo bài "Lưu lượng truy cập sản phẩm" của Học viện TikTok Shop, CTR là lượt nhấp vào sản phẩm chia cho lượt hiển thị sản phẩm. TikTok ghi nhận chỉ số này theo từng luồng: Thẻ sản phẩm, Tab cửa hàng, Video, LIVE và Liên kết.

CTR của Thẻ sản phẩm khác CTR của một video. Trong video, người xem bấm vào giỏ hàng vì nội dung của video; trên Thẻ sản phẩm, họ bấm vì ảnh bìa, tiêu đề, giá và số đã bán hiện trên tấm thẻ nhỏ đó. Nếu gộp chung các luồng, một video đang lên có thể che mất việc Thẻ sản phẩm đang giảm.

{{hinh:ctr-the-pheu}}

Trong trang Phân tích, mỗi luồng có phễu bốn ô, và dưới mỗi ô là số đồng mỗi ngày mà thay đổi của chỉ số đó kéo GMV lên hoặc xuống. Ô CTR là nơi bắt đầu. Cách đọc cả trang được giải thích ở trang [Phân tích shop](/san-pham/phan-tich-shop), và cách tìm sản phẩm gây ra con số trên ô ở bài [tìm sản phẩm kéo GMV xuống](/blog/tim-san-pham-keo-gmv-xuong-tiktok-shop).

## Khi nào Juli mở một thẻ CTR

Một thẻ bắt đầu từ dữ liệu của chính sản phẩm, không từ danh sách mẹo chung. Juli mở thẻ CTR khi:

- CTR của sản phẩm trên luồng đó giảm nhiều hơn mức dao động bình thường của chính nó.
- Có đủ dữ liệu: khoảng 30 lượt nhấp trở lên trong khoảng thời gian xét. Juli thử 14, 30 rồi 60 ngày; không đủ thì sản phẩm được ghi là ít dữ liệu.
- Thay đổi đó hợp lệ với TikTok Shop và với Quy tắc của bạn.
- Sản phẩm không có một thay đổi khác đang được đo.
- Cùng thay đổi chưa bị từ chối hay hoàn tác trong 7 ngày qua.

Juli chọn tiêu đề hay ảnh bìa theo những gì đọc được về trang sản phẩm: chẩn đoán mà TikTok trả về cho sản phẩm (ví dụ ảnh chính chất lượng thấp), và những gì kiểm tra được trên chính tiêu đề và ảnh (thiếu từ khoá khách hay tìm, sản phẩm chiếm quá ít khung ảnh). Việc chọn sản phẩm, chọn thay đổi và tính con số do quy tắc và phép tính đảm nhận; mô hình AI chỉ được gọi sau khi bạn duyệt, để soạn nội dung, và không bao giờ tạo ra con số trên thẻ.

## Thẻ tiêu đề: Juli soạn, bạn xác nhận

{{hinh:ctr-the-tieu-de}}

Thẻ trên nhắm CTR trên luồng Thẻ sản phẩm của một kem dưỡng ẩm, từ 3,7 % lên 3,9 %. Lý do đầy đủ nói CTR đã giảm so với 30 ngày trước và tiêu đề chưa có hai từ khoá khách hay tìm. Phần nội dung cho bạn thấy trước tiêu đề cũ (gạch ngang) và tiêu đề đề xuất.

Sau khi bạn bấm **Duyệt**, Juli tạo một lượt chạy:

1. Đọc chẩn đoán của TikTok và thông tin sản phẩm.
2. Phân tích từ khoá liên quan.
3. Soạn tiêu đề mới theo giọng văn và danh sách từ không được dùng trong Quy tắc của bạn.
4. Kiểm tra bản soạn: độ dài, từ không được dùng, và đối chiếu với thông tin của chính sản phẩm, để tiêu đề không nói điều sản phẩm không có.
5. Dừng ở bước **Xác nhận một lần**: bạn xem tiêu đề cũ và mới, sửa nếu muốn, rồi bấm Xác nhận hoặc Không thực hiện.

Chỉ khi bạn xác nhận, Juli mới ghi tiêu đề mới lên TikTok Shop qua Open API và lưu tiêu đề cũ. Quyền ghi được cấp cho đúng một sản phẩm và một loại thao tác, có thời hạn và chỉ dùng một lần. Bạn vẫn là người đọc lại và quyết định cuối cùng: nếu tiêu đề đề xuất dùng một từ bạn thấy không đúng với sản phẩm, sửa ngay ở bước xác nhận.

## Thẻ ảnh bìa: Juli phân tích, ảnh là của bạn

Juli không tự chọn và không tự tạo ảnh cho sản phẩm. Thẻ ảnh bìa ghi rõ điều đó bằng nhãn "Juli tải lên · cần ảnh từ bạn".

{{hinh:ctr-the-anh-bia}}

Trong ví dụ, ảnh bìa của một sữa rửa mặt có nền rối, sản phẩm chỉ chiếm 35 % khung, ảnh 600 × 600 px, và TikTok báo "Ảnh chính chất lượng thấp". Dòng cuối thẻ tóm tắt cả quy trình: Duyệt, Juli hỏi ảnh, bạn tải ảnh, xác nhận, Juli thay ảnh bìa.

{{hinh:ctr-the-tai-anh}}

Sau khi duyệt, lượt chạy dừng ở bước "Chờ ảnh từ bạn" với yêu cầu cụ thể cho ảnh mới. Bạn chọn ảnh từ máy, Juli kiểm tra ảnh, rồi đến bước Xác nhận một lần. Chỉ sau khi bạn xác nhận, Juli mới tải ảnh lên TikTok Shop và giữ ảnh bìa cũ để có thể hoàn tác. TikTok duyệt lại trang sản phẩm, rồi Juli đặt lịch đo. Yêu cầu ảnh trong lượt chạy mẫu còn hiệu lực 3 ngày; quá hạn thì lượt chạy dừng và không thay đổi gì.

Vì sao Juli không tạo ảnh? Ảnh bìa phải là ảnh thật của đúng sản phẩm bạn bán. Một ảnh tạo ra có thể đẹp hơn nhưng khác hàng thật, và người mua thấy khác thì trả hàng. Chụp lại hay chọn ảnh khác là việc của người hiểu sản phẩm nhất, tức là bạn.

## Vì sao chỉ đổi một thứ một lúc

Tiêu đề và ảnh bìa cùng tác động đến CTR, nên rất dễ muốn đổi cả hai một lần. Juli không làm vậy: Juli không bao giờ thực hiện hai thay đổi cùng lúc trên một sản phẩm. Nếu hai thay đổi chồng lên nhau, đến ngày 14 không ai biết thay đổi nào tạo ra kết quả, và lần sau cũng không biết nên làm gì.

Một sản phẩm cũng chỉ có một chỉ số mục tiêu tại một thời điểm. Một thẻ CTR không chạy song song với một thẻ CTOR trên cùng sản phẩm. Đề xuất tiếp theo cho sản phẩm có thể hiện ra ở ngày 7, nhưng chỉ được thực hiện sau khi thay đổi trước đã chốt ở ngày 14.

## GMV dự kiến của thẻ CTR tính cả CTOR

Lượt nhấp tăng thêm chỉ thành GMV khi có người đặt hàng. Vì vậy GMV dự kiến của một thẻ CTR đi qua cả bước CTOR, theo đúng phép tách GMV của TikTok:

> GMV có thể lấy lại mỗi ngày = Lượt hiển thị × (CTR mục tiêu − CTR hiện tại) × CTOR × AOV

Một ví dụ giả định: sản phẩm có 4.000 lượt hiển thị mỗi ngày trên Thẻ sản phẩm, CTR từ 3,0 % lên mục tiêu 3,5 %, CTOR 5 %, AOV 150.000đ.

- Lượt nhấp thêm mỗi ngày: 4.000 × 0,5 % = 20.
- Đơn thêm mỗi ngày: 20 × 5 % = 1.
- GMV thêm mỗi ngày: 1 × 150.000đ = 150.000đ.

Nếu CTOR của sản phẩm chỉ 1 %, cùng mức tăng CTR đó chỉ mang thêm khoảng 30.000đ mỗi ngày. Vì thế một sản phẩm có CTR thấp nhưng CTOR cũng thấp chưa chắc đứng đầu danh sách: thêm người bấm vào một trang chưa thuyết phục không mang lại nhiều. Số liệu trên thẻ là trung bình 30 ngày, và thẻ ghi rõ là ước tính theo quy tắc, không phải lời hứa.

## Đo trên đúng luồng Thẻ sản phẩm

Ảnh bìa và tiêu đề chủ yếu được người mua nhìn thấy trên Thẻ sản phẩm, nên mục tiêu của thẻ CTR được đặt và đo trên luồng này, không bị pha loãng bởi lượt xem từ video hay LIVE. Khi luồng Thẻ sản phẩm của một sản phẩm có quá ít dữ liệu, Juli đo trên tất cả các kênh và ghi rõ điều đó trên thẻ.

Trước khi áp dụng, Juli chụp lại mốc so sánh: chuỗi số liệu 14 ngày, giá, khuyến mãi đang chạy và nội dung trang sản phẩm. Các chỉ số không phải mục tiêu, như lượt hiển thị và CTOR, có một ngưỡng giữ ổn định. Một tiêu đề mới có thể tăng CTR nhưng kéo về những người không định mua, và ngưỡng này là nơi điều đó lộ ra.

- **Ngày 7**: kiểm tra giữa chừng. CTR ghi **Đang lên** nếu đang tiến về mục tiêu, hoặc **Chưa rõ**. Nếu một chỉ số bạn muốn giữ ổn định ra ngoài khoảng cho phép, Juli hỏi bạn có muốn hoàn tác không, kèm số liệu cụ thể.
- **Ngày 14**: kết quả chốt, một trong bốn nhãn **Đạt**, **Đạt · chưa chắc chắn**, **Một phần** hoặc **Không đạt**, đặt cạnh GMV dự kiến ban đầu.

Nếu trong thời gian đo bạn tự sửa tiêu đề, đổi giá hay mở khuyến mãi, kết quả ghi "Bị ảnh hưởng bởi thay đổi khác" thay vì ghi công cho đề xuất. Cách đo chi tiết ở trang [Đo lường GMV](/san-pham/do-luong-gmv).

## Hoàn tác về tiêu đề hay ảnh bìa cũ

Mọi thay đổi Juli ghi lên TikTok Shop đều được lưu giá trị cũ. Nút **Hoàn tác** có ở lượt chạy đã áp dụng và trong phần Đo lường.

{{hinh:ctr-the-hoan-tac}}

Khi bấm, bạn chọn một lý do, rồi Juli tạo một lượt chạy mới để khôi phục tiêu đề hay ảnh bìa cũ. Lượt hoàn tác cũng dừng ở bước xác nhận trước khi ghi, và việc đo kết quả của thay đổi đó dừng lại. Trước khi khôi phục, Juli đọc lại sản phẩm trên TikTok Shop: nếu nội dung đã bị sửa bên ngoài Juli sau lần thay đổi, Juli không ghi đè và báo cho bạn.

Juli không bao giờ tự hoàn tác, kể cả khi ngày 7 cho thấy một chỉ số ra ngoài ngưỡng. Juli hỏi, bạn quyết định. Lý do bạn chọn khi hoàn tác cũng làm loại thay đổi đó được ưu tiên thấp hơn cho shop trong thời gian sau.

## Những gì tiêu đề và ảnh bìa không sửa được

Trên Thẻ sản phẩm, người mua còn thấy giá, số đã bán và điểm đánh giá. Tiêu đề và ảnh bìa không thay được những thứ đó:

- **Giá**: Juli không đổi giá sản phẩm. Với giảm giá hay flash sale, Juli đề xuất mức giảm nằm trong biên lợi nhuận bạn đặt trong Quy tắc (chỉ khi Juli biết giá vốn), bạn tạo trên Seller Center, rồi Juli kiểm tra lại và bắt đầu đo.
- **Đánh giá và số đã bán**: đến từ đơn hàng thật, không sửa được bằng nội dung.
- **Khi CTR ổn mà ít đơn**: vấn đề nằm sau cú nhấp, ở trang sản phẩm hay bước thanh toán. Đọc bài [CTOR thấp: viết lại mô tả](/blog/ctor-thap-viet-lai-mo-ta-san-pham).

Toàn bộ các loại thẻ, phần Juli làm và phần bạn làm được mô tả ở trang [Đề xuất và thực thi](/san-pham/de-xuat-va-thuc-thi). Muốn thấy thẻ CTR cho sản phẩm của chính shop mình, kết nối shop ở trang [Kết nối TikTok Shop](/ket-noi/tiktok-shop) hoặc xem [Tổng quan sản phẩm](/san-pham) trước; tài khoản mới được [dùng thử miễn phí 3 tháng](/dang-ky).
`;
