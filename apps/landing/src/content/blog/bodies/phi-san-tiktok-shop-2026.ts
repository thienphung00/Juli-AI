/**
 * News post (D56 G3 TMĐT-change track, P46-C2): fees and what is left of an
 * order. Main keyword "phí sàn tiktok shop 2026" (Google autocomplete VN
 * 2026-10-17; also "phí hoa hồng tiktok shop 2026", "phí bán hàng tiktok shop"
 * with 9 suggestions). Built ONLY from Học viện TikTok Shop pages re-read on
 * 2026-10-17, each dated: Phí của Nhà Bán Hàng (04/08/2026), Phí Hoa Hồng Nền
 * Tảng (30/09/2026; default 14 % standard from 03/07/2026, 16 % Mall from
 * 03/08/2026; Mall Sách table from 20/10/2026; support programme ended
 * 30/09/2026), the two commission PDFs (from 03/07 + 03/08/2026, and from
 * 20/10/2026) compared row by row (1,945 shared level-3 rows: 0 standard
 * changes, 41 Mall decreases, all Sách), Phí Giao Dịch (13/10/2026; 6 % for
 * orders after 00:00 09/05/2026; savings tiers from 21/10/2026), Phí Xử Lý Đơn
 * Hàng (11/10/2025; 3.000 đ from 27/10/2025), Phí Vận Hành Logistic
 * (08/10/2026; > 10 kg, 3.000 to 65.000 VND, from 12/10/2026), Thông Tin Cơ Bản
 * về Thuế trên Phí Nền Tảng (30/09/2026). No "from X to Y" for older levels:
 * official pages show only the current ones. Update when a fee page changes.
 */
