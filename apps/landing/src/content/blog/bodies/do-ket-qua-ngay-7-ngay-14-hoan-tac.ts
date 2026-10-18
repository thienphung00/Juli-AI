/**
 * Guide post (D59 additions 5, P49-A1, C4): reading Juli's day-7 and day-14
 * measurement and when to undo. Main keyword "đọc kết quả đo lường sau khi
 * sửa sản phẩm tiktok shop" (commercial, long tail; `/san-pham/do-luong-gmv`
 * keeps "đo lường gmv sau thay đổi" and "đo lường gmv ngày 7 ngày 14"; the
 * reach post `do-hieu-qua-sau-khi-sua-san-pham-tiktok-shop` keeps the generic
 * "đo hiệu quả sau khi sửa sản phẩm"). Facts: D14 (day 7 check-in, next
 * proposal executes only after day 14, day 14 final), D29.8 (day 7 Đang lên /
 * Chưa rõ, day 14 Đạt / Một phần / Không đạt), D29.9 / D29.10 (guard bands,
 * volatile products judged at day 14), D31.7 (change strength, "Đạt · chưa
 * chắc chắn", never a stronger label), D30.1 (baseline frozen at approval and
 * execution), D30.4 (outside changes, "bị ảnh hưởng bởi thay đổi khác"), D32
 * (lever channel; CTOR and AOV on all channels), D22.3 / D24.6 (calibration,
 * reasons lower priority), D24.17 (7-day return after Hoàn tác),
 * `/san-pham/do-luong-gmv` and `/san-pham/de-xuat-va-thuc-thi` (labels,
 * "Hoàn tác?", undo steps, outside-edit guard, what cannot be undone, Juli
 * never undoes by itself, no published averages). Day 7 wording follows the
 * product pages / D29 (Juli asks), not D14's "recommend a revert". Not
 * described: control groups (D34 not built), simulation (D35/D45), uplift
 * percentages.
 */
