/**
 * Pillar post 1 (D43.7): TikTok Shop metrics. Facts about TikTok's metrics are
 * from TikTok Academy VN, "Lưu lượng truy cập sản phẩm" (17/06/2026) unless a
 * paragraph names another page. Every number in a "Ví dụ" is hypothetical and
 * says so. Juli's method: docs/adr/106, docs/adr/108.
 */
export const body = `
Nếu bạn bán hàng trên TikTok Shop, mỗi sáng bạn mở Trung tâm nhà bán hàng và thấy hàng chục con số: GMV, Lượt hiển thị sản phẩm, Lượt nhấp vào sản phẩm, CTR, CTOR, Đơn hàng SKU, AOV, Tỷ lệ thêm vào giỏ hàng, cùng các phiên bản "độc nhất" của chúng. Mỗi con số đều đúng, nhưng đọc từng con số riêng lẻ rất dễ dẫn đến kết luận sai: GMV tăng nên tưởng mọi thứ đều tốt, CTOR toàn shop đi ngang nên tưởng trang sản phẩm không có vấn đề, CTR giảm nên vội đổi ảnh bìa trong khi nguyên nhân nằm ở nguồn traffic.

Bài viết này giải thích bốn chỉ số cốt lõi theo đúng định nghĩa TikTok công bố trên Học viện TikTok Shop, cách chúng ghép lại thành một công thức phễu, cách đọc chúng theo từng kênh, những cách đọc sai phổ biến nhất, và việc nên làm khi phễu bị nghẽn ở từng bước. Mọi tên chỉ số trong bài dùng đúng cách gọi tiếng Việt trên Trung tâm nhà bán hàng để bạn có thể đối chiếu ngay trên tài khoản của mình.

## Vì sao cần đọc chỉ số theo phễu, không theo cảm giác

GMV là kết quả cuối cùng, không phải nguyên nhân. Khi GMV giảm, câu hỏi hữu ích không phải là "làm sao tăng doanh thu" mà là "doanh thu giảm ở bước nào": ít người nhìn thấy sản phẩm hơn, người thấy nhưng ít người nhấp hơn, người nhấp nhưng ít người đặt hàng hơn, hay mỗi đơn có giá trị thấp hơn. Mỗi bước có những đòn bẩy khác nhau. Đổi ảnh bìa giúp ích khi người xem không nhấp, nhưng gần như vô dụng khi người nhấp rồi bỏ đi vì giá. Thêm voucher giúp ích khi khách đã vào trang nhưng chần chừ, nhưng không kéo thêm người nhìn thấy sản phẩm.

Đọc theo phễu giúp bạn làm ba việc:

- **Khoanh vùng**: biết chính xác bước nào đang yếu thay vì sửa mọi thứ cùng lúc.
- **Ưu tiên**: chọn một hành động có khả năng tác động lớn nhất lên bước yếu nhất.
- **Đo lại**: sau khi thay đổi, biết nên nhìn vào chỉ số nào để biết thay đổi có hiệu quả hay không.

Học viện TikTok Shop cũng hướng dẫn theo tinh thần này. Trang "Lưu lượng truy cập sản phẩm" mô tả mô-đun phân tích được thiết kế "để giúp người bán hiểu rõ lưu lượng truy cập sản phẩm của họ đến từ đâu, hiệu quả chuyển đổi của từng giai đoạn trong phễu và kênh lưu lượng truy cập nào đóng góp nhiều nhất". Bạn tìm thấy nó tại Trung tâm nhà bán hàng → La bàn dữ liệu → Số liệu phân tích sản phẩm → Lưu lượng truy cập sản phẩm.

## Bốn chỉ số cốt lõi theo đúng định nghĩa của TikTok

Năm 2026, TikTok cập nhật bộ chỉ số phân tích sản phẩm cho thống nhất hơn: một số chỉ số đổi tên, một số đổi định nghĩa, một số bị bỏ. Nếu bạn từng quen với "Tỷ lệ chuyển đổi" hay "Lượt xem trang", phần dưới đây giải thích chúng đã trở thành gì.

### Lượt hiển thị sản phẩm

Đây là số lần sản phẩm của bạn được hiển thị cho người dùng, ở bất kỳ đâu: trong video, trong buổi LIVE, trên thẻ sản phẩm ở trang tìm kiếm hay trang đề xuất. Theo trang "Lưu lượng truy cập sản phẩm", chỉ số cũ "Lượt hiển thị" từng được theo dõi riêng theo loại nội dung; logic mới thống nhất thành một chỉ số **Lượt hiển thị sản phẩm**.

TikTok cũng cung cấp **Lượt hiển thị sản phẩm độc nhất**, được định nghĩa là "số người dùng đã xem sản phẩm này", trong đó mỗi người dùng chỉ được tính một lần mỗi ngày dù họ thấy sản phẩm nhiều lần. Khi so sánh với Lượt nhấp và Đơn hàng SKU để tính tỷ lệ, hãy dùng các chỉ số đếm theo lượt (không phải "độc nhất") cho nhất quán, vì các chỉ số độc nhất không cộng dồn được qua nhiều ngày.

### Lượt nhấp vào sản phẩm và CTR (Tỷ lệ nhấp)

**Lượt nhấp vào sản phẩm** thay thế cho chỉ số cũ "Lượt xem trang". TikTok giải thích rằng chỉ số này "ghi nhận mọi lượt nhấp chủ động vào sản phẩm của bạn trên tất cả các kênh của nhà sáng tạo và người bán", phản ánh sát hơn ý định mua sắm so với lượt xem trang thô.

**CTR (Tỷ lệ nhấp)** là tỷ lệ giữa lượt nhấp và lượt hiển thị:

> CTR = Lượt nhấp vào sản phẩm ÷ Lượt hiển thị sản phẩm

CTR trả lời câu hỏi: trong số những lần sản phẩm xuất hiện trước mắt người dùng, bao nhiêu lần người dùng thấy đủ hấp dẫn để nhấp vào? Trên kênh thẻ sản phẩm, CTR phụ thuộc phần lớn vào những gì hiển thị trên thẻ: ảnh bìa, tiêu đề, giá, nhãn khuyến mãi, số lượng đã bán và điểm đánh giá.

### Đơn hàng SKU và CTOR (Tỷ lệ từ nhấp đến đặt hàng)

Đây là chỉ số dễ gây nhầm lẫn nhất. Trước đây Trung tâm nhà bán hàng hiển thị "Tỷ lệ chuyển đổi". Trong lần cập nhật 2026, TikTok đổi tên chỉ số này thành **CTOR**, viết tắt của Tỷ lệ từ nhấp đến đặt hàng (đơn hàng SKU). TikTok nói rõ "logic tính toán của số liệu này không thay đổi, chỉ cập nhật tên gọi", và lý do đổi tên là "mỗi nền tảng có cách tính CVR khác nhau". CTOR đo "tỷ lệ phần trăm số lượt nhấp vào liên kết sản phẩm dẫn đến đơn hàng SKU":

> CTOR = Đơn hàng SKU ÷ Lượt nhấp vào sản phẩm

Điểm quan trọng là mẫu số. CTOR không chia cho số người xem hay số khách truy cập, mà chia cho **lượt nhấp vào sản phẩm**. Và tử số là **Đơn hàng SKU**, không phải số đơn hàng. Một đơn hàng có hai sản phẩm khác nhau được tính là một đơn hàng của shop nhưng tạo ra hai đơn hàng SKU, mỗi sản phẩm một. Khi phân tích ở cấp sản phẩm, Đơn hàng SKU là đơn vị đúng.

Vì vậy, khi ai đó nói "tỷ lệ chuyển đổi của shop là 3 %", hãy hỏi lại: chuyển đổi từ đâu đến đâu? Nếu là từ lượt nhấp đến đơn hàng SKU, đó là CTOR. Nếu là từ khách truy cập đến người mua, đó là một chỉ số khác, ở cấp shop, và không so sánh được với CTOR.

### AOV (SKU)

TikTok định nghĩa **AOV (SKU)** là "số tiền trung bình mỗi khách hàng chi tiêu trên mỗi đơn hàng SKU trong khoảng thời gian đã chọn". Trong thực tế, bạn có thể tính lại nó bằng:

> AOV (SKU) = GMV ÷ Đơn hàng SKU

AOV tăng khi khách mua nhiều món hơn trong một đơn hàng SKU (ví dụ mua hai chai thay vì một), khi khách chọn biến thể đắt hơn, hoặc khi giá bán sau giảm tăng lên. AOV giảm khi bạn giảm giá sâu, khi biến thể rẻ hơn chiếm tỷ trọng lớn hơn, hoặc khi các chương trình mua nhiều bị tắt.

### GMV: TikTok tính những gì

GMV trong La bàn dữ liệu là "tổng số tiền thanh toán cho các đơn hàng trong khoảng thời gian đã chọn, bao gồm cả đơn đã hủy và hoàn tiền". Hai hệ quả thực tế:

- GMV không phải doanh thu thực nhận. Đơn bị hủy hoặc hoàn tiền vẫn nằm trong GMV. Muốn biết phần bị mất, hãy xem thêm chỉ số **Hoàn tiền**.
- Hoàn tiền thường đến muộn hơn GMV. TikTok lấy ví dụ: đơn mua ngày 1/10 được tính vào GMV tháng 10; nếu khách yêu cầu hoàn tiền ngày 15/10 và yêu cầu được xử lý ngày 20/10, khoản hoàn tiền được tính vào tháng 10. Nếu bạn chọn khoảng 01–07/10, bạn sẽ thấy GMV nhưng chưa thấy khoản hoàn tiền đó. Vì vậy so sánh tỷ lệ hoàn tiền của tuần gần nhất với một tuần cũ hơn thường cho kết quả lạc quan giả.

TikTok cũng bổ sung các biến thể như **GMV bao gồm thuế** và **GMV có đồng tài trợ của TTS** (cộng thêm khoản TikTok Shop đồng tài trợ). Khi so sánh hai kỳ, hãy luôn dùng cùng một loại GMV.

### Các chỉ số phụ nên biết

- **Số lượt thêm vào giỏ hàng**: số lần người mua nhấp nút Thêm vào giỏ hàng của sản phẩm.
- **Tỷ lệ thêm vào giỏ hàng**: TikTok định nghĩa lại năm 2026 thành số lượt nhấp nút Thêm vào giỏ hàng chia cho tổng số lượt nhấp vào sản phẩm (trước đây chia cho số người xem độc nhất). Nhờ định nghĩa mới, chỉ số này nằm gọn giữa Lượt nhấp và Đơn hàng SKU trong phễu.
- **Các chỉ số "độc nhất"** (CTR độc nhất, Người dùng thêm vào giỏ hàng, CTOR độc nhất): đếm theo người, mỗi người một lần mỗi ngày. Hữu ích để hiểu hành vi, nhưng không cộng dồn được qua nhiều ngày.
- **Hai chỉ số đã bị bỏ**: "Doanh số gộp" (thay bằng GMV) và "Tỷ lệ chuyển đổi giỏ hàng" (thay bằng Số lượt thêm vào giỏ hàng và Tỷ lệ thêm vào giỏ hàng).

## Công thức phễu: GMV = Lượt hiển thị × CTR × CTOR × AOV

Bốn chỉ số trên ghép lại thành một đẳng thức đơn giản:

> GMV = Lượt hiển thị sản phẩm × CTR × CTOR × AOV (SKU)

TikTok không in công thức này trên Trung tâm nhà bán hàng, nhưng nó suy ra trực tiếp từ chính các định nghĩa TikTok công bố. Đây là công thức Juli AI dùng để đọc mọi shop, và bạn có thể tự kiểm tra trên dữ liệu của mình.

### Vì sao đẳng thức này đúng

Thay từng định nghĩa vào, các số hạng triệt tiêu nhau:

- Lượt hiển thị × CTR = Lượt hiển thị × (Lượt nhấp ÷ Lượt hiển thị) = **Lượt nhấp**
- Lượt nhấp × CTOR = Lượt nhấp × (Đơn hàng SKU ÷ Lượt nhấp) = **Đơn hàng SKU**
- Đơn hàng SKU × AOV = Đơn hàng SKU × (GMV ÷ Đơn hàng SKU) = **GMV**

Đẳng thức đúng chính xác khi cả bốn chỉ số được lấy trên cùng một sản phẩm (hoặc cùng một nhóm sản phẩm), cùng một kênh và cùng một khoảng thời gian. Nó sai ngay khi bạn trộn phạm vi, ví dụ lấy Lượt hiển thị của riêng kênh thẻ sản phẩm nhân với CTOR của tất cả các kênh.

### Ví dụ minh họa

Giả sử một sản phẩm trong 30 ngày có (số giả định, chỉ để minh họa):

| Bước | Chỉ số | Giá trị |
|---|---|---|
| Lượt hiển thị sản phẩm | | 20.000 |
| Lượt nhấp vào sản phẩm | CTR 4 % | 800 |
| Đơn hàng SKU | CTOR 5 % | 40 |
| GMV | AOV 200.000 ₫ | 8.000.000 ₫ |

Đọc theo hàng ngang: 20.000 lượt hiển thị × 4 % = 800 lượt nhấp; 800 × 5 % = 40 đơn hàng SKU; 40 × 200.000 ₫ = 8.000.000 ₫. Mỗi tầng là một câu hỏi riêng: có đủ người thấy không, người thấy có nhấp không, người nhấp có mua không, và mỗi lần mua được bao nhiêu tiền.

### Tách mức thay đổi GMV thành bốn phần

Công thức phễu mạnh nhất khi so sánh hai kỳ. Giả sử 30 ngày tiếp theo, sản phẩm trên có Lượt hiển thị 22.000 (tăng 10 %), CTR giữ 4 %, CTOR giữ 5 %, nhưng AOV giảm còn 190.000 ₫ (giảm 5 %). GMV mới là 22.000 × 4 % × 5 % × 190.000 ₫ = 8.360.000 ₫, tăng 360.000 ₫.

Nhìn GMV thì thấy tăng 4,5 %, tưởng là tốt. Nhưng đọc từng hệ số thì thấy hai câu chuyện ngược chiều nhau: lượt hiển thị tăng 10 % kéo GMV lên, còn AOV giảm 5 % kéo xuống; CTR và CTOR đứng yên nên không góp phần nào. Vì GMV là tích của bốn hệ số, hệ số nào đổi nhiều nhất theo tỷ lệ là hệ số giải thích phần lớn mức thay đổi, và hai hệ số đi ngược chiều có thể che nhau trong con số GMV tổng.

Câu hỏi tiếp theo trở nên cụ thể: vì sao AOV giảm 5 %? Có phải một chương trình mua nhiều giảm nhiều đã hết hạn, hay một biến thể rẻ hơn đang bán chạy hơn? Đó là việc của người bán; công thức chỉ cho bạn biết nên nhìn vào đâu.

Nếu GMV gần như không đổi, đừng vội kết luận là không có gì xảy ra: so tỷ lệ thay đổi của từng hệ số, vì một hệ số tăng có thể đang bù cho một hệ số giảm.

## Đọc chỉ số theo năm kênh

TikTok ghi nhận mỗi lượt hiển thị, lượt nhấp và đơn hàng theo kênh. Trên trang "Lưu lượng truy cập sản phẩm", các chỉ số như GMV, Lượt nhấp vào sản phẩm, CTR và CTOR có thể xem theo các khía cạnh: Tất cả, LIVE của người bán, video của người bán, thẻ sản phẩm của người bán, Liên kết (gồm LIVE liên kết và video liên kết) và Tab Cửa hàng. Juli gom chúng thành năm kênh:

| Kênh | Khách đến từ đâu | Chỉ số nên theo dõi chính |
|---|---|---|
| Thẻ sản phẩm của người bán | Tìm kiếm, đề xuất, trang mua sắm | CTR, CTOR |
| Tab Cửa hàng | Khách vào trang cửa hàng của bạn | CTOR |
| Video của người bán | Video do tài khoản shop đăng | Lượt hiển thị, GMV |
| LIVE của người bán | Buổi LIVE của shop | Lượt hiển thị, GMV |
| Liên kết | Video và LIVE của nhà sáng tạo tiếp thị liên kết | Lượt hiển thị, GMV |

Lý do phải tách kênh: cùng một sản phẩm có thể chuyển đổi rất khác nhau tùy khách đến từ đâu. Người xem LIVE đã nghe người dẫn giới thiệu mấy phút trước khi nhấp; người lướt trang tìm kiếm chỉ thấy ảnh bìa, tiêu đề và giá. Gộp hai luồng này lại thì CTR và CTOR "toàn shop" là trung bình của hai hành vi khác hẳn nhau, và thay đổi theo tỷ trọng giữa các kênh chứ không chỉ theo chất lượng trang sản phẩm.

### Thẻ sản phẩm của người bán

TikTok định nghĩa thẻ sản phẩm là thẻ hiển thị "tiêu đề, hình ảnh, mô tả và giá của sản phẩm sau khi được niêm yết thành công", và nói rằng doanh thu "được tạo ra thông qua các kênh không đến từ LIVE và video sẽ được xem là doanh thu đến từ Thẻ sản phẩm" (Học viện TikTok Shop, "Thẻ Sản Phẩm"). Khách đến từ tìm kiếm, đề xuất và trang mua sắm.

Đây là kênh phản ánh trung thực nhất chất lượng của chính trang sản phẩm, vì không có người dẫn LIVE hay nhà sáng tạo nào "bán hộ". Nếu bạn muốn biết ảnh bìa, tiêu đề, mô tả hay giá có đang làm tốt việc của chúng không, hãy đọc CTR và CTOR ở kênh này. Bài [Tối ưu thẻ sản phẩm TikTok Shop từ A–Z](/blog/toi-uu-the-san-pham-tiktok-shop) đi sâu vào từng yếu tố.

### Tab Cửa hàng

Tab Cửa hàng là nơi khách chủ động vào trang shop của bạn và duyệt sản phẩm. Khách ở đây thường có ý định mua rõ hơn, nên CTOR ở Tab Cửa hàng thường khác CTOR ở thẻ sản phẩm. Theo bảng khía cạnh số liệu của TikTok, Tab Cửa hàng có Lượt nhấp, CTR và CTOR, nhưng không nằm trong danh sách khía cạnh của Lượt hiển thị sản phẩm. Hãy đọc kênh này cùng thẻ sản phẩm, vì cả hai đều phản ánh khách tự tìm đến.

### Video của người bán

Video do chính tài khoản shop đăng. Ở kênh này, câu hỏi quan trọng nhất thường là video có được phân phối không (Lượt hiển thị sản phẩm) và mang về bao nhiêu GMV. Người xem video có thể đặt mua ngay mà không qua giỏ hàng, nên các tỷ lệ liên quan đến giỏ hàng ở đây cần đọc thận trọng.

### LIVE của người bán

Tương tự video, nhưng hành vi khác: buổi LIVE tạo ra lượt hiển thị và lượt nhấp tập trung trong vài giờ, CTOR thường cao vì người xem được tư vấn trực tiếp. Một buổi LIVE lớn có thể làm thay đổi rõ các chỉ số toàn shop trong ngày đó, đây là lý do bạn không nên đọc chỉ số toàn shop của một ngày có LIVE lớn như một ngày bình thường.

### Liên kết (video và LIVE liên kết)

Đây là traffic từ nhà sáng tạo tiếp thị liên kết. Kênh này quan trọng để hiểu tổng thể shop: với nhiều shop, Liên kết chiếm phần lớn lượt nhấp. Nhưng kết quả của kênh này phụ thuộc chủ yếu vào nhà sáng tạo và nội dung của họ, nên nó không nên là căn cứ để kết luận về trang sản phẩm của bạn.

### Hai nhóm kênh: khách tự tìm đến và nội dung

Khi đọc báo cáo, Juli chia năm kênh thành hai nhóm:

- **Nhóm khách tự tìm đến**: Thẻ sản phẩm của người bán và Tab Cửa hàng. Ảnh bìa, tiêu đề, mô tả, giá và voucher tác động trực tiếp ở đây. **CTOR là chỉ số chính của nhóm này.**
- **Nhóm nội dung**: Video của người bán, LIVE của người bán và Liên kết. **Lượt hiển thị sản phẩm và GMV là chỉ số chính**; CTOR chỉ để tham khảo, vì nó phụ thuộc nhiều vào nội dung và người bán hàng trong video hay LIVE.

Cách chia này giúp tránh một lỗi phổ biến: sửa trang sản phẩm vì CTOR toàn shop giảm, trong khi CTOR giảm chỉ vì tỷ trọng traffic từ một kênh có CTOR thấp tăng lên.

## Những cách đọc sai thường gặp

### CTOR toàn shop đi ngang che giấu một thẻ sản phẩm đang tụt

Đây là lỗi nguy hiểm nhất vì nó trông như tin tốt. Hãy xem ví dụ sau (số giả định):

| Kênh | Kỳ trước: lượt nhấp → đơn hàng SKU | CTOR | Kỳ này: lượt nhấp → đơn hàng SKU | CTOR |
|---|---|---|---|---|
| Thẻ sản phẩm | 1.000 → 50 | 5,0 % | 1.000 → 35 | 3,5 % |
| Liên kết | 2.600 → 120 | 4,6 % | 2.600 → 120 | 4,6 % |
| LIVE của người bán | 400 → 30 | 7,5 % | 800 → 60 | 7,5 % |
| **Toàn shop** | 4.000 → 200 | **5,0 %** | 4.400 → 215 | **4,9 %** |

CTOR toàn shop chỉ giảm từ 5,0 % xuống 4,9 %, đơn hàng SKU còn tăng. Nhưng CTOR của thẻ sản phẩm giảm 30 %, từ 5,0 % xuống 3,5 %. Nguyên nhân bị che: số lượt nhấp từ LIVE (kênh có CTOR cao) tăng gấp đôi, bù lại phần mất ở thẻ sản phẩm. Nếu chỉ nhìn số toàn shop, bạn sẽ không biết trang sản phẩm đang mất khách, và khi buổi LIVE kế tiếp không đạt như kỳ này, GMV sẽ giảm mà không rõ lý do.

Cách tránh: luôn đọc CTOR theo kênh, và với nhóm khách tự tìm đến, đọc riêng cho từng sản phẩm bán chạy.

### Lấy trung bình của các tỷ lệ theo ngày

Nếu bạn xuất dữ liệu theo ngày rồi lấy trung bình cộng của 30 giá trị CTR, kết quả sẽ khác CTR mà Trung tâm nhà bán hàng hiển thị cho cả 30 ngày. Lý do: ngày có 40 lượt hiển thị và ngày có 4.000 lượt hiển thị được tính nặng như nhau. Cách đúng là **cộng tổng** các đại lượng đếm được (lượt hiển thị, lượt nhấp, đơn hàng SKU, GMV) trong cả kỳ, rồi mới chia để ra tỷ lệ. Đó cũng là cách La bàn dữ liệu tính khi bạn chọn một khoảng ngày.

### So sánh hai kỳ có ngày sale lớn

Các ngày như 9.9, 10.10, 11.11 có traffic và CTOR khác hẳn ngày thường. So sánh 30 ngày có 11.11 với 30 ngày không có 11.11 gần như chắc chắn cho thấy "tăng trưởng" giả. Hãy đánh dấu các ngày sale trong cả hai kỳ, hoặc chọn hai kỳ có cùng số ngày sale.

### Nhầm Đơn hàng với Đơn hàng SKU

Khi tự tính CTOR hoặc AOV từ file xuất, rất nhiều người dùng cột "Đơn hàng" thay vì "Đơn hàng SKU". Ở cấp sản phẩm và trên một kênh, hai con số thường bằng nhau hoặc gần bằng; ở cấp toàn shop chúng có thể chênh lệch vì một đơn chứa nhiều sản phẩm. Dùng đúng Đơn hàng SKU để con số của bạn khớp với con số TikTok hiển thị.

### Đổi ảnh bìa khi CTR giảm vì traffic bị "loãng"

CTR giảm không phải lúc nào cũng do ảnh bìa hay tiêu đề. Khi một chiến dịch, một buổi LIVE hay một video liên kết đưa sản phẩm đến rất nhiều người không có nhu cầu, lượt hiển thị tăng vọt nhưng CTR giảm, vì phần lớn người xem chỉ lướt qua. Đó là traffic loãng, không phải trang sản phẩm kém.

Cách phân biệt: so sánh CTR **theo từng kênh**. Nếu CTR giảm ở gần như mọi kênh, kể cả những kênh không nhận thêm traffic, nguyên nhân nằm ở chính sản phẩm (ảnh bìa, giá, tiêu đề). Nếu CTR chỉ giảm ở đúng kênh vừa có lượt hiển thị tăng mạnh, còn các kênh khác ổn định, đó là traffic loãng, và việc sửa trang sản phẩm sẽ không giải quyết được gì.

### Kết luận trên quá ít dữ liệu

Với 3 đơn hàng một tuần, CTOR có thể dao động từ 2 % lên 6 % chỉ vì ngẫu nhiên. Trước khi kết luận một chỉ số "giảm", hãy chắc rằng mỗi kỳ có đủ dữ liệu. Juli gắn nhãn độ tin cậy cho mỗi so sánh: chỉ khi mỗi kỳ có đủ dữ liệu và chênh lệch vượt khỏi vùng nhiễu thống kê thì kết luận mới được coi là "rõ". Dưới mức đó, chênh lệch chỉ là "dấu hiệu" để theo dõi tiếp.

## Làm gì ở từng điểm nghẽn

Một khi đã biết phễu nghẽn ở đâu, bước tiếp theo là chọn đòn bẩy phù hợp. Loạt bài "Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào" trên Học viện TikTok Shop chia các yếu tố tối ưu thẻ sản phẩm thành ba nhóm: **Hiển thị** (hình ảnh chính, tiêu đề, mô tả), **Lợi ích** (giá cạnh tranh, chiết khấu, voucher, ưu đãi chớp nhoáng, mua thêm tiết kiệm nhiều hơn, thanh toán khi giao hàng) và **Sự tin cậy** (thương hiệu, đánh giá, tỷ lệ trả hàng). Dưới đây là cách nối các nhóm đó với từng bước của phễu.

### Lượt hiển thị thấp

Lượt hiển thị là bước người bán kiểm soát ít nhất bằng trang sản phẩm. Theo loạt bài chẩn đoán của TikTok, thẻ sản phẩm cần đạt ngưỡng tối thiểu để vào nhóm đề xuất, và lượt hiển thị có thể tăng qua các hoạt động khuyến mãi của nền tảng, quảng cáo, tối ưu tiêu đề cho tìm kiếm, và nội dung (video, LIVE, hợp tác với nhà sáng tạo). Hiệu quả vận hành như giao hàng đúng hạn cũng được TikTok nhắc đến như điều kiện để không bị tụt hạng.

Hãy nhớ: khi lượt hiển thị tăng, CTR thường giảm nhẹ vì traffic mới ít "nóng" hơn. Đừng vội sửa trang sản phẩm khi thấy CTR giảm ngay sau một đợt tăng traffic.

### CTR thấp

Khi CTR ở kênh thẻ sản phẩm thấp hơn các sản phẩm khác của shop hoặc giảm so với chính nó trước đây, những gì người dùng thấy trên thẻ là nghi phạm đầu tiên:

- **Ảnh bìa**: sản phẩm có rõ không, nền có đồng nhất không, có bị che bởi chữ hay nhãn dán không.
- **Tiêu đề**: có chứa từ khóa người mua thật sự tìm không, có nói rõ sản phẩm là gì không.
- **Giá hiển thị**: có cạnh tranh so với sản phẩm tương tự không. Công cụ Chẩn đoán giá của TikTok cho biết sản phẩm đang ở trạng thái "Giá không cạnh tranh", "Giá cạnh tranh" hay "Giá tốt nhất".

### CTOR thấp: trước giỏ hay sau giỏ

CTOR thấp nghĩa là người dùng đã nhấp vào nhưng không mua. Hãy tách CTOR làm hai nửa bằng Tỷ lệ thêm vào giỏ hàng:

- **Trước giỏ** (Tỷ lệ thêm vào giỏ hàng giảm): khách vào trang nhưng không thêm vào giỏ. Nghi phạm là giá, bộ ảnh chi tiết, mô tả và đánh giá. Khách chưa bị thuyết phục.
- **Sau giỏ** (số đơn hàng trên mỗi lượt thêm vào giỏ giảm): khách đã thêm vào giỏ nhưng không thanh toán. Nghi phạm là phí vận chuyển, voucher hết hạn, hoặc khách đang chờ một đợt flash sale mà họ đoán sẽ đến.

Phân biệt hai trường hợp này rất quan trọng, vì đòn bẩy cho chúng khác nhau hoàn toàn. Viết lại mô tả không giúp được khách đang chờ flash sale; giảm phí vận chuyển không giúp được khách chưa hiểu sản phẩm.

### AOV thấp

AOV giảm hoặc thấp hơn kỳ vọng thường có ba nguyên nhân: giảm giá sâu, cơ cấu biến thể chuyển sang loại rẻ hơn, hoặc khách mua ít món hơn mỗi lần. Đòn bẩy phổ biến nhất cho trường hợp cuối là **Mua Sỉ Giá Hời (BMSM)**, công cụ khuyến mãi mà TikTok mô tả là "để tăng giá trị đơn hàng trung bình": giảm giá khi khách mua đủ số lượng tối thiểu, tối đa hai bậc. TikTok gợi ý theo dõi "số lượng mặt hàng trung bình trên mỗi đơn hàng" để chọn ngưỡng. Một nguyên tắc thực tế: đặt ngưỡng ở mức mà một phần khách hiện tại đã mua (ví dụ "từ 2 món" nếu đã có khách mua 2), thay vì một mức gần như không ai đạt tới.

## Quy trình đọc chỉ số hàng tuần trong 30 phút

Nếu bạn chỉ có 30 phút mỗi tuần, đây là thứ tự Juli khuyên dùng:

1. **Chọn hai kỳ 30 ngày liền nhau** (30 ngày gần nhất và 30 ngày trước đó), đánh dấu các ngày sale lớn trong mỗi kỳ.
2. **Tách GMV theo năm kênh**: kênh nào tăng, kênh nào giảm, và mỗi kênh đóng góp bao nhiêu vào mức thay đổi GMV của shop.
3. **Với kênh có thay đổi lớn nhất**, tách GMV thành Lượt hiển thị, CTR, CTOR và AOV. Hệ số nào đóng góp nhiều nhất là câu chuyện chính.
4. **Chọn năm sản phẩm có GMV cao nhất** và lặp lại bước 3 trên nhóm khách tự tìm đến (thẻ sản phẩm và Tab Cửa hàng) của từng sản phẩm.
5. **Nếu câu chuyện là CTOR**, tách trước giỏ và sau giỏ. Nếu là CTR, kiểm tra xem có phải traffic loãng không.
6. **Đối chiếu với lịch khuyến mãi**: flash sale, chiết khấu, voucher nào bắt đầu hoặc kết thúc trong kỳ.
7. **Ghi lại một kết luận và một hành động cho mỗi sản phẩm**, kèm ngày bắt đầu, để kỳ sau đo lại.

Bước 7 thường bị bỏ qua nhất nhưng lại quan trọng nhất. Không có ngày bắt đầu, bạn không biết thay đổi nào gây ra kết quả nào.

## Juli AI đọc chỉ số này như thế nào

Juli AI là trợ lý AI vận hành cho nhà bán TMĐT do chúng tôi phát triển, hiện kết nối TikTok Shop (Shopee đang tích hợp). Phần đọc số trong bài này Juli làm sẵn cho bạn: [phân tích shop theo từng luồng truy cập](/san-pham/phan-tich-shop), tách GMV theo năm kênh và bốn hệ số của phễu, gắn nhãn độ tin cậy cho mỗi so sánh, và chỉ ra sản phẩm nào đang mất khách ở bước nào. Từ đó Juli [đề xuất hành động và chỉ thực thi khi bạn phê duyệt](/san-pham/de-xuat-va-thuc-thi), rồi [đo tác động lên GMV](/san-pham/do-luong-gmv) sau 7 và 14 ngày.

Juli dùng đúng tên và định nghĩa chỉ số của TikTok, đọc dữ liệu qua [kết nối chính thức với TikTok Shop](/ket-noi/tiktok-shop), và không tự đặt ra một chỉ số mà bạn không tìm thấy trên Trung tâm nhà bán hàng. Bạn có thể xem tổng quan tại trang [sản phẩm Juli AI](/san-pham). Nếu bạn đang cân nhắc các công cụ khác, bài [Top công cụ cho nhà bán TikTok Shop 2026](/blog/cong-cu-cho-nha-ban-tiktok-shop-2026) so sánh các nhóm công cụ một cách trung lập.

## Tóm tắt

- Bốn chỉ số cốt lõi: **Lượt hiển thị sản phẩm**, **CTR** (lượt nhấp ÷ lượt hiển thị), **CTOR** (đơn hàng SKU ÷ lượt nhấp, tên mới của "Tỷ lệ chuyển đổi") và **AOV (SKU)** (GMV ÷ đơn hàng SKU).
- Chúng nhân với nhau ra GMV: **GMV = Lượt hiển thị × CTR × CTOR × AOV**, đúng khi cả bốn cùng phạm vi sản phẩm, kênh và thời gian.
- Đọc theo kênh. Thẻ sản phẩm và Tab Cửa hàng phản ánh chất lượng trang sản phẩm; video, LIVE và Liên kết phản ánh nội dung.
- Cảnh giác với CTOR toàn shop, trung bình của tỷ lệ theo ngày, kỳ có ngày sale và traffic loãng.
- Sửa đúng bước yếu: CTR thấp thì xem ảnh bìa, tiêu đề, giá; CTOR thấp thì tách trước giỏ và sau giỏ; AOV thấp thì xem cơ cấu giá và chương trình mua nhiều.
`;
