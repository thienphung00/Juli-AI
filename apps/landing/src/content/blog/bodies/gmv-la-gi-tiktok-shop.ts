/**
 * Post (D48 additions 6, P39-B): "GMV là gì" for TikTok Shop. Target queries:
 * "gmv là gì" (Semrush VN 4,400/month, KD 21, D48), "gmv tiktok shop là gì",
 * "cách tăng gmv trên tiktok". Metric facts are from TikTok Academy VN,
 * "Lưu lượng truy cập sản phẩm" (17/06/2026: GMV definition incl. cancelled and
 * refunded orders, GMV variants, refund timing, channel dimensions); settlement
 * facts from "Tài Chính cho Người Mới Bắt Đầu: Hướng Dẫn về Phương Thức và Thời
 * Điểm Bạn Được Thanh Toán" (01/12/2023: balance after all fees, "Quyết toán",
 * standard (D+6)+1, accrual basis); product-card facts from "Thẻ Sản Phẩm" and
 * "Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 1/4"; BMSM from "Mua Sỉ Giá Hời".
 * No fee rates are quoted (they change; the seller reads them in Seller Center).
 * Every number in a "Ví dụ giả định" is hypothetical and says so. The funnel
 * identity is derived from TikTok's definitions and presented as Juli's method
 * (docs/adr/106, docs/adr/108). Juli's scope per fasttrack/SPEC.md: analyses,
 * proposes, writes only title / description after approval, measures day 7 / 14;
 * no ads, no orders or inventory management.
 */