export const body = `
Sau khi một thay đổi được áp dụng, Juli đọc lại sản phẩm hai lần: ngày 7 là kiểm tra giữa chừng, chỉ báo chỉ số mục tiêu đang lên hay chưa rõ và các chỉ số khác có còn trong ngưỡng không; ngày 14 mới là kết quả chốt, với một trong bốn nhãn Đạt, Đạt · chưa chắc chắn, Một phần hoặc Không đạt. Juli không bao giờ tự hoàn tác. Nếu ở ngày 7 một chỉ số bạn muốn giữ ổn định ra ngoài ngưỡng, Juli hỏi "Hoàn tác?" kèm số liệu, và bạn quyết định. Bài này chỉ cách đọc từng nhãn, khi nào nên hoàn tác và khi nào nên chờ đến ngày 14.

Phương pháp đo được mô tả ở trang [Đo lường GMV](/san-pham/do-luong-gmv). Ở đây chúng ta đọc một thay đổi cụ thể của Cửa hàng Mẫu Hoa Mai, một shop minh hoạ, từ ngày 7 đến ngày 14; số liệu trong ảnh là dữ liệu mẫu. Thay đổi này đến từ một thẻ đề xuất đã được duyệt và xác nhận, theo các bước trong bài [duyệt một thẻ đề xuất](/blog/duyet-de-xuat-toi-uu-san-pham-tiktok-shop).

## Vì sao không kết luận sau vài ngày

Số liệu TikTok Shop dao động mạnh theo ngày trong tuần, theo ngày lương, theo đợt sale và theo cách TikTok phân phối. Một hai ngày tốt sau khi sửa gần như không nói gì. Có thêm một cái bẫy ít ai để ý: thẻ đề xuất thường được tạo đúng lúc một sản phẩm vừa giảm, và nhiều chỉ số sau một đợt giảm sẽ tự hồi lại phần nào dù không ai làm gì. Nếu chỉ so trước và sau, phần hồi tự nhiên đó dễ bị tính là tác dụng của thay đổi.

Vì vậy Juli không dùng một phép trừ đơn giản. Mỗi kết luận dựa trên bốn thứ: một mốc so sánh cố định, một chỉ số mục tiêu trên đúng luồng, ngưỡng giữ ổn định cho các chỉ số còn lại, và mức thay đổi đặt cạnh mức dao động bình thường. Bài [đo hiệu quả sau khi sửa sản phẩm](/blog/do-hieu-qua-sau-khi-sua-san-pham-tiktok-shop) giải thích phương pháp này cho người tự đo bằng bảng tính; bài này đọc đúng những gì Juli hiện trên màn hình.

## Mốc so sánh 14 ngày, chụp trước khi áp dụng

Việc đo bắt đầu trước khi thay đổi được ghi lên shop. Khi bạn duyệt và khi Juli thực hiện, Juli chụp lại trạng thái của sản phẩm: chuỗi số liệu 14 ngày trước đó, giá, các khuyến mãi đang chạy và nội dung trang sản phẩm. Đó là mốc so sánh, cố định từ thời điểm áp dụng.

Mốc dài 14 ngày vì nó chứa hai tuần trọn vẹn, cả ngày thường lẫn cuối tuần, nên so sánh ít bị lệch vì thay đổi rơi vào đầu hay cuối tuần. Mọi con số trong phần đo là **trung bình mỗi ngày**, để hai khoảng có độ dài khác nhau, như 7 ngày sau và 14 ngày trước, vẫn so được với nhau.

## Một chỉ số mục tiêu, trên đúng luồng

Mỗi thay đổi có một chỉ số mục tiêu, với giá trị trước và giá trị mục tiêu. Một sản phẩm chỉ có một chỉ số mục tiêu tại một thời điểm: nếu cùng lúc đổi để tăng CTR và CTOR, không thể biết thay đổi nào tạo ra kết quả.

Chỉ số đó được đo trên đúng luồng mà thay đổi tác động. Ảnh bìa, tiêu đề và mô tả chủ yếu được người mua thấy trên Thẻ sản phẩm, nên lượt hiển thị và CTR của các thay đổi này được đo trên luồng Thẻ sản phẩm, không bị pha loãng bởi lượt xem từ video hay LIVE. TikTok không tách đơn hàng SKU theo từng luồng cho từng sản phẩm, nên CTOR và AOV được đo trên tất cả các kênh. Khuyến mãi hiện ở mọi nơi nên cũng được đo trên tất cả các kênh. Khi luồng Thẻ sản phẩm của một sản phẩm có quá ít dữ liệu, Juli đo trên tất cả các kênh và ghi rõ điều đó trên thẻ.

## Ngưỡng giữ ổn định cho các chỉ số còn lại

Một thay đổi có thể đẩy chỉ số mục tiêu lên nhưng kéo chỉ số khác xuống. Ví dụ, một tiêu đề mới có thể đưa đến nhiều người ít liên quan hơn, làm CTOR giảm. Vì vậy mỗi chỉ số không phải mục tiêu có một khoảng được phép dao động, gọi là **ngưỡng giữ ổn định**. Juli đề xuất ngưỡng dựa trên mức dao động bình thường của chính chỉ số đó, và bạn có thể chỉnh trong Quy tắc.

{{hinh:hd-dl-quy-tac-on-dinh}}

Phần đầu của mọi thẻ đang đo hiện cả hai thứ cạnh nhau: chỉ số mục tiêu với điều kiện "Đạt khi" và mức được coi là đang tiến triển, rồi bảng "Chỉ số không được lệch" với giá trị trước, ngưỡng và khoảng được phép dao động của từng chỉ số. Đọc bảng này trước khi đọc kết quả: nó cho biết ngày 7 sẽ hỏi bạn điều gì.

## Ngày 7: Đang lên hay Chưa rõ

Bảy ngày sau khi áp dụng, Juli chạy một lượt kiểm tra gồm bốn bước, hiện thành dòng thời gian trên thẻ:

1. Đọc dữ liệu 7 ngày sau thay đổi, so với trung bình 14 ngày trước khi đổi.
2. So chỉ số mục tiêu: **Đang lên** nếu đang tiến về mục tiêu, **Chưa rõ** nếu chưa thấy khác biệt.
3. So từng chỉ số còn lại với ngưỡng giữ ổn định.
4. Báo kết quả sơ bộ, hoặc hỏi bạn có muốn hoàn tác không.

{{hinh:hd-dl-ngay-7}}

Đọc ảnh mẫu theo bốn bước đó: chỉ số mục tiêu CTOR đi từ 5,4 % lên 5,7 %, chưa chạm mục tiêu 5,9 % nhưng đã qua mức "đang tiến triển", nên được ghi Đang lên. Lượt hiển thị mỗi ngày, CTR và AOV đều nằm trong khoảng cho phép, ghi Giữ ổn định. Dòng GMV mỗi ngày ghi Sơ bộ: ở ngày 7, con số GMV chỉ để tham khảo. Vì không có chỉ số nào ra ngoài ngưỡng, bước 4 là "Báo kết quả sơ bộ · không cần bạn làm gì", và thẻ chờ chốt ở ngày 14.

### Khi một chỉ số ra ngoài ngưỡng: câu hỏi "Hoàn tác?"

Nếu một chỉ số bạn muốn giữ ổn định đã ra ngoài khoảng cho phép, Juli hiện câu hỏi **"Hoàn tác?"** kèm số liệu cụ thể: chỉ số nào, giá trị bao nhiêu, ngoài khoảng nào. Bạn chọn **Hoàn tác** hoặc **Giữ thay đổi**. Nếu giữ, Juli đo tiếp đến ngày 14 và ghi chú rằng chỉ số đó đã ra ngoài khoảng ở ngày 7. Juli không tự hoàn tác, ở ngày 7 hay bất kỳ lúc nào.

### Ngày 7 không phải kết luận

Kết quả ngày 7 luôn được ghi là sơ bộ. Với sản phẩm có số liệu dao động mạnh, Juli chỉ đánh giá ở ngày 14. Trong thời gian này, đề xuất tiếp theo cho cùng sản phẩm có thể đã hiện ra, nhưng chỉ được thực hiện sau khi thay đổi hiện tại chốt ở ngày 14.

## Ngày 14: bốn nhãn kết quả

Ở ngày 14, Juli đọc lại toàn bộ 14 ngày sau thay đổi, so với mốc 14 ngày trước, và gắn một trong bốn nhãn:

| Nhãn | Nghĩa là |
|---|---|
| **Đạt** | Chỉ số mục tiêu tăng rõ, chạm mục tiêu, và GMV giữ được |
| **Đạt · chưa chắc chắn** | Chạm mục tiêu, nhưng mức tăng chỉ gấp một đến hai lần mức dao động bình thường, nên chưa loại trừ được may rủi |
| **Một phần** | Chỉ tăng rõ hoặc chỉ chạm mục tiêu, hoặc dữ liệu quá ít để chốt rõ |
| **Không đạt** | Không tăng rõ và không chạm mục tiêu |

"Tăng rõ" có một nghĩa cụ thể. Juli tính mức dao động của trung bình mỗi ngày trong cả hai khoảng, trước và sau, rồi so mức thay đổi với nó: lớn hơn hai lần mức dao động là rõ; từ một đến hai lần là có thể đã thay đổi; dưới một lần là vẫn trong dao động bình thường. Một kết quả yếu không bao giờ được gắn nhãn mạnh hơn.

{{hinh:hd-dl-ngay-14}}

Thẻ mẫu ở ngày 14 cho thấy đủ các bước: đọc 14 ngày sau thay đổi, so chỉ số mục tiêu (CTOR lên 5,95 %, mục tiêu 5,9 %), tính GMV thực tế và đặt cạnh GMV dự kiến, chốt kết quả Đạt, cập nhật mức kỳ vọng cho loại thay đổi đó, rồi mở khoá đề xuất tiếp theo cho sản phẩm. Ô kết luận màu xanh nói gọn: chỉ số mục tiêu đã chạm mục tiêu, GMV thực tế so với GMV dự kiến bao nhiêu, và thay đổi được giữ.

## "Bị ảnh hưởng bởi thay đổi khác"

Juli theo dõi những thay đổi diễn ra bên ngoài Juli: bạn tự sửa tiêu đề, đổi giá, mở hay tắt một khuyến mãi. Nếu một thay đổi như vậy rơi vào thời gian đo, kết quả ghi rõ "Bị ảnh hưởng bởi thay đổi khác", kèm thay đổi đó và ngày xảy ra, thay vì ghi công cho đề xuất của Juli.

Điều này có hệ quả thực tế cho bạn: trong 14 ngày đo, nếu có thể, đừng sửa thêm gì trên chính sản phẩm đó, và tránh mở một đợt khuyến mãi riêng cho nó. Ngày sale của sàn không bị xoá khỏi dữ liệu mà được đánh dấu, như bài [doanh thu sau sale](/blog/doanh-thu-sau-sale-tiktok-shop) mô tả; một thay đổi đo trùng đợt sale lớn nên được đọc thận trọng hơn.

## GMV dự kiến đặt cạnh kết quả thật

GMV dự kiến tính ở thời điểm đề xuất được lưu cùng thay đổi. Đến ngày 14, kết quả thật được đặt cạnh con số này, để cả bạn và Juli biết ước tính đã sát đến đâu. GMV dự kiến không phải cam kết: nó là ước tính theo quy tắc, tính từ số liệu 30 ngày của sản phẩm. Một kết quả Đạt với GMV thực tế thấp hơn dự kiến vẫn là Đạt; nhãn dựa trên chỉ số mục tiêu và GMV có giữ được hay không, không dựa trên việc vượt con số dự kiến.

## Hoàn tác từng bước

Mọi thay đổi Juli ghi lên TikTok Shop đều được lưu giá trị cũ. Nút **Hoàn tác** có ở lượt chạy đã áp dụng và trong phần Đo lường. Các bước:

1. Bấm Hoàn tác. Hộp thoại cho biết Juli sẽ khôi phục nội dung cũ nào của sản phẩm nào, và rằng kết quả đo của thay đổi này sẽ dừng.
2. Chọn một lý do (bắt buộc), thêm ghi chú nếu muốn.
3. Bấm Bắt đầu hoàn tác. Juli tạo một lượt chạy mới để khôi phục tiêu đề, mô tả hoặc ảnh bìa cũ.
4. Lượt hoàn tác cũng dừng ở bước xác nhận. Bạn xác nhận lần cuối, rồi Juli mới ghi.

{{hinh:hd-dl-hoan-tac}}

**Juli kiểm tra trước khi ghi đè.** Trước khi khôi phục, Juli đọc lại sản phẩm trên TikTok Shop. Nếu nội dung đã bị sửa bên ngoài Juli sau lần thay đổi, Juli không ghi đè và báo cho bạn biết, để không xoá mất chỉnh sửa của chính bạn.

**Những gì không hoàn tác qua Juli.** Khuyến mãi do bạn tạo: muốn dừng, bạn tắt khuyến mãi trên Seller Center, Juli tự ghi nhận. Thẻ "Juli soạn · bạn làm" cho video và LIVE: Juli không ghi gì lên TikTok Shop nên không có gì để hoàn tác.

**Sau khi hoàn tác.** Thẻ được đóng, và cùng thay đổi cho cùng sản phẩm chỉ có thể quay lại sau ít nhất 7 ngày. Lý do bạn chọn làm loại thay đổi đó được ưu tiên thấp hơn cho shop trong thời gian sau, nhạt dần trong khoảng 60 ngày.

## Khi nào nên hoàn tác, khi nào nên chờ đến ngày 14

Juli không đưa ra một con số để quyết định thay bạn, và bài này cũng không. Nhưng có vài tình huống rõ ràng:

**Nên cân nhắc hoàn tác ngay:**

- Nội dung mới sai thông tin sản phẩm, hoặc khách nhắn hỏi vì không hiểu tên sản phẩm mới.
- TikTok cảnh báo sản phẩm sau thay đổi.
- Nội dung không hợp giọng thương hiệu và bạn không muốn khách thấy thêm ngày nào.
- Ở ngày 7, Juli hỏi "Hoàn tác?" vì một chỉ số bạn muốn giữ ổn định đã ra ngoài ngưỡng, và đó là chỉ số bạn coi trọng hơn chỉ số mục tiêu.

**Nên chờ đến ngày 14:**

- Ngày 7 ghi Chưa rõ nhưng mọi chỉ số khác vẫn Giữ ổn định: chưa thấy tác dụng không có nghĩa là có hại.
- Một chỉ số chỉ vừa chạm mép ngưỡng trong tuần có ngày sale hoặc ngày lương.
- Sản phẩm có số liệu dao động mạnh, mà Juli chỉ đánh giá ở ngày 14.

Nếu bạn hoàn tác sớm, thay đổi đó không có kết quả ngày 14 để Juli học. Đó không phải lý do để giữ một nội dung sai; đó là lý do để không hoàn tác chỉ vì một hai ngày xấu.

## Juli học gì từ kết quả

Mỗi kết quả ngày 14 quay lại quyết định đề xuất tiếp theo. Với mỗi loại thay đổi (ảnh bìa, tiêu đề, mô tả, giảm giá…), Juli giữ một hệ số so sánh GMV thực tế với GMV dự kiến của các lần đã đo trong shop của bạn. Loại chưa được đo đứng ở mức trung tính; loại đã mang lại đúng như dự kiến được xếp lên trước, loại thường không đạt được xếp xuống. Khi thứ tự đã được điều chỉnh, thẻ ghi "Thứ tự đề xuất đã điều chỉnh theo kết quả trước của shop". Con số GMV dự kiến trên thẻ vẫn là ước tính theo quy tắc, để còn so được với kết quả thật.

Juli không chép lựa chọn của shop này sang shop khác. Một kết luận chung giữa các shop chỉ được dùng khi nó đứng vững qua nhiều shop; hiện chưa có loại thay đổi nào đạt chuẩn đó, nên Juli không công bố con số hiệu quả chung nào, trên trang web hay trong ứng dụng.

Để đi lại cả vòng từ đầu: [kết nối TikTok Shop với Juli](/blog/huong-dan-ket-noi-tiktok-shop-voi-juli) và trang [Kết nối TikTok Shop](/ket-noi/tiktok-shop), [đọc màn hình Phân tích theo luồng](/blog/doc-phan-tich-tiktok-shop-theo-luong-truy-cap) và trang [Phân tích shop](/san-pham/phan-tich-shop), rồi trang [Đề xuất và thực thi](/san-pham/de-xuat-va-thuc-thi). Nếu chỉ số nào trong bài còn lạ, xem [CTR, CTOR, AOV trên TikTok Shop](/blog/chi-so-tiktok-shop-ctr-ctor-aov) và [GMV là gì](/blog/gmv-la-gi-tiktok-shop). Tổng quan sản phẩm và bảng giá ở trang [Sản phẩm](/san-pham).
`;
