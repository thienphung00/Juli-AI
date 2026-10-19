/**
 * Pain post (D56, P46-D2, week 3 #11): "Khách hỏi mãi một câu: mô tả sản phẩm
 * trả lời trước". Main keyword "mô tả sản phẩm tiktok shop" (Google
 * autocomplete VN 2026-10-18: "mô tả sản phẩm tiktok" suggests "mô tả sản phẩm
 * tiktok shop", "cách viết mô tả sản phẩm trên tiktok"; the keyword moved here
 * from the pillar's supporting list). Scope is only the description as the
 * place that answers repeated buyer questions (CTOR, "không đúng mô tả"):
 * titles, cover images and prices stay in the pillar
 * `toi-uu-the-san-pham-tiktok-shop`. Facts re-opened on 2026-10-18 on
 * seller-vn.tiktok.com (title + date in the text and `sources`): Tiêu đề, mô
 * tả, hình ảnh và video về sản phẩm (23/04/2026); Hướng dẫn đăng bán sản phẩm
 * tại TikTok Shop (05/10/2026) 3.1.1 to 3.1.5; Mô tả sản phẩm phóng đại là gì?
 * (29/06/2025); Thông tin đặt hàng thay thế (Chuyển hướng truy cập)
 * (10/06/2026); Mặt hàng khác biệt lớn so với mô tả (SNAD) (18/06/2025); Hiển
 * thị thông tin sai lệch và hướng dẫn về nội dung đăng bán tạo bởi AI
 * (30/09/2026); Trình Tối Ưu Hoá Sản Phẩm (04/08/2025); Hướng dẫn bảng kích cỡ
 * cho Nhà bán hàng Thời trang (01/10/2026). No official page gives an optimal
 * length or format: structure advice is labelled as ours. D59 reach post
 * (P48-C): no Juli, no product links; the last how-to section is a per-product
 * question log the seller keeps. Example numbers are hypothetical and say so.
 */
