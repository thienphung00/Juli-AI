/**
 * Guide post (D59 additions 5, P49-A1, C1): connecting a TikTok Shop to Juli,
 * step by step, and what happens in the first hour. Main keyword "kết nối
 * tiktok shop với juli" (transactional / navigational; `/ket-noi/tiktok-shop`
 * keeps "kết nối tiktok shop"); support "kết nối api tiktok shop", "hủy kết
 * nối tiktok shop" (FAQ, real autocomplete per the conversion plan). Facts:
 * SPEC §2.1 (OAuth, signed state), `/ket-noi/tiktok-shop` (steps, permission
 * groups, reads / writes, encryption, staff access, disconnect, Shopee wording),
 * D26 / D25.12 / P17 via that page (quick scan 14 days, reading 60 days,
 * nightly history to 180 days; SPEC §3.1 "30 days" is stale), D24.17 (day-1
 * slots), D25.15 (missing scopes strip), D43 additions 2 and 3 (sign-in door,
 * trial, no seller disconnect button), D44.5 / D47.6 (auth screen). Durations
 * are not promised (SPEC §5 targets are estimates until measured).
 */
export const body = `
Kết nối TikTok Shop với Juli mất khoảng một hai phút và không cần mật khẩu shop: bạn đăng nhập Juli, bấm Kết nối TikTok Shop, đồng ý cấp quyền trên trang uỷ quyền của chính TikTok, rồi được đưa trở lại Juli. Từ lúc đó Juli tự đọc dữ liệu, trước tiên là một lượt quét nhanh 14 ngày gần nhất, và không thay đổi gì trên shop cho đến khi bạn duyệt và xác nhận một đề xuất cụ thể. Bài này đi qua từng bước, giải thích từng nhóm quyền bằng lời dễ hiểu, và chỉ cách đọc những gì hiện ra trong giờ đầu tiên.

Trang [Kết nối TikTok Shop](/ket-noi/tiktok-shop) tóm tắt cách kết nối hoạt động. Bài này đi sâu hơn: bạn cần chuẩn bị gì, mỗi màn hình hỏi gì, dải tiến trình nói gì, và làm gì khi Juli báo thiếu quyền. Ảnh trong bài chụp từ bản demo của Juli với Cửa hàng Mẫu Hoa Mai, một shop minh hoạ; tên shop, email và số liệu đều là dữ liệu mẫu.

## Trước khi kết nối: bạn cần gì

Bạn chỉ cần ba thứ:

1. **Tài khoản người bán TikTok Shop** có quyền đăng nhập Trung tâm nhà bán hàng của shop muốn kết nối. Ở bước uỷ quyền, chính TikTok hỏi bạn đăng nhập, nên người bấm đồng ý phải là người có quyền với shop đó.
2. **Một tài khoản Google hoặc một địa chỉ email** để đăng nhập Juli. Juli không dùng mật khẩu riêng cho người bán: đăng nhập bằng Google, hoặc nhận mã đăng nhập gửi về email.
3. **Vài phút không bị gián đoạn** cho bước uỷ quyền. Đường dẫn uỷ quyền chỉ dùng được trong ít phút sau khi tạo; nếu bạn để quá lâu, chỉ cần bấm kết nối lại từ đầu.

Bạn không cần đưa mật khẩu TikTok Shop cho ai, không cần cài thêm phần mềm, và không cần tự tạo khoá API. Juli là một ứng dụng trên TikTok Shop Partner Center và kết nối qua trang uỷ quyền chính thức của TikTok, nên phần "kết nối API TikTok Shop" đã nằm sẵn trong bước bấm đồng ý.

Nếu bạn muốn xem Juli trông thế nào trước khi kết nối shop thật, màn hình đăng nhập có đường dẫn "Xem thử với dữ liệu mẫu, không cần tài khoản". Bản xem thử chạy trên shop minh hoạ và không ghi gì lên TikTok Shop.

## Bốn bước kết nối TikTok Shop với Juli

### Bước 1: đăng nhập Juli

Mở Juli và chọn **Tiếp tục với Google**, hoặc nhập email rồi bấm **Gửi mã đăng nhập** và nhập mã nhận được. Nếu đây là lần đầu, Juli tự tạo tài khoản cho bạn ở chính bước này, không có biểu mẫu đăng ký riêng. Dòng "Đối tác thẩm định" ở trên cùng dành cho đối tác của các sàn khi họ kiểm tra ứng dụng; người bán bỏ qua dòng này.

{{hinh:hd-kn-dang-nhap}}

Nếu bạn đến từ trang [dùng thử miễn phí 3 tháng](/dang-ky), màn hình đăng nhập giữ nguyên bố cục, chỉ đổi lời chào. Sau khi đăng nhập, bạn đi tiếp bước 2 như mọi tài khoản khác.

### Bước 2: bấm Kết nối TikTok Shop

Tài khoản mới chưa có shop nào, nên Juli đưa bạn đến màn hình **Kết nối TikTok Shop**, ghi rõ bạn đang đăng nhập bằng email nào và "Bạn chưa kết nối shop TikTok nào". Hãy kiểm tra dòng email này trước khi bấm: shop sẽ được gắn với đúng tài khoản đó.

{{hinh:hd-kn-nut-ket-noi}}

Dòng chữ nhỏ dưới nút nói một điều quan trọng: khi kết nối, bạn đồng ý để nhân viên Juli xem dữ liệu shop nhằm hỗ trợ và vận hành dịch vụ, không gồm dữ liệu người mua, và mọi lần truy cập đều được ghi nhật ký. Phần này được giải thích kỹ ở mục bảo mật bên dưới và trong [Chính sách bảo mật](/privacy).

### Bước 3: đồng ý cấp quyền trên trang của TikTok

Bấm nút, Juli chuyển bạn sang trang uỷ quyền của TikTok Shop. Đây là trang của TikTok, không phải của Juli. Bạn đăng nhập tài khoản người bán (nếu trình duyệt chưa đăng nhập sẵn), đọc danh sách quyền mà ứng dụng Juli yêu cầu, rồi bấm đồng ý.

Đường dẫn uỷ quyền được máy chủ của Juli tạo và ký riêng cho tài khoản đang đăng nhập. Nhờ vậy, một lượt kết nối không thể bị gắn nhầm sang tài khoản Juli khác, kể cả khi ai đó có được đường dẫn.

### Bước 4: quay lại Juli

Sau khi bạn đồng ý, TikTok đưa bạn trở lại Juli. Bạn không cần bấm gì thêm: Juli bắt đầu đọc dữ liệu ngay và hiện dải tiến trình ở các màn hình chính. Nếu bước quay lại báo lỗi, hãy đăng nhập Juli lại và bấm Kết nối TikTok Shop thêm một lần: đường dẫn uỷ quyền chỉ dùng được trong ít phút, nên một lượt để quá lâu cần làm lại từ đầu.

## Các nhóm quyền, nói dễ hiểu

Trang uỷ quyền của TikTok liệt kê chính xác từng quyền. Juli dùng các quyền đó cho năm việc:

| Nhóm quyền | Juli dùng để làm gì |
|---|---|
| Thông tin shop và sản phẩm | Biết shop có những sản phẩm nào, tên, danh mục, giá, tồn kho theo SKU |
| Đơn hàng và tài chính theo đơn | Tính GMV, đơn hàng SKU, đơn huỷ và hoàn; chi tiết giá của đơn |
| Số liệu phân tích | Lượt hiển thị, lượt nhấp, đơn hàng và GMV theo từng luồng, của sản phẩm, video và LIVE |
| Khuyến mãi và voucher | Biết đợt giảm giá nào đang chạy, để không nhầm tác động của khuyến mãi với tác động của trang sản phẩm |
| Cập nhật thông tin sản phẩm | Ghi tiêu đề, mô tả, hoặc ảnh bìa bạn gửi, chỉ sau khi bạn duyệt và xác nhận một thay đổi cụ thể |

Bốn nhóm đầu là quyền đọc. Nhóm cuối là quyền ghi duy nhất Juli dùng, và nó không tự kích hoạt khi bạn kết nối. Một thao tác trên shop chỉ xảy ra khi bạn đã duyệt đề xuất đó và xác nhận nội dung, với một quyền ghi cấp riêng cho đúng một sản phẩm và một loại thao tác, có thời hạn và chỉ dùng được một lần. Cách hai bước đồng ý đó diễn ra được giải thích trong bài [duyệt một thẻ đề xuất](/blog/duyet-de-xuat-toi-uu-san-pham-tiktok-shop).

## Giờ đầu sau khi kết nối: quét nhanh, đọc 60 ngày, tải lịch sử nền

Ngay khi TikTok đưa bạn trở lại, Juli chạy ba bước và hiện tiến trình "Juli đang đọc dữ liệu shop · bước 1/3" ở Trang chủ, Quyết định và Phân tích. Ảnh dưới đây chụp lúc bước 1 đã xong và bước 2 đang chạy.

{{hinh:hd-kn-quet-nhanh}}

### Bước 1/3: quét nhanh 14 ngày

Trong vài phút đầu, Juli đọc hiệu suất sản phẩm của 14 ngày gần nhất và chẩn đoán sản phẩm mà TikTok trả về cho các sản phẩm bán chạy. Từ đó Juli có thể tạo 1 đến 3 **đề xuất nhanh** về ảnh bìa, tiêu đề hoặc mô tả. Các thẻ này mang nhãn "Đề xuất nhanh · dựa trên 14 ngày" và độ tin cậy **Tham khảo**, vì 14 ngày còn ngắn để chắc chắn. Không phải shop nào cũng nhận đủ ba thẻ nhanh: nếu chưa có sản phẩm nào đủ dữ liệu, ô đó để trống.

Đọc một thẻ nhanh như đọc mọi thẻ khác: chỉ số mục tiêu (ví dụ CTR trên kênh Thẻ sản phẩm, giá trị hiện tại và mục tiêu), GMV dự kiến ghi rõ "ước tính theo quy tắc", lý do và thay đổi đề xuất. Bạn có thể duyệt ngay, hoặc chờ chẩn đoán đầy đủ để xem thẻ còn đứng vững không.

### Bước 2/3: đọc 60 ngày và chẩn đoán đầy đủ

Juli đọc 60 ngày đơn hàng và số liệu phân tích, đủ để so 30 ngày gần nhất với 30 ngày trước đó, rồi dựng báo cáo Phân tích và các thẻ đề xuất đầy đủ. Dải tiến trình ghi phần trăm và thời gian ước tính còn lại. Thời gian thật tuỳ theo số sản phẩm của shop, nên con số "khoảng 9 phút" trong ảnh chỉ là của shop mẫu. Khi bước này xong, các thẻ nhanh còn hợp lệ được giữ lại và cập nhật số, các ô đề xuất còn lại trong ngày được lấp đầy.

Ngày đầu, thẻ mới được chia theo loại: đến 3 thẻ Juli thực hiện (tiêu đề, mô tả, ảnh bìa), 1 thẻ bạn làm trên Seller Center và 1 thẻ nội dung video hoặc LIVE. Ô nào không có ứng viên tốt thì để trống, Juli không lấp bằng thẻ kém hơn.

### Bước 3/3: tải lịch sử nền

Mỗi đêm, Juli tải thêm lịch sử cũ hơn, đến 180 ngày hoặc đến giới hạn TikTok cho phép, ở mức ưu tiên thấp để không làm chậm phần còn lại. Bạn không cần chờ bước này để dùng Juli.

### Sau đó, mỗi ngày

Đơn hàng, sản phẩm và tồn kho được đồng bộ nhiều lần trong ngày. Số liệu phân tích được lấy mỗi ngày một lần, khi TikTok công bố ngày dữ liệu mới, và báo cáo được dựng lại. Vì số liệu phân tích của TikTok có độ trễ, ngày mới nhất trên Juli thường là hôm qua.

## Việc nên làm trong giờ đầu

Trong lúc chờ bước 2, có ba việc đáng làm:

1. **Mở Phân tích và đọc dòng đầu trang.** Juli tóm tắt 30 ngày thành một câu, ví dụ "Thẻ sản phẩm: CTOR giảm 7 %", kèm luồng và chỉ số đang kéo GMV xuống. Bài [đọc màn hình Phân tích theo luồng truy cập](/blog/doc-phan-tich-tiktok-shop-theo-luong-truy-cap) giải thích từng ô.
2. **Xem lại Quy tắc.** Giọng văn, những từ không được dùng, giá vốn hoặc biên lợi nhuận tối thiểu và số thẻ mở cùng lúc là con số của bạn; Juli không tự chọn chúng. Đặt trước khi duyệt thẻ đầu tiên giúp nội dung Juli soạn đúng ý bạn ngay từ lần đầu.
3. **Đọc kỹ một thẻ trước khi duyệt.** Bấm "Xem thêm" để thấy lý do đầy đủ và công thức GMV dự kiến. Duyệt chưa đổi gì trên shop; bạn còn một bước xác nhận nữa.

{{hinh:hd-kn-phan-tich-dau-tien}}

## Juli đọc gì và không đọc gì

Sau khi kết nối, Juli đồng bộ định kỳ các dữ liệu sau từ API của TikTok Shop, theo [Chính sách bảo mật](/privacy):

- Đơn hàng và chi tiết đơn: mã đơn, trạng thái, giá trị, thời gian thanh toán và giao hàng.
- Sản phẩm (tên, danh mục, giá bán, doanh thu, số lượng đã bán) và tồn kho theo SKU.
- Đơn hoàn và huỷ: loại, lý do, số tiền hoàn.
- Số liệu hiệu suất theo từng luồng truy cập, và hiệu suất video, LIVE của shop.
- Chương trình khuyến mãi và mã giảm giá của shop.

Juli không đọc tin nhắn của bạn với khách, và không lưu thông tin liên hệ của người mua ngoài mã định danh cần thiết để xử lý đơn hàng.

Về phía ghi, Juli thực hiện ba loại thay đổi: tiêu đề, mô tả sản phẩm, và ảnh bìa khi bạn tự gửi ảnh. Mọi thay đổi đều được lưu giá trị cũ để hoàn tác. Juli không ghi giá sản phẩm (chỉ đề xuất), không tạo khuyến mãi hay voucher (bạn tạo trên Seller Center theo hướng dẫn của Juli), và không ghi bất cứ thứ gì khác ngoài những thay đổi bạn đã duyệt và xác nhận.

## Mã truy cập, nhân viên Juli và dữ liệu gửi đi soạn nội dung

**Mã truy cập được mã hoá.** Mã truy cập TikTok Shop của bạn được mã hoá trước khi lưu, và khoá giải mã nằm trong hệ thống quản lý khoá bí mật, không nằm trong mã nguồn. Mã được làm mới tự động trước khi hết hạn, nên bạn không phải kết nối lại định kỳ.

**Nhân viên Juli chỉ xem dữ liệu shop.** Dữ liệu shop chỉ dùng để cung cấp dịch vụ cho chính bạn. Nhân viên được xem dữ liệu shop để hỗ trợ và vận hành, ở chế độ chỉ xem; họ không bao giờ xem dữ liệu người mua, và mọi lần truy cập đều được ghi nhật ký.

**Dữ liệu gửi đi soạn nội dung không dùng để huấn luyện.** Khi bạn duyệt một thẻ tiêu đề hay mô tả, Juli gửi thông tin cần thiết của sản phẩm đó đến OpenAI để soạn nội dung. Dữ liệu này không được dùng để huấn luyện mô hình. Trước khi bạn duyệt, không có lời gọi nào như vậy.

## Khi Juli báo thiếu quyền hoặc cần kết nối lại

Mỗi lần làm mới mã truy cập, Juli ghi lại những quyền TikTok thực sự đã cấp. Nếu Juli cần một quyền mà shop chưa cấp, bạn sẽ thấy dòng **"Kết nối lại TikTok Shop để cấp quyền mới"** trong ứng dụng. Bạn chỉ cần đi lại bước 2 và bước 3 ở trên, đọc danh sách quyền trên trang của TikTok và đồng ý. Kết nối lại không xoá dữ liệu, quy tắc hay kết quả đo đã có; Juli tiếp tục từ chỗ đã dừng.

Dòng nhắc này chỉ hiện khi thật sự thiếu quyền. Việc làm mới mã truy cập định kỳ diễn ra tự động và không cần bạn làm gì.

## Ngắt kết nối: liên hệ Juli

Người bán không có nút tự ngắt kết nối trong Juli. Muốn ngắt, bạn liên hệ Juli qua email lienhe@app-juli.com hoặc [trang Liên hệ](/contact); đội Juli ngắt kết nối shop giúp bạn. Khi đó:

- Juli ngừng lấy dữ liệu mới và ngừng tạo đề xuất cho shop đó ngay.
- Các lượt chạy đang chờ được huỷ, và Juli không ghi thêm gì lên TikTok Shop.
- Lịch sử, quy tắc và kết quả đo được giữ lại, để khi bạn kết nối lại Juli tiếp tục từ chỗ cũ.
- Nếu bạn yêu cầu xoá tài khoản, dữ liệu tài khoản và dữ liệu shop được xoá trong vòng 30 ngày, trừ dữ liệu pháp luật yêu cầu lưu.

Shopee đang được tích hợp qua Shopee Open Platform và chưa thể kết nối. Hiện Juli hoạt động với TikTok Shop; khi tích hợp Shopee hoàn tất, trang Kết nối và Chính sách bảo mật sẽ mô tả cách kết nối và dữ liệu Juli đọc.

## Sau khi kết nối: đi tiếp đến đâu

Kết nối chỉ là bước mở cửa. Ba bài tiếp theo đi theo đúng thứ tự bạn sẽ gặp trong Juli:

1. [Đọc màn hình Phân tích theo luồng truy cập](/blog/doc-phan-tich-tiktok-shop-theo-luong-truy-cap): luồng nào, chỉ số nào đang kéo GMV xuống. Chi tiết tính năng ở trang [Phân tích shop](/san-pham/phan-tich-shop).
2. [Duyệt một thẻ đề xuất](/blog/duyet-de-xuat-toi-uu-san-pham-tiktok-shop): từ lý do, sửa nội dung đến xác nhận lần cuối. Trang [Đề xuất và thực thi](/san-pham/de-xuat-va-thuc-thi) tóm tắt phần Juli làm và phần bạn làm.
3. [Đo kết quả ngày 7, ngày 14 và hoàn tác](/blog/do-ket-qua-ngay-7-ngay-14-hoan-tac): cách biết một thay đổi có tác dụng. Phương pháp đo nằm ở trang [Đo lường GMV](/san-pham/do-luong-gmv).

Nếu bạn mới làm quen với các chỉ số, hãy đọc trước [GMV là gì](/blog/gmv-la-gi-tiktok-shop) và [CTR, CTOR, AOV trên TikTok Shop](/blog/chi-so-tiktok-shop-ctr-ctor-aov). Tổng quan về những gì Juli làm, dành cho ai và bảng giá nằm ở trang [Sản phẩm](/san-pham).
`;
