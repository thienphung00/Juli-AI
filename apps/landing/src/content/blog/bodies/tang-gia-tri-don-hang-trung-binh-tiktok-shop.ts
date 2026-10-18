/**
 * Pain post (D56, P46-C1, week 2 #6): "Mỗi đơn giá trị thấp, bán nhiều mà vẫn
 * ít tiền". Main keyword "tăng giá trị đơn hàng trung bình tiktok shop" (brief
 * variant of the plan's "cách tăng giá trị đơn hàng tiktok shop": Google
 * autocomplete VN 2026-10-17 has the generic "tăng giá trị đơn hàng trung bình",
 * empty with the platform name, as is the plan phrase). "aov là gì" stays with
 * `chi-so-tiktok-shop-ctr-ctor-aov`; the step after the click stays with
 * `khach-xem-nhung-khong-mua-tiktok-shop`. Facts re-opened on 2026-10-17 in
 * TikTok Academy VN (title + date in the text and `sources`): Voucher Thông
 * Thường Của Nhà Bán Hàng (13/06/2025, tip 1,2 to 1,5 × AOV, tiers), Mua Sỉ Giá
 * Hời (09/12/2025, two tiers), Ưu Đãi Theo Gói (16/04/2024, 2 to 3 products,
 * not stacked with BMSM), Quà Tặng Khi Mua Hàng (05/01/2026), Chiết Khấu Phí
 * Vận Chuyển của Nhà Bán Hàng (24/01/2025), Cách Tính Khuyến Mãi Cộng Dồn
 * (29/10/2025, three layers), Phí Xử Lý Đơn Hàng (11/10/2025, 3.000 đ per
 * delivered order, tax included), Lưu lượng truy cập sản phẩm (17/06/2026,
 * AOV (SKU)). Third-party "mua 2 giảm 5 %, freeship từ 499K" recipes are not
 * used. D59 reach post (P48-C): no Juli, no product links; the last how-to
 * section is a self-kept AOV-by-source and promotion sheet from Seller Center.
 */