export const body = `
"GMV tháng này được bao nhiêu?" là câu hỏi đầu tiên của hầu hết nhà bán TikTok Shop khi mở Trung tâm nhà bán hàng. GMV là con số to nhất, nằm ở vị trí dễ thấy nhất, và thường là con số được báo cáo cho sếp, cho đối tác hay cho chính mình. Nhưng rất nhiều người bán dùng GMV mỗi ngày mà không chắc nó gồm những gì, vì sao nó lớn hơn số tiền về tài khoản, và vì sao GMV tăng chưa chắc là shop đang tốt lên.

Bài viết này trả lời ba câu hỏi theo thứ tự. Thứ nhất, GMV là gì theo đúng định nghĩa TikTok công bố trên Học viện TikTok Shop, và GMV khác doanh thu thực nhận ở đâu. Thứ hai, cách tính GMV bằng một công thức phễu gồm bốn chỉ số mà bạn tìm thấy ngay trên tài khoản của mình, tách theo từng luồng truy cập. Thứ ba, cách tìm bước yếu nhất trong phễu và cách tăng GMV trên TikTok bằng đúng đòn bẩy cho bước đó. Mọi ví dụ có số trong bài là ví dụ giả định, chỉ để minh họa cách tính.

## GMV là gì

GMV là viết tắt của cụm từ tiếng Anh Gross Merchandise Value, dịch sát là tổng giá trị hàng hóa giao dịch. Trong thương mại điện tử nói chung, GMV là tổng giá trị các đơn hàng mà khách đã đặt và thanh toán trong một khoảng thời gian, trước khi trừ đơn hủy, hoàn tiền và các loại phí. Nói cách khác, GMV đo quy mô giao dịch đi qua shop, không đo số tiền shop giữ lại.

### GMV TikTok Shop là gì: định nghĩa theo TikTok

Trên TikTok Shop, GMV có một định nghĩa cụ thể. Theo trang "Lưu lượng truy cập sản phẩm" của Học viện TikTok Shop (cập nhật 17/06/2026), GMV trong La bàn dữ liệu là "tổng số tiền thanh toán cho các đơn hàng trong khoảng thời gian đã chọn, bao gồm cả đơn đã hủy và hoàn tiền". Đây là định nghĩa bạn nên dùng khi đọc số trên Trung tâm nhà bán hàng, vì nó quyết định con số bạn nhìn thấy.

Có ba điểm đáng chú ý trong định nghĩa này:

- **"Tổng số tiền thanh toán"**: GMV tính theo số tiền khách thanh toán cho đơn hàng, tức giá sau các khoản giảm mà khách được hưởng, không phải giá niêm yết gốc.
- **"Trong khoảng thời gian đã chọn"**: GMV luôn gắn với một khoảng ngày. Đổi khoảng ngày là đổi con số, nên khi so sánh hai kỳ hãy chắc rằng hai kỳ dài bằng nhau.
- **"Bao gồm cả đơn đã hủy và hoàn tiền"**: đơn bị hủy hay bị hoàn tiền vẫn nằm trong GMV của ngày khách đặt. Đây là lý do chính khiến GMV lớn hơn số tiền bạn thật sự nhận được.

### Các loại GMV trên La bàn dữ liệu

Cũng theo trang "Lưu lượng truy cập sản phẩm", TikTok bổ sung các biến thể của GMV, ví dụ **GMV bao gồm thuế** và **GMV có đồng tài trợ của TTS**, trong đó TTS là viết tắt của TikTok Shop và phần đồng tài trợ là khoản TikTok Shop cùng tài trợ cho đơn hàng. Các biến thể này không sai, chúng chỉ trả lời những câu hỏi khác nhau. Quy tắc duy nhất: khi so sánh hai kỳ, hai sản phẩm hay hai luồng truy cập, hãy dùng cùng một loại GMV. So GMV bao gồm thuế của tháng này với GMV không bao gồm thuế của tháng trước sẽ tạo ra một mức "tăng trưởng" không có thật.

### Đơn hàng và Đơn hàng SKU

Khi đọc GMV ở cấp sản phẩm, bạn sẽ gặp hai chỉ số đếm đơn: Đơn hàng và **Đơn hàng SKU**. SKU là mã của từng phiên bản sản phẩm, ví dụ cùng một chiếc áo nhưng màu trắng cỡ M là một SKU, màu đen cỡ L là một SKU khác. Một đơn hàng có hai sản phẩm khác nhau là một đơn hàng của shop nhưng tạo ra hai đơn hàng SKU. Khi tính GMV theo phễu ở cấp sản phẩm, Đơn hàng SKU là đơn vị đúng, và các chỉ số trong phần sau đều dùng nó.

## GMV khác doanh thu thực nhận như thế nào

Nhầm GMV với doanh thu thực nhận là lỗi phổ biến nhất khi người bán tính lãi lỗ. GMV trả lời câu hỏi "khách đã đặt và thanh toán bao nhiêu", còn doanh thu thực nhận trả lời câu hỏi "bao nhiêu tiền thật sự về tay shop". Giữa hai con số có ít nhất ba lớp chênh lệch.

### Từ GMV đến số tiền về tài khoản

- **Đơn hủy**: nằm trong GMV theo định nghĩa của TikTok, nhưng không tạo ra tiền cho shop.
- **Hoàn tiền**: cũng nằm trong GMV. Trang "Lưu lượng truy cập sản phẩm" lấy ví dụ một đơn mua ngày 1/10 được tính vào GMV tháng 10; nếu khách yêu cầu hoàn tiền ngày 15/10 và yêu cầu được xử lý ngày 20/10, khoản hoàn tiền được ghi vào tháng 10. Nếu bạn xem khoảng 01/10 đến 07/10, bạn thấy GMV của đơn đó nhưng chưa thấy khoản hoàn. Muốn biết phần bị mất, hãy xem thêm chỉ số **Hoàn tiền**.
- **Phí**: theo bài "Tài Chính cho Người Mới Bắt Đầu: Hướng Dẫn về Phương Thức và Thời Điểm Bạn Được Thanh Toán" của Học viện TikTok Shop, khoản thu "sau khi trừ tất cả các khoản phí" mới được chuyển vào Số dư Nhà bán hàng, và việc tiền chuyển vào số dư này được gọi là "Quyết toán". Mức phí do chính sách phí hiện hành của TikTok Shop quy định; hãy đọc trực tiếp trong mục Tài chính của Trung tâm nhà bán hàng thay vì dựa vào một con số truyền miệng.

Ngoài ba lớp trên, thời điểm cũng khác nhau. Cùng bài viết đó mô tả chu kỳ quyết toán tiêu chuẩn là (D+6)+1: D là ngày đơn được giao cho người mua, cộng 6 ngày để đơn được coi là hoàn tất, cộng 1 ngày để tiền vào số dư. Bài viết cũng nói hệ thống ghi nhận theo nguyên tắc dồn tích, tức "ghi nhận doanh thu (khi kiếm được) và chi phí (khi phát sinh) ngay khi xảy ra giao dịch", kể cả khi tiền chưa thật sự về. Vì vậy GMV hôm nay và tiền về hôm nay gần như không bao giờ khớp nhau.

### Ví dụ giả định: từ GMV đến tiền về

Giả sử một shop trong một tháng có các con số sau (toàn bộ là số giả định, kể cả khoản phí, chỉ để minh họa cách trừ):

| Khoản | Giá trị |
|---|---|
| GMV trên La bàn dữ liệu | 50.000.000 ₫ |
| Trừ đơn đã hủy | 3.000.000 ₫ |
| Trừ hoàn tiền | 2.000.000 ₫ |
| Giá trị đơn thành công | 45.000.000 ₫ |
| Trừ các khoản phí (giả định) | 5.400.000 ₫ |
| Số tiền quyết toán ước tính | 39.600.000 ₫ |

GMV 50 triệu nhưng tiền về khoảng 39,6 triệu, và chưa trừ giá vốn hàng hóa, chi phí đóng gói hay chi phí quảng cáo. Nếu bạn lập kế hoạch nhập hàng dựa trên GMV, bạn đang tính cả khoảng một phần năm GMV không bao giờ về tài khoản trong ví dụ này. Tỷ lệ thật của shop bạn có thể cao hơn hoặc thấp hơn nhiều, tùy tỷ lệ hủy, tỷ lệ hoàn và ngành hàng.

### Vì sao vẫn nên theo dõi GMV

Nếu GMV không phải tiền thật, vì sao vẫn nên theo dõi nó? Vì GMV là con số phản ánh nhanh nhất và trực tiếp nhất nhu cầu của khách. Nó có ngay trong ngày, trong khi tiền quyết toán đến sau cả tuần. Nó cũng là đầu ra của phễu bán hàng: mỗi thay đổi về lượt hiển thị, tỷ lệ nhấp hay tỷ lệ đặt hàng đều hiện ra ở GMV trước tiên. Cách dùng đúng là đọc GMV để hiểu phễu, và đọc số tiền quyết toán, đơn hủy, hoàn tiền để hiểu tiền.

Một thói quen tốt: mỗi tháng, đặt GMV, tổng hoàn tiền và số tiền quyết toán cạnh nhau. Nếu khoảng cách giữa GMV và tiền về đột nhiên rộng ra, câu hỏi cần đặt ra không nằm ở phễu mà ở đơn hủy, hoàn hàng hoặc phí.

## Cách tính GMV: công thức phễu

GMV có thể tính trực tiếp bằng cách cộng giá trị các đơn hàng. Nhưng cách tính đó không cho bạn biết vì sao GMV tăng hay giảm. Cách hữu ích hơn là tách GMV thành các bước mà khách đi qua trước khi mua.

### Bốn chỉ số tạo nên GMV

Học viện TikTok Shop định nghĩa các chỉ số sau trên trang "Lưu lượng truy cập sản phẩm", và bạn tìm thấy chúng tại Trung tâm nhà bán hàng, mục La bàn dữ liệu, phần Số liệu phân tích sản phẩm:

- **Lượt hiển thị sản phẩm**: số lần sản phẩm của bạn xuất hiện trước mắt người dùng, ở bất kỳ đâu như video, buổi LIVE, trang tìm kiếm hay trang đề xuất.
- **CTR (Tỷ lệ nhấp)**: tỷ lệ giữa Lượt nhấp vào sản phẩm và Lượt hiển thị sản phẩm. CTR cho biết trong số những lần sản phẩm được nhìn thấy, bao nhiêu lần người xem nhấp vào.
- **CTOR (Tỷ lệ từ nhấp đến đặt hàng)**: tỷ lệ giữa Đơn hàng SKU và Lượt nhấp vào sản phẩm. TikTok cho biết đây là tên mới năm 2026 của chỉ số trước đây gọi là Tỷ lệ chuyển đổi trong phân tích sản phẩm, và cách tính không đổi.
- **AOV (SKU)**: giá trị trung bình của mỗi đơn hàng SKU. TikTok định nghĩa là "số tiền trung bình mỗi khách hàng chi tiêu trên mỗi đơn hàng SKU trong khoảng thời gian đã chọn", và bạn tính lại được bằng GMV chia cho Đơn hàng SKU.

Ghép bốn chỉ số lại, ta có:

> GMV = Lượt hiển thị sản phẩm × CTR × CTOR × AOV (SKU)

TikTok không in công thức này trên Trung tâm nhà bán hàng; nó suy ra trực tiếp từ chính các định nghĩa trên. Lượt hiển thị nhân CTR ra Lượt nhấp, Lượt nhấp nhân CTOR ra Đơn hàng SKU, Đơn hàng SKU nhân AOV ra GMV. Đẳng thức đúng chính xác khi cả bốn chỉ số lấy trên cùng một sản phẩm hoặc nhóm sản phẩm, cùng một luồng truy cập và cùng một khoảng thời gian. Bài [Các chỉ số TikTok Shop: Lượt hiển thị, CTR, CTOR, AOV và cách đọc đúng](/blog/chi-so-tiktok-shop-ctr-ctor-aov) giải thích chi tiết từng chỉ số và các lần đổi tên.

### Ví dụ giả định: tính GMV của một sản phẩm

Giả sử một sản phẩm trong 30 ngày có các số sau (số giả định):

| Bước | Chỉ số | Giá trị |
|---|---|---|
| Lượt hiển thị sản phẩm | | 50.000 |
| Lượt nhấp vào sản phẩm | CTR 3 % | 1.500 |
| Đơn hàng SKU | CTOR 4 % | 60 |
| GMV | AOV 180.000 ₫ | 10.800.000 ₫ |

Đọc theo từng hàng: 50.000 lượt hiển thị nhân 3 % ra 1.500 lượt nhấp; 1.500 nhân 4 % ra 60 đơn hàng SKU; 60 nhân 180.000 ₫ ra 10.800.000 ₫. Mỗi hàng là một câu hỏi riêng: có đủ người nhìn thấy sản phẩm không, người thấy có nhấp không, người nhấp có mua không, và mỗi lần mua được bao nhiêu tiền.

{{hinh:gmv-pheu}}

### Vì sao công thức này giúp tăng GMV

Công thức phễu biến câu hỏi mơ hồ "làm sao tăng GMV" thành bốn câu hỏi cụ thể. Nếu CTR tăng từ 3 % lên 3,6 % trong ví dụ trên, trong khi ba chỉ số còn lại giữ nguyên, GMV tăng đúng 20 %, lên 12.960.000 ₫. Nếu AOV tăng từ 180.000 ₫ lên 198.000 ₫, GMV cũng tăng 20 %. Hai thay đổi cho cùng một kết quả nhưng đòi hỏi hai loại việc khác hẳn nhau: một bên là ảnh bìa, tiêu đề và giá hiển thị, bên kia là chương trình mua nhiều hay cơ cấu quy cách. Biết bước nào đang yếu giúp bạn chọn đúng việc.

## Tách GMV theo luồng truy cập

GMV của một sản phẩm hiếm khi đến từ một nơi. Khách có thể thấy sản phẩm trên trang tìm kiếm, trong video của shop, trong buổi LIVE, trong video của nhà sáng tạo hoặc khi vào trang cửa hàng. Mỗi nơi là một luồng truy cập với hành vi rất khác nhau.

### Năm luồng truy cập trên TikTok Shop

Trang "Lưu lượng truy cập sản phẩm" cho phép xem GMV, Lượt nhấp, CTR và CTOR theo các khía cạnh: Tất cả, LIVE của người bán, video của người bán, thẻ sản phẩm của người bán, Liên kết (gồm LIVE liên kết và video liên kết) và Tab Cửa hàng. Juli gom chúng thành năm luồng:

| Luồng | Khách đến từ đâu | Điều quyết định GMV của luồng |
|---|---|---|
| Thẻ sản phẩm | Tìm kiếm, đề xuất, trang mua sắm | Ảnh bìa, tiêu đề, giá, đánh giá |
| Tab cửa hàng | Khách chủ động vào trang shop | Trang sản phẩm, giá, khuyến mãi |
| Video | Video do tài khoản shop đăng | Nội dung và mức phân phối của video |
| LIVE | Buổi LIVE của shop | Người dẫn, kịch bản, ưu đãi trong phiên |
| Liên kết | Video và LIVE của nhà sáng tạo tiếp thị liên kết | Nhà sáng tạo và nội dung của họ |

Theo bài "Thẻ Sản Phẩm" của Học viện TikTok Shop, doanh thu "được tạo ra thông qua các kênh không đến từ LIVE và video sẽ được xem là doanh thu đến từ Thẻ sản phẩm". Vì vậy luồng thẻ sản phẩm là nơi phản ánh trung thực nhất chất lượng của chính trang sản phẩm: không có người dẫn hay nhà sáng tạo nào bán hộ.

Một lưu ý về Tab cửa hàng: trong bảng khía cạnh của TikTok, Tab Cửa hàng có Lượt nhấp, CTR và CTOR nhưng không nằm trong danh sách khía cạnh của Lượt hiển thị sản phẩm. Với luồng này, hãy tính từ Lượt nhấp: GMV = Lượt nhấp × CTOR × AOV.

{{hinh:nam-luong}}

### Ví dụ giả định: GMV của một shop theo năm luồng

Giả sử một shop trong 30 ngày có (toàn bộ là số giả định):

| Luồng | Lượt hiển thị | CTR | Lượt nhấp | CTOR | Đơn hàng SKU | AOV | GMV |
|---|---|---|---|---|---|---|---|
| Thẻ sản phẩm | 40.000 | 3 % | 1.200 | 4 % | 48 | 180.000 ₫ | 8.640.000 ₫ |
| Tab cửa hàng | | | 300 | 8 % | 24 | 200.000 ₫ | 4.800.000 ₫ |
| Video | 60.000 | 1,5 % | 900 | 5 % | 45 | 170.000 ₫ | 7.650.000 ₫ |
| LIVE | 20.000 | 4 % | 800 | 7 % | 56 | 210.000 ₫ | 11.760.000 ₫ |
| Liên kết | 80.000 | 2 % | 1.600 | 4,5 % | 72 | 175.000 ₫ | 12.600.000 ₫ |
| **Toàn shop** | | | 4.800 | 5,1 % | 245 | | **45.450.000 ₫** |

Bảng này cho thấy ba điều mà con số tổng 45,45 triệu không nói. Liên kết và LIVE mang về hơn một nửa GMV. Tab cửa hàng có CTOR cao nhất, vì khách vào đây thường đã có ý định mua. Còn video có nhiều lượt hiển thị nhưng CTR thấp nhất, nên nếu muốn tăng GMV từ video, câu hỏi đầu tiên là vì sao người xem video ít nhấp vào sản phẩm.

### Không gộp tỷ lệ của các luồng

CTOR toàn shop trong ví dụ là khoảng 5,1 %, nhưng không luồng nào có CTOR bằng 5,1 %. Đó là trung bình có trọng số của năm hành vi khác nhau. Nếu tháng sau shop có thêm nhiều lượt nhấp từ LIVE (CTOR 7 %) và ít lượt nhấp từ thẻ sản phẩm (CTOR 4 %), CTOR toàn shop sẽ tăng dù không trang sản phẩm nào tốt lên. Ngược lại, CTOR toàn shop có thể đi ngang trong khi thẻ sản phẩm đang tụt. Vì vậy khi tìm nguyên nhân, luôn tách theo luồng trước, rồi mới đọc tỷ lệ.

## Tìm bước yếu nhất trong phễu

Có công thức và bảng theo luồng, việc tìm chỗ cần sửa trở thành một quy trình bốn bước. Mục tiêu là tìm một điểm nghẽn cụ thể, ở một luồng cụ thể, trên một vài sản phẩm cụ thể, thay vì sửa mọi thứ cùng lúc.

{{hinh:buoc-yeu-nhat}}

### Bước 1: luồng nào thay đổi nhiều nhất

So sánh GMV của từng luồng giữa hai kỳ dài bằng nhau, ví dụ 30 ngày gần nhất với 30 ngày trước đó. Luồng có mức thay đổi tuyệt đối lớn nhất là nơi bắt đầu. Đừng nhìn phần trăm: một luồng nhỏ tăng 80 % có thể chỉ thêm vài trăm nghìn đồng, trong khi một luồng lớn giảm 10 % mất vài triệu.

### Bước 2: hệ số nào trong luồng đó

Trong luồng đã chọn, so sánh từng hệ số giữa hai kỳ: Lượt hiển thị, CTR, CTOR và AOV. Hệ số thay đổi nhiều nhất theo tỷ lệ là câu chuyện chính. Bài [Các chỉ số TikTok Shop](/blog/chi-so-tiktok-shop-ctr-ctor-aov) có một ví dụ hai hệ số đi ngược chiều nhau và che nhau trong con số GMV tổng.

Ví dụ giả định: GMV luồng thẻ sản phẩm giảm từ 8,64 triệu xuống 7,2 triệu. Lượt hiển thị giữ 40.000, CTR giữ 3 %, AOV giữ 180.000 ₫, còn CTOR giảm từ 4 % xuống khoảng 3,3 %. Bước yếu là CTOR: khách vẫn nhìn thấy và vẫn nhấp như cũ, nhưng ít người đặt hàng hơn.

### Bước 3: so với chính nó và với sản phẩm khác

Một chỉ số "thấp" chỉ có nghĩa khi có mốc so sánh. TikTok không công bố một mức CTR hay CTOR chuẩn cho mọi ngành, và các chỉ số này khác nhau nhiều giữa ngành hàng và giữa các luồng. Hãy dùng hai mốc:

- **Chính sản phẩm đó ở kỳ trước**, trên cùng luồng truy cập.
- **Các sản phẩm khác trong shop**, trên cùng luồng truy cập. Sản phẩm thấp hơn hẳn phần lớn sản phẩm khác cùng luồng là ứng viên cần xem trước.

### Bước 4: đủ dữ liệu để kết luận chưa

Một sản phẩm có 3 đơn mỗi tuần có thể dao động CTOR từ 2 % lên 6 % chỉ vì ngẫu nhiên. Trước khi kết luận, hãy chắc rằng mỗi kỳ có đủ lượt hiển thị, lượt nhấp và đơn hàng. Juli chỉ đọc một chỉ số khi luồng thẻ sản phẩm có đủ lượt hiển thị, lượt nhấp và đơn hàng; dưới mức đó, Juli ghi "chưa đủ dữ liệu" thay vì đọc một con số. Nếu tự làm, hãy chờ đến khi số liệu đủ nhiều để không bị nhiễu, hoặc gộp một khoảng thời gian dài hơn, và giữ cùng một cách đọc cho mọi lần so sánh. TikTok không đưa ra ngưỡng chính thức cho việc này.

## Cách tăng GMV trên TikTok theo từng hệ số

Khi đã biết hệ số nào yếu, đây là các đòn bẩy phù hợp. Loạt bài "Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào" của Học viện TikTok Shop chia các yếu tố của thẻ sản phẩm thành ba nhóm: Hiển thị (hình ảnh chính, tiêu đề, mô tả), Lợi ích (giá cạnh tranh, chiết khấu, voucher, ưu đãi chớp nhoáng, mua thêm tiết kiệm nhiều hơn, thanh toán khi giao hàng) và Sự tin cậy (thương hiệu, đánh giá, tỷ lệ trả hàng). Dưới đây là cách nối các nhóm đó với từng hệ số.

### Tăng Lượt hiển thị sản phẩm

Lượt hiển thị là bước người bán kiểm soát ít nhất bằng trang sản phẩm. Bài "Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 1" giải thích rằng thẻ sản phẩm cần đạt ngưỡng tối thiểu để vào nhóm đề xuất, và sau đó cần giữ hiệu quả vận hành như giao hàng đúng hạn, phản hồi nhanh đơn hàng mới để không bị tụt hạng. Những việc thường giúp tăng lượt hiển thị:

- **Tiêu đề đúng từ khóa người mua tìm**, để sản phẩm xuất hiện trong kết quả tìm kiếm. Trình Tối Ưu Hóa Tiêu Đề Sản Phẩm trong La bàn dữ liệu gợi ý từ khóa theo ý định tìm kiếm.
- **Nội dung**: video của shop, buổi LIVE, hợp tác với nhà sáng tạo tiếp thị liên kết.
- **Tham gia chương trình khuyến mãi của nền tảng** khi biên lợi nhuận cho phép.
- **Giữ vận hành ổn định**: giao đúng hạn, ít hủy đơn.

Lưu ý: khi lượt hiển thị tăng mạnh, CTR thường giảm nhẹ, vì phần traffic mới ít quan tâm hơn. Đừng vội sửa trang sản phẩm khi thấy CTR giảm ngay sau một đợt tăng traffic.

### Tăng CTR

CTR thấp ở luồng thẻ sản phẩm thường do những gì người xem nhìn thấy trên thẻ trước khi nhấp:

- **Ảnh bìa**: sản phẩm có rõ ở kích thước nhỏ trên điện thoại không, nền có đồng nhất không, có bị chữ hay nhãn dán che không.
- **Tiêu đề**: nói rõ sản phẩm là gì, đặc điểm chính và quy cách, đặt phần quan trọng lên đầu vì phần cuối thường bị cắt.
- **Giá hiển thị**: công cụ Chẩn đoán giá cho biết sản phẩm đang ở trạng thái "Giá không cạnh tranh", "Giá cạnh tranh" hay "Giá tốt nhất" so với sản phẩm tương tự.

Bài [Tối ưu thẻ sản phẩm TikTok Shop từ A–Z](/blog/toi-uu-the-san-pham-tiktok-shop) đi sâu vào từng thành phần, kèm quy định của TikTok về hình ảnh và tiêu đề.

### Tăng CTOR

CTOR thấp nghĩa là khách đã nhấp vào nhưng không đặt hàng. Hãy tách làm hai nửa bằng Tỷ lệ thêm vào giỏ hàng, chỉ số mà TikTok định nghĩa lại năm 2026 là số lượt nhấp nút Thêm vào giỏ hàng chia cho số lượt nhấp vào sản phẩm:

- **Khách không thêm vào giỏ**: chưa bị thuyết phục. Xem lại bộ ảnh chi tiết, mô tả, đánh giá và giá.
- **Khách thêm vào giỏ nhưng không thanh toán**: xem phí vận chuyển, voucher đã hết hạn chưa, hoặc khách có đang chờ một đợt ưu đãi họ đoán sẽ đến không.

Mô tả sản phẩm là nơi khách tìm câu trả lời trước khi quyết định. Một cách làm đơn giản: mở hộp tin nhắn và phần đánh giá, liệt kê 5 câu hỏi khách hay hỏi nhất, rồi trả lời chúng ngay trong mô tả.

### Tăng AOV

AOV tăng khi khách mua nhiều món hơn mỗi lần, chọn quy cách lớn hơn, hoặc khi giá bán thực tế cao hơn. Công cụ phổ biến nhất là **Mua Sỉ Giá Hời**, mà Học viện TikTok Shop mô tả là công cụ khuyến mãi dựa trên đơn hàng "để tăng giá trị đơn hàng trung bình": giảm giá khi khách mua đủ số lượng tối thiểu, tối đa hai bậc. Hãy đặt ngưỡng ở mức một phần khách hiện tại đã mua, ví dụ "từ 2 món" nếu đã có khách mua 2, thay vì một mức gần như không ai đạt tới. Ưu đãi theo gói và quà tặng kèm là lựa chọn khác, nên dựa trên các cặp sản phẩm thật sự hay được mua cùng nhau.

### Những cách tăng GMV dễ phản tác dụng

- **Giảm giá đại trà cho mọi sản phẩm**: GMV có thể tăng nhờ CTOR, nhưng AOV giảm và biên lợi nhuận mất. Nếu bước yếu là CTR do ảnh bìa, giảm giá không giải quyết được.
- **Tăng ngân sách quảng cáo khi CTOR đang thấp**: thêm lượt hiển thị cho một trang sản phẩm đang không chuyển đổi chỉ làm tăng số người rời đi. Kiểm tra CTR và CTOR trước, rồi mới quyết định mua thêm traffic.
- **Đổi nhiều thứ cùng lúc**: đổi ảnh, giảm giá và viết lại mô tả trong cùng một ngày khiến bạn không biết thay đổi nào có tác dụng.
- **Đẩy traffic vào sản phẩm có đánh giá kém**: Học viện TikTok Shop xếp đánh giá tiêu cực và tỷ lệ trả hàng vào nhóm Sự tin cậy. Thêm khách cho một sản phẩm bị đánh giá thấp chỉ làm tăng số người thất vọng.

## Đo lại sau khi thay đổi

Tăng GMV không kết thúc ở lúc bạn bấm lưu. Nếu không đo lại, bạn không biết thay đổi nào đáng giữ. Ba nguyên tắc đơn giản:

1. **Một thay đổi, một sản phẩm, một lúc.** Ghi lại ngày thay đổi và không chạm vào sản phẩm đó cho đến khi đo xong.
2. **So sánh cửa sổ trước và sau.** Juli dùng 14 ngày trước thay đổi, đọc sơ bộ sau 7 ngày và kết luận sau 14 ngày.
3. **Đo đúng hệ số mà thay đổi nhắm tới, và nếu tự đo, để vài sản phẩm chưa sửa làm mốc so sánh.** Đổi ảnh bìa thì đọc CTR trước. Thêm Mua Sỉ Giá Hời thì đọc AOV. Nếu các sản phẩm không sửa cũng tăng như sản phẩm đã sửa, có thể cả shop đang được hưởng một đợt traffic chung, không phải nhờ thay đổi của bạn.

{{hinh:dl-tang-them}}

Ghi lại cả những kết quả "không đổi". Chúng cho biết thành phần đó không phải điểm nghẽn, và lần sau bạn có thể bỏ qua.

## Juli AI giúp gì trong việc tăng GMV

Juli AI là trợ lý AI cho nhà bán TMĐT do chúng tôi phát triển, hiện kết nối TikTok Shop (Shopee đang tích hợp). Với GMV, phần đọc số trong bài này Juli làm sẵn cho bạn, còn mọi thay đổi trên shop chỉ diễn ra khi bạn duyệt:

- **Phân tích**: [phân tích shop theo từng luồng truy cập](/san-pham/phan-tich-shop), tách GMV theo năm luồng (Thẻ sản phẩm, Tab cửa hàng, Video, LIVE, Liên kết) và theo bốn hệ số Lượt hiển thị × CTR × CTOR × AOV, rồi chỉ ra sản phẩm nào đang mất khách ở bước nào.
- **Đề xuất**: [đề xuất cách sửa kèm lý do bằng số](/san-pham/de-xuat-va-thuc-thi). Juli chỉ ghi tiêu đề và mô tả sản phẩm lên shop sau khi bạn duyệt; những thay đổi khác như giá hay khuyến mãi là đề xuất để bạn tự quyết định và thực hiện.
- **Đo lường**: [đo tác động lên GMV](/san-pham/do-luong-gmv) ở ngày 7 (sơ bộ) và ngày 14 (chốt), so với mốc 14 ngày trước khi áp dụng.

{{hinh:pt-luong}}

Juli không chạy quảng cáo và không quản lý đơn hàng hay tồn kho; Juli đọc dữ liệu qua [kết nối chính thức với TikTok Shop](/ket-noi/tiktok-shop). Xem tổng quan tại trang [sản phẩm Juli AI](/san-pham).

## Tóm tắt

- **GMV là gì**: theo TikTok, GMV là tổng số tiền thanh toán cho các đơn hàng trong khoảng thời gian đã chọn, bao gồm cả đơn đã hủy và hoàn tiền.
- **GMV không phải tiền về**: muốn biết tiền thật, trừ đơn hủy, hoàn tiền và các khoản phí, rồi đọc số tiền quyết toán trong mục Tài chính.
- **Cách tính GMV theo phễu**: GMV = Lượt hiển thị sản phẩm × CTR × CTOR × AOV, đúng khi bốn chỉ số cùng phạm vi sản phẩm, luồng và thời gian.
- **Tách theo năm luồng**: Thẻ sản phẩm, Tab cửa hàng, Video, LIVE và Liên kết có hành vi khác nhau; không đọc tỷ lệ gộp toàn shop.
- **Tăng GMV bằng đúng đòn bẩy**: tìm luồng thay đổi nhiều nhất, hệ số yếu nhất trong luồng đó, kiểm tra đủ dữ liệu, sửa một thứ và đo lại sau 7 và 14 ngày.

Nếu bạn muốn xem GMV của shop mình được tách theo luồng và theo bốn hệ số mà không phải tự xuất bảng tính, bạn có thể [đăng ký dùng thử Juli AI](/dang-ky) và kết nối shop TikTok khi sẵn sàng.
`;
