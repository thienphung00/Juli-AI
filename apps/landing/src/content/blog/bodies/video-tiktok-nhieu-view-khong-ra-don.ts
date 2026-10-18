/**
 * Post (D56, P46-B1, week 1 #1): "Video nhiều lượt xem nhưng không ra đơn".
 * Main query "video tiktok nhiều view không ra đơn" (keyword-map.md); it must
 * not compete with `tiktok-shop-khong-ra-don` ("tiktok shop không ra đơn"),
 * which it links to. Facts re-opened on 2026-10-17 in TikTok Academy VN:
 * - "Tinh chỉnh GMV" (11/05/2026): GMV by content type and order source,
 *   direct vs indirect GMV, a view counts only with a click on the product link,
 *   7 days, last touch.
 * - "Lưu lượng truy cập sản phẩm" (17/06/2026): path, funnel metrics, CTOR
 *   rename, content-type filters (Video cá nhân → Chi tiết video), AOV (SKU).
 * - "Hướng dẫn sử dụng La bàn Dữ liệu trong Trung tâm Người bán" (13/12/2022):
 *   Phân tích Video lists VV next to Lượt hiển thị Sản phẩm and Lượt nhấp vào
 *   Sản phẩm.
 * - "Phân Tích Hiệu Suất Video - Hướng Dẫn cho Nhà Sáng Tạo" (22/03/2024):
 *   Tỷ lệ xem hết, viewer profile, "GMV đến từ" = last clicked content type.
 * Nothing here describes how TikTok distributes views or impressions (not
 * published). Reach tier (D59): no Juli; the weekly sheet uses only the
 * Seller Center fields above. Numbers in examples are hypothetical and say so.
 */