export const body = `
Tại ngày 17/10/2026, một đơn giao thành công trên TikTok Shop chịu ba khoản phí cố định của nền tảng: phí hoa hồng theo ngành hàng (mặc định 14% với Nhà Bán Hàng Tiêu Chuẩn, 16% với Mall), phí giao dịch 6% và phí xử lý đơn 3.000 đồng. Kiện trên 10 kg đặt từ 12/10/2026 có thêm phí vận hành logistic từ 3.000 đến 65.000 VND. Với một đơn 200.000 đồng ở mức phí mặc định, ba khoản đầu đã khoảng 22% giá bán, trước giá vốn và quảng cáo.

> **Cập nhật ngày 17/10/2026.** Mọi mức phí và ngày dưới đây lấy từ các trang Học viện TikTok Shop, kèm ngày cập nhật của từng trang. Phí sàn thay đổi nhiều lần trong năm 2026 và còn hai mốc trong tuần tới (20/10 và 21/10). Trước khi định giá, hãy kiểm tra lại trên trang gốc và trong Trung tâm nhà bán hàng, mục Tài chính, Giao dịch.

## Phí sàn TikTok Shop 2026: bốn khoản và ngày hiệu lực

| Khoản phí | Mức hiện hành | Tính trên | Hiệu lực | Nguồn (ngày cập nhật) |
|---|---|---|---|---|
| Phí hoa hồng nền tảng | Theo ngành hàng cấp 3; mặc định 14% (Tiêu Chuẩn), 16% (Mall) | Giá gốc trừ chiết khấu của Nhà Bán Hàng | 03/07/2026 (Tiêu Chuẩn), 03/08/2026 (Mall) | Phí Hoa Hồng Nền Tảng (30/09/2026) |
| Phí giao dịch | 6% | Số tiền khách thanh toán cộng chiết khấu của nền tảng, trừ phần hoàn tiền | Đơn sau 00:00 ngày 09/05/2026 | Phí Giao Dịch (13/10/2026) |
| Phí xử lý đơn hàng | 3.000 đồng mỗi đơn, đã gồm thuế | Mỗi đơn giao thành công, mọi giá trị | Thu từ 27/10/2025 | Phí Xử Lý Đơn Hàng (11/10/2025) |
| Phí vận hành logistic | Từ 3.000 đến tối đa 65.000 VND mỗi kiện | Chỉ kiện có trọng lượng tính phí trên 10 kg | Đơn đặt từ 00:00 ngày 12/10/2026 | Phí Vận Hành Logistic (08/10/2026) |

Trang tổng quan "Phí của Nhà Bán Hàng" (04/08/2026) còn nêu **phí vận chuyển**: người bán chỉ trả khi kích thước kiện thực tế vượt kích thước đã khai lúc niêm yết. Khai đúng kích thước là cách đơn giản nhất để tránh khoản này. Trang tổng quan cũ hơn các trang chi tiết và chưa nhắc phí vận hành logistic; bài này theo các trang chi tiết.

## Phí hoa hồng TikTok Shop 2026 tính thế nào

Theo trang "Phí Hoa Hồng Nền Tảng", phí được trừ tự động sau khi đơn giao thành công, theo công thức **(Giá gốc sản phẩm trừ Chiết khấu của Nhà Bán Hàng) nhân Phí suất**. Phí suất khác nhau theo ngành hàng cấp 3 và giữa Nhà Bán Hàng Tiêu Chuẩn với Mall. Ngành không có trong bảng dùng mức mặc định: 14,00% (Tiêu Chuẩn, từ 03/07/2026) và 16,00% (Mall, từ 03/08/2026).

Cách tra mức của ngành bạn: tải bảng phí suất PDF trên trang đó, tìm đúng ngành hàng cấp 3 của sản phẩm. Trong bảng áp dụng từ 03/07/2026, phí suất Tiêu Chuẩn đi từ 1,5% đến 16,0%, mức ở giữa của bảng là 14,0%.

### Mốc 20/10/2026: chỉ một số ngành Sách của Mall

Trang hoa hồng đã đăng bảng phí suất từ 20/10/2026. Chúng tôi so từng dòng hai bảng PDF trên 1.945 ngành cấp 3 có ở cả hai: phí suất Tiêu Chuẩn không đổi ở ngành nào; phí suất Mall đổi ở 41 ngành, tất cả đều **giảm** và đều thuộc Sách, tạp chí & âm thanh (phần lớn từ 15,0% xuống 12,5%). Nói cách khác, mốc này không phải đợt tăng phí với người bán thông thường.

### Chương trình hỗ trợ hoa hồng cho shop mới đã kết thúc

Shop tạo từ 01/01/2026 đến 26/06/2026 từng được giảm 50% phí hoa hồng, tối đa không quá 3% (ngành dưới 6% giảm một nửa; ngành từ 6% trừ thẳng 3%, ví dụ 10% còn 7%). Chương trình chạy đến 23:59:59 ngày 30/09/2026 cho cả Tiêu Chuẩn và Mall. Nếu shop bạn từng được hưởng, từ tháng 10 phí hoa hồng về mức trong bảng; trang không nêu chương trình tiếp theo.

## Phí giao dịch 6% có tính cả tiền ship không

Có, phần ship do khách trả nằm trong cơ sở tính. Ví dụ trên trang "Phí Giao Dịch": giá gốc 100.000 đồng, chiết khấu người bán 5.000, chiết khấu nền tảng 5.000, phí vận chuyển khách trả 5.600, cơ sở tính là 105.600 và phí giao dịch là 6.336 đồng. Phần hoàn tiền thì được trừ khỏi cơ sở.

Từ ngày 21/10/2026, Chương trình Tiết Kiệm Phí Giao Dịch chuyển sang bậc theo tỷ lệ chi tiêu quảng cáo 30 ngày của shop: mức tiết kiệm từ 0,0% (tỷ lệ dưới 4%) đến 1,5% (tỷ lệ từ 20%), các bậc không cộng dồn. Shop có toàn bộ GMV từ ngành không được chạy quảng cáo có thể được tiết kiệm 1,0% theo một quy tắc riêng. Xem shop có đủ điều kiện ở Trung tâm nhà bán hàng.

## Ví dụ giả định: một đơn 200.000 đồng còn lại bao nhiêu

Ví dụ giả định: một sản phẩm giá 200.000 đồng, không chiết khấu, ngành dùng phí suất mặc định 14% của Nhà Bán Hàng Tiêu Chuẩn, khách trả 20.000 đồng phí ship, kiện dưới 10 kg, người bán là cá nhân nên phí đã gồm thuế.

| Khoản | Cách tính | Số tiền |
|---|---|---|
| Giá bán | | 200.000 đ |
| Phí hoa hồng | 200.000 × 14% | 28.000 đ |
| Phí giao dịch | (200.000 + 20.000 ship khách trả) × 6% | 13.200 đ |
| Phí xử lý đơn | cố định | 3.000 đ |
| Còn lại sau phí sàn | 200.000 trừ 44.200 | 155.800 đ |
| Giá vốn và đóng gói | giả định 110.000 + 4.000 | 114.000 đ |
| Lãi trước quảng cáo, hoa hồng nhà sáng tạo, thuế | | 41.800 đ |

{{hinh:phi-mot-don-200k}}

Trong ví dụ, phí sàn là 44.200 đồng, tức 22,1% giá bán, và lãi còn 20,9% trước các chi phí khác. Phí xử lý cố định nặng hơn ở đơn nhỏ. Vẫn là ví dụ giả định, ở mức mặc định: đơn 60.000 đồng không ship chịu 8.400 hoa hồng, 3.600 phí giao dịch và 3.000 phí xử lý, tức 25% giá bán. Nếu đơn 200.000 đồng bị trả hàng sau khi đã giao, phí xử lý 3.000 đồng không được hoàn; chi tiết từng trường hợp có trong bài [Tỷ lệ hoàn hàng TikTok Shop](/blog/ty-le-hoan-hang-tiktok-shop).

## Phí đã gồm thuế chưa

Theo trang "Thông Tin Cơ Bản về Thuế trên Phí Nền Tảng" (30/09/2026), phí nền tảng chịu 10% thuế GTGT và 5% thuế TNDN. Cá nhân, hộ kinh doanh và tổ chức chưa có mã số thuế được TikTok Shop xác minh trả phí **đã gồm thuế**, TikTok kê khai và nộp. Tổ chức đã đăng ký thuế tại Việt Nam và có mã số thuế được xác minh trả phí **chưa gồm thuế** và tự kê khai, nộp. Bảng phí vận hành logistic là mức trước thuế. Thuế trên doanh thu bán hàng của người bán là chuyện khác, xem bài [Thuế bán hàng TikTok Shop 2026](/blog/thue-ban-hang-tiktok-shop).

## Đọc GMV và tiền thực nhận cho đúng

GMV trong La bàn dữ liệu là tổng tiền khách thanh toán, **gồm cả đơn đã hủy và hoàn tiền** (trang "Lưu lượng truy cập sản phẩm", 17/06/2026). Tiền thực nhận là GMV trừ đơn hủy, hoàn tiền và các khoản phí ở trên, đọc ở mục Tài chính, Giao dịch, theo từng đơn đã quyết toán.

{{hinh:gmv-den-tien-ve}}

Vì vậy, khi phí tăng hay đơn hoàn nhiều, GMV có thể vẫn đẹp trong khi tiền về giảm. Bài [GMV là gì](/blog/gmv-la-gi-tiktok-shop) giải thích khoảng cách này chi tiết hơn.

### Tự đối chiếu phí mỗi tháng

Mỗi tháng, mở mục Tài chính, Giao dịch và chọn vài đơn đã quyết toán ở các mức giá khác nhau. Với mỗi đơn, so từng dòng phí với cách tính ở trên: phí hoa hồng theo đúng ngành hàng của sản phẩm, phí giao dịch trên cơ sở có cả phí ship khách trả, phí xử lý đơn cố định. Một dòng lệch là dấu hiệu sản phẩm đang ở ngành hàng khác bạn nghĩ, hoặc một trang phí vừa được cập nhật. Ghi lại phần còn lại của mỗi đơn cạnh giá vốn để biết mức giá nào vẫn có lãi.

Thuế được sàn khấu trừ trên từng giao dịch là một khoản khác, xem bài [Thuế bán hàng TikTok Shop 2026](/blog/thue-ban-hang-tiktok-shop); chi phí của đơn bị trả có trong bài [Tỷ lệ hoàn hàng TikTok Shop](/blog/ty-le-hoan-hang-tiktok-shop). Để xem GMV đổi ra sao khi một chỉ số của phễu tăng, thử [công cụ tính GMV miễn phí](/cong-cu/tinh-gmv).
`;
