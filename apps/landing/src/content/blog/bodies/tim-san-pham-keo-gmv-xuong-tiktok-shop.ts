/**
 * Conversion problem post C6 (D59 additions 5, P49-A2): "Tìm sản phẩm đang kéo GMV TikTok Shop
 * xuống". Main keyword "sản phẩm kéo gmv xuống tiktok shop" (long tail, no volume; the reach post
 * `doanh-thu-tiktok-shop-giam` keeps "doanh thu tiktok shop giảm" and the by-hand diagnosis; this
 * post shows only how Juli finds the product and turns it into a card). Facts: `/san-pham/phan-tich-shop`
 * (Kéo xuống / Kéo lên, rows sum to the tile, "Còn lại", Rõ / Tham khảo, Xem đề xuất / Chưa có đề
 * xuất), `/san-pham/de-xuat-va-thuc-thi` (best-sellers considered, conditions before a card). D61:
 * no expected-GMV formula, data floor, window search, peer reference, target bounds, ranking or card
 * caps. No AOV card is promised (D45 keeps AOV levers in Ops). Worked numbers are hypothetical and
 * say so; screenshot numbers are the sample shop's.
 */
export const body = `
Khi GMV của shop giảm, câu hỏi đầu tiên là "sản phẩm nào?". Nhưng sắp xếp sản phẩm theo doanh thu giảm nhiều nhất thường chỉ ra sai chỗ: một sản phẩm có thể giảm vì ít người thấy, vì ít người bấm, hay vì người bấm vào không mua, và mỗi trường hợp cần một cách sửa khác. Juli làm ngược lại: tìm luồng và chỉ số đang lấy đi nhiều GMV nhất trước, rồi mới chia con số đó cho từng sản phẩm theo số đồng mỗi ngày.

Bài này đi qua cách đọc bảng "sản phẩm kéo xuống" trong trang Phân tích của Juli và cách một dòng trong bảng trở thành thẻ đề xuất. Nếu bạn muốn tự chẩn đoán bằng số liệu Seller Center, không dùng công cụ nào, bài [Doanh thu TikTok Shop giảm](/blog/doanh-thu-tiktok-shop-giam) đi qua từng bước bằng tay. Ảnh màn hình trong bài lấy từ "Cửa hàng Mẫu Hoa Mai", shop minh hoạ của Juli.

## Vì sao nhìn doanh thu từng sản phẩm chưa đủ

Danh sách sản phẩm theo doanh thu cho biết sản phẩm nào bán ít đi, nhưng không cho biết vì sao. Theo bài "Lưu lượng truy cập sản phẩm" của Học viện TikTok Shop, GMV của một sản phẩm trên một luồng là tích của bốn chỉ số:

> GMV = Lượt hiển thị sản phẩm × CTR × CTOR × AOV (SKU)

trong đó CTR = lượt nhấp ÷ lượt hiển thị, CTOR = đơn hàng SKU ÷ lượt nhấp, AOV (SKU) = GMV ÷ đơn hàng SKU. Hai sản phẩm cùng giảm 100.000đ mỗi ngày có thể có hai nguyên nhân khác hẳn: sản phẩm thứ nhất mất lượt hiển thị vì TikTok phân phối ít đi, sản phẩm thứ hai vẫn được thấy và được bấm nhưng khách không đặt hàng. Sửa tiêu đề cho cả hai là đoán.

Có thêm hai cái bẫy:

- **Luồng bù nhau.** Một sản phẩm có thể giữ nguyên GMV tổng vì video của một nhà sáng tạo đang kéo đơn, trong khi trên Thẻ sản phẩm, nơi bạn kiểm soát ảnh bìa, tiêu đề và mô tả, nó đang giảm rõ.
- **Dao động bình thường.** Số liệu TikTok Shop lên xuống mạnh theo ngày trong tuần và theo đợt sale. Một tuần xấu chưa chắc là vấn đề.

Vì vậy Juli không bắt đầu từ danh sách sản phẩm.

## Bắt đầu từ luồng và ô chỉ số

Trang Phân tích của Juli mở bằng một câu tóm tắt, ví dụ "Thẻ sản phẩm: CTOR giảm 7 %", so sánh 30 ngày gần nhất với 30 ngày ngay trước đó.

{{hinh:keo-xuong-luong}}

Câu đó đến từ hai bước. Trước hết, Juli tách GMV của shop theo năm luồng truy cập mà TikTok ghi nhận: Thẻ sản phẩm, Tab cửa hàng, Video, LIVE và Liên kết. Sau đó, với mỗi luồng, Juli dựng phễu bốn ô và ghi dưới mỗi ô số đồng mỗi ngày mà thay đổi của chỉ số đó kéo GMV lên hoặc xuống. Bốn con số cộng lại bằng đúng mức thay đổi GMV của luồng.

{{hinh:keo-xuong-pheu}}

Trong ví dụ của shop mẫu, luồng Thẻ sản phẩm có lượt hiển thị tăng và GMV vẫn tăng, nhưng CTOR giảm và lấy đi khoảng 250.000đ mỗi ngày, nhiều hơn hẳn CTR hay AOV. Juli đánh dấu "Juli gợi ý" lên ô CTOR. Đây là chỗ mà một tổng GMV đang tăng che mất: shop vẫn lớn lên, nhưng để rơi một phần đáng kể ở bước từ cú nhấp đến đơn hàng.

Một mức giảm chỉ được đánh dấu khi nó lớn hơn mức dao động bình thường của chính chỉ số đó trên chính luồng đó. Lượt hiển thị phụ thuộc nhiều vào cách TikTok phân phối và vào mùa vụ, còn những gì bạn sửa được trên trang sản phẩm thường hiện ra ở CTR và CTOR. Cách đọc từng luồng được giải thích ở trang [Phân tích shop](/san-pham/phan-tich-shop).

## Đọc bảng sản phẩm kéo xuống

Bấm vào ô được đánh dấu, Juli mở bảng chia con số của ô đó cho từng sản phẩm.

{{hinh:keo-xuong-bang}}

Mỗi dòng có bốn thông tin:

1. **Sản phẩm**: mã SKU và tên.
2. **Chỉ số trước và nay**: ở đây là CTOR của 30 ngày trước và 30 ngày gần nhất, tính từ tổng của kỳ như Seller Center, không lấy trung bình các tỷ lệ hằng ngày.
3. **GMV mỗi ngày**: số đồng mà thay đổi CTOR của riêng sản phẩm đó lấy đi mỗi ngày. Thanh màu cho thấy độ lớn so với dòng đầu.
4. **Tin cậy**: Rõ hoặc Tham khảo.

Dòng đầu bảng là nơi một thay đổi có thể mang lại nhiều nhất. Trong ví dụ, Son môi số 12 có CTOR giảm từ 6,3 % xuống 5,4 % và lấy đi khoảng 112.000đ mỗi ngày, nhiều nhất trong năm sản phẩm.

Hai nút ở góc bảng, **Kéo xuống** và **Kéo lên**, đổi giữa sản phẩm làm GMV giảm nhiều nhất và sản phẩm đang đóng góp tăng trưởng.

## Vì sao các dòng cộng đúng bằng ô

Bảng không phải một danh sách riêng. Nó là cùng một con số của ô CTOR, chia ra theo sản phẩm. Năm dòng đầu cộng với dòng **Còn lại** (gộp các sản phẩm ảnh hưởng nhỏ và sản phẩm kéo CTOR lên) bằng đúng con số trên ô, ghi ở cuối bảng "Tổng · bằng số của ô CTOR".

Điều này quan trọng vì hai lẽ. Thứ nhất, bạn biết sửa năm sản phẩm đầu sẽ chạm tới phần lớn vấn đề hay chỉ một phần nhỏ: nếu dòng Còn lại nhỏ, vấn đề tập trung ở vài sản phẩm; nếu nó lớn, vấn đề rải đều và có thể nằm ở thứ chung của cả shop như phí vận chuyển hay voucher. Thứ hai, không có con số nào bị đếm hai lần: một sản phẩm không thể vừa nằm trong bảng CTOR vừa được tính lại trong bảng CTR cho cùng một đồng GMV.

## Rõ hay Tham khảo: khi nào chưa nên sửa

Nhãn tin cậy cho biết một dòng có đủ cơ sở hay không.

- **Rõ**: cả hai kỳ có đủ đơn hàng và mức thay đổi nằm ngoài vùng dao động ngẫu nhiên.
- **Tham khảo**: dữ liệu còn ít, hoặc thay đổi chưa vượt khỏi mức nhiễu. Juli gợi ý theo dõi thêm thay vì kết luận.

Với sản phẩm quá ít dữ liệu, Juli ghi là ít dữ liệu và chưa đưa ra chẩn đoán, thay vì đọc một con số chưa đủ chắc.

Một dòng Tham khảo không có nghĩa là sản phẩm ổn. Nó có nghĩa là sửa bây giờ thì sau 14 ngày bạn cũng khó biết thay đổi có tác dụng hay không, vì kết quả sẽ lẫn trong dao động. Trong bảng mẫu, hai sản phẩm Tham khảo ghi "Chưa có đề xuất".

## Sản phẩm bán chạy mất vài phần trăm, sản phẩm nhỏ mất một nửa

Người bán hay để ý sản phẩm có tỷ lệ giảm "đáng sợ" nhất. Nhưng thứ tự trong bảng là theo số đồng, không theo phần trăm. Một ví dụ giả định, cùng AOV 150.000đ:

| | Sản phẩm A (bán chạy) | Sản phẩm B (bán ít) |
|---|---|---|
| Lượt nhấp mỗi ngày | 800 | 60 |
| CTOR trước → nay | 6,0 % → 5,4 % | 6,0 % → 3,0 % |
| Mức giảm tương đối | khoảng 10 % | 50 % |
| Đơn mất mỗi ngày | 800 × 0,6 % = 4,8 | 60 × 3,0 % = 1,8 |
| GMV mất mỗi ngày | khoảng 720.000đ | khoảng 270.000đ |

CTOR của B giảm một nửa, nhưng A lấy đi gần gấp ba số tiền. Vì vậy sản phẩm bán chạy cũng được xét, và thường đứng đầu bảng, dù mức giảm phần trăm trông nhỏ. Ngược lại, một sản phẩm chỉ vài lượt nhấp mỗi ngày có thể chưa đủ dữ liệu để kết luận.

Bạn có thể thử phép tính này với số của chính sản phẩm mình bằng [công cụ tính GMV miễn phí](/cong-cu/tinh-gmv), chạy ngay trên trình duyệt.

## Từ dòng sản phẩm đến thẻ đề xuất

Ở cuối mỗi dòng có một trong hai chữ:

- **Xem đề xuất**: sản phẩm đã có thẻ đề xuất. Bấm vào, bạn sang thẳng trang Quyết định.
- **Chưa có đề xuất**: sản phẩm chưa đủ cơ sở cho một thẻ.

Một sản phẩm nhận thẻ khi qua đủ các điều kiện: có đủ dữ liệu, thay đổi đó hợp lệ với TikTok Shop và với Quy tắc của bạn, sản phẩm không có một thay đổi khác đang được đo, và bạn chưa vừa từ chối hay hoàn tác cùng thay đổi đó.

{{hinh:keo-xuong-the}}

Thẻ của Mặt nạ đất sét 100g nối thẳng với dòng thứ hai của bảng: CTOR (đo trên tất cả các kênh), mục tiêu từ 5,4 % lên 5,9 %. Lý do là mô tả quá ngắn, và TikTok cũng báo "Mô tả quá ngắn", nên thay đổi đề xuất là Mô tả.

Con số **GMV dự kiến** trên thẻ là phần GMV Juli ước tính có thể lấy lại nếu chỉ số đạt mục tiêu, tính từ số liệu hiện tại của chính sản phẩm. Với thẻ nhắm CTR, lượt nhấp tăng thêm chỉ thành GMV khi có người đặt hàng, nên con số còn phụ thuộc CTOR. Mục tiêu được đặt ở mức đủ rõ để đo được và không hứa quá tay. Thẻ ghi rõ đây là ước tính, không phải lời hứa.

Juli đưa lên trước những việc có khả năng mang lại nhiều GMV nhất, và giữ số thẻ mỗi ngày ở mức bạn duyệt kịp. Cách duyệt, xác nhận và những gì Juli làm hay bạn làm được mô tả ở trang [Đề xuất và thực thi](/san-pham/de-xuat-va-thuc-thi).

## Kéo lên: sản phẩm đang đóng góp

Bảng Kéo lên ít được để ý nhưng cũng có ích. Nó cho biết sản phẩm nào đang mang thêm GMV trên cùng chỉ số, ví dụ một sản phẩm có CTOR tăng sau khi bạn bổ sung đánh giá. Ba việc nên làm với nó:

1. **Đừng sửa thứ đang chạy tốt.** Một sản phẩm đang kéo lên không phải ứng viên cho một thay đổi mới trên cùng chỉ số.
2. **Học từ nó.** So trang của sản phẩm đang kéo lên với sản phẩm đang kéo xuống cùng nhóm: ảnh, tiêu đề, mô tả khác nhau ở đâu.
3. **Kiểm tra nguyên nhân bên ngoài.** Nếu một sản phẩm kéo lên mạnh trùng với một đợt khuyến mãi hay một ngày sale, mức tăng có thể tụt lại sau đợt đó.

## Sau khi đã biết sản phẩm nào

Bảng chỉ ra sản phẩm và chỉ số. Việc tiếp theo tuỳ chỉ số:

- **CTR thấp trên Thẻ sản phẩm** (người mua thấy mà không bấm): Juli đề xuất đổi tiêu đề hoặc ảnh bìa. Xem bài [CTR Thẻ sản phẩm thấp](/blog/ctr-the-san-pham-thap-doi-tieu-de-anh-bia).
- **CTOR thấp** (người mua bấm vào mà không đặt): Juli tách tiếp trước hay sau giỏ hàng, rồi đề xuất mô tả hoặc hướng dẫn khuyến mãi. Xem bài [CTOR thấp: viết lại mô tả](/blog/ctor-thap-viet-lai-mo-ta-san-pham).
- **Lượt hiển thị giảm**: thường do phân phối và mùa vụ; Juli vẫn hiển thị phần GMV do nó gây ra, để bạn biết mức giảm nằm ở đâu.

Sau khi một thay đổi được áp dụng, Juli đo nó ở ngày 7 và chốt ở ngày 14 so với mốc 14 ngày trước khi áp dụng, cách đo ở trang [Đo lường GMV](/san-pham/do-luong-gmv). Định nghĩa từng chỉ số có ở bài [các chỉ số TikTok Shop](/blog/chi-so-tiktok-shop-ctr-ctor-aov).

Muốn xem bảng này với số liệu của shop mình? Kết nối shop theo hướng dẫn ở trang [Kết nối TikTok Shop](/ket-noi/tiktok-shop), hoặc xem [Tổng quan sản phẩm](/san-pham) trước. Tài khoản mới được [dùng thử miễn phí 3 tháng](/dang-ky).
`;
