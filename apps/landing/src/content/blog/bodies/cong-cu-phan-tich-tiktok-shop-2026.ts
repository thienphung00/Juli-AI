/**
 * P44 post b (D49.2b): TikTok Shop analytics tools, 2026. Market-research
 * tools (soi thị trường / đối thủ) are kept apart from own-shop analysis.
 * Juli appears once, disclosed as our product, in the own-shop group, with no
 * superlatives. Every vendor fact comes from that vendor's own public pages,
 * read 2026-10-16 (no sign-up, no log-in); prices only as published.
 *
 * Sources (checked 16/10/2026):
 * - TikTok Shop (Học viện, VN): "Hướng dẫn sử dụng La bàn Dữ liệu trong Trung tâm Người bán"
 *   (knowledge_id=10008597, 13/12/2022), "Lưu lượng truy cập sản phẩm" (knowledge_id=10015238,
 *   17/06/2026)
 * - FastMoss: https://www.fastmoss.com/vi, https://www.fastmoss.com/vi/pricing
 * - Kalodata: https://www.kalodata.com/ (FAQ), https://www.kalodata.com/product?region=VN&language=vi-VN;
 *   /pricing redirects to the log-in page, so no price is given
 * - Metric: https://metric.vn/, https://metric.vn/analytics/pricing, https://hotro.metric.vn/,
 *   https://hotro.metric.vn/ho-tro/cau-hoi-thuong-gap/du-lieu
 * - Juli AI: app-juli.com (our product)
 * Checked and left out: EchoTik (echotik.live) and Shoplus (shoplus.net) are real TikTok
 * analytics tools, but neither public page we read names Vietnam; "Kalowave" is Kalowave
 * Technology Co., Limited, the company that operates Kalodata (Kalodata FAQ), not a
 * separate tool.
 */