export const body = `
Video lên cả trăm nghìn lượt xem mà shop gần như không có đơn thường không phải vì video dở, mà vì lượt xem chưa phải là đơn hàng. Giữa một lượt xem và một đơn hàng còn bốn bước: sản phẩm có hiện ra trước người xem không (Lượt hiển thị sản phẩm), người xem có bấm vào sản phẩm không (CTR), bấm vào rồi có đặt hàng không (CTOR), và mỗi đơn đáng bao nhiêu tiền (AOV). Bài này giúp bạn đọc số liệu của chính video đó để biết nó đang gãy ở bước nào, rồi mới quyết định sửa video hay sửa trang sản phẩm.

Mọi con số trong các ví dụ là ví dụ giả định. Nếu shop của bạn không ra đơn ở mọi luồng chứ không chỉ ở video, hãy đọc bài [TikTok Shop không ra đơn: đọc phễu để tìm nguyên nhân](/blog/tiktok-shop-khong-ra-don) trước.

## Nhiều view mà không có đơn: lượt xem chưa phải là đơn hàng

"Video viral mà doanh thu không tăng", "người ta vào xem, bình luận đủ thứ mà không ai hỏi mua": lý do đầu tiên là lượt xem video và đơn hàng nằm ở hai chỗ khác nhau trong La bàn dữ liệu.

Trang "Hướng dẫn sử dụng La bàn Dữ liệu trong Trung tâm Người bán" của Học viện TikTok Shop mô tả mục Phân tích Video với các số liệu lưu lượng truy cập gồm VV (lượt xem video), lượt thích, bình luận, lượt chia sẻ, **Lượt hiển thị Sản phẩm** và **Lượt nhấp vào Sản phẩm**. Cùng một video có con số của nội dung (xem, thích, bình luận) và con số của sản phẩm gắn trong video. Đơn hàng chỉ đi theo nhánh thứ hai, theo công thức GMV của mỗi luồng truy cập:

**GMV = Lượt hiển thị sản phẩm × CTR × CTOR × AOV**

Lượt xem video không có mặt trong công thức này: video rất được xem mà sản phẩm ít người bấm vào thì vẫn không thành đơn.

{{hinh:video-view-den-don}}

### Một video viral có phải là vấn đề không

Không hẳn. Trang hướng dẫn cho nhà sáng tạo của TikTok coi lượt xem cao kèm nhiều người theo dõi mới là dấu hiệu nhận biết thương hiệu. Vấn đề chỉ xuất hiện khi video được làm **để bán** một sản phẩm mà số đơn không theo kịp. Khi đó câu hỏi đúng là "video đang gãy ở bước nào".

## Đơn từ video được tính thế nào: trực tiếp và trong 7 ngày

Trước khi kết luận, hãy chắc rằng bạn đọc đúng con số. Bài "Tinh chỉnh GMV" của Học viện TikTok Shop (cập nhật 11/05/2026) cho biết từ giữa tháng 4/2026, GMV được phân tích theo nguồn đơn hàng (Tiếp thị liên kết hay Nhà bán hàng) và theo loại nội dung (LIVE, video ngắn, thẻ sản phẩm), và chia thành hai phần:

- **GMV trực tiếp**: người dùng xem video có link sản phẩm, nhấp vào link, thêm vào giỏ và hoàn tất mua hàng ngay. Đơn này thuộc phần trực tiếp của GMV video.
- **GMV gián tiếp**: người dùng xem video, nhấp vào sản phẩm nhưng chưa mua; sau đó họ tự tìm sản phẩm trong TikTok Shop và mua. Đơn này được ghi vào GMV video gián tiếp. Theo phần câu hỏi thường gặp của bài, đơn có thể được đóng góp bởi một video khách đã xem trong vòng 7 ngày.

Hai chi tiết trong bài đó rất quan trọng với người bán:

1. **Chỉ xem mà không bấm vào link sản phẩm thì không được tính.** TikTok ghi rõ người dùng phải xem video hoặc LIVE và bấm vào link sản phẩm thì lượt tương tác đó mới được xét để ghi nhận.
2. **Đơn được ghi cho nội dung cuối cùng.** Nếu khách xem nhiều video và LIVE của shop rồi mới mua, đơn được ghi nhận theo điểm tiếp xúc cuối cùng.

Hệ quả: video nhiều lượt xem mà ít người bấm vào sản phẩm sẽ có ít GMV video, kể cả phần gián tiếp. Còn GMV video ở một ngày không đăng video nào là bình thường, vì đơn có thể đến từ video khách đã xem trong 7 ngày trước.

{{hinh:video-truc-tiep-gian-tiep}}

## Đơn gãy ở bước nào: Lượt hiển thị, CTR, CTOR hay AOV

Mỗi bước có nguyên nhân và cách sửa riêng, nên trước hết phải tìm đúng bước.

### Xem số liệu video ở đâu

Theo bài "Lưu lượng truy cập sản phẩm" của Học viện TikTok Shop (cập nhật 17/06/2026), phễu của từng sản phẩm nằm tại Trung tâm nhà bán hàng, La bàn dữ liệu, Số liệu phân tích sản phẩm, trang Lưu lượng truy cập sản phẩm. Ở đầu trang, bạn chọn loại nội dung. Khi chọn Video cá nhân, danh sách video và số liệu tương ứng hiện ra, và nút Xem đưa bạn tới trang Chi tiết video. Phễu hiển thị Lượt hiển thị sản phẩm, Lượt nhấp vào sản phẩm, Đơn hàng SKU, CTR và CTOR của sản phẩm.

Chọn khoảng thời gian đủ dài, ví dụ 28 ngày, và cộng tổng lượt hiển thị, lượt nhấp, đơn hàng của cả kỳ rồi mới tính tỷ lệ.

### Bảng triệu chứng

| Bạn thấy | Bước nghi ngờ | Xem trước |
|---|---|---|
| Lượt xem cao, Lượt hiển thị sản phẩm thấp | Sản phẩm ít được nhìn thấy | Sản phẩm có được gắn vào video không, video có nói về sản phẩm không |
| Lượt hiển thị sản phẩm ổn, CTR thấp | Thấy mà không bấm | Video có cho thấy rõ sản phẩm, công dụng, giá không |
| CTR ổn, CTOR thấp | Bấm vào mà không mua | Trang sản phẩm: ảnh, mô tả, đánh giá, giá, phí vận chuyển |
| Có đơn, GMV vẫn thấp | AOV thấp | Biến thể khách chọn, ưu đãi mua nhiều |

Mốc so sánh đúng là chính video đó ở kỳ trước và các video khác của shop gắn cùng sản phẩm, trên cùng luồng Video. TikTok không công bố một mức CTR hay CTOR chuẩn chung cho mọi ngành, nên đừng so với con số bạn đọc được ở nơi khác.

{{hinh:video-trieu-chung}}

## View cao nhưng ít người bấm vào sản phẩm

Đây là trường hợp hay gặp nhất khi video "viral mà không bán được": người xem thích nội dung nhưng không thấy lý do để bấm vào sản phẩm. Dấu hiệu là Lượt hiển thị sản phẩm của video tăng mà CTR giảm, so với các video trước của chính bạn.

Những câu hỏi nên tự đặt khi xem lại video:

- **Sản phẩm xuất hiện lúc nào?** Nếu ba phần tư video là phần giải trí và sản phẩm chỉ hiện ở cuối, nhiều người xem có thể đã lướt đi trước khi kịp thấy nó.
- **Người xem có hiểu sản phẩm là gì, dùng để làm gì, giá bao nhiêu không?** Một video kể chuyện hay nhưng không nói rõ ba điều này thường được xem nhiều mà ít người bấm.
- **Tên và giá hiển thị của sản phẩm có khớp với điều video hứa không?** Người xem thấy một mức giá trong video và một mức khác khi sản phẩm hiện ra sẽ ngần ngại bấm vào.
- **Sản phẩm gắn trong video có đúng là sản phẩm được nói đến không?** Gắn nhầm sản phẩm, hoặc gắn một sản phẩm đã hết các biến thể chính, là lỗi nhỏ nhưng làm mất đơn.

Ở bước này, sửa trang sản phẩm ít giúp, vì người xem chưa vào tới trang. Việc cần làm nằm ở video: cách mở đầu, thời điểm giới thiệu sản phẩm, lời nói về công dụng và giá. Bài [các chỉ số TikTok Shop: Lượt hiển thị, CTR, CTOR, AOV](/blog/chi-so-tiktok-shop-ctr-ctor-aov) giải thích kỹ hơn vì sao CTR của từng luồng phải đọc riêng.

## Bấm vào nhiều nhưng không mua

Nếu CTR của video ổn mà CTOR thấp, nghĩa là video đã làm tốt việc của nó: người xem đủ quan tâm để bấm vào. Họ rời đi ở trang sản phẩm. Mọi lượt bấm, dù từ video, LIVE hay tìm kiếm, đều dẫn về cùng một trang sản phẩm, nên hãy kiểm tra xem CTOR ở luồng Thẻ sản phẩm có thấp tương tự không. Nếu có, vấn đề nằm ở trang chứ không ở video.

Những chỗ thường làm khách rời đi:

- Bộ ảnh không trả lời câu hỏi khách vừa có khi xem video: kích thước thật, chất liệu, màu thật của biến thể.
- Mô tả thiếu thông tin hoặc khác với điều video nói.
- Ít đánh giá, hoặc đánh giá gần đây thấp.
- Giá trên trang khác giá khách nghe trong video, hoặc ưu đãi đã hết hạn.
- Phí vận chuyển hiện ra ở bước thanh toán cao hơn khách nghĩ.

## Có đơn nhưng doanh thu vẫn ít

Trường hợp thứ ba ít được để ý: video ra đơn đều, nhưng GMV vẫn thấp vì mỗi đơn có giá trị nhỏ. TikTok định nghĩa **AOV (SKU)** là số tiền trung bình khách thanh toán cho một đơn hàng SKU trong khoảng thời gian đã chọn.

AOV thấp ở luồng Video thường đến từ:

- Video nói về biến thể rẻ nhất, nên khách chọn đúng biến thể đó.
- Không có ưu đãi mua nhiều, mua theo gói hay quà tặng kèm để khách thêm món thứ hai.
- Sản phẩm chính trong video có giá thấp so với các sản phẩm khác của shop.

Nếu bạn muốn ước tính nhanh GMV thay đổi ra sao khi một trong bốn hệ số đổi, hãy thử [công cụ tính GMV](/cong-cu/tinh-gmv) với số liệu của chính video đó.

## Video viral nhưng sai tệp khách: nhận ra thế nào

Một video có thể được xem nhiều bởi những người không phải là khách của sản phẩm: video hài về mỹ phẩm được nam sinh viên xem nhiều, video dụng cụ bếp được trẻ em xem vì đoạn mở đầu vui. Bạn không cần đoán. Có ba cách kiểm tra:

1. **Đọc bình luận.** Bình luận hỏi về sản phẩm (giá, size, giao hàng) là tín hiệu khác hẳn bình luận chỉ khen nội dung hay gắn tên bạn bè.
2. **Xem hồ sơ người xem.** Theo trang "Phân Tích Hiệu Suất Video" dành cho nhà sáng tạo của Học viện TikTok Shop, phần Hồ sơ video cho xem độ tuổi, giới tính, khu vực của người xem video trong khoảng thời gian đã chọn. So với hồ sơ của người mua sản phẩm đó.
3. **So CTR với video khác.** Video sai tệp thường có CTR thấp hơn hẳn các video khác gắn cùng sản phẩm, dù Lượt hiển thị sản phẩm cao hơn.

Nếu cả ba dấu hiệu cùng xuất hiện, đó là video giải trí tốt nhưng không phải video bán sản phẩm này. Giữ nó cho tài khoản, và làm video khác nhắm đúng người cần sản phẩm.

## Nên sửa gì trước và đo kết quả sau 7, 14 ngày

Khi đã biết bước gãy, hãy sửa **một chỗ** mỗi lần: làm video mới nếu CTR thấp, hoặc sửa trang sản phẩm nếu CTOR thấp, không làm cả hai cùng lúc. Ghi ngày bắt đầu, đọc sơ bộ ở ngày 7 và chốt ở ngày 14: giữ thay đổi, sửa tiếp, hoặc quay lại bản cũ. Nếu đổi video, giá, ảnh và mô tả trong cùng một tuần, bạn sẽ không biết điều gì có tác dụng. Video mới thì so với các video trước của cùng sản phẩm; thay đổi trên trang thì so cùng sản phẩm trước và sau ngày đổi.

{{hinh:video-sua-va-do}}

## Những điều không nên làm khi video vừa viral

- **Đừng đổi giá ngay trong lúc video đang được xem nhiều.** Người xem vừa nghe một mức giá trong video; giá trên trang khác đi sẽ làm CTOR giảm thêm.
- **Đừng vội mua thêm người xem cho video khi CTR đang thấp.** Thêm người xem không làm họ bấm vào sản phẩm nhiều hơn. Bài [TikTok Shop không ra đơn](/blog/tiktok-shop-khong-ra-don) có một ví dụ giả định cho thấy vì sao nên sửa phễu trước khi mua thêm traffic.
- **Đừng kết luận sau một hai ngày.** Đơn gián tiếp có thể đến trong 7 ngày sau khi khách xem video.
- **Đừng xóa video chỉ vì ít đơn.** Nó vẫn có thể mang lại lượt hiển thị cho sản phẩm và người theo dõi cho tài khoản.

Nếu video bán hàng của bạn chủ yếu là LIVE chứ không phải video ngắn, bài [LIVE đông người xem mà ít đơn](/blog/live-tiktok-shop-khong-ra-don) đi qua phễu riêng của LIVE.

## Bảng theo dõi video mỗi tuần

Bạn có thể tự làm phần đọc số trong bài này bằng một bảng tính, cập nhật mỗi tuần từ mục Phân tích Video và trang Chi tiết video trong La bàn dữ liệu:

1. **Mỗi video một dòng**: ngày đăng và sản phẩm được gắn.
2. **Các cột số của 7 ngày**: lượt xem video, Lượt hiển thị sản phẩm, Lượt nhấp vào sản phẩm, Đơn hàng SKU. Tự tính CTR và CTOR từ tổng, không lấy trung bình theo ngày.
3. **Một cột so sánh**: CTR của video so với các video khác gắn cùng sản phẩm. Video có CTR thấp hơn hẳn là video cần xem lại trước.
4. **Một cột kết luận**: "sửa video" khi CTR thấp, "sửa trang" khi CTOR thấp ở mọi video của sản phẩm đó, "xem AOV" khi có đơn mà GMV vẫn thấp.

Ví dụ giả định: video A có 80.000 lượt xem, 12.000 Lượt hiển thị sản phẩm và CTR 0,8 %; video B gắn cùng sản phẩm có 15.000 lượt xem, 4.000 Lượt hiển thị sản phẩm và CTR 2,5 %. Video A nhiều view hơn, nhưng video B mới là cách nói về sản phẩm mà người xem chịu bấm. Video tiếp theo nên học từ B.

Thêm một cột ngày cho mỗi thay đổi bạn làm, để lúc đọc ở ngày 7 và ngày 14 biết đang đo thay đổi nào. Cách tách GMV theo luồng và theo bốn chỉ số có trong bài [GMV là gì](/blog/gmv-la-gi-tiktok-shop).

## Tóm tắt

- Lượt xem video không nằm trong công thức GMV. Đơn hàng đi qua Lượt hiển thị sản phẩm, CTR, CTOR và AOV.
- Video chỉ được tính đơn khi người xem đã bấm vào link sản phẩm, mua ngay (trực tiếp) hoặc trong 7 ngày sau (gián tiếp).
- View cao mà CTR thấp: sửa video. CTR ổn mà CTOR thấp: sửa trang sản phẩm. Có đơn mà GMV thấp: xem AOV.
- Kiểm tra tệp khách, sửa một chỗ mỗi lần, đo lại ở ngày 7 và ngày 14.

Nếu người xem bấm vào sản phẩm mà vẫn không mua, bài [Khách xem nhưng không mua](/blog/khach-xem-nhung-khong-mua-tiktok-shop) đi sâu vào phần sau cú nhấp.
`;
