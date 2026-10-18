/**
 * Guide post (D59 additions 5, P49-A1, C2): a worked reading of Juli's Phân
 * tích screen, top to bottom. Main keyword "phân tích tiktok shop theo luồng
 * truy cập" (commercial, long tail; `/san-pham/phan-tich-shop` keeps "phân
 * tích gmv tiktok shop"). Facts: D22.2 (GMV = Lượt hiển thị × CTR × CTOR × AOV
 * (SKU), TikTok Academy "Lưu lượng truy cập sản phẩm"), `/san-pham/phan-tich-shop`
 * (five streams, tabs, 30 vs prior 30 days, ratios from totals, GMV incl.
 * cancelled / refunded, đồng mỗi ngày per tile summing to the stream, "Juli
 * gợi ý", fluctuation test, CTOR before / after cart, Rõ vs Tham khảo,
 * "Phụ thuộc sản phẩm", Khuyến mãi "giảm thật", sale days marked, cadence),
 * SPEC §3.3 (analytics once a day, self-heals gaps), D32 (lever channel),
 * D29.1 (≈ 30 clicks / orders). The product ranking table gets one paragraph
 * (its detail belongs to the problem post C6). The AOV lever is not promised
 * (D59 additions 5); no simulation, no control groups.
 */
export const body = `
Màn hình Phân tích của Juli trả lời một câu hỏi: GMV của shop đang đổi ở luồng truy cập nào, vì chỉ số nào, và do sản phẩm nào. Đọc từ trên xuống: dòng kết luận ở đầu trang cho biết luồng và chỉ số đáng để tâm nhất, mỗi luồng có một dãy bốn ô Lượt hiển thị, CTR, CTOR, AOV kèm số đồng mỗi ngày mà từng ô kéo GMV lên hay xuống, rồi đến bảng sản phẩm, phần khuyến mãi và ngày sale. Bài này đọc một màn hình mẫu từng phần, chỉ ra khi nào một con số đủ chắc để hành động, và khi nào chưa nên sửa gì.

Trang [Phân tích shop](/san-pham/phan-tich-shop) mô tả tính năng. Ở đây chúng ta đọc một màn hình cụ thể của Cửa hàng Mẫu Hoa Mai, một shop minh hoạ; mọi con số trong ảnh là dữ liệu mẫu, mọi phép tính khác ghi rõ là ví dụ giả định. Nếu shop của bạn chưa kết nối, xem trước bài [kết nối TikTok Shop với Juli](/blog/huong-dan-ket-noi-tiktok-shop-voi-juli).

## Năm luồng truy cập và vì sao đọc từng luồng

TikTok Shop ghi nhận mỗi đơn hàng đến từ đâu. Trong mục Lưu lượng truy cập sản phẩm của Trung tâm nhà bán hàng, GMV và các chỉ số phễu được chia theo năm luồng: Thẻ sản phẩm, Tab cửa hàng, Video, LIVE và Liên kết (video và LIVE của nhà sáng tạo). Juli dùng đúng cách chia đó.

Lý do rất thực tế: mỗi luồng có người xem khác nhau, lý do mua khác nhau và cách sửa khác nhau. Khách tìm kiếm rồi chạm vào Thẻ sản phẩm phản ứng với ảnh bìa, tiêu đề, giá; khách xem một video phản ứng với chính video đó. Một shop có thể tăng GMV tổng trong khi một luồng quan trọng đi xuống, và nếu chỉ nhìn số tổng, bạn sẽ không thấy cho đến khi luồng đang tăng chững lại.

Trong Juli, năm luồng được xếp vào hai tab và một chỗ riêng:

| Nơi xem | Luồng | Đọc gì trước |
|---|---|---|
| Tab Sản phẩm | Thẻ sản phẩm, Tab cửa hàng | CTR và CTOR: những gì bạn sửa được trên trang sản phẩm tác động mạnh nhất ở đây |
| Tab Nội dung | Video, LIVE | Lượt hiển thị và GMV; CTOR chỉ để tham khảo |
| Trang chủ | Liên kết | Toàn cảnh; không dùng để kết luận về một sản phẩm |

Tab cửa hàng hơi khác bốn luồng còn lại: TikTok không chia Lượt hiển thị cho luồng này, nên Juli đọc nó từ lượt nhấp trở đi.

## Dòng đầu trang: đọc "Thẻ sản phẩm: CTOR giảm 7 %"

{{hinh:hd-pt-dau-trang}}

Dòng đầu trang là kết luận của cả màn hình, gói trong một câu: luồng nào, chỉ số nào, đổi bao nhiêu. Bên cạnh là phạm vi so sánh, "30 ngày · so với 30 ngày trước". Mọi số trên màn hình là trung bình mỗi ngày của 30 ngày gần nhất, đặt cạnh trung bình mỗi ngày của 30 ngày ngay trước đó.

Ô "Juli gợi ý" ở bên phải nói chỉ số đó lấy đi bao nhiêu GMV mỗi ngày, ở đây là CTOR kéo GMV đi 250 nghìn đồng mỗi ngày, kèm nút xem các đề xuất liên quan. Bấm nút này là cách nhanh nhất để đi từ chẩn đoán sang việc cần làm. Nếu chưa muốn duyệt gì, cứ đọc tiếp xuống dưới: phần còn lại của trang giải thích vì sao Juli chọn đúng câu kết luận đó.

Hai điều nên nhớ khi đọc dòng này:

- **Tỷ lệ được tính từ tổng của kỳ.** CTR của 30 ngày bằng tổng lượt nhấp chia tổng lượt hiển thị của 30 ngày, giống cách Seller Center tính cho một khoảng ngày, không phải trung bình của các tỷ lệ hằng ngày.
- **GMV là GMV của TikTok**, gồm cả đơn đã huỷ và hoàn tiền. Juli không tự trừ bớt, để số khớp với nơi bạn vẫn đối chiếu.

## Phễu của một luồng: bốn ô và số đồng mỗi ngày

Bấm vào một luồng, Juli mở dãy ô của luồng đó. Mỗi ô là một hệ số trong công thức TikTok dùng trong Học viện người bán:

GMV = Lượt hiển thị sản phẩm × CTR × CTOR × AOV (SKU)

trong đó CTR bằng lượt nhấp chia lượt hiển thị, CTOR bằng đơn hàng SKU chia lượt nhấp, AOV (SKU) bằng GMV chia đơn hàng SKU. Nếu cần ôn lại từng khái niệm, xem [CTR, CTOR, AOV trên TikTok Shop](/blog/chi-so-tiktok-shop-ctr-ctor-aov) và [GMV là gì](/blog/gmv-la-gi-tiktok-shop).

{{hinh:hd-pt-pheu-luong}}

Điều quan trọng nhất trên dãy ô là dòng nhỏ dưới mỗi chỉ số: **số đồng mỗi ngày** mà thay đổi của chỉ số đó kéo GMV lên hoặc xuống. Phần trăm dễ đánh lừa. CTR giảm 5 % nghe nghiêm trọng hơn AOV giảm 3 %, nhưng điều đáng hỏi là mỗi thay đổi lấy đi bao nhiêu tiền. Bốn con số cộng lại bằng đúng mức thay đổi GMV của luồng.

Đọc ảnh mẫu theo cách đó: ở luồng Thẻ sản phẩm, Lượt hiển thị tăng và mang thêm khoảng 620 nghìn đồng mỗi ngày, CTR lấy đi 12 nghìn, CTOR lấy đi 250 nghìn, AOV lấy đi 105 nghìn. Cộng lại, GMV của luồng vẫn tăng 7,5 %. Nói cách khác, nhiều người thấy sản phẩm hơn đã che đi việc người bấm vào ít đặt hàng hơn. Chỉ nhìn GMV, bạn sẽ nghĩ luồng này ổn.

### Khi một ô màu xám

Không phải luồng nào cũng có đủ chỉ số có nghĩa. Ở luồng Video, CTOR và AOV phụ thuộc vào trang sản phẩm nhiều hơn là vào chính video, nên Juli để hai ô này màu xám với ghi chú "Phụ thuộc sản phẩm" và hướng bạn sang tab Sản phẩm. Khi TikTok không cung cấp một số liệu, Juli để trống và ghi rõ, không điền một con số ước đoán.

## Chỉ số kéo GMV xuống nhiều nhất, và dao động bình thường

Sau khi tách GMV thành bốn phần, Juli đánh dấu "Juli gợi ý" lên chỉ số lấy đi nhiều GMV nhất của luồng. Nhưng không phải mức giảm nào cũng được đánh dấu. Chỉ số trên TikTok Shop dao động mạnh từ ngày này sang ngày khác, nhất là với shop ít đơn. Một mức giảm chỉ được coi là đáng chú ý khi nó lớn hơn mức dao động bình thường của chính chỉ số đó, trên chính luồng đó. Nhờ vậy một tuần xấu ngẫu nhiên không bị biến thành một "vấn đề".

Lượt hiển thị được đối xử hơi khác. Nó phụ thuộc nhiều vào cách TikTok phân phối, vào mùa vụ và vào nội dung của nhà sáng tạo, trong khi chỉnh trang sản phẩm thường tác động rõ hơn đến CTR và CTOR. Juli vẫn hiện phần GMV do lượt hiển thị gây ra, nhưng khi tìm việc cụ thể để làm, Juli ưu tiên những chỉ số bạn thay đổi được.

### CTOR giảm: trước hay sau giỏ hàng

Khi CTOR là chỉ số nghẽn, Juli tách tiếp thành hai bước. Nếu tỷ lệ thêm vào giỏ hàng giảm, vấn đề nằm trước giỏ hàng: giá, hình ảnh, mô tả hoặc đánh giá chưa thuyết phục. Nếu khách vẫn thêm vào giỏ nhưng ít đặt hàng hơn, vấn đề nằm sau giỏ hàng: voucher, phí vận chuyển, hoặc khách đang chờ một đợt flash sale. Hai trường hợp dẫn đến hai loại việc rất khác nhau, nên đừng sửa mô tả khi chỗ gãy nằm ở voucher. Bài [khách xem nhưng không mua](/blog/khach-xem-nhung-khong-mua-tiktok-shop) đi sâu vào phần này.

## Từ ô chỉ số đến sản phẩm

Bấm vào một ô, Juli mở bảng chia con số của ô đó cho từng sản phẩm: chỉ số trước và nay, số đồng GMV mỗi ngày sản phẩm đó làm mất hoặc mang thêm, nhãn tin cậy, và nút "Xem đề xuất" nếu sản phẩm đã có thẻ. Các dòng cộng lại bằng đúng con số trên ô, phần nhỏ được gộp vào dòng "Còn lại". Thứ tự trong bảng cũng là thứ tự ưu tiên: sản phẩm lấy đi nhiều GMV nhất là nơi một thay đổi có thể mang lại nhiều nhất. Sản phẩm chưa đủ cơ sở để đề xuất ghi "Chưa có đề xuất", và đó là tín hiệu chờ, không phải lỗi.

## Tab Nội dung: video và LIVE

Ở tab Nội dung, Juli làm điều tương tự cho video và LIVE của shop. Với luồng Video, chỉ số thường được gợi ý là CTR: video có nhiều người thấy sản phẩm nhưng ít người bấm. Bảng bên dưới xếp những video tác động đến chỉ số đó nhiều nhất, kèm ngày đăng và sản phẩm được gắn.

{{hinh:hd-pt-video-tin-cay}}

Từ một video, bạn mở được trang của sản phẩm được gắn trong đó. Đây là một bước kiểm tra hữu ích: nếu CTOR của chính sản phẩm đó trên Thẻ sản phẩm cũng thấp, vấn đề nằm ở trang sản phẩm, không ở video. Với LIVE, Juli xếp các phiên có người xem bấm vào sản phẩm nhưng ít chốt đơn. Cách đọc phễu riêng của từng loại nội dung có trong bài [video nhiều view không ra đơn](/blog/video-tiktok-nhieu-view-khong-ra-don) và [LIVE không ra đơn](/blog/live-tiktok-shop-khong-ra-don).

## Rõ hay Tham khảo: khi nào một dòng đủ chắc

Mỗi dòng trong bảng mang một nhãn tin cậy:

- **Rõ**: cả hai kỳ có đủ đơn hàng, khoảng 30 đơn mỗi bên trở lên, và mức thay đổi nằm ngoài vùng dao động ngẫu nhiên.
- **Tham khảo**: dữ liệu còn ít, hoặc thay đổi chưa vượt khỏi mức nhiễu. Juli gợi ý theo dõi thêm thay vì kết luận.

Quy tắc thực hành: hành động trên dòng Rõ trước. Một dòng Tham khảo có thể đúng, nhưng nếu bạn sửa sản phẩm đó ngay, kết quả đo sau này cũng sẽ khó đọc. Với sản phẩm quá ít dữ liệu, Juli tìm khoảng thời gian ngắn nhất (14, 30 rồi 60 ngày) có đủ khoảng 30 lượt nhấp hoặc 30 đơn; nếu cả 60 ngày cũng không đủ, sản phẩm được ghi là ít dữ liệu và không có chẩn đoán.

## Khuyến mãi và ngày sale: đừng sửa trang khi nguyên nhân là lịch giảm giá

Rất nhiều biến động của CTOR và AOV đến từ khuyến mãi: một đợt flash sale bắt đầu, một voucher hết hạn, một ngày sale lớn của sàn. Vì vậy Juli đặt phần Khuyến mãi ngay bên dưới các luồng.

{{hinh:hd-pt-khuyen-mai}}

Ba con số ở đầu phần này đáng đọc theo thứ tự:

1. **Flash sale**: bao nhiêu ngày trong 60 ngày có flash sale, bao nhiêu sản phẩm tham gia.
2. **Giảm thật**: giá flash sale so với giá đang bán ngay trước đó, không phải so với giá niêm yết. Khi sản phẩm đã có giảm giá sản phẩm, một đợt giảm chỉ thấp hơn vài phần trăm gần như không tạo khác biệt cho người mua; Juli đánh dấu những đợt "quá nông" như vậy.
3. **Voucher**: tỷ lệ đơn đạt ngưỡng trong số voucher đang chạy, để bạn thấy voucher có thực sự được dùng.

Bảng sản phẩm so GMV mỗi ngày trong và ngoài thời gian khuyến mãi. Nếu một sản phẩm vừa hết flash sale đúng lúc CTOR giảm, hãy nghĩ đến lịch giảm giá trước khi nghĩ đến mô tả. Juli đọc khuyến mãi và voucher ở chế độ chỉ đọc; tạo hay sửa khuyến mãi vẫn do bạn làm trên Seller Center.

Ngày sale lớn như 9.9 hay 10.10 làm GMV tăng vọt rồi giảm lại. Juli không xoá những ngày này khỏi dữ liệu, mà đánh dấu trên biểu đồ để bạn biết một thay đổi lớn có trùng với ngày sale hay không. Cách đọc số sau một đợt sale có trong bài [doanh thu sau sale](/blog/doanh-thu-sau-sale-tiktok-shop).

## Số trên Juli có khớp Seller Center không

Juli dùng đúng định nghĩa của TikTok cho CTR, CTOR, AOV (SKU) và GMV, tính tỷ lệ của kỳ từ tổng của kỳ, và lấy số qua API chính thức mà bạn uỷ quyền khi kết nối, không cào trang web và không dùng số ước đoán của bên thứ ba cho phần Phân tích. Khi đối chiếu, hãy chọn cùng khoảng ngày và cùng luồng trong mục Lưu lượng truy cập sản phẩm của Trung tâm nhà bán hàng. Khác biệt nhỏ vẫn có thể xảy ra nếu hai bên chốt số liệu ở thời điểm khác nhau, nhất là với ngày gần nhất.

## Nếu thấy X thì làm Y

Bảng dưới gom các tình huống hay gặp khi đọc màn hình Phân tích và việc nên làm tiếp. Nó không thay cho thẻ đề xuất; nó giúp bạn hiểu vì sao một thẻ xuất hiện.

| Bạn thấy | Nghĩa là | Việc tiếp theo |
|---|---|---|
| GMV của luồng tăng nhưng một ô ghi số âm lớn | Một chỉ số đang giảm, bị chỉ số khác che | Đọc ô đó trước, đừng dừng ở GMV |
| CTR được gợi ý ở Thẻ sản phẩm | Người mua thấy sản phẩm nhưng ít bấm | Xem ảnh bìa, tiêu đề, giá hiển thị; đọc [đặt tên sản phẩm](/blog/dat-ten-san-pham-tiktok-shop) và [ảnh bìa](/blog/anh-bia-san-pham-tiktok-shop) |
| CTOR được gợi ý, tỷ lệ thêm vào giỏ giảm | Trang sản phẩm chưa thuyết phục | Xem mô tả, bộ ảnh, đánh giá; đọc [mô tả sản phẩm](/blog/mo-ta-san-pham-tiktok-shop) |
| CTOR được gợi ý, giỏ vẫn nhiều mà ít đơn | Vướng sau giỏ hàng | Xem voucher, phí vận chuyển, lịch flash sale |
| Lượt hiển thị giảm mạnh, các ô khác ổn | Ít chỗ xuất hiện hơn | Kiểm tra trạng thái, tồn kho, từ khoá; đọc [không có lượt hiển thị](/blog/san-pham-tiktok-shop-khong-co-luot-hien-thi) |
| Video có CTR gợi ý, sản phẩm được gắn có CTOR ổn | Video chưa làm người xem bấm | Thẻ "Juli soạn · bạn làm" cho kịch bản video |
| Dòng sản phẩm ghi Tham khảo | Chưa đủ chắc | Theo dõi thêm, chưa sửa |
| Thay đổi lớn trùng ngày sale hoặc flash sale vừa hết | Có thể do lịch giảm giá | Đọc phần Khuyến mãi trước khi sửa trang |

Khi đã chọn được việc, bước tiếp theo là [duyệt một thẻ đề xuất](/blog/duyet-de-xuat-toi-uu-san-pham-tiktok-shop), rồi [đo kết quả ở ngày 7 và ngày 14](/blog/do-ket-qua-ngay-7-ngay-14-hoan-tac). Muốn thử phễu với số của chính một sản phẩm mà chưa cần tài khoản, dùng [công cụ tính GMV](/cong-cu/tinh-gmv).

## Bao lâu số liệu được cập nhật

Báo cáo Phân tích không phải một tệp bạn phải tải về; nó nằm ngay trong Juli và được dựng lại mỗi ngày. Nhịp lấy dữ liệu:

- **Số liệu phân tích** (lượt hiển thị, lượt nhấp, đơn hàng SKU, GMV theo luồng): mỗi ngày một lần, ngay khi TikTok công bố ngày dữ liệu mới. Vì số liệu phân tích của TikTok có độ trễ, ngày mới nhất thường là hôm qua.
- **Đơn hàng, sản phẩm, tồn kho, đơn hoàn**: đồng bộ nhiều lần trong ngày.
- **Ngày bị thiếu**: nếu một lần lấy dữ liệu thất bại, lần sau Juli lấy bù từ ngày cuối cùng đã có, nên báo cáo không bị hổng.

Góc trên màn hình luôn ghi giờ cập nhật gần nhất. Xem phân tích không làm thay đổi gì trên shop: mọi thay đổi đi qua thẻ đề xuất ở trang [Đề xuất và thực thi](/san-pham/de-xuat-va-thuc-thi), được đo theo cách ở trang [Đo lường GMV](/san-pham/do-luong-gmv). Quyền đọc dữ liệu được mô tả ở trang [Kết nối TikTok Shop](/ket-noi/tiktok-shop), và tổng quan sản phẩm ở trang [Sản phẩm](/san-pham).
`;