export const body = `
Bán được nhiều đơn mà cuối tháng còn lại ít tiền thường là vì mỗi đơn có giá trị quá nhỏ. GMV bằng số đơn nhân giá trị trung bình mỗi đơn (AOV), nhưng có những khoản tính theo từng đơn chứ không theo giá trị đơn, như phí xử lý đơn hàng 3.000 đồng của TikTok Shop, nên đơn càng nhỏ thì phần bị trừ càng lớn. Tăng giá trị đơn hàng trung bình không có nghĩa là giảm giá sâu hơn: bài này chỉ cách đọc AOV theo từng nguồn, chọn đúng công cụ khuyến mãi chính thức để khách mua thêm, tránh giảm giá chồng giảm giá, rồi đo lại sau 7 và 14 ngày.

Định nghĩa AOV và cách TikTok tính nó có trong bài [các chỉ số TikTok Shop](/blog/chi-so-tiktok-shop-ctr-ctor-aov); bài này không giải thích lại. Nếu vấn đề của bạn là khách bấm vào mà không đặt, hãy đọc bài [khách xem nhưng không mua](/blog/khach-xem-nhung-khong-mua-tiktok-shop) trước. Mọi con số trong các ví dụ là ví dụ giả định.

## Bán nhiều mà ít tiền: kiểm tra AOV trước khi kết luận

"Đơn nào cũng 50, 80 nghìn": trước khi tìm cách tăng giá trị đơn, hãy xem con số thật của shop. Theo bài "Lưu lượng truy cập sản phẩm" của Học viện TikTok Shop (cập nhật 17/06/2026), **AOV (SKU)** là số tiền trung bình khách thanh toán cho một đơn hàng SKU trong khoảng thời gian đã chọn. Bạn có thể tự tính lại:

> AOV (SKU) = GMV ÷ Đơn hàng SKU

Chỉ số này nằm trong La bàn dữ liệu, Số liệu phân tích sản phẩm. TikTok không công bố một mức AOV "tốt" chung; mốc so sánh là chính shop ở kỳ trước và các sản phẩm khác trong shop.

### Ba câu hỏi trước khi kết luận AOV thấp

- **AOV giảm hay vốn đã thấp?** Nếu vừa giảm, xem ưu đãi mua nhiều nào vừa kết thúc, đợt giảm giá sâu nào vừa bắt đầu, hay khách đang chọn biến thể rẻ hơn.
- **Lợi nhuận thấp vì AOV hay vì biên lợi nhuận?** AOV cao vẫn có thể lỗ nếu giá vốn và khuyến mãi ăn hết phần chênh.
- **AOV thấp ở cả shop hay vài sản phẩm?** Một sản phẩm giá rẻ bán chạy có thể kéo AOV cả shop xuống mà không có gì sai.

## Vì sao đơn nhỏ khó có lãi: phí tính theo từng đơn

Theo bài "Phí Xử Lý Đơn Hàng" của Học viện TikTok Shop (cập nhật 11/10/2025), từ ngày 27/10/2025 mỗi đơn giao thành công bị thu một khoản cố định 3.000 đồng, đã gồm thuế, **áp dụng cho mọi giá trị đơn và số lượng hàng trong đơn**. Đơn đã giao thành công rồi mới phát sinh hoàn tiền hoặc trả hàng vẫn bị thu khoản này.

Khoản cố định theo đơn nghĩa là đơn càng nhỏ, phần trăm bị trừ càng lớn. Hình dưới chỉ tách riêng phí xử lý đơn; ngoài nó còn các khoản phí và chi phí khác.

{{hinh:aov-phi-co-dinh}}

Hai món trong một đơn chịu một lần phí xử lý, hai món ở hai đơn chịu hai lần: khách mua thêm trong cùng một đơn có lợi hơn cho người bán.

## AOV thấp ở nguồn nào: video, LIVE, thẻ sản phẩm hay tab cửa hàng

Bài "Lưu lượng truy cập sản phẩm" cho xem GMV, Đơn hàng SKU và Số món bán ra theo khía cạnh: LIVE, video và thẻ sản phẩm của người bán, Liên kết. Chia GMV cho Đơn hàng SKU của từng khía cạnh, bạn có AOV theo nguồn. Các nguồn thường khác nhau nhiều:

- **Video và LIVE** thường đẩy một sản phẩm cụ thể, đôi khi là biến thể rẻ nhất để thu hút. AOV thấp ở đây hay đến từ việc chỉ giới thiệu một món.
- **Thẻ sản phẩm và Tab cửa hàng** là nơi khách tự tìm và tự chọn. Nếu khách vào Tab cửa hàng mà vẫn chỉ mua một món, có thể shop chưa cho họ lý do để thêm món thứ hai.

Biết AOV thấp ở nguồn nào giúp chọn cách sửa: ở LIVE là giới thiệu thêm sản phẩm đi kèm, ở Tab cửa hàng là voucher theo bậc hay gói sản phẩm.

## Nên tăng giá trị đơn hay tăng số đơn

GMV của mỗi luồng là Lượt hiển thị × CTR × CTOR × AOV. Tăng AOV chỉ là một trong bốn đòn bẩy, và không phải lúc nào cũng là đòn bẩy rẻ nhất.

{{hinh:aov-hai-shop}}

Trong ví dụ giả định ở trên, hai shop cùng GMV nhưng shop A phải đóng gói, giao 1.000 đơn và trả 3 triệu đồng phí xử lý, shop B chỉ 400 đơn. Câu hỏi đúng là "bước nào trong phễu đang yếu nhất":

- **Lượt hiển thị hoặc CTR thấp**: ít người thấy hay ít người bấm vào. Tăng AOV lúc này không giải quyết vấn đề chính.
- **CTOR thấp**: khách bấm vào rồi không mua. Thêm điều kiện "mua 2 mới được giảm" có thể làm CTOR giảm thêm.
- **Ba bước đầu ổn, AOV thấp**: đây là lúc tăng giá trị đơn đáng làm nhất, vì khách đã tin và đã mua.

Thử [công cụ tính GMV miễn phí](/cong-cu/tinh-gmv) để ước tính GMV đổi ra sao khi AOV đổi; bài [GMV là gì](/blog/gmv-la-gi-tiktok-shop) giải thích cách tách GMV theo bốn hệ số.

## Voucher theo bậc: đặt mức chi tối thiểu từ AOV hiện tại

Bài "Voucher Thông Thường Của Nhà Bán Hàng" (13/06/2025) mở đầu bằng việc dùng voucher "để tăng giá trị đơn hàng trung bình và tỷ lệ chuyển đổi". Voucher giảm theo số tiền hoặc phần trăm, có **mức chi tối thiểu** và, với giảm theo phần trăm, có thể đặt **mức giảm tối đa cho mỗi đơn hàng**. Phần mẹo của bài đưa ra hai gợi ý:

1. Đặt mức chi tối thiểu **cao hơn 1,2 đến 1,5 lần** giá trị đơn hàng trung bình, xem trong La bàn dữ liệu.
2. Tạo **nhiều bậc** với mức chi thấp, trung bình, cao, mức chiết khấu sâu hơn cho mức chi cao hơn.

Ví dụ giả định: AOV 120.000 ₫ thì mức chi tối thiểu nằm trong khoảng 144.000 đến 180.000 ₫, chẳng hạn đơn từ 150.000 ₫ giảm 10.000 ₫, đơn từ 250.000 ₫ giảm 25.000 ₫. Số giảm là quyết định của bạn, dựa trên giá vốn.

Ba điều cần nhớ khi chạy voucher:

- **Mỗi đơn chỉ dùng một voucher của nhà bán hàng**, voucher giảm cao nhất được áp dụng.
- **Mức chi tối thiểu xét trên giá sau giảm giá sản phẩm**, theo bài "Cách Tính Khuyến Mãi Cộng Dồn". Một sản phẩm đang giảm giá có thể làm giỏ hàng không còn đạt ngưỡng.
- **Tỷ lệ đổi thấp là tín hiệu** mức chi tối thiểu quá cao so với giá bán trung bình, theo bài voucher.

Bài "Chiết Khấu Phí Vận Chuyển của Nhà Bán Hàng" (24/01/2025) cho một mẹo tương tự với miễn phí vận chuyển: đặt mức chi tối thiểu cao hơn một chút so với giá trị đơn hàng trung bình.

## Mua nhiều giảm nhiều, ưu đãi theo gói và quà tặng: chọn công cụ nào

Ngoài voucher, Học viện TikTok Shop mô tả thêm ba công cụ do nhà bán hàng trợ giá với mục tiêu tăng giá trị đơn hàng trung bình. Mỗi công cụ hợp với một kiểu sản phẩm.

### Mua Sỉ Giá Hời: khi khách hay mua nhiều cái cùng loại

Theo bài "Mua Sỉ Giá Hời (BMSM)" (09/12/2025), khách mua đủ số lượng thì được giảm phần trăm, **tối đa hai bậc**. Bài gợi ý chọn sản phẩm hay mua số lượng lớn, dùng cùng nhau hoặc có nhiều kiểu dáng, màu sắc, và theo dõi số mặt hàng trung bình trên mỗi đơn để chọn ngưỡng: nếu khách thường mua 1 món, ngưỡng "mua 2" dễ đạt hơn "mua 4".

### Ưu đãi theo gói (combo): khi sản phẩm dùng cùng nhau

Theo bài "Ưu Đãi Theo Gói" (16/04/2024), công cụ này cho bán **2 đến 3 sản phẩm** cùng nhau với giá cố định hoặc phần trăm giảm, và giá ưu đãi của từng SKU trong gói phải thấp hơn giá gốc. Bài gợi ý tạo gói từ những sản phẩm khách đã từng mua chung. Lưu ý: Ưu đãi theo gói **không cộng dồn** với Mua Sỉ Giá Hời của nhà bán hàng, và được ưu tiên hơn; khách phải chọn qua mục mua theo gói thì mới được giá gói.

### Quà tặng khi mua hàng: khi không muốn giảm giá

Theo bài "Quà Tặng Khi Mua Hàng" (05/01/2026), khách mua đủ số món hoặc chi đủ mức thì được quà, cách này "không trực tiếp giảm giá sản phẩm". Bài lưu ý khách chịu phí vận chuyển cả quà tặng, nên chọn quà nhẹ; quà có giá niêm yết trên 1.500.000 ₫ không được dùng.

{{hinh:aov-cong-cu}}

## Đừng để khuyến mãi chồng nhau ăn hết lãi

Nguy cơ lớn nhất khi tăng giá trị đơn là chạy nhiều khuyến mãi cùng lúc mà không biết chúng cộng lại thành bao nhiêu. Bài "Cách Tính Khuyến Mãi Cộng Dồn" (29/10/2025) chia khuyến mãi thành ba lớp:

- **Khuyến mãi sản phẩm riêng lẻ** (chiến dịch, Flash Sale của shop, Giảm giá sản phẩm): nếu có nhiều, chỉ một mức giá có hiệu lực.
- **Khuyến mãi cấp giỏ hàng** (Mua thêm, tiết kiệm nhiều hơn, Quà khi mua): cộng dồn được với lớp đầu.
- **Voucher**: cộng dồn được với hai lớp trên, một voucher mỗi đơn.

{{hinh:aov-cong-don}}

Trong ví dụ giả định ở trên, mỗi khuyến mãi trông vừa phải, nhưng cộng lại khách trả 147.000 ₫ cho 200.000 ₫ giá gốc. Trước khi chạy, hãy mở công cụ **Phân tích hiểu sâu về định giá** (Trung tâm nhà bán hàng, Marketing, Khuyến mãi). Theo bài trên, công cụ có phần Dự báo giá ước tính giá cuối cùng khách thấy và Công cụ mô phỏng khuyến mãi cho xem khuyến mãi nào áp dụng, cộng dồn hay bị thay thế. Khuyến mãi do nền tảng tài trợ không nằm trong công cụ này, nên giá hiển thị chỉ là ước tính.

## Tiêu đề và mô tả có giúp khách mua theo bộ không

Một gói hay một mức "mua 2 giảm" chỉ có tác dụng khi khách biết nó tồn tại và hiểu mình được gì. Trang chính sách "Tiêu đề, mô tả, hình ảnh và video về sản phẩm" của TikTok (cập nhật 23/04/2026) cho hai điểm tựa:

- **Nói rõ số lượng và quy cách**: trang yêu cầu tiêu đề có số lượng hoặc thể tích, và nêu rõ mọi tùy chọn khi một bài niêm yết có nhiều biến thể; ví dụ tiêu đề đúng của trang có "(Gói 3 áo)". Khách thấy "hộp 3 chai" sẽ tự so giá trên mỗi đơn vị.
- **Không đưa ưu đãi vào tiêu đề**: trang ghi không nên đưa nội dung tiếp thị, khuyến mãi (ví dụ "giảm giá x%") vào tiêu đề. Ưu đãi để công cụ khuyến mãi hiển thị.
- **Mô tả cách dùng cùng nhau**: sản phẩm A dùng với sản phẩm B thế nào, vì sao nên mua đủ bộ.

Giá, voucher và gói vẫn là quyết định của người bán.

## Đo kết quả sau 7 và 14 ngày: AOV lên nhưng CTOR giảm thì sao

Khuyến mãi tăng giá trị đơn có thể làm khách đã mua mua nhiều hơn (AOV lên) nhưng khiến một số khách bỏ đi vì điều kiện khó đạt (CTOR xuống). Vì vậy:

1. **Ghi ngày bắt đầu** và giữ một thay đổi trên một nhóm sản phẩm.
2. **Đọc sơ bộ ở ngày 7, chốt ở ngày 14**, so với 14 ngày trước khi chạy.
3. **Đọc AOV cùng CTOR và GMV**: AOV lên 10 % mà CTOR giảm 15 % thì GMV của luồng đó giảm (ví dụ giả định: 1,10 × 0,85 = 0,935).
4. **Đọc thêm số đơn đạt ngưỡng**: trang Phân tích khuyến mãi trong Trung tâm nhà bán hàng cho xem mức sử dụng, doanh thu, đơn hàng của từng công cụ.

GMV đi ngang mà AOV lên, số đơn giảm vẫn có thể có lợi, vì ít đơn hơn là ít phí và chi phí theo đơn hơn.

## Tự lập bảng AOV theo nguồn và theo khuyến mãi

Mọi con số ở đây đều có trong Trung tâm nhà bán hàng. Mỗi tuần một lần, hoặc trước và sau mỗi khuyến mãi, ghi hai bảng nhỏ:

| Bảng | Cột | Lấy ở đâu |
|---|---|---|
| AOV theo nguồn | GMV, Đơn hàng SKU, Số món bán ra của từng khía cạnh; AOV = GMV ÷ Đơn hàng SKU; số món mỗi đơn = Số món bán ra ÷ Đơn hàng SKU | Lưu lượng truy cập sản phẩm, 28 ngày gần nhất |
| Khuyến mãi đang chạy | Tên công cụ, ngày bắt đầu và kết thúc, mức chi tối thiểu hoặc số lượng, mức sử dụng, doanh thu, đơn hàng | Phân tích khuyến mãi; điều kiện thì bạn tự ghi lúc tạo |

Ba điều bảng này trả lời được mà một con số AOV của cả shop không trả lời được:

- **Số món mỗi đơn có nhích lên không.** Mua Sỉ Giá Hời và Ưu đãi theo gói nhắm vào số món, voucher theo bậc nhắm vào số tiền. Nếu số món mỗi đơn đứng yên sau khi chạy Mua Sỉ Giá Hời, ngưỡng có thể quá xa so với thói quen mua của khách.
- **Khuyến mãi có được dùng không.** Mức sử dụng thấp ở một voucher theo bậc là tín hiệu mức chi tối thiểu quá cao, như bài voucher của Học viện TikTok Shop đã nói.
- **AOV lên ở nguồn nào.** Ví dụ giả định: AOV của LIVE lên 15 % nhưng AOV của Thẻ sản phẩm đứng yên, thì gói sản phẩm đang được giới thiệu trong LIVE mà khách tự tìm đến chưa thấy nó.

Ghi thêm một dòng "đã thay đổi gì, ngày nào" dưới mỗi bảng. Khi đọc lại ở ngày 14, dòng này cho biết mức thay đổi của AOV đến từ khuyến mãi nào. Nếu vấn đề là ít đơn chứ không phải đơn nhỏ, xem bài [sản phẩm không có lượt hiển thị](/blog/san-pham-tiktok-shop-khong-co-luot-hien-thi), [TikTok Shop không ra đơn](/blog/tiktok-shop-khong-ra-don), [video nhiều view không ra đơn](/blog/video-tiktok-nhieu-view-khong-ra-don) hoặc [LIVE đông người xem mà ít đơn](/blog/live-tiktok-shop-khong-ra-don).

## Những điểm chính

- Phí xử lý đơn 3.000 ₫ tính theo đơn, nên đơn nhỏ chịu phần trăm phí cao hơn. Kiểm tra AOV theo nguồn trước khi kết luận.
- Tăng AOV đáng làm nhất khi Lượt hiển thị, CTR và CTOR đã ổn.
- Voucher theo bậc với mức chi tối thiểu 1,2 đến 1,5 lần AOV; Mua Sỉ Giá Hời cho hàng mua nhiều cái; Ưu đãi theo gói cho sản phẩm dùng cùng nhau; quà tặng khi không muốn giảm giá.
- Mô phỏng khuyến mãi cộng dồn trước khi chạy. Đo AOV cùng CTOR ở ngày 7 và ngày 14.

Khi khách bấm vào nhiều mà ít người đặt, vấn đề nằm ở bước trước AOV: bài [khách xem nhưng không mua](/blog/khach-xem-nhung-khong-mua-tiktok-shop) đi qua từng chỗ sau cú nhấp.
`;
