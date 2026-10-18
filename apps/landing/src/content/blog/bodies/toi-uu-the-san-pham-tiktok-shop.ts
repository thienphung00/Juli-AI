/**
 * Pillar post 2 (D43.7): the TikTok Shop product card A–Z. Listing rules are
 * from TikTok Academy VN policy and feature pages named in the text; the
 * measurement section is a do-it-yourself method with no numeric data floors
 * or Juli rules (D61).
 */
export const body = `
Thẻ sản phẩm là thứ đầu tiên khách hàng nhìn thấy khi tìm kiếm hoặc lướt trang mua sắm trên TikTok Shop, và là thứ duy nhất "bán hàng" thay bạn khi không có video hay buổi LIVE nào. Một thẻ sản phẩm tốt không cần đẹp nhất; nó cần làm đúng việc ở từng bước: khiến người xem nhấp vào, khiến người nhấp thêm vào giỏ, và khiến người thêm vào giỏ thanh toán.

Bài viết này đi qua từng thành phần của thẻ sản phẩm: ảnh bìa, tiêu đề, mô tả, thuộc tính, giá và khuyến mãi. Mỗi phần nêu rõ quy định của TikTok (trích từ Học viện TikTok Shop và Trung tâm chính sách), những điều nên làm để cải thiện chỉ số, và cuối cùng là cách đo một thay đổi sao cho bạn biết chắc nó có hiệu quả hay không.

## Thẻ sản phẩm là gì và vì sao nó quan trọng

Theo Học viện TikTok Shop (bài "Thẻ Sản Phẩm"), thẻ sản phẩm là thẻ hiển thị "mọi thứ bạn cần biết về sản phẩm, chẳng hạn như tiêu đề, hình ảnh, mô tả và giá của sản phẩm sau khi được niêm yết thành công trên TikTok Shop". Sản phẩm nhận traffic từ thẻ này khi người dùng tìm đến qua Tìm kiếm, Đề xuất, Trung tâm mua sắm, Cửa hàng hay Trang trưng bày. Mọi sản phẩm được tải lên thành công đều đủ điều kiện làm thẻ sản phẩm, và doanh thu không đến từ LIVE hay video được tính là doanh thu từ thẻ sản phẩm.

Điều này có hai ý nghĩa thực tế:

- **Thẻ sản phẩm là kênh bạn kiểm soát hoàn toàn.** Video phụ thuộc vào nội dung, LIVE phụ thuộc vào người dẫn, tiếp thị liên kết phụ thuộc vào nhà sáng tạo. Thẻ sản phẩm chỉ phụ thuộc vào những gì bạn niêm yết.
- **Chỉ số của kênh thẻ sản phẩm phản ánh trung thực nhất chất lượng niêm yết.** Nếu muốn biết ảnh bìa hay mô tả có tốt không, hãy đọc CTR và CTOR của riêng kênh này, không phải của toàn shop. Bài [Các chỉ số TikTok Shop: Lượt hiển thị, CTR, CTOR, AOV và cách đọc đúng](/blog/chi-so-tiktok-shop-ctr-ctor-aov) giải thích chi tiết vì sao.

## Trước khi sửa: xác định bước đang mất khách

Sai lầm phổ biến nhất khi tối ưu thẻ sản phẩm là sửa theo một danh sách cố định: tuần này đổi ảnh bìa, tuần sau đổi tiêu đề, tuần sau nữa viết lại mô tả. Học viện TikTok Shop không đưa ra thứ tự nào như vậy. Điều các công cụ chẩn đoán của TikTok làm là tìm ra vấn đề cụ thể của từng sản phẩm rồi đề xuất cách xử lý tương ứng. Hãy làm theo cùng tinh thần đó: tìm bước yếu trước, rồi sửa đúng thành phần tác động lên bước đó.

### Đọc CTR và CTOR trên kênh thẻ sản phẩm

Mở La bàn dữ liệu → Số liệu phân tích sản phẩm → Lưu lượng truy cập sản phẩm, chọn một sản phẩm và lọc theo kênh thẻ sản phẩm của người bán. Bạn sẽ thấy phễu: Lượt hiển thị sản phẩm → Lượt nhấp vào sản phẩm → Đơn hàng SKU, cùng CTR và CTOR. So sánh với hai mốc:

- **Với chính sản phẩm đó trước đây**: CTR hay CTOR của 14 ngày gần nhất có giảm rõ so với 28 ngày trước đó không?
- **Với các sản phẩm khác của shop**: sản phẩm này có thấp hơn hẳn phần lớn sản phẩm khác trong shop trên cùng luồng không?

Nếu CTR yếu, hãy bắt đầu từ những gì hiển thị trên thẻ: ảnh bìa và tiêu đề. Nếu CTR ổn nhưng CTOR yếu, vấn đề nằm trên trang chi tiết: bộ ảnh, mô tả, giá, khuyến mãi, đánh giá. Đừng sửa ảnh bìa của một sản phẩm có CTR đang tốt chỉ vì CTOR của nó giảm; bạn sẽ đụng vào đúng phần đang hoạt động.

### Ba nhóm yếu tố theo Học viện TikTok Shop

Bài "Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 4" chia các yếu tố tăng khả năng cạnh tranh của thẻ sản phẩm thành ba nhóm:

| Nhóm | Người mua đánh giá điều gì | Yếu tố chính theo TikTok |
|---|---|---|
| Hiển thị | Hình ảnh chính, trang chi tiết và thông tin cơ bản | Hình ảnh chính, tiêu đề, mô tả, hình ảnh theo biến thể, thông tin nhãn hiệu |
| Lợi ích | Hiệu quả chi phí, lợi thế giá, hoạt động khuyến mãi, thanh toán khi giao hàng | Chiết khấu sản phẩm, voucher, ưu đãi chớp nhoáng, mua thêm tiết kiệm nhiều hơn, giá cạnh tranh, COD |
| Sự tin cậy | Thương hiệu, đánh giá của người mua khác | Ủy quyền thương hiệu, đánh giá tiêu cực, tỷ lệ trả hàng |

Nhóm Hiển thị tác động mạnh nhất lên CTR; nhóm Lợi ích và Sự tin cậy tác động mạnh nhất lên CTOR.

### Công cụ chẩn đoán có sẵn trong Trung tâm nhà bán hàng

Trước khi tự đoán, hãy xem TikTok đã chỉ ra vấn đề gì:

- **Chẩn Đoán Thẻ Sản Phẩm** (La bàn dữ liệu → Thẻ sản phẩm → Hiệu suất): mục "Cơ hội tăng trưởng" đưa ra các đề xuất như "Tiêu đề có thể được tối ưu hóa", "Tối ưu hóa thông tin sản phẩm", "Cải thiện mức hấp dẫn về giá", "Thiết lập thêm các công cụ khuyến mãi".
- **Công cụ Tối Ưu Hoá Sản Phẩm** (Trung tâm nhà bán hàng → Sản phẩm → Công cụ Tối Ưu Hoá Sản Phẩm): liệt kê sản phẩm cần tối ưu kèm các điểm cần cải thiện về tên, mô tả và hình ảnh, có hỗ trợ tối ưu tiêu đề và mô tả bằng AI.
- **Trình Tối Ưu Hóa Tiêu Đề Sản Phẩm** (La bàn dữ liệu → Tìm kiếm → Tối ưu hóa tiêu đề sản phẩm): gợi ý từ khóa theo ý định tìm kiếm của người dùng.
- **Chẩn đoán giá** (Trung tâm nhà bán hàng → Sản phẩm → Chẩn Đoán Giá): cho biết giá của từng SKU đang ở mức nào so với sản phẩm tương tự.

Các công cụ này không thay được việc đọc phễu, nhưng chúng cho bạn danh sách việc cụ thể sau khi đã biết bước nào yếu.

## Ảnh bìa (hình ảnh chính)

Ảnh bìa là phần chiếm nhiều diện tích nhất trên thẻ sản phẩm và là yếu tố đầu tiên quyết định người xem có nhấp hay không. Nó cũng là thay đổi dễ kiểm chứng nhất: bạn biết chính xác ngày đổi ảnh.

Nếu sản phẩm có lượt hiển thị mà ít người bấm và bạn nghi ảnh bìa, bài [ảnh bìa khiến người mua lướt qua](/blog/anh-bia-san-pham-tiktok-shop) đi chi tiết từ cách đọc CTR đến cách đổi một ảnh rồi đo lại.

### Yêu cầu bắt buộc theo chính sách

Trang chính sách "Tiêu đề, mô tả, hình ảnh và video về sản phẩm" (Trung tâm chính sách TikTok Shop, cập nhật 23/04/2026) nêu các yêu cầu kỹ thuật cho mọi hình ảnh:

- Độ phân giải tối thiểu 600 × 600 pixel, có màu, chất lượng cao, không mờ, không vỡ điểm ảnh.
- Sản phẩm không bị che khuất bởi nhãn dán hay hình mờ, không bị làm mờ một phần.
- Mỗi hình thể hiện một góc khác nhau của sản phẩm; tối đa 9 hình vuông.

Với **hình ảnh chính**, tức "hình ảnh đầu tiên hiển thị cho người dùng":

- Phải hiển thị mặt trước của sản phẩm thực tế.
- Nền có màu đồng nhất, nên dùng màu trắng.
- Sản phẩm chiếm ít nhất 60 % khung hình.
- Hiển thị toàn bộ sản phẩm, không cắt xén.

### Khuyến nghị để tăng CTR

Bài chẩn đoán thẻ sản phẩm của TikTok đưa thêm các khuyến nghị tối ưu: hình ảnh chính "tốt nhất là nền trắng, ảnh cho thấy toàn bộ sản phẩm, không bị che khuất, không lặp lại", thêm video, kích thước điểm ảnh lớn hơn 1200 × 1200 và có ít nhất 3 hình ảnh. Từ kinh nghiệm thực tế, vài điểm nên kiểm tra thêm:

- **Nhìn ảnh ở kích thước thật trên điện thoại.** Thẻ sản phẩm trên trang tìm kiếm rất nhỏ. Chi tiết nhỏ, chữ nhỏ và sản phẩm nhỏ trong khung đều biến mất.
- **Nói rõ quy cách nếu nó là điểm bán.** Nếu bạn bán combo 3 chai, ảnh bìa nên cho thấy 3 chai, không phải 1. Người mua so sánh giá trên thẻ; ảnh 1 chai với giá của 3 chai trông như đắt gấp ba.
- **So với đối thủ trên cùng trang tìm kiếm.** Tìm từ khóa chính của sản phẩm trên ứng dụng TikTok và xem thẻ của bạn nằm giữa các thẻ khác. Nếu mọi thẻ đều nền trắng và giống hệt nhau, khác biệt nằm ở quy cách, góc chụp và mức độ rõ ràng.
- **Không nhồi khuyến mãi lên ảnh.** Chữ "giảm 50 %" che sản phẩm vừa vi phạm yêu cầu "không bị che khuất", vừa trở thành sai khi chương trình kết thúc. Giá và khuyến mãi đã có chỗ riêng trên thẻ.

### Bộ ảnh phụ và video

Ảnh thứ hai trở đi phục vụ người đã nhấp vào, tức tác động lên CTOR. Chính sách yêu cầu chúng thể hiện mặt bên, mặt sau, chi tiết và phụ kiện đi kèm. Một bộ ảnh tốt thường trả lời lần lượt: sản phẩm trông thế nào từ mọi phía, kích thước thật ra sao (đặt cạnh vật quen thuộc hoặc ghi số đo), dùng như thế nào, trong hộp có gì, và điểm khác biệt so với sản phẩm tương tự.

Mỗi thẻ sản phẩm được tải lên tối đa 1 video, dung lượng không quá 5 MB. Video ngắn quay cận sản phẩm đang được sử dụng thường trả lời câu hỏi nhanh hơn ảnh tĩnh.

TikTok cũng khuyên thêm hình ảnh khác nhau cho từng biến thể (SKU). Khi khách chọn màu đỏ mà ảnh vẫn hiện màu xanh, họ có lý do để rời đi.

### Lỗi hay gặp

- Ảnh bìa trùng với ảnh phụ (TikTok liệt kê "không lặp lại" là yêu cầu).
- Ảnh chụp chung nhiều sản phẩm khác nhau, người xem không biết đang mua cái nào.
- Ảnh có chữ nước ngoài hoặc logo sàn khác.
- Thay ảnh bìa liên tục mỗi vài ngày, khiến không đo được thay đổi nào có tác dụng.

## Tiêu đề sản phẩm

Tiêu đề có hai việc: giúp sản phẩm xuất hiện khi người mua tìm kiếm (lượt hiển thị) và giúp người xem hiểu ngay đây là gì (CTR).

Cách viết lại tiêu đề từng bước khi CTR thấp, kèm những từ không được dùng, có trong bài [cách đặt tên sản phẩm TikTok Shop](/blog/dat-ten-san-pham-tiktok-shop).

### Cấu trúc tiêu đề theo chính sách

Theo trang chính sách của TikTok, tiêu đề "phải hoàn chỉnh, chính xác và cô đọng" và nên có:

1. Tên thương hiệu (chỉ khi bạn được ủy quyền bán sản phẩm của thương hiệu).
2. Loại sản phẩm.
3. Nguyên vật liệu hoặc thành phần chính (nếu có).
4. Các tính năng hoặc đặc điểm chính: màu sắc, chức năng, biến thể.
5. Số lượng hoặc thể tích: trọng lượng tịnh, dung tích, kích thước đóng gói. Nếu một niêm yết có nhiều kích thước, nêu rõ tất cả, ví dụ 100 ml / 150 ml / 200 ml.

Ví dụ TikTok đưa ra: "Áo phông cổ tròn cotton Thương hiệu B – Trắng (Gói 3 áo)", "Sữa rửa mặt trà xanh Thương hiệu C 100 ml (Bao bì mới)". Khi bao bì thay đổi, bạn có thể thêm ghi chú ngắn như "Bao bì mới" để khách nhận biết.

### Những gì không được đưa vào tiêu đề

Cũng theo chính sách đó, tiêu đề **không** được chứa:

- Thông tin tiếp thị, khuyến mãi hay bất kỳ nội dung nào không mô tả sản phẩm, ví dụ "giảm x %".
- URL hoặc tên người bán.
- Tham chiếu đến "TikTok" (khi chưa được TikTok ủy quyền) hoặc đến các nền tảng, trang thương mại điện tử khác.
- Ký hiệu hoặc ký tự đặc biệt.

Bài chẩn đoán của TikTok cũng lưu ý tránh lặp từ trong tiêu đề. Nhồi cùng một từ khóa ba lần không giúp tìm kiếm mà làm tiêu đề khó đọc.

### Từ khóa: dùng Trình Tối Ưu Hóa Tiêu Đề

Thay vì đoán người mua tìm gì, hãy dùng Trình Tối Ưu Hóa Tiêu Đề Sản Phẩm trong La bàn dữ liệu. Theo hướng dẫn của TikTok, công cụ hiển thị bên cạnh mỗi sản phẩm một bộ từ khóa được đề xuất, "được so khớp dựa trên các tính năng sản phẩm và ý định tìm kiếm của người dùng", kèm điểm số lượng tìm kiếm. Sau khi thêm từ khóa, bạn theo dõi kết quả ở tab "Sản phẩm được tối ưu hóa", xuất hiện một ngày sau khi tối ưu.

Nguyên tắc chọn từ khóa: chỉ thêm từ khóa mô tả đúng sản phẩm. Một từ khóa có lượng tìm kiếm cao nhưng không đúng sẽ kéo traffic không có nhu cầu, làm CTR và CTOR giảm, và có thể vi phạm yêu cầu thông tin nhất quán.

### Độ dài

Bài chẩn đoán thẻ sản phẩm của TikTok ghi "tiêu đề phải dài hơn 25 ký tự". Trong thực tế, một tiêu đề có đủ năm thành phần ở trên hiếm khi ngắn hơn 40 ký tự. Hãy nhắm khoảng 40 ký tự và không viết dưới 25 ký tự. Phần đầu tiêu đề quan trọng nhất vì trên thẻ nhỏ, phần cuối thường bị cắt: hãy đặt loại sản phẩm và đặc điểm chính lên trước.

## Mô tả sản phẩm

Mô tả không hiện trên thẻ ở trang tìm kiếm, nên nó gần như không ảnh hưởng đến CTR. Nhưng nó là nơi khách đã nhấp vào tìm câu trả lời trước khi quyết định, nên tác động trực tiếp đến Tỷ lệ thêm vào giỏ hàng và CTOR.

### Mô tả cần trả lời những gì

Chính sách TikTok yêu cầu mô tả:

- Nêu các đặc điểm chính của sản phẩm: đặc tính, chức năng, thành phần, số lượng.
- Dài không dưới 30 từ.
- Trình bày rõ ràng để khách đưa ra quyết định sáng suốt.
- Cung cấp thông tin an toàn, thông số kỹ thuật và cảnh báo, đặc biệt quan trọng với các ngành như thực phẩm bổ sung.
- Liệt kê sản phẩm và tất cả phụ kiện đi kèm ("Hộp sản phẩm bao gồm những gì").

Ngoài yêu cầu tối thiểu, một mô tả bán được hàng trả lời các câu hỏi mà khách thường hỏi trong tin nhắn hoặc bình luận. Hãy mở hộp tin nhắn và phần đánh giá của sản phẩm, liệt kê 5 câu hỏi hay gặp nhất, rồi trả lời chúng ngay trong mô tả. Bài [khách hỏi mãi một câu: mô tả sản phẩm trả lời trước](/blog/mo-ta-san-pham-tiktok-shop) đi sâu vào cách gom câu hỏi, các giới hạn của chính sách và cách đo lại.

### Cấu trúc gợi ý

1. **Một câu mở đầu** nói sản phẩm là gì và dành cho ai.
2. **Ba đến năm lợi ích chính**, mỗi lợi ích một dòng, cụ thể và kiểm chứng được.
3. **Thông số**: kích thước, chất liệu, dung tích, trọng lượng, xuất xứ.
4. **Cách dùng** và lưu ý an toàn.
5. **Trong hộp có gì.**
6. **Chính sách đổi trả hoặc bảo hành**, nếu có.

Xuống dòng giữa các phần. Một khối chữ dài không ngắt đoạn rất khó đọc trên điện thoại.

### Hình ảnh trong mô tả

Bài chẩn đoán của TikTok nhắc người bán "kiểm tra xem có ảnh trong khu vực mô tả hay không". Ảnh trong mô tả là chỗ thích hợp cho bảng kích thước, bảng thành phần hay so sánh các phiên bản, những thông tin khó trình bày bằng chữ.

Hãy nhớ yêu cầu nhất quán: tiêu đề, hình ảnh, video và mô tả phải thống nhất và phản ánh đúng đặc điểm của sản phẩm. Thông tin không nhất quán hoặc gây hiểu nhầm có thể dẫn đến vi phạm chính sách.

## Thuộc tính, biến thể và thông tin thương hiệu

Thuộc tính (ngành hàng, chất liệu, kích thước, màu sắc...) giúp TikTok hiểu sản phẩm để đưa vào đúng kết quả tìm kiếm và bộ lọc. Điền đầy đủ và chính xác thuộc tính là việc ít tốn công nhưng thường bị bỏ qua.

Với biến thể, bài chẩn đoán của TikTok khuyên thêm hình ảnh khác nhau cho từng biến thể và cân nhắc tăng tồn kho cho các SKU nhất định, vì SKU hết hàng khiến khách đã chọn biến thể đó không thể mua. TikTok cũng khuyên sản phẩm nên được liên kết với thông tin nhãn hiệu; ở nhóm Sự tin cậy, TikTok nêu rằng "các sản phẩm có chứng nhận thương hiệu thường có nhiều khả năng đạt được sự tin cậy hơn". Chỉ dùng tên thương hiệu khi bạn đã được chủ sở hữu thương hiệu ủy quyền.

## Giá và khuyến mãi: đòn bẩy cho CTOR và AOV

Giá xuất hiện trên thẻ sản phẩm nên ảnh hưởng đến cả CTR, nhưng tác động lớn nhất của giá và khuyến mãi là lên CTOR (khách quyết định mua hay không) và AOV (khách mua bao nhiêu). Không giống ảnh hay mô tả, mỗi đòn bẩy về giá đều tốn biên lợi nhuận, nên hãy dùng chúng sau khi đã sửa những gì không tốn tiền.

### Chẩn đoán giá

Công cụ Chẩn đoán giá xếp sản phẩm vào ba nhóm: "Giá không cạnh tranh" (giá cao so với sản phẩm tương tự), "Giá cạnh tranh" và "Giá tốt nhất". Với hai nhóm đầu, TikTok đề xuất mức giá kèm lợi ích traffic ước tính, và bạn có thể điều chỉnh bằng Chiết khấu sản phẩm hoặc Voucher của nhà bán hàng ngay trên trang. Theo hướng dẫn của TikTok:

- Chiết khấu sản phẩm áp dụng theo từng chủng loại (SKU); Voucher của nhà bán hàng áp dụng cho cả sản phẩm, tức mọi chủng loại.
- Khuyến mãi tạo từ trang Chẩn đoán giá có hiệu lực mặc định 30 ngày.
- Bạn phải duy trì giá hấp dẫn trong một hoặc nhiều ngày để nhận được lợi ích.
- Không có hình phạt nếu bạn không điều chỉnh theo giá đề xuất; nếu không đạt mức đề xuất, bạn không nhận được lợi ích bổ sung từ nền tảng.
- Nếu không đồng ý với giá đề xuất, bạn có thể gửi phản hồi.

### Chiết khấu sản phẩm và voucher

Chiết khấu sản phẩm thay đổi giá hiển thị trên thẻ, nên có thể tác động lên cả CTR. Voucher thì khách thấy khi đã quan tâm, nên tác động chủ yếu lên CTOR. Trước khi tạo chiết khấu, hãy đặt cho mình một mức giảm tối đa có thể chấp nhận cho từng sản phẩm, và không vượt qua nó chỉ vì công cụ đề xuất.

Voucher có mức chi tiêu tối thiểu là công cụ cho AOV hơn là cho CTOR: đặt ngưỡng cao hơn giá trị đơn phổ biến một chút để khuyến khích khách mua thêm.

### Flash sale: dùng đúng liều

Flash sale tạo cảm giác khan hiếm và thường đẩy CTOR lên trong những ngày diễn ra. Nhưng có hai cái bẫy:

- **Flash sale gần như liên tục**: khi khách quen thấy sản phẩm luôn có flash sale, họ sẽ chờ đợt tiếp theo thay vì mua ở giá thường. Dấu hiệu là CTOR vào những ngày không có flash sale giảm dần, đặc biệt ở bước sau khi thêm vào giỏ.
- **Flash sale quá nông**: nếu giá flash chỉ thấp hơn vài phần trăm so với giá đang giảm sẵn, khách gần như không thấy khác biệt, nhưng bạn vẫn mất công vận hành và có thể làm khách chờ.

Hãy so sánh độ sâu thực của flash sale với giá đang bán, không phải với giá niêm yết gốc.

### Mua Sỉ Giá Hời (BMSM) để tăng AOV

Học viện TikTok Shop mô tả Mua Sỉ Giá Hời là công cụ khuyến mãi dựa trên đơn hàng "để tăng giá trị đơn hàng trung bình": giảm giá cho nhóm sản phẩm được chọn khi khách đạt số lượng tối thiểu, do người bán tài trợ. Một số điểm từ hướng dẫn của TikTok:

- Tối đa hai bậc; số lượng và phần trăm giảm của bậc 2 phải lớn hơn bậc 1.
- Thời gian khuyến mãi tối thiểu 10 phút, tối đa 365 ngày.
- Một sản phẩm chỉ tham gia một chương trình BMSM trong cùng một khoảng thời gian.
- Tối đa 30 chương trình BMSM đang và sắp diễn ra.
- Khách mua vượt bậc cao nhất được hưởng mức giảm của bậc đó cho tất cả sản phẩm.

TikTok gợi ý theo dõi "số lượng mặt hàng trung bình trên mỗi đơn hàng" để chọn ngưỡng. Một cách chọn ngưỡng: đặt ngay trên số món khách hay mua trong một đơn, ở mức mà một phần khách hiện tại đã đạt. Một ngưỡng mà gần như không ai đạt tới chỉ làm thẻ sản phẩm thêm rối.

### Ưu đãi theo gói và quà tặng

Nếu dữ liệu đơn hàng cho thấy hai sản phẩm thường được mua cùng nhau, Ưu đãi theo gói là cách tự nhiên để tăng AOV. Quà tặng kèm là lựa chọn khi giảm giá theo số lượng không phù hợp. Cả hai đều nên dựa trên dữ liệu đơn hàng thật: cặp sản phẩm nào đã xuất hiện cùng nhau trong nhiều đơn.

### Đánh giá và độ tin cậy

Đánh giá không phải là trường bạn chỉnh sửa trong niêm yết, nhưng nó ảnh hưởng lớn đến CTOR. TikTok xếp đánh giá tiêu cực và tỷ lệ trả hàng cao vào nhóm Sự tin cậy. Một nguyên tắc nên áp dụng: với sản phẩm bị người mua chấm điểm thấp, đừng bắt đầu bằng giảm giá hay đổi ảnh bìa. Đưa thêm khách đến một sản phẩm mà người mua trước đánh giá kém chỉ làm tăng số người thất vọng. Hãy xử lý chất lượng sản phẩm hoặc mô tả sai lệch trước.

## Đo lường một thay đổi đúng cách

Tối ưu mà không đo thì chỉ là thay đổi. Phần này mô tả một cách đo một thay đổi trên thẻ sản phẩm, bạn áp dụng được với một bảng tính.

### Một thay đổi, một sản phẩm, một lúc

Nếu bạn đổi ảnh bìa và giảm giá cùng một ngày, rồi CTR tăng, bạn không biết điều gì gây ra kết quả. Hãy thay đổi một thành phần trên một sản phẩm, ghi lại ngày thay đổi, và không chạm vào sản phẩm đó cho đến khi đo xong. Muốn đi nhanh hơn, hãy thử song song trên nhiều sản phẩm khác nhau, mỗi sản phẩm một thay đổi, thay vì nhiều thay đổi trên một sản phẩm.

### Cửa sổ trước và sau

- **Trước**: 14 ngày ngay trước ngày thay đổi.
- **Sau**: đọc sơ bộ sau 7 ngày, kết luận sau 14 ngày.

Đừng kết luận sau 2–3 ngày. Chỉ số theo ngày của một sản phẩm dao động mạnh, và vài ngày đầu sau thay đổi có thể chưa phản ánh hành vi ổn định.

### Đủ dữ liệu mới đo

Một chỉ số chỉ đáng để tối ưu nếu nó đủ dữ liệu để đo lại sau đó. Mỗi chỉ số cần một loại số liệu riêng trên kênh thẻ sản phẩm:

| Chỉ số | Cần đủ nhiều |
|---|---|
| CTR | Lượt hiển thị sản phẩm |
| CTOR | Lượt nhấp vào sản phẩm |
| AOV | Đơn hàng |

Chỉ đọc một chỉ số khi số liệu tương ứng đủ nhiều để không bị nhiễu, hoặc gộp một cửa sổ dài hơn, và giữ cùng một cách đọc cho mọi lần so sánh; TikTok không đưa ra ngưỡng chính thức. Khi số liệu còn quá ít, hãy ghi nhận "chưa đủ dữ liệu" thay vì đọc một con số. Một sản phẩm có CTOR 0 % trên 24 lượt nhấp trong 14 ngày không phải là sản phẩm "không bán được"; nó là sản phẩm chưa đủ dữ liệu để kết luận.

### Nhìn thêm những sản phẩm bạn chưa sửa

Traffic chung của shop thay đổi theo mùa, theo chiến dịch của nền tảng, theo ngày sale. Nếu CTR của sản phẩm bạn sửa tăng 10 % nhưng CTR của các sản phẩm không sửa cũng tăng 10 % trong cùng thời gian, thay đổi của bạn có lẽ không tạo ra gì. Vì vậy, hãy nhìn thêm vài sản phẩm tương tự trong shop mà bạn chưa sửa: nếu chúng cũng tăng gần như vậy, phần tăng đó đến từ cả shop chứ chưa chắc từ thay đổi của bạn. Khi đo một thay đổi, Juli ghi rõ kết quả bị ảnh hưởng nếu có thay đổi khác chạm vào sản phẩm trong cửa sổ đo.

### Đọc kết quả

- **Đo đúng chỉ số mà thay đổi nhắm tới.** Đổi ảnh bìa hay tiêu đề thì đọc CTR trước, CTOR sau. Sửa mô tả hay giảm giá thì đọc CTOR. Thêm BMSM thì đọc AOV.
- **Đọc lượt hiển thị bên cạnh.** Nếu lượt hiển thị tăng mạnh trong cửa sổ sau, CTR có thể giảm vì traffic loãng, không phải vì ảnh mới kém.
- **Ghi lại cả kết quả không rõ.** "Không đổi" cũng là một kết quả: nó cho biết thành phần đó không phải điểm nghẽn.

## Checklist tối ưu thẻ sản phẩm

Dùng danh sách này cho từng sản phẩm bán chạy:

- **Phễu**: Đã đọc CTR và CTOR trên kênh thẻ sản phẩm, so với 28 ngày trước và với các sản phẩm khác của shop.
- **Ảnh bìa**: Mặt trước sản phẩm, nền đồng nhất, sản phẩm chiếm từ 60 % khung, không che, không cắt; trên 1200 × 1200 pixel.
- **Bộ ảnh**: Từ 3 ảnh trở lên (tối đa 9), mỗi ảnh một góc; có ảnh cho từng biến thể; có video nếu được.
- **Tiêu đề**: Có loại sản phẩm, đặc điểm chính, quy cách; không khuyến mãi, không ký tự đặc biệt, không lặp từ; dài hơn 25 ký tự; từ khóa từ Trình Tối Ưu Hóa Tiêu Đề.
- **Mô tả**: Từ 30 từ; đặc điểm, thông số, cách dùng, trong hộp có gì; xuống dòng giữa các phần; trả lời 5 câu hỏi khách hay hỏi.
- **Thuộc tính**: Đầy đủ, đúng ngành hàng; thông tin nhãn hiệu nếu được ủy quyền.
- **Giá**: Đã xem Chẩn đoán giá; có mức giảm tối đa cho phép của riêng mình.
- **Khuyến mãi**: Flash sale không liên tục và không quá nông; BMSM có ngưỡng dựa trên số món khách đang mua.
- **Đo lường**: Ghi ngày thay đổi; một thay đổi mỗi sản phẩm; đọc sau 7 và 14 ngày; chỉ kết luận khi đủ dữ liệu.

## Juli AI hỗ trợ ở đâu

Juli AI là trợ lý AI vận hành cho nhà bán TMĐT do chúng tôi phát triển, hiện kết nối TikTok Shop (Shopee đang tích hợp). Với thẻ sản phẩm, Juli hỗ trợ ba việc trong bài này, và mọi thay đổi trên shop chỉ diễn ra khi bạn duyệt:

- **Tìm bước yếu**: [phân tích shop theo luồng truy cập](/san-pham/phan-tich-shop), đọc CTR và CTOR của kênh thẻ sản phẩm cho từng sản phẩm, so với chính nó và với các sản phẩm khác trong shop, kiểm tra traffic loãng trước khi đề xuất sửa ảnh bìa.
- **Đề xuất một thay đổi cụ thể**: ảnh bìa, tiêu đề, mô tả hay chiết khấu, kèm lý do bằng số. Juli [chỉ thực hiện khi bạn phê duyệt](/san-pham/de-xuat-va-thuc-thi): tiêu đề và mô tả do Juli viết, ảnh bìa dùng ảnh bạn gửi, còn giá và khuyến mãi là đề xuất để bạn tự quyết định trong giới hạn bạn đặt.
- **Đo lại**: [đọc tác động lên GMV](/san-pham/do-luong-gmv) sau 7 và 14 ngày, so với mốc 14 ngày trước khi áp dụng, khi số liệu đủ để đọc.

Juli đọc dữ liệu qua [kết nối chính thức với TikTok Shop](/ket-noi/tiktok-shop). Xem tổng quan tại trang [sản phẩm Juli AI](/san-pham), hoặc đọc bài [Top công cụ cho nhà bán TikTok Shop 2026](/blog/cong-cu-cho-nha-ban-tiktok-shop-2026) để so sánh với các lựa chọn khác.
`;