export const body = `
Gõ "tool phân tích tiktok shop" và bạn sẽ thấy hàng chục cái tên. Phần lớn trong số đó trả lời một câu hỏi: ngoài thị trường đang bán chạy cái gì, đối thủ đang làm gì. Một số ít trả lời câu hỏi khác hẳn: shop của chính bạn đang mất khách ở đâu. Hai câu hỏi cần hai loại dữ liệu khác nhau, và nhầm hai loại này là lý do nhiều người bán trả tiền cho một công cụ rồi thấy nó không giúp được việc mình cần.

Bài viết này chia các công cụ phân tích dữ liệu TikTok Shop thành hai nhóm theo nguồn dữ liệu: công cụ soi thị trường và đối thủ, và công cụ đọc dữ liệu shop của bạn. Mỗi công cụ được mô tả bằng thông tin chính nhà cung cấp công bố. Chúng tôi không xếp hạng và không chọn ra công cụ "tốt nhất".

## Cách chúng tôi chọn và mô tả các công cụ

Bài viết thuộc chuỗi bài về công cụ cho nhà bán, với các nguyên tắc sau:

- **Tiêu chí chọn**: công cụ có trang chính thức công khai, phân tích dữ liệu TikTok Shop, và có dấu hiệu rõ ràng là phục vụ người bán Việt Nam (trang tiếng Việt, hoặc dữ liệu thị trường Việt Nam được nêu trên trang của họ).
- **Chỉ dùng thông tin nhà cung cấp tự công bố**, kiểm tra ngày 16/10/2026 trên trang chính thức. Với công cụ của TikTok, chúng tôi dựa trên các bài của Học viện TikTok Shop bản tiếng Việt. Chúng tôi chỉ đọc trang công khai, không đăng ký và không đăng nhập.
- **Giá ghi đúng như trang công bố**: tên gói, số tiền, đơn vị tiền, kỳ thanh toán. Nếu không đọc được bảng giá công khai, chúng tôi ghi rõ.
- **Không chấm điểm, không đánh giá độ chính xác** của dữ liệu mà chúng tôi không tự kiểm chứng được. Thứ tự trong mỗi nhóm là thứ tự chữ cái.
- **Công khai lợi ích**: Juli AI là sản phẩm của chúng tôi. Juli xuất hiện một lần, trong nhóm đọc dữ liệu shop của bạn, với cùng cách mô tả như các công cụ khác.

## Soi thị trường hay đọc shop của bạn: hai câu hỏi khác nhau

Trước khi so sánh công cụ, hãy tách hai loại câu hỏi mà người bán thường gộp chung dưới chữ "phân tích".

**Câu hỏi về thị trường**: sản phẩm nào trong ngành hàng của tôi đang bán chạy, shop đối thủ đang bán giá bao nhiêu, nhà sáng tạo nào mang về doanh số cho sản phẩm giống tôi, video nào đang được đẩy mạnh. Dữ liệu để trả lời là dữ liệu của người khác. Công cụ thị trường thu thập nó từ những gì công khai trên TikTok rồi ước tính phần còn lại, như doanh số của một sản phẩm.

**Câu hỏi về shop của bạn**: vì sao GMV tuần này giảm, sản phẩm nào có nhiều người xem mà ít người nhấp, luồng truy cập nào đang yếu đi. Dữ liệu để trả lời nằm trong Trung tâm nhà bán hàng của bạn: Lượt hiển thị sản phẩm, CTR, CTOR, Đơn hàng SKU, AOV theo từng kênh. Các chỉ số phễu này hiển thị trong Trung tâm nhà bán hàng của chủ shop; một công cụ bên ngoài chỉ đọc được chúng khi chủ shop ủy quyền kết nối, nên không thể có chúng cho shop của người khác.

Hệ quả thực tế:

- Một công cụ thị trường trả lời tốt "cái gì đang bán", nhưng không biết vì sao sản phẩm của bạn mất khách.
- Một công cụ đọc shop của bạn trả lời được "mất khách ở bước nào", nhưng không cho bạn xem doanh số của đối thủ.
- Số doanh thu của shop khác trên công cụ thị trường là số ước tính. Kalodata, chẳng hạn, nói rõ điều này trong phần mô tả nguồn dữ liệu trên trang của họ.

## Bảng so sánh công cụ phân tích TikTok Shop

| Công cụ | Nhóm | Phù hợp với | Chức năng chính theo trang chính thức | Nền tảng, thị trường nêu trên trang | Bản miễn phí |
|---|---|---|---|---|---|
| La bàn dữ liệu (TikTok Shop) | Shop của bạn (dữ liệu gốc) | Mọi shop TikTok Shop | Tổng quan dữ liệu, phân tích sản phẩm, video, LIVE, người sáng tạo, lưu lượng truy cập sản phẩm | TikTok Shop, bài hướng dẫn áp dụng cho Việt Nam | Có sẵn trong Trung tâm nhà bán hàng |
| FastMoss | Thị trường và đối thủ | Chọn sản phẩm, theo dõi đối thủ, tìm nhà sáng tạo | Bảng xếp hạng sản phẩm, shop, nhà sáng tạo, LIVE, video, quảng cáo; công cụ AI | TikTok, gói thành viên gồm sáu nước Đông Nam Á có Việt Nam | Dùng thử 7 ngày |
| Kalodata | Thị trường và đối thủ | Chọn sản phẩm, nhà sáng tạo, ý tưởng video và LIVE | Sản phẩm xu hướng, hợp tác nhà sáng tạo, video, LIVE, quảng cáo, đối thủ | TikTok Shop, có trang xếp hạng Việt Nam bằng tiếng Việt | Dùng thử 7 ngày |
| Metric | Thị trường và đối thủ (nhiều sàn) | Nghiên cứu thị trường, ngành hàng, đối thủ trên nhiều sàn | Phân tích thị trường, ngành hàng, xu hướng, đối thủ | Shopee, Tiki, Lazada, Sendo, TikTok Shop tại Việt Nam | Trải nghiệm 7 ngày |
| Juli AI (sản phẩm của chúng tôi) | Shop của bạn | Shop đang có đơn, cần biết nên sửa gì trước | Tách GMV theo luồng và chỉ số, đề xuất khi bạn duyệt, đo lại sau thay đổi | Kết nối TikTok Shop, Shopee đang tích hợp | Miễn phí 3 tháng, rồi trả phí |

## Dữ liệu gốc: La bàn dữ liệu của TikTok Shop

Mọi phân tích shop của bạn đều bắt đầu từ đây. La bàn dữ liệu nằm trong Trung tâm nhà bán hàng, không mất phí, và có số liệu phễu của từng sản phẩm theo đúng định nghĩa của TikTok. Mọi công cụ bên thứ ba đọc shop của bạn đều đọc lại dữ liệu này qua kết nối mà bạn ủy quyền.

### Các mô-đun của La bàn dữ liệu

Theo bài "Hướng dẫn sử dụng La bàn Dữ liệu trong Trung tâm Người bán" (áp dụng cho Việt Nam), La bàn dữ liệu phân tích số liệu hoạt động từ video ngắn và các buổi phát trực tiếp để giúp người bán hiểu hiệu suất của sản phẩm, kênh quảng bá và tình trạng hoạt động của chính mình. Bài liệt kê trang chủ với các mục Hành động cần làm, Đề xuất dữ liệu, Hiệu quả cửa hàng, và các mô-đun Tổng quan dữ liệu, Phân tích người sáng tạo, Phát trực tiếp hôm nay, Phân tích phát trực tiếp, Phân tích sản phẩm và Phân tích video.

### Lưu lượng truy cập sản phẩm

Mô-đun quan trọng nhất cho câu hỏi tăng trưởng là Lưu lượng truy cập sản phẩm (Trung tâm nhà bán hàng, La bàn dữ liệu, Số liệu phân tích sản phẩm, Lưu lượng truy cập sản phẩm). Bài cùng tên của Học viện TikTok Shop, cập nhật 17/06/2026, mô tả mô-đun này giúp người bán hiểu "lưu lượng truy cập sản phẩm của họ đến từ đâu, hiệu quả chuyển đổi của từng giai đoạn trong phễu và kênh lưu lượng truy cập nào đóng góp nhiều nhất". Cách đọc từng chỉ số có trong bài [Các chỉ số TikTok Shop: Lượt hiển thị, CTR, CTOR, AOV và cách đọc đúng](/blog/chi-so-tiktok-shop-ctr-ctor-aov).

**Giới hạn khi dùng một mình**: bạn tự ghép các màn hình để tìm nguyên nhân. La bàn dữ liệu cho bạn từng chỉ số, còn việc nối chúng thành một câu trả lời ("luồng nào làm GMV giảm, qua chỉ số nào, ở sản phẩm nào") là việc của bạn.

Thông tin kiểm tra ngày 16/10/2026 trên trang chính thức của TikTok Shop (Học viện TikTok Shop).

## Nhóm 1: công cụ phân tích thị trường và đối thủ

Nhóm này nhìn ra ngoài shop của bạn. Chúng hữu ích nhất ở ba thời điểm: khi chọn sản phẩm mới, khi chọn nhà sáng tạo để hợp tác, và khi muốn biết đối thủ trong ngành hàng đang định giá và khuyến mãi thế nào.

### FastMoss

Trang tiếng Việt của FastMoss giới thiệu đây là "nền tảng phân tích dữ liệu khép kín đầu tiên trong hệ sinh thái TikTok". Các tính năng trang nêu: theo dõi sản phẩm bán chạy; theo dõi shop đối thủ, với sản phẩm, giá cả và chương trình khuyến mãi của họ; số liệu hiệu suất của nhà sáng tạo; phân tích LIVE; tìm kiếm quảng cáo. Nhóm công cụ AI gồm Ý kiến khách hàng (phân tích phản hồi và cảm xúc khách hàng), Cắt video thông minh, Phân tích kịch bản, Viết lại kịch bản và Tối ưu tiêu đề sản phẩm. Trang cũng nêu dữ liệu FastMoss cho quy trình AI qua MCP, CLI và API.

**Thị trường**: trang bảng giá ghi gói thành viên cho quyền truy cập thông tin TikTok tại sáu quốc gia Đông Nam Á: Thái Lan, Indonesia, Việt Nam, Malaysia, Philippines và Singapore.

**Giá**: trang chủ ghi dùng thử miễn phí 7 ngày, không cần thẻ tín dụng. Trang bảng giá tiếng Việt, ở kỳ thanh toán hằng tháng, hiển thị gói Cơ bản 342.000₫/tháng, Nâng cao 461.000₫/tháng và Doanh nghiệp 1.052.000₫/tháng, cùng một gói tùy chỉnh liên hệ báo giá; kỳ 6 tháng và 1 năm ghi mức giảm tới 10 % và 25 %. Gói Cơ bản ghi lịch sử dữ liệu 90 ngày.

Thông tin kiểm tra ngày 16/10/2026 trên trang chính thức của FastMoss.

### Kalodata

Kalodata tự mô tả là công cụ phân tích dữ liệu và thông tin chuyên sâu cho TikTok Shop, cung cấp thông tin về sản phẩm xu hướng, nhà sáng tạo, video ngắn, LIVE, nghiên cứu thị trường và phân tích đối thủ, cho người bán, thương hiệu, nhà sáng tạo và người làm tiếp thị liên kết. Kalodata có trang xếp hạng sản phẩm "Việt Nam TikTok" bằng tiếng Việt, nơi có thể lọc sản phẩm bán qua LIVE hay video ngắn và tìm sản phẩm đang tăng trưởng bán hàng.

**Nguồn dữ liệu**: mục câu hỏi thường gặp ghi Kalodata thu thập dữ liệu thương mại điện tử TikTok từ các kênh công khai rồi dùng mô hình AI để xử lý, và lưu ý một số chi tiết như giá trị giao dịch và chi phí quảng cáo có thể chênh lệch nhỏ so với thực tế. Trang cũng ghi Kalodata là nền tảng độc lập do Kalowave Technology Co., Limited vận hành, không liên kết, không được bảo trợ hay tài trợ bởi TikTok, TikTok Shop hoặc ByteDance.

**Giá**: trang chủ ghi dùng thử 7 ngày, không cần thẻ tín dụng. Đường dẫn bảng giá chuyển sang trang đăng nhập, nên chúng tôi không đọc được giá công khai vào ngày kiểm tra.

Thông tin kiểm tra ngày 16/10/2026 trên trang chính thức của Kalodata.

### Metric

Metric là nền tảng dữ liệu thương mại điện tử tập trung vào thị trường Việt Nam. Trang hỗ trợ của Metric mô tả đây là công cụ phân tích dữ liệu bán hàng thị trường thương mại điện tử Shopee, Tiki, Lazada, Sendo, Tiktok, giúp người bán phân tích quy mô thị trường, tìm sản phẩm bán chạy và theo dõi đối thủ, với dữ liệu lấy từ các kênh bán đang hoạt động ở Việt Nam. Trang chủ nêu bốn hướng phân tích: thị trường, ngành hàng, xu hướng và đối thủ, cùng dịch vụ nghiên cứu thị trường theo yêu cầu và thư viện báo cáo.

**Khác biệt về phạm vi**: Metric nhìn nhiều sàn cùng lúc. Nếu bạn muốn so một ngành hàng giữa TikTok Shop và Shopee, đây là loại công cụ phù hợp; nếu chỉ cần dữ liệu nhà sáng tạo và video TikTok, các công cụ chuyên TikTok ở trên mô tả sâu hơn phần đó.

**Giá**: trang bảng giá Metric Analytics ghi trải nghiệm miễn phí 7 ngày và, với 500 lượt phân tích, gói Advanced 18 triệu đồng (lịch sử số liệu 1 năm) và gói Premium 27 triệu đồng (lịch sử 2 năm), thời hạn 12 tháng; trang quy đổi khoảng 1,5 và 2,25 triệu đồng mỗi tháng. Gói tùy chỉnh liên hệ báo giá.

Thông tin kiểm tra ngày 16/10/2026 trên trang chính thức của Metric.

### Đọc số của công cụ thị trường cho đúng

Ba lưu ý khi dùng bất kỳ công cụ nào trong nhóm này:

- **Dùng để so xu hướng và thứ hạng, không dùng như số chính xác.** Doanh số của shop khác là ước tính từ dữ liệu công khai.
- **Một sản phẩm đang lên hạng chưa chắc hợp với bạn.** Biên lợi nhuận, nguồn hàng và tệp khách là những thứ bảng xếp hạng không cho biết.
- **Kiểm tra độ phủ cho ngành hàng của bạn.** Hãy dùng bản dùng thử để xem dữ liệu Việt Nam cho đúng ngành hàng mình bán trước khi trả tiền.

## Nhóm 2: công cụ phân tích dữ liệu shop của bạn

Nhóm này nhìn vào trong shop: dữ liệu bán hàng, phễu chuyển đổi, từng sản phẩm. La bàn dữ liệu ở trên là nền tảng của nhóm. Các công cụ bên thứ ba trong nhóm đọc lại dữ liệu đó qua kết nối được bạn ủy quyền, rồi làm phần việc mà bạn phải tự làm khi chỉ dùng La bàn dữ liệu: nối các chỉ số thành một kết luận.

### Juli AI

Juli AI là sản phẩm của chúng tôi, do Công ty TNHH Công Nghệ Juli AI phát triển. Juli là trợ lý AI cho nhà bán thương mại điện tử, hiện kết nối với TikTok Shop qua [kết nối chính thức của TikTok Shop](/ket-noi/tiktok-shop), Shopee đang tích hợp. Những gì Juli làm:

- **[Phân tích shop](/san-pham/phan-tich-shop)**: tách GMV theo năm luồng truy cập (thẻ sản phẩm, Tab cửa hàng, video, LIVE, liên kết) và theo bốn hệ số Lượt hiển thị, CTR, CTOR, AOV; chỉ ra sản phẩm nào mất khách ở bước nào, với nhãn độ tin cậy cho mỗi so sánh.
- **[Đề xuất và thực thi khi bạn phê duyệt](/san-pham/de-xuat-va-thuc-thi)**: đề xuất một việc cụ thể cho từng sản phẩm, kèm lý do bằng số. Không có thay đổi nào trên shop nếu bạn chưa đồng ý.
- **[Đo lường GMV](/san-pham/do-luong-gmv)**: đo lại kết quả của từng thay đổi sau 7 và 14 ngày.

**Juli không làm**: Juli không cho xem doanh số hay sản phẩm của shop khác, nên không thay cho các công cụ ở nhóm 1. Juli cũng không quản lý đơn hàng hay kho.

**Giá**: theo app-juli.com, miễn phí 3 tháng, sau đó 500.000đ/tháng. Xem tổng quan tại trang [sản phẩm Juli AI](/san-pham).

Thông tin kiểm tra ngày 16/10/2026 trên trang chính thức của Juli AI.

### Báo cáo trong phần mềm quản lý bán hàng đa kênh

Nếu bạn đã dùng một phần mềm quản lý bán hàng đa kênh, phần báo cáo của nó cũng là một nguồn phân tích shop: doanh thu, lợi nhuận, chi phí theo sàn và theo sản phẩm. Loại báo cáo này mạnh ở phần tiền: lãi lỗ, phí sàn, đối soát. Phễu chuyển đổi trên TikTok Shop (Lượt hiển thị, CTR, CTOR) vẫn nằm trong La bàn dữ liệu. Danh sách và giá các phần mềm này có trong bài [Phần mềm quản lý bán hàng đa kênh 2026](/blog/phan-mem-quan-ly-ban-hang-da-kenh-2026).

## Những công cụ chúng tôi đã kiểm tra nhưng chưa đưa vào

Để bạn biết danh sách được lập thế nào, đây là các cái tên chúng tôi đã xem mà không đưa vào bảng:

- **EchoTik** (echotik.live) và **Shoplus** (shoplus.net): là công cụ phân tích TikTok có trang công khai và bảng giá. Trên các trang công khai chúng tôi đọc ngày 16/10/2026, cả hai không nêu thị trường Việt Nam, nên chưa đạt tiêu chí "dấu hiệu rõ ràng phục vụ người bán Việt Nam" ở đầu bài. Nếu bạn quan tâm, hãy hỏi trực tiếp nhà cung cấp về dữ liệu Việt Nam.
- **Kalowave**: theo trang của Kalodata, đây là tên công ty vận hành Kalodata (Kalowave Technology Co., Limited), không phải một công cụ riêng.

## Dùng hai nhóm cùng nhau: một quy trình mẫu

Hai nhóm công cụ không thay thế nhau. Một quy trình hằng tuần đơn giản có thể dùng cả hai:

1. **Đọc shop của bạn trước.** Mở dữ liệu 7 hoặc 30 ngày gần nhất, so với kỳ trước dài bằng nhau. Tìm luồng truy cập có GMV thay đổi nhiều nhất. Bài [GMV là gì? Cách tính và cách tăng GMV TikTok Shop](/blog/gmv-la-gi-tiktok-shop) giải thích cách tách GMV thành Lượt hiển thị × CTR × CTOR × AOV.
2. **Tìm bước yếu nhất trong luồng đó.** Lượt hiển thị thấp, CTR thấp hay CTOR thấp mỗi thứ dẫn tới một nhóm việc khác nhau. Nếu shop gần như không có đơn, đi theo bài [TikTok Shop không ra đơn: đọc phễu để tìm nguyên nhân](/blog/tiktok-shop-khong-ra-don); nếu doanh thu đang giảm, đi theo [Doanh thu TikTok Shop giảm: checklist tìm nguyên nhân theo từng luồng](/blog/doanh-thu-tiktok-shop-giam).
3. **Lúc này mới nhìn ra thị trường.** Khi đã biết bước yếu là CTR do giá hiển thị, hãy dùng công cụ thị trường để xem các sản phẩm tương tự đang được bán giá nào. Khi bước yếu là Lượt hiển thị từ video, xem nhà sáng tạo và video nào đang mang doanh số cho ngành hàng.
4. **Làm một thay đổi, ghi ngày bắt đầu, đo lại.** Đọc lại cùng chỉ số sau 7 và 14 ngày, trên cùng luồng truy cập.

Thứ tự này quan trọng: bắt đầu từ thị trường thường dẫn tới việc sao chép điều đối thủ làm, trong khi điểm nghẽn của shop bạn có thể nằm ở chỗ khác hẳn.

## Câu hỏi nên hỏi trước khi trả tiền cho một tool phân tích TikTok Shop

1. **Dữ liệu lấy từ đâu?** Từ kết nối được bạn ủy quyền với shop của bạn, từ tệp bạn tải lên, hay ước tính từ dữ liệu công khai về shop khác?
2. **Có dữ liệu Việt Nam cho ngành hàng của bạn không?** Kiểm tra trong thời gian dùng thử, với vài sản phẩm bạn biết rõ.
3. **Lịch sử dữ liệu dài bao lâu?** Gói rẻ nhất thường giới hạn số ngày lịch sử và số lượt xem mỗi ngày.
4. **Tên chỉ số có khớp với Trung tâm nhà bán hàng không?** Nếu công cụ ghi "tỷ lệ chuyển đổi", hãy hỏi nó tính từ bước nào đến bước nào.
5. **Công cụ có nói khi dữ liệu chưa đủ để kết luận không?** Một kết luận cho sản phẩm chỉ có vài đơn mỗi tuần nên được ghi là tham khảo.
6. **Với công cụ kết nối vào shop: xin những quyền gì?** Chỉ đọc dữ liệu, hay cả quyền thay đổi sản phẩm, giá? Mọi thay đổi có cần bạn xác nhận trước không?

## Kết luận

Công cụ phân tích TikTok Shop chia làm hai nhóm rõ ràng. FastMoss, Kalodata và Metric nhìn ra thị trường: sản phẩm đang bán, đối thủ, nhà sáng tạo, với doanh số của shop khác là số ước tính. La bàn dữ liệu và các công cụ đọc shop của bạn nhìn vào trong: phễu chuyển đổi của chính bạn theo đúng định nghĩa của TikTok. Hãy xác định câu hỏi của bạn thuộc nhóm nào trước khi chọn công cụ, dùng thử trên dữ liệu thật, và xem lại giá trên trang chính thức của từng nhà cung cấp.

Nếu bạn muốn xem toàn cảnh các nhóm công cụ khác cho nhà bán, bài [Top công cụ cho nhà bán TikTok Shop 2026](/blog/cong-cu-cho-nha-ban-tiktok-shop-2026) tóm tắt cả bốn nhóm.
`;
