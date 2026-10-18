/**
 * Post (D56, P46-B1, week 1 #2): "LIVE đông người xem mà ít đơn". Main query
 * "live tiktok shop không ra đơn" (keyword-map.md); the opening says "đông
 * người xem" so it does not pull the "live ít người xem" searches it cannot
 * answer. Facts re-opened on 2026-10-17 in TikTok Academy VN:
 * - "Phân tích dữ liệu LIVE của bạn" (03/01/2023, Creator): five-stage funnel,
 *   per-minute replay, product data per 1 / 5 / 15 minutes, paid vs organic.
 * - "Cẩm nang lưu lượng LIVE" (24/07/2025, Creator): Reach / Engage / Convert
 *   metrics and their definitions (Lượt hiển thị, ERR, CTR = clicks / LIVE
 *   views, CTOR, GPM hiển thị, GPM lượt xem), ERR settles in 15–30 min, the
 *   CTR / CTOR tips, 3 worst metrics vs the last 5 sessions, review every 7 days,
 *   violations under Chất lượng nội dung.
 * - "Hiệu Suất LIVE" (21/05/2024, Seller): path, six default metrics, Hiển thị
 *   GPM, why seller and creator pages differ (last-clicked content type vs
 *   commission attribution; market vs global traffic).
 * - "Hướng dẫn sử dụng La bàn Dữ liệu trong Trung tâm Người bán" (13/12/2022):
 *   LIVE product impressions include the product list and its cards; C_O.
 * - "Tinh chỉnh GMV" (11/05/2026): direct / indirect GMV, click required, 7 days.
 * How TikTok distributes LIVE impressions is not published: the post says so
 * and claims nothing about it. Reach tier (D59): no Juli; the session log
 * uses only the Cẩm nang metrics above.
 */