export const body = `
Khi khách nào cũng hỏi đúng một câu, "có size nào", "chất liệu gì", "trong hộp có gì", thì thường là trang sản phẩm chưa trả lời câu đó, và những người không muốn hỏi sẽ rời đi mà không đặt hàng. Mô tả sản phẩm là chỗ để trả lời trước, trong khuôn khổ chính sách của TikTok Shop: không dưới 30 từ, đúng với hàng thật, không phóng đại, không để số điện thoại hay đường dẫn ra ngoài. Bài này chỉ cách gom các câu hỏi lặp lại của chính shop, viết chúng thành mô tả và đo lại sau 7, 14 ngày.

Bài này chỉ nói về mô tả; tiêu đề, ảnh bìa, thuộc tính và giá có trong bài trụ [tối ưu thẻ sản phẩm TikTok Shop](/blog/toi-uu-the-san-pham-tiktok-shop). Mọi con số trong các ví dụ là ví dụ giả định.

## Khách hỏi mãi một câu: mô tả sản phẩm đang thiếu gì

Một câu hỏi lặp lại là dấu hiệu thông tin khách cần chưa có trên trang, hoặc có nhưng khó thấy. Người hỏi là khách còn đủ kiên nhẫn để nhắn tin; nhiều khách khác chỉ bấm vào, không thấy câu trả lời rồi quay lại trang tìm kiếm.

Trên số liệu, việc này hiện ra ở bước sau cú nhấp: CTOR (Tỷ lệ từ nhấp đến đặt hàng), bằng Đơn hàng SKU chia cho Lượt nhấp vào sản phẩm. Nếu CTR ổn mà CTOR thấp, và cùng một câu hỏi cứ đến, mô tả là một trong những chỗ đầu tiên nên xem. Đây là suy luận của chúng tôi từ cách phễu vận hành, không phải tuyên bố của TikTok rằng sửa mô tả sẽ tăng CTOR. Cách đọc CTOR theo từng nguồn có trong bài [khách xem nhưng không mua](/blog/khach-xem-nhung-khong-mua-tiktok-shop).

## Gom câu hỏi lặp lại của chính shop trong một tuần

Đừng viết mô tả từ trí nhớ. Trong 7 ngày, ghi lại mọi câu hỏi về sản phẩm, rồi đếm. Nguồn để gom:

- **Tin nhắn với người mua**: mỗi câu hỏi ghi một dòng, kèm tên sản phẩm.
- **Bình luận dưới video và trong LIVE**: nhiều người khác cũng đọc được câu hỏi đó.
- **Đánh giá**: những câu như "tưởng to hơn" là câu hỏi khách đã không hỏi trước khi mua.
- **Lý do trả hàng**: không đúng mô tả, sai kích thước, thiếu phụ kiện cho biết chính xác thông tin nào khách đã hiểu sai. Cách đọc lý do trả hàng có trong bài [tỷ lệ hoàn hàng TikTok Shop](/blog/ty-le-hoan-hang-tiktok-shop).

Sau một tuần, giữ năm câu xuất hiện nhiều nhất cho mỗi sản phẩm bán chạy. Câu chỉ một người hỏi thì chưa cần vào mô tả.

### Năm nhóm câu hỏi hay gặp nhất

1. **Kích thước, biến thể**: size nào, vừa với ai, màu thật, dung tích.
2. **Chất liệu, thành phần**: làm bằng gì, có chất gây kích ứng không, xuất xứ.
3. **Cách dùng, bảo quản**: dùng thế nào, giặt hay cất ra sao, hạn sử dụng.
4. **Trong hộp có gì**: bán lẻ hay cả bộ, có kèm phụ kiện không.
5. **Giao nhận, đổi trả**: có được đổi size không, bảo hành thế nào.

{{hinh:mo-ta-nam-nhom-cau-hoi}}

Với nhóm thứ năm, thời gian giao và phí vận chuyển do nền tảng hiển thị lúc thanh toán; mô tả chỉ nên nói chính sách riêng của shop, và chỉ khi bạn thực sự áp dụng nó.

## TikTok yêu cầu gì ở mô tả sản phẩm

Trang chính sách "Tiêu đề, mô tả, hình ảnh và video về sản phẩm" (cập nhật 23/04/2026, áp dụng Việt Nam) yêu cầu cung cấp đủ thông tin theo pháp luật, và hướng dẫn:

- Mô tả các đặc điểm chính: đặc tính, chức năng, thành phần, số lượng.
- Độ dài không dưới 30 từ.
- Trình bày rõ ràng để khách quyết định sáng suốt.
- Cung cấp thông tin an toàn, thông số kỹ thuật, cảnh báo, đặc biệt với các loại như thực phẩm bổ sung.
- Nêu rõ sản phẩm và tất cả phụ kiện đi kèm ("Hộp sản phẩm bao gồm những gì"); loa bán kèm bộ sạc USB thì liệt kê từng món.
- Chỉ đưa tên thương hiệu khi được chủ sở hữu ủy quyền.

Đặt cạnh năm nhóm câu hỏi, chính sách đã phủ bốn nhóm đầu: một mô tả đủ chính sách thường đã trả lời phần lớn câu hỏi lặp lại.

### Mô tả sản phẩm TikTok Shop phải dài bao nhiêu

Mức chính thức duy nhất là tối thiểu 30 từ. Chúng tôi không tìm thấy trang nào của TikTok nói mô tả dài bao nhiêu thì bán tốt hơn, hay gạch đầu dòng tốt hơn đoạn văn. Độ dài đúng là đủ để trả lời năm câu hỏi của khách.

### Hàng thời trang: bảng kích cỡ trả lời câu hỏi về size

Trang "Hướng dẫn bảng kích cỡ cho Nhà bán hàng Thời trang" (01/10/2026) yêu cầu sản phẩm cần độ vừa vặn có bảng kích cỡ rõ ràng: số đo bằng số kèm đơn vị như cm, phủ mọi SKU kích cỡ khách chọn được, không dùng cụm mơ hồ như "phù hợp với hầu hết mọi người". Bảng có thể nằm ở mục bảng kích cỡ riêng, trong ảnh hoặc trong mô tả. Trang gợi ý thêm cách lấy số đo, gợi ý size theo chiều cao, cân nặng và ghi chú độ co giãn.

## Cách viết mô tả sản phẩm trên TikTok để trả lời trước câu hỏi

Cấu trúc dưới đây là khuyến nghị của chúng tôi, không phải quy định của TikTok:

1. **Một câu mở**: sản phẩm là gì, dành cho ai.
2. **Ba đến năm điểm chính kiểm chứng được**: điều bạn chứng minh được bằng nhãn, giấy công bố hay thông số.
3. **Thông số**: kích thước, dung tích, chất liệu, thành phần chính, xuất xứ.
4. **Cách dùng và lưu ý an toàn**: tần suất, cảnh báo, bảo quản, hạn sử dụng.
5. **Trong hộp có gì**: từng món, đúng số lượng.
6. **Chính sách của shop**: đổi size, bảo hành, nếu có.

Mỗi câu trong danh sách năm câu phải có chỗ trả lời ở một trong sáu phần này, và câu hay gặp nhất nên nằm trong vài dòng đầu. Ngắt dòng giữa các phần để dễ đọc trên điện thoại, rồi đọc lại trên điện thoại như một khách hàng: nếu còn phải hỏi, phần đó chưa đủ.

{{hinh:mo-ta-truoc-sau}}

Viết đúng điều khách sẽ nhận. Nếu bạn giao màu ngẫu nhiên, trang "Mặt hàng khác biệt lớn so với mô tả (SNAD)" (18/06/2025) yêu cầu nêu rõ điều đó trên trang mô tả.

## Những gì không được viết trong mô tả sản phẩm

Trả lời trước câu hỏi không có nghĩa là hứa nhiều hơn. Theo Trung tâm chính sách TikTok Shop:

- **Phóng đại.** Trang "Mô tả sản phẩm phóng đại là gì?" (29/06/2025) và mục 3.1.2 của "Hướng dẫn đăng bán sản phẩm tại TikTok Shop" (05/10/2026) không cho phép "Sản phẩm số 1", "tốt nhất", "duy nhất", "100% tự nhiên", công dụng "thần kỳ", kết quả "ngay tức thì", trừ khi chính xác và xác minh được; tuyên bố tuyệt đối cần tài liệu của cơ quan có thẩm quyền. Riêng dược mỹ phẩm, trang nêu cách viết bắt đầu bằng "hỗ trợ" hoặc "giúp", hoặc câu miễn trừ rằng hiệu quả khác nhau tùy người dùng.
- **So sánh** với sản phẩm hoặc trang khác, như "rẻ hơn XX trên trang ABC" (mục 3.1.3).
- **Giá khuyến mại phóng đại, giải thưởng hay chứng nhận không có** (mục 3.1.4, 3.1.5), thông tin sai về bảo hành, đổi trả (trang "Hiển thị thông tin sai lệch và hướng dẫn về nội dung đăng bán tạo bởi AI", 30/09/2026).
- **Thông tin không khớp**: mô tả, hình ảnh, thuộc tính phải khớp nhau và khớp sản phẩm thực tế; không gây hiểu lầm bằng cách bỏ sót thông tin (mục 3.1.1).

{{hinh:mo-ta-duoc-khong-duoc}}

### Có được để số điện thoại, Zalo cho khách hỏi thêm không

Không. Trang "Thông tin đặt hàng thay thế (Chuyển hướng truy cập)" (10/06/2026) không cho phép liên kết, số điện thoại, tài khoản mạng xã hội, email hay mã QR có thể đưa người dùng rời nền tảng để đặt hàng hoặc liên hệ, kể cả lời kêu gọi hành động. Vi phạm liên quan thông tin cá nhân của người mua bị xử lý nặng hơn, đến tạm ngưng hoặc vô hiệu hóa tài khoản. Vì vậy hãy trả lời ngay trong mô tả; khách cần hỏi thêm thì hỏi qua tin nhắn trên TikTok Shop.

## Mô tả và "không đúng mô tả": trả lời sai còn tệ hơn không trả lời

Mô tả thiếu làm khách hỏi lại hoặc bỏ đi; mô tả sai làm khách mua rồi trả hàng. Trang SNAD gọi là vi phạm khi khách nhận sản phẩm không khớp mô tả: khác màu, khác size, thiếu thành phần đã hứa. Theo chính sách hủy đơn, trả hàng và hoàn tiền của TikTok Shop, trả hàng vì không khớp mô tả là lỗi người bán: người bán chịu phí trả hàng và đơn đó tính vào Tỷ lệ trả hàng/hoàn tiền do lỗi của người bán (SFRR). Vì vậy mỗi câu trả lời trong mô tả phải là điều bạn kiểm tra được trên chính lô hàng đang bán.

## Dùng AI viết mô tả sản phẩm có được không

Được. Trang "Trình Tối Ưu Hoá Sản Phẩm" (04/08/2025) mô tả Công cụ Tối Ưu Hoá Sản Phẩm trong Trung Tâm Nhà Bán Hàng, có tính năng "Tối ưu hóa bằng AI" cho tiêu đề và mô tả, và lưu ý: nếu mô tả ban đầu quá ngắn, hệ thống có thể không tạo được mô tả phong phú hơn. AI chỉ viết lại được từ thông tin bạn cung cấp; câu hỏi và thông số thật vẫn do bạn đưa vào. Dù ai soạn, thông tin phải "chính xác và trung thực" và người bán chịu trách nhiệm: đọc lại từng câu, gạch mọi tính từ tuyệt đối trước khi đăng.

## Sửa mô tả xong, đo lại thế nào

Bạn tự đo được bằng trang Lưu lượng truy cập sản phẩm trong La bàn dữ liệu:

- **Một thay đổi, một sản phẩm**: chỉ sửa mô tả, ghi lại ngày sửa.
- **So với 14 ngày trước**: đọc CTOR sơ bộ ở ngày 7, chốt ở ngày 14.
- **Đủ dữ liệu**: với vài chục lượt nhấp, một hai đơn đã làm CTOR nhảy mạnh. Sản phẩm ít lượt nhấp cần đo lâu hơn, và kết quả chỉ để tham khảo; TikTok không đưa ra một ngưỡng chính thức.
- **Nhìn thêm sản phẩm chưa sửa**: nếu CTOR của những sản phẩm bạn không sửa cũng tăng, mức tăng chưa chắc nhờ mô tả.

Ví dụ giả định: sản phẩm có 300 lượt nhấp mỗi ngày, CTOR 2,0 % trước khi sửa, 2,4 % ở ngày 14, các sản phẩm khác giữ nguyên. Chênh 0,4 điểm trên 300 lượt nhấp là khoảng 1,2 đơn mỗi ngày. Kết quả "không đổi" cũng có ích: mô tả không phải chỗ nghẽn của sản phẩm này.

## Khi nào mô tả không phải là chỗ cần sửa

- **Câu hỏi về giá, mã giảm giá, phí vận chuyển**: đó là chuyện của giá và bước thanh toán, xem bài [khách xem nhưng không mua](/blog/khach-xem-nhung-khong-mua-tiktok-shop).
- **CTR thấp**: mô tả nằm sau cú nhấp, không giúp khi khách chưa vào trang.
- **Khách hỏi về điều LIVE đã hứa**: sửa lời nói ở buổi sau; bài [LIVE đông người xem mà ít đơn](/blog/live-tiktok-shop-khong-ra-don) chỉ cách đọc phễu LIVE.
- **Câu hỏi đến từ chất lượng hàng**: "lần trước bị lỗi" không phải câu hỏi của mô tả.

## Một bảng ghi chép cho mỗi mô tả bạn sửa

Câu hỏi lặp lại là dữ liệu của chính shop, nên cách giữ nó cũng nên đơn giản. Với mỗi sản phẩm bạn định viết lại mô tả, mở một bảng tính và ghi:

| Cột | Ghi gì |
|---|---|
| Câu hỏi | Năm câu nhiều nhất trong tuần gom, mỗi câu một dòng |
| Số lần | Bao nhiêu lần câu đó xuất hiện, cộng cả tin nhắn, bình luận, đánh giá và lý do trả hàng |
| Trả lời ở đâu | Phần nào của mô tả mới trả lời câu đó: mở đầu, thông số, cách dùng, trong hộp có gì, chính sách |
| Ngày sửa | Ngày mô tả mới lên shop |
| CTOR trước, CTOR ngày 14 | Đọc trên cùng luồng, cùng độ dài khoảng thời gian |

Sau 14 ngày, gom câu hỏi thêm một tuần nữa theo cùng cách. Ngoài CTOR, bảng này cho bạn một tín hiệu mà số liệu của TikTok không có: câu hỏi nào khách không còn hỏi nữa, và câu nào vẫn quay lại. Câu vẫn quay lại nghĩa là câu trả lời chưa đủ rõ hoặc nằm quá sâu trong mô tả; đưa nó lên vài dòng đầu là thay đổi tiếp theo, vẫn một thay đổi mỗi lần.

Ví dụ giả định: trước khi sửa, câu "tuýp bao nhiêu ml" xuất hiện 9 lần trong tuần; tuần sau khi sửa còn 2 lần, trong khi câu "da dầu dùng được không" vẫn 7 lần. Phần trả lời cho câu thứ hai cần rõ hơn.

Giữ thêm một dòng cho lý do trả hàng "không đúng mô tả" của sản phẩm đó trong cùng hai khoảng thời gian. Số này đến chậm vì khách cần thời gian nhận hàng, nên đọc nó sau khi chốt CTOR. Định nghĩa CTOR và các chỉ số khác có trong bài [các chỉ số TikTok Shop](/blog/chi-so-tiktok-shop-ctr-ctor-aov); khi cần ước tính GMV đổi ra sao nếu CTOR lên, thử [công cụ tính GMV miễn phí](/cong-cu/tinh-gmv).
`;
