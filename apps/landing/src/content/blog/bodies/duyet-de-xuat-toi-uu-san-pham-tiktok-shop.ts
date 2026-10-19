/**
 * Guide post (D59 additions 5, P49-A1, C3): walking one proposal card from its
 * reason to the final confirmation. Main keyword "duyệt đề xuất tối ưu sản
 * phẩm tiktok shop" (commercial; the head term "tối ưu sản phẩm tiktok shop"
 * stays with `/san-pham/de-xuat-va-thuc-thi`, used here only in an H2 / FAQ).
 * Facts: D12, D13 (title, description executed; cover only with the seller's
 * photo; price off; promotions seller-executed), D24.16 / D24.22 (drafts
 * checked for length, tone, banned and protected terms), D29.4 (one target
 * metric per product), D47.5 (lapsed consent puts the card back),
 * `/san-pham/de-xuat-va-thuc-thi` (card anatomy, two consents, one-use write
 * grant, run timeline, queue, Seller Center and content cards, undo).
 * D61: no card caps, slots, validity or cooldown numbers, no trigger, ranking
 * or target rule, no expected-GMV formula, no rules-vs-model architecture.
 * Not described: AOV / pack proposals (Ops only, D45), control groups (D34),
 * simulation (D35/D45).
 */
export const body = `
Duyệt một thẻ đề xuất của Juli gồm hai lần đồng ý, không phải một: bấm **Duyệt** trên thẻ chỉ cho phép Juli bắt đầu chuẩn bị, còn thay đổi chỉ được ghi lên TikTok Shop khi bạn xem bản cũ và bản mới rồi bấm **Xác nhận thay đổi này** trong lượt chạy. Giữa hai lần đó, bạn đọc lý do, sửa nội dung nếu muốn, hoặc dừng lại bằng Không thực hiện. Bài này đi qua một thẻ từ đầu đến cuối: thẻ nói gì, GMV dự kiến nghĩa là gì, ai làm phần nào, và chuyện gì xảy ra khi bạn từ chối.

Trang [Đề xuất và thực thi](/san-pham/de-xuat-va-thuc-thi) mô tả tính năng. Ở đây chúng ta đi từng bước trên các thẻ của Cửa hàng Mẫu Hoa Mai, một shop minh hoạ; số liệu và nội dung trong ảnh là dữ liệu mẫu, các phép tính khác ghi rõ là ví dụ giả định.

## Một thẻ đề xuất nói gì

Mỗi đề xuất là một thẻ trong trang Quyết định. Một thẻ nói về **một sản phẩm**, nhắm **một chỉ số** trên **một luồng**, và đề xuất **một loại thay đổi**.

{{hinh:hd-dx-the-mo-ta}}

Đọc thẻ trong ảnh từ trên xuống:

1. **Sản phẩm và trạng thái.** Mã SKU, tên sản phẩm, nhãn "Chờ duyệt" và ngày cập nhật số liệu. Số trên thẻ được cập nhật mỗi ngày.
2. **Chỉ số mục tiêu.** Ở đây là CTOR, từ 5,4 % lên 5,9 %: giá trị hiện tại, mục tiêu và mức tăng. Mục tiêu được đặt ở mức đủ rõ để đo được và không hứa quá tay. Với sản phẩm dao động mạnh, mục tiêu hiện dưới dạng một khoảng.
3. **GMV dự kiến mỗi tháng** nếu đạt mục tiêu, ghi rõ là ước tính.
4. **Lý do ngắn** ("Mô tả quá ngắn") và **thay đổi đề xuất** (chip Mô tả).
5. **Lý do đầy đủ**, khi bấm "Xem thêm": số liệu cụ thể của sản phẩm, điều TikTok báo về trang sản phẩm nếu có, và GMV dự kiến của thẻ.
6. **Hai nút**: Duyệt và Từ chối. "Xem phân tích" đưa bạn về đúng chỗ trong màn hình Phân tích nơi thẻ này bắt đầu.

Một số thẻ còn mang nhãn "Độ tin cậy: Cao, Vừa hoặc Thấp", tính từ lượng dữ liệu và mức dao động của sản phẩm trên luồng đó. Thẻ tạo ngay sau khi kết nối ghi "Đề xuất nhanh · dựa trên 14 ngày" với độ tin cậy Tham khảo.

## Khi nào một thẻ xuất hiện

Một thẻ bắt đầu từ dữ liệu, không từ danh sách mẹo chung. Juli đọc từng sản phẩm trên từng luồng. Khi một chỉ số của phễu trên một luồng yếu đi rõ rệt, kể cả khi GMV tổng của sản phẩm vẫn giữ được nhờ một chỉ số khác tăng, Juli đề xuất thay đổi hợp với chỉ số đó: ảnh bìa hoặc tiêu đề cho CTR, mô tả hoặc giá cho CTOR.

Trước khi thẻ hiện ra, Juli kiểm tra bốn điều:

- Số liệu đủ để đọc được kết quả.
- Thay đổi đó hợp lệ với TikTok Shop và với quy tắc của bạn.
- Sản phẩm không có một thay đổi khác đang được đo.
- Bạn chưa vừa từ chối hay hoàn tác cùng thay đổi đó.

Juli đưa lên trước những việc có khả năng mang lại nhiều GMV nhất. Sản phẩm bán chạy cũng được xét, vì một sản phẩm lớn mất vài phần trăm CTOR có thể mất nhiều tiền hơn một sản phẩm nhỏ mất một nửa. Bài [đọc màn hình Phân tích theo luồng truy cập](/blog/doc-phan-tich-tiktok-shop-theo-luong-truy-cap) giải thích cách đọc bảng sản phẩm trong màn hình đó.

## GMV dự kiến là một ước tính

Con số GMV dự kiến trên thẻ là phần GMV Juli ước tính có thể lấy lại từ số liệu hiện tại của sản phẩm, trên đúng luồng mà thẻ nhắm tới. Lượt nhấp tăng thêm chỉ thành GMV khi có người đặt hàng, nên GMV dự kiến của một thẻ CTR còn phụ thuộc vào CTOR của chính sản phẩm: một trang sản phẩm chưa thuyết phục thì thêm người bấm vào cũng không mang lại nhiều đơn.

Muốn tự thử với số của mình, dùng [công cụ tính GMV](/cong-cu/tinh-gmv): công cụ cho thấy GMV thay đổi ra sao khi CTR, CTOR hay AOV của một sản phẩm tăng một mức bạn chọn.

Đây là **ước tính, không phải lời hứa**. Con số được lưu cùng thay đổi, và đến ngày 14 kết quả thật được đặt cạnh nó, như bài [đo kết quả ngày 7, ngày 14](/blog/do-ket-qua-ngay-7-ngay-14-hoan-tac) mô tả. Nếu kết quả thật thấp hơn, bạn thấy ngay điều đó trên thẻ đo lường, cùng lựa chọn giữ hay hoàn tác.

## Trước khi bấm Duyệt: đặt Quy tắc của bạn

Phía trên các thẻ, trang Quyết định hiện hai ô: **Giữ ổn định** và **Quy tắc do bạn đặt**.

{{hinh:hd-dx-quy-tac}}

Trong Quy tắc, bạn đặt giọng văn, những từ không được dùng, giá vốn hoặc biên lợi nhuận tối thiểu, mức giảm giá tối đa và số thẻ mở cùng lúc. Juli không tự chọn các con số này. Một đề xuất giảm giá chỉ xuất hiện khi Juli biết giá vốn của sản phẩm, và luôn nằm trong biên lợi nhuận bạn cho phép.

Ô Giữ ổn định liệt kê các chỉ số không được lệch quá mức khi một thay đổi đang được đo, mỗi chỉ số một ngưỡng do Juli gợi ý. Ở ngày thứ 7, chỉ số nào lệch quá ngưỡng thì Juli hỏi bạn có muốn hoàn tác không. Đặt giọng văn và từ cấm trước khi duyệt thẻ tiêu đề hay mô tả đầu tiên là việc đáng làm nhất: nội dung Juli soạn được kiểm tra theo chính danh sách đó.

## Duyệt chưa đổi gì trên shop

Bấm **Duyệt** tạo ra một **lượt chạy**, và từ đó Juli mới bắt đầu soạn nội dung. Khi nhiều thẻ cùng nhắm một chỉ số, bạn có thể duyệt cả nhóm bằng một lần bấm, nhưng mỗi sản phẩm vẫn có bước xác nhận riêng trước khi Juli ghi.

Ví dụ với thẻ tiêu đề dưới đây: CTR của sản phẩm giảm so với 30 ngày trước, và lý do đầy đủ chỉ ra tiêu đề chưa có những từ khoá khách hay tìm. Bản tiêu đề mới ở thẻ này là bản Juli đề xuất để bạn hình dung; nội dung cuối cùng chỉ được chốt trong lượt chạy.

{{hinh:hd-dx-the-tieu-de}}

## Lượt chạy và bước Xác nhận một lần

Trong lượt chạy, Juli lần lượt đọc chẩn đoán của TikTok, đọc thông tin sản phẩm, phân tích từ khoá và ảnh, rồi soạn thay đổi. Lượt chạy dừng ở bước **Xác nhận một lần** và chờ bạn:

1. Bạn xem nội dung cũ (gạch ngang) và nội dung mới của từng phần sẽ thay đổi.
2. Nếu muốn, bạn bấm "Sửa nội dung trước khi áp dụng" và sửa trực tiếp.
3. Bạn bấm **Xác nhận thay đổi này**, hoặc **Không thực hiện** nếu đổi ý.
4. Juli ghi lên TikTok Shop, TikTok duyệt lại trang sản phẩm, và Juli đặt lịch đo: ngày 7 đo sơ bộ, ngày 14 chốt.

Nội dung AI soạn được kiểm tra độ dài, giọng văn và danh sách từ không được dùng trong Quy tắc của bạn trước khi hiện ra, và được đối chiếu với thông tin của chính sản phẩm đó. Bạn vẫn là người đọc lại và quyết định cuối cùng: kiểm tra kỹ thành phần, kích thước, công dụng trước khi xác nhận.

Hộp xác nhận ghi thời gian còn hiệu lực. Quyền ghi được cấp riêng cho đúng một sản phẩm, đúng một loại thao tác, có thời hạn và chỉ dùng được một lần. Nếu bạn để hết hạn, lượt chạy dừng mà không đổi gì, và thẻ trở lại "Chờ duyệt" để bạn duyệt lại khi sẵn sàng.

Trong tab **Đang thực hiện**, mỗi lượt chạy hiện thành một dòng thời gian: bước nào đã xong, lúc mấy giờ, kết quả là gì. Khi Juli ghi lên TikTok Shop, bước đó ghi rõ đã đổi phần nào và "giá trị cũ đã lưu", để có thể hoàn tác.

## Juli làm phần nào, bạn làm phần nào

Juli chỉ tự thực hiện những thay đổi có thể kiểm soát và hoàn tác an toàn qua TikTok Shop Open API. Phần còn lại, Juli chuẩn bị sẵn để bạn làm.

| Loại thay đổi | Ai làm | Bước của bạn |
|---|---|---|
| Tiêu đề, mô tả | Juli ghi sau khi bạn xác nhận | Duyệt, đọc bản mới, sửa nếu cần, xác nhận |
| Ảnh bìa | Juli tải lên ảnh bạn gửi | Duyệt, gửi ảnh, xác nhận |
| Giá, giảm giá, flash sale, phí vận chuyển | Bạn làm trên Seller Center | Làm theo hướng dẫn, bấm "Đã áp dụng" |
| Kịch bản video, kịch bản LIVE | Juli soạn, bạn quay hoặc lên LIVE | Chọn kịch bản, quay, đăng |

### Ảnh bìa: chỉ với ảnh của bạn

Juli phân tích ảnh bìa hiện tại và đề xuất cần đổi gì, nhưng không tự tạo hay tự chọn ảnh. Thẻ ảnh bìa ghi rõ "Juli tải lên · cần ảnh từ bạn", và dòng cuối thẻ tóm tắt cả quy trình: Duyệt, Juli hỏi ảnh, bạn tải ảnh, xác nhận, Juli thay ảnh bìa.

{{hinh:hd-dx-the-anh-bia}}

Sau khi bạn duyệt, lượt chạy đọc chẩn đoán của TikTok, phân tích ảnh hiện tại, rồi dừng ở bước "Chờ ảnh từ bạn" với yêu cầu cụ thể cho ảnh mới. Bạn chọn ảnh từ máy; Juli kiểm tra ảnh, bạn xác nhận một lần, rồi Juli mới tải ảnh lên TikTok Shop. Nếu yêu cầu ảnh hết hiệu lực mà bạn chưa gửi, lượt chạy dừng và không thay đổi gì.

{{hinh:hd-dx-cho-anh}}

### Giá và khuyến mãi: Juli đề xuất, bạn áp dụng

Juli không thay đổi giá sản phẩm. Với giảm giá sản phẩm, flash sale hay giảm phí vận chuyển, thẻ ghi "Bạn thực hiện trên Seller Center". Sau khi duyệt, Juli đưa hướng dẫn từng bước với mức giảm cụ thể nằm trong quy tắc biên lợi nhuận của bạn. Bạn tạo khuyến mãi, bấm "Đã áp dụng", Juli kiểm tra lại trên TikTok bằng quyền chỉ đọc và bắt đầu đo.

### Video và LIVE: Juli soạn, bạn quay

Khi CTR của video hay khả năng chốt đơn trong LIVE của một sản phẩm giảm, Juli tạo thẻ "Juli soạn · bạn làm": kịch bản video mới, hoặc kịch bản cho người dẫn LIVE và thứ tự giỏ hàng. Bạn chọn dùng kịch bản, yêu cầu soạn lại hoặc bỏ qua, rồi tự quay hay lên LIVE. Juli nhận ra video mới gắn sản phẩm hoặc phiên LIVE tiếp theo bán sản phẩm và đo trên đó. Loại thẻ này không ghi gì lên TikTok Shop.

## Từ chối kèm lý do, và điều gì xảy ra sau đó

Không phải thẻ nào cũng nên duyệt. Bấm **Từ chối**, bạn chọn một lý do; thẻ rời khỏi danh sách đề xuất và Juli không thay đổi gì trên sản phẩm.

{{hinh:hd-dx-tu-choi}}

Sau khi từ chối, cùng thay đổi đó không quay lại ngay cho sản phẩm. Lý do bạn chọn được ghi lại để các đề xuất sau hợp với shop hơn, dù đó là "không hợp thương hiệu hoặc giọng văn", "lý do hoặc số liệu chưa thuyết phục" hay một lý do hoàn cảnh như đang tự sửa sản phẩm. Ô ghi chú không bắt buộc, nhưng một câu như "shop không dùng từ cao cấp trong tên sản phẩm" là thứ nên chuyển vào danh sách từ không được dùng trong Quy tắc.

## Nhịp thẻ: vì sao mỗi ngày chỉ vài thẻ

Quá nhiều đề xuất cùng lúc khiến người bán khó theo kịp, và cũng khó đo kết quả. Vì vậy Juli giữ nhịp đề xuất vừa phải, giống nhau cho mọi shop:

- Mỗi ngày chỉ vài thẻ mới, gồm việc Juli làm, việc bạn làm trên Seller Center và nội dung video hoặc LIVE. Không có việc đáng làm thì Juli không thêm thẻ cho đủ số.
- Bạn có thể giảm số thẻ mở cùng lúc trong Quy tắc.
- Số liệu trên thẻ được cập nhật mỗi ngày. Thẻ có thời hạn; thẻ chưa duyệt tự hết hạn, và Juli đề xuất lại sau nếu thay đổi đó vẫn còn phù hợp.
- Thẻ bị rút sớm chỉ khi không còn hợp lệ: sản phẩm bị sửa bên ngoài Juli, hết hàng, hoặc chỉ số đã đạt mục tiêu.
- Thẻ đã hết hạn, bị từ chối, không thực hiện hoặc hoàn tác không quay lại ngay.

### Một sản phẩm, một thay đổi tại một thời điểm

Juli chạy lần lượt và không bao giờ thực hiện hai thay đổi cùng lúc trên một sản phẩm. Hàng chờ thẻ tối ưu cho thấy sản phẩm nào đang chờ bạn và sản phẩm nào đã áp dụng.

{{hinh:hd-dx-hang-cho}}

Lý do rất đơn giản: nếu hai thay đổi chồng lên nhau, không ai biết thay đổi nào tạo ra kết quả. Một sản phẩm chỉ có một chỉ số mục tiêu tại một thời điểm. Đề xuất tiếp theo cho cùng sản phẩm có thể hiện ra ở ngày 7, nhưng chỉ được thực hiện sau khi thay đổi trước đã chốt ở ngày 14.

## Cách tối ưu sản phẩm trên TikTok Shop theo thẻ: một thứ tự gợi ý

Nếu bạn mới bắt đầu và có nhiều thẻ cùng lúc, thứ tự sau giúp kết quả dễ đọc nhất:

1. Đặt Quy tắc trước: giọng văn, từ không được dùng, giá vốn nếu có.
2. Duyệt thẻ có độ tin cậy cao và lý do bạn đồng ý ngay khi đọc.
3. Với thẻ ảnh bìa, chuẩn bị ảnh trước khi duyệt, để lượt chạy không phải chờ.
4. Đọc kỹ bản mới ở bước xác nhận; sửa những chỗ chưa đúng giọng shop.
5. Từ chối kèm lý do những thẻ không hợp, thay vì để chúng hết hạn: lý do giúp đề xuất sau tốt hơn.

## Nếu đổi ý sau khi đã áp dụng: Hoàn tác

Mọi thay đổi Juli ghi lên TikTok Shop đều được lưu giá trị cũ. Nút Hoàn tác có ở lượt chạy đã áp dụng và trong phần Đo lường. Khi bấm, bạn chọn lý do, Juli tạo một lượt chạy mới để khôi phục nội dung cũ, và lượt hoàn tác cũng dừng ở bước xác nhận trước khi ghi. Juli kiểm tra trước khi ghi đè: nếu nội dung đã bị sửa bên ngoài Juli, Juli không ghi đè và báo cho bạn. Khuyến mãi do bạn tạo và thẻ "Juli soạn · bạn làm" không có gì để hoàn tác qua Juli. Bài [đo kết quả ngày 7, ngày 14 và hoàn tác](/blog/do-ket-qua-ngay-7-ngay-14-hoan-tac) đi qua phần này chi tiết, cùng trang [Đo lường GMV](/san-pham/do-luong-gmv).

Muốn ôn lại nền tảng: [tối ưu thẻ sản phẩm TikTok Shop](/blog/toi-uu-the-san-pham-tiktok-shop) giải thích ảnh bìa, tiêu đề, mô tả tác động đến phễu thế nào; [kết nối TikTok Shop với Juli](/blog/huong-dan-ket-noi-tiktok-shop-voi-juli) và trang [Kết nối TikTok Shop](/ket-noi/tiktok-shop) nói rõ Juli được phép ghi gì; [Phân tích shop](/san-pham/phan-tich-shop) là nơi mọi thẻ bắt đầu; tổng quan ở trang [Sản phẩm](/san-pham).
`;