export const body = `
LIVE đông người vào xem mà chốt được rất ít đơn thường có nghĩa là người xem đang dừng lại ở một bước trước khi mua: vào phòng nhưng không thấy sản phẩm, thấy sản phẩm nhưng không bấm vào, hoặc bấm vào rồi không đặt hàng. Số người xem chỉ cho biết bước đầu tiên của phễu đang ổn. Bài này đi qua phễu LIVE theo đúng các bước TikTok dùng trong La bàn dữ liệu, để bạn tìm ra chỗ tụt mạnh nhất và sửa chỗ đó trước.

Bài viết cho trường hợp buổi LIVE **có người xem** nhưng ít đơn. Nếu phòng LIVE của bạn gần như không có ai vào, vấn đề nằm ở bước Lượt hiển thị và cần một hướng đọc khác. Mọi con số trong các ví dụ là ví dụ giả định.

## LIVE đông người xem mà ít đơn: tách người xem khỏi người mua

"Live hai ba tiếng, người vào đông mà không chốt được đơn nào", "host nói hoài mà khách không mua": những câu này trộn hai nhóm người khác nhau, **người xem** và **người mua**.

Trong Cẩm nang lưu lượng LIVE của Học viện TikTok Shop (cập nhật 24/07/2025), chỉ số LIVE được chia thành ba góc độ:

- **Phạm vi tiếp cận**: Lượt hiển thị, Lượt xem, Người xem, Thời lượng xem trung bình, Tỷ lệ vào phòng (ERR).
- **Tương tác**: Tỷ lệ bình luận, Tỷ lệ theo dõi, Tỷ lệ chia sẻ, Tỷ lệ thích.
- **Chuyển đổi**: CTR, CTOR, GPM hiển thị, GPM lượt xem.

"Đông người xem" là chuyện của góc độ thứ nhất. Đơn hàng nằm ở góc độ thứ ba. Một buổi LIVE có thể rất tốt ở phạm vi tiếp cận và tương tác mà vẫn yếu ở chuyển đổi, và đó chính là tình huống "đông mà ít đơn".

{{hinh:live-ba-goc-do}}

## Phễu LIVE của TikTok gồm những bước nào

Bài "Phân tích dữ liệu LIVE của bạn" của Học viện TikTok Shop mô tả phễu chuyển đổi của một buổi LIVE với năm giai đoạn:

1. **Lượt hiển thị của buổi LIVE**: số lần LIVE của bạn được hiển thị với mọi người.
2. **Tham gia LIVE**: số người đã vào buổi LIVE.
3. **Lượt hiển thị sản phẩm**: lượt hiển thị của sản phẩm trong buổi LIVE. Trang hướng dẫn La bàn dữ liệu nói rõ hơn: số lần hiển thị sản phẩm trong LIVE, bao gồm hiển thị danh sách sản phẩm và thẻ danh sách sản phẩm.
4. **Lượt nhấp vào sản phẩm**: số lần người xem nhấp vào sản phẩm.
5. **Đơn hàng đã được thanh toán**: số đơn hàng đã thanh toán.

Theo TikTok, biết bạn mất người mua tiềm năng ở giai đoạn nào thì biết cần cải thiện ở đâu. Hãy so tỷ lệ giữa hai bước liền nhau với các buổi LIVE trước của chính bạn.

{{hinh:live-pheu}}

### Xem phễu LIVE ở đâu

Có hai nơi, tùy bạn dùng tài khoản nào:

- **Trung tâm nhà bán hàng**: theo bài "Hiệu Suất LIVE", vào La bàn dữ liệu, LIVE & Video, LIVE, rồi chọn Hiệu suất LIVE. Mặc định có sáu chỉ số: GMV, Đơn hàng, Người mua, Lượt mua, Tỷ lệ CO và CTR; bạn có thể thêm Lượt xem LIVE, Thời gian xem trung bình, Hiển thị GPM. Mục Chi tiết LIVE liệt kê từng buổi LIVE để so sánh.
- **Streamer Desktop**: La bàn dữ liệu, Phân tích buổi LIVE, nơi có tab Người xem với phễu năm bước ở trên.

Cùng một buổi LIVE có thể cho số khác nhau ở hai nơi: theo phần câu hỏi thường gặp của bài "Hiệu Suất LIVE", phía nhà bán hàng ghi nhận GMV cho loại nội dung được bấm vào cuối cùng trước khi chốt đơn, còn phía nhà sáng tạo ghi nhận theo hoa hồng; lưu lượng phía nhà bán hàng tính theo thị trường của shop, phía nhà sáng tạo tính toàn cầu. Hãy chọn một nơi và luôn so trên nơi đó.

## Lượt hiển thị và Tỷ lệ vào phòng: người vào phòng có đúng người không

Cẩm nang lưu lượng LIVE định nghĩa **Lượt hiển thị** là số lần buổi LIVE được hiển thị với khán giả trên trang Dành cho bạn, và **Tỷ lệ vào phòng (ERR)** là số lượt xem chia cho số lượt hiển thị của phòng LIVE. Cẩm nang lưu ý ERR cần khoảng 15 đến 30 phút đầu để ổn định, nên đừng đánh giá cả buổi theo vài phút mở đầu.

Với tình huống "đông người xem", ERR thường không phải bước yếu nhất. Nhưng nó cho một gợi ý quan trọng về **tệp người xem**: trang "Phân tích dữ liệu LIVE của bạn" có tab Hồ sơ người dùng, cho xem độ tuổi, giới tính của người xem và người mua, người theo dõi và người chưa theo dõi. Nếu người vào phòng rất khác người thường mua sản phẩm bạn đang bán, phòng có thể đông mà đơn vẫn ít.

## Vào phòng rồi nhưng không thấy sản phẩm

Bước từ Tham gia LIVE đến Lượt hiển thị sản phẩm là bước người bán hay bỏ qua. Người xem vào phòng, nghe host nói, nhưng sản phẩm không hiện ra trước mắt họ đủ thường xuyên.

Cẩm nang lưu lượng LIVE khuyên:

- Luôn có **ít nhất một**, tốt hơn là nhiều sản phẩm được ghim trong buổi LIVE, để giới thiệu ngay các sản phẩm chủ lực.
- **Thường xuyên sắp xếp lại Túi mua sắm**, đưa sản phẩm được quan tâm nhiều hơn lên trên, ưu tiên sản phẩm từng là chủ lực, thuộc danh mục cốt lõi hoặc đang là xu hướng.
- Thêm các sản phẩm cùng chủ đề vào Túi mua sắm để người xem có nhiều lựa chọn hơn và ở lại lâu hơn.

LIVE hai tiếng mà chỉ ghim sản phẩm vài phút thì Lượt hiển thị sản phẩm sẽ thấp so với số người vào phòng.

## Thấy sản phẩm mà không bấm vào

Đây là bước tụt mạnh nhất trong ví dụ giả định ở trên: 3.600 lượt hiển thị sản phẩm mà chỉ 90 lượt nhấp. Có một chi tiết cần biết trước khi so số: Cẩm nang lưu lượng LIVE tính **CTR trong LIVE** bằng lượt bấm vào sản phẩm chia cho lượt xem LIVE, khác với CTR của thẻ sản phẩm (lượt nhấp chia cho lượt hiển thị sản phẩm). Vì vậy đừng so CTR của LIVE với CTR của thẻ sản phẩm; hãy so với các buổi LIVE trước của chính bạn.

Cẩm nang gợi ý liên tục dẫn dắt người xem bấm vào sản phẩm được ghim và Túi mua sắm, định kỳ chỉ cho họ thấy vị trí các nút này trên màn hình. Ngoài ra, hãy tự kiểm tra: giá và ưu đãi host nói có khớp với giá hiển thị trên sản phẩm không, và sản phẩm được ghim có còn hàng ở biến thể khách hỏi nhiều nhất không. Bình luận hỏi giá, hỏi size mà host không trả lời kịp cũng là lý do người xem không bấm.

## Bấm vào sản phẩm nhưng không đặt hàng

Nếu người xem bấm vào khá nhiều mà đơn vẫn ít, bước yếu là **CTOR**: Cẩm nang định nghĩa là số đơn hàng SKU chia cho lượt bấm vào sản phẩm trong buổi LIVE. Tùy trang, chỉ số tương tự có thể hiện với tên Tỷ lệ CO hay C_O; trang hướng dẫn La bàn dữ liệu ghi C_O là đơn đặt hàng chia cho số lần nhấp vào sản phẩm qua kênh phát trực tiếp.

Cẩm nang gợi ý cho CTOR: tạo cảm giác cấp bách bằng cách nhấn mạnh hàng còn lại trong kho và giới hạn của chương trình ưu đãi; đưa vào các sản phẩm cùng chủ đề và các sản phẩm nằm trong mức AOV để vượt qua rào cản về giá.

Bấm vào sản phẩm trong LIVE vẫn dẫn về trang sản phẩm, nên những gì trên trang cũng quyết định đơn: ảnh, mô tả, đánh giá, giá, phí vận chuyển. Nếu CTOR của cùng sản phẩm ở luồng Thẻ sản phẩm cũng thấp, vấn đề nằm ở trang chứ không ở buổi LIVE. Bài [TikTok Shop không ra đơn](/blog/tiktok-shop-khong-ra-don) có danh sách kiểm tra trang sản phẩm theo từng bước, và bài [các chỉ số TikTok Shop](/blog/chi-so-tiktok-shop-ctr-ctor-aov) giải thích cách đọc CTOR theo luồng.

## GPM hiển thị: đo hiệu quả theo 1.000 lượt hiển thị

Đếm người xem thưởng cho buổi đông người chứ không cho buổi bán tốt. Cẩm nang lưu lượng LIVE đưa ra hai chỉ số khác:

- **GPM hiển thị**: GMV tạo ra từ phòng LIVE trên mỗi 1.000 lượt hiển thị của buổi LIVE.
- **GPM lượt xem**: GMV trên mỗi 1.000 lượt xem.

Cẩm nang cho rằng GPM hiển thị cao là chỉ số tốt hơn để phản ánh chuyển đổi lưu lượng, tương tự như lượt hiển thị phản ánh hiệu suất lưu lượng tốt hơn lượt xem. Khi so hai buổi LIVE, hãy so GPM hiển thị trước, rồi mới nhìn số người xem.

{{hinh:live-gpm}}

GMV của LIVE trên Trung tâm nhà bán hàng cũng theo cách ghi nhận mới. Bài "Tinh chỉnh GMV" (cập nhật 11/05/2026) chia GMV của mỗi loại nội dung thành trực tiếp và gián tiếp: người xem phải xem LIVE và bấm vào link sản phẩm thì buổi LIVE mới được xét ghi nhận, và đơn đặt sau đó trong vòng 7 ngày có thể được tính là gián tiếp. Vì vậy GMV của một buổi LIVE có thể còn tăng vài ngày sau khi buổi đó kết thúc; đánh giá ngay sau buổi là đọc sớm.

## Đọc số liệu theo từng phút: lúc nào người xem rời đi

Số tổng của cả buổi che mất diễn biến bên trong. Bài "Phân tích dữ liệu LIVE của bạn" cho phép phát lại buổi LIVE và xem theo thời gian: lúc nào giao dịch diễn ra, bao nhiêu người vào và rời phòng, mức tương tác, lượt nhấp vào sản phẩm và đơn hàng. Tab Sản phẩm cho xem sản phẩm bán được theo từng khoảng 1, 5 hoặc 15 phút.

Cẩm nang lưu lượng LIVE gợi ý: trong khi LIVE, theo dõi xu hướng Lượt hiển thị và ERR, nhất là lúc đổi sản phẩm ghim, chạy flash sale hay tặng phẩm. Sau khi LIVE, tìm 3 chỉ số kém nhất và so với 5 buổi gần đây; nếu cả ba cùng thuộc một góc độ, đó là chỗ của vấn đề trong phễu. Với những đoạn chỉ số giảm đột ngột, hỏi sản phẩm nào đang được ghim, ưu đãi nào đang chạy, có vi phạm nào không. Và xem lại dữ liệu cấp tài khoản ít nhất 7 ngày một lần.

{{hinh:live-trong-sau}}

## Điều chỉnh gì trước, đo thế nào sau 7 và 14 ngày

Khi đã biết bước tụt mạnh nhất, hãy chọn **một** điều chỉnh cho buổi LIVE tiếp theo:

| Bước yếu nhất | Điều chỉnh cho buổi sau | Đo bằng |
|---|---|---|
| Vào phòng nhưng ít lượt hiển thị sản phẩm | Ghim sản phẩm suốt buổi, sắp lại Túi mua sắm | Lượt hiển thị sản phẩm so với Lượt xem |
| Thấy sản phẩm mà không bấm | Lời dẫn mời bấm, thứ tự giới thiệu sản phẩm | CTR của LIVE |
| Bấm mà không đặt | Ưu đãi có hạn, trang sản phẩm, giá | CTOR (Tỷ lệ CO) |
| Có đơn nhưng GMV thấp | Sản phẩm cùng chủ đề, ưu đãi mua nhiều | GPM hiển thị, AOV |

Một buổi LIVE là một mẫu nhỏ: giờ phát, ngày trong tuần, sản phẩm bán đều làm số thay đổi. Hãy so nhiều buổi cùng khung giờ, và đọc kết quả của một thay đổi ở ngày 7 (sơ bộ) và ngày 14 (chốt) thay vì sau một buổi.

Một câu hay gặp là "TikTok có bóp LIVE không". Học viện TikTok Shop không công bố cách phân phối lượt hiển thị cho buổi LIVE, nên bài này không kết luận về điều đó. Điều Cẩm nang có nêu: khi muốn đánh giá tác động lưu lượng do vi phạm, hãy xem Tổng quan dữ liệu LIVE, Xu hướng hiệu suất, Chất lượng nội dung, và đối chiếu với Chính sách nội dung TikTok Shop.

## Sổ theo dõi các buổi LIVE

Lời khuyên "so 3 chỉ số kém nhất với 5 buổi gần đây" của Cẩm nang chỉ làm được khi bạn có số của các buổi trước. Một bảng tính đơn giản, mỗi buổi LIVE một dòng, ghi ngay sau buổi:

1. **Thông tin buổi**: ngày, khung giờ, thời lượng, các sản phẩm chính được ghim.
2. **Năm bước của phễu**: Lượt hiển thị LIVE, Lượt xem, Lượt hiển thị sản phẩm, Lượt nhấp vào sản phẩm, Đơn hàng.
3. **Các tỷ lệ**: ERR, CTR của LIVE, CTOR, GPM hiển thị.
4. **Một cột thay đổi**: điều chỉnh duy nhất bạn thử ở buổi đó, ví dụ thứ tự giới thiệu sản phẩm hay ưu đãi có hạn.
5. **Một cột ba chỉ số kém nhất** so với trung bình 5 buổi gần nhất.

Ví dụ giả định: ba buổi liền có CTR và CTOR kém nhất, còn Lượt xem vẫn như các buổi trước. Cả hai chỉ số thuộc nhóm Chuyển đổi, nên buổi sau giữ nguyên khung giờ và thử một điều chỉnh ở lời dẫn mời bấm, thay vì tìm cách kéo thêm người xem.

Sau một hai tuần, bảng cho bạn mốc của chính shop để đọc mọi buổi sau. Để ước tính GMV đổi bao nhiêu khi một bước của phễu tăng, thử [công cụ tính GMV miễn phí](/cong-cu/tinh-gmv). Nếu bạn bán chủ yếu bằng video ngắn, bài [video nhiều view nhưng không ra đơn](/blog/video-tiktok-nhieu-view-khong-ra-don) đi qua luồng Video theo cùng cách, còn bài [GMV là gì](/blog/gmv-la-gi-tiktok-shop) giải thích cách tách GMV theo luồng.

## Tóm tắt

- Đông người xem là chuyện của Phạm vi tiếp cận; đơn hàng nằm ở nhóm Chuyển đổi.
- Tìm bước tụt mạnh nhất trong năm bước của phễu LIVE, so với các buổi trước của chính bạn.
- CTR trong LIVE tính trên lượt xem LIVE, không so với CTR của thẻ sản phẩm.
- So các buổi LIVE bằng GPM hiển thị, không chỉ bằng số người xem.
- Sau mỗi buổi, tìm 3 chỉ số kém nhất; chọn một điều chỉnh cho buổi sau và đo lại ở ngày 7, ngày 14.

Trước khi lên LIVE bán hàng, bài [Quy định livestream bán hàng](/blog/quy-dinh-livestream-ban-hang) tóm tắt những gì luật và TikTok Shop yêu cầu với người bán và người livestream.
`;
