/**
 * Pain post (D56, P46-E, week 4 #13): "Sửa sản phẩm xong, làm sao biết có
 * hiệu quả". Main keyword "đo hiệu quả sau khi sửa sản phẩm" (plan keyword;
 * Google autocomplete VN 2026-10-18 empty for it and every variant, kept as a
 * demand-creating long tail; "sửa sản phẩm tiktok shop" and "tối ưu sản phẩm
 * tiktok shop" have suggestions and stay with other pages). The method is
 * Juli's, as `/san-pham/do-luong-gmv` and DECISIONS D14 / D29 / D30 / D31.7 /
 * D34 describe it: a 14-day baseline frozen when the change goes live, per-day
 * averages, one target metric on the lever's channel, guard bands, day 7
 * "Đang lên / Chưa rõ", day 14 "Đạt / Đạt · chưa chắc chắn / Một phần / Không
 * đạt", change strength against the combined band (≥ 2 × rõ, 1 to 2 × có thể,
 * < 1 × trong dao động), "Bị ảnh hưởng bởi thay đổi khác" for seller-made
 * changes, the delayed-control group still experimental. Juli does NOT detect
 * or exclude platform sale days (nothing in SPEC / D30 does); the post says the
 * seller marks them. No uplift figure is quoted (none exists; the "+30 % /
 * +25 %" SEO claims seen in the SERP are not used). Campaign dates from the
 * TikTok Academy page "Lịch Chiến Dịch TikTok Shop 2026" (16/10/2026), image
 * re-read 2026-10-18. Shop-wide period comparison stays with
 * `doanh-thu-tiktok-shop-giam` (one sentence + link).
 */
export const body = `

Sửa xong một sản phẩm rồi so số hôm nay với hôm qua gần như luôn cho kết luận sai, vì số liệu trên TikTok Shop tự lên xuống theo ngày trong tuần, theo ngày lương và theo các đợt sale. Muốn biết thay đổi có hiệu quả không, hãy ghi lại ngày sửa, chốt mốc 14 ngày trước khi sửa, chỉ theo dõi một chỉ số mục tiêu, đọc sơ bộ ở ngày 7 và chỉ kết luận ở ngày 14, khi mức thay đổi đã được đặt cạnh mức dao động bình thường của sản phẩm. Bài này đi qua từng bước, kèm một bảng theo dõi tự làm bằng bảng tính, và cách Juli AI đo cùng việc đó.

Đây là bài về cách đo, không phải bài về nên sửa gì. Muốn biết vì sao doanh thu của cả shop giảm, xem bài [doanh thu TikTok Shop giảm](/blog/doanh-thu-tiktok-shop-giam), nơi chỉ cách so hai kỳ của toàn shop. Mọi con số trong các ví dụ là ví dụ giả định.

| | Bài doanh thu giảm | Bài này |
|---|---|---|
| Đơn vị | Cả shop, hai kỳ bất kỳ | Một sản phẩm, một thay đổi có ngày |
| Câu hỏi | Giảm ở đâu: luồng, sản phẩm, chỉ số | Thay đổi có tác dụng không |
| Mốc so sánh | Hai kỳ dài bằng nhau | Mốc 14 ngày chốt tại ngày sửa, đọc ở ngày 7 và ngày 14 |
| Kết luận | Khoanh vùng nguyên nhân | Đạt, Đạt · chưa chắc chắn, Một phần hoặc Không đạt |

## Vì sao “sửa xong thấy đơn tăng” chưa chứng minh được gì

“Mình mới sửa tiêu đề hôm qua, hôm nay lên ba đơn, vậy là có hiệu quả chưa?” Chưa, vì ba lý do:

- **Số liệu theo ngày dao động mạnh.** Cuối tuần, ngày lương, một video nhắc đến sản phẩm, một đợt sale đều làm số đơn đổi trong vài ngày, dù bạn không sửa gì.
- **Hồi lại sau một đợt giảm.** Người bán thường sửa đúng lúc sản phẩm vừa bán kém, và nhiều chỉ số tự hồi lại phần nào. Chỉ so trước và sau thì phần hồi tự nhiên dễ bị tính là tác dụng của việc sửa.
- **Số đơn ít thì may rủi lớn.** Sản phẩm bán 3 đến 5 đơn mỗi ngày có thể có ngày 2 đơn, ngày 7 đơn mà không có gì thay đổi.

{{hinh:do-doc-sai-doc-dung}}

So hai ngày lẻ thì thấy “tăng gấp đôi”. So trung bình 14 ngày trước với 14 ngày sau thì mức tăng là 0,8 đơn mỗi ngày, chỉ gấp khoảng 1,5 lần mức dao động: có thể đã có tác dụng, nhưng chưa đủ chắc.

## Trước khi sửa: ghi ngày và chốt mốc 14 ngày

Việc đo bắt đầu trước khi bạn bấm lưu. Ghi lại ngay trong ngày sửa:

1. **Ngày giờ thay đổi lên shop**, và thay đổi đó là gì (bản cũ, bản mới).
2. **Trung bình mỗi ngày của 14 ngày trước đó**: Lượt hiển thị sản phẩm, CTR, CTOR, Đơn hàng SKU, AOV, GMV.
3. **Giá và khuyến mãi đang chạy**, vì một khuyến mãi bật hay tắt trong lúc đo sẽ làm lệch kết quả.
4. **Nội dung trang lúc đó**, để còn quay về bản cũ nếu cần.

Mốc chốt cố định từ ngày sửa; đừng “cập nhật” nó khi số liệu mới về. 14 ngày là hai tuần trọn vẹn, chứa đủ cuối tuần và ngày thường hai lần; 30 ngày thì dễ chứa cả một đợt sale.

Số liệu theo sản phẩm có trong Trung tâm Nhà bán hàng: theo bài “Lưu lượng truy cập sản phẩm” của Học viện TikTok Shop (cập nhật 17/06/2026), Lượt hiển thị, CTR, CTOR và GMV được tính trong khoảng thời gian bạn chọn, theo từng định dạng nội dung. Bài “Trình Tối Ưu Hoá Sản Phẩm” (04/08/2025) cho thấy công cụ của TikTok hiện hiệu suất trước đây của sản phẩm (số đơn, lượt xem) cùng các điểm cần cải thiện, nhưng không nêu mức tăng sau khi tối ưu. Việc đo sau khi sửa là của bạn.

{{hinh:do-lich-14-ngay}}

## Chọn một chỉ số mục tiêu, trên đúng luồng

Mỗi thay đổi nhắm vào một bước của phễu Lượt hiển thị × CTR × CTOR × AOV (xem bài [các chỉ số TikTok Shop](/blog/chi-so-tiktok-shop-ctr-ctor-aov)):

- **[Tiêu đề](/blog/dat-ten-san-pham-tiktok-shop), [ảnh bìa](/blog/anh-bia-san-pham-tiktok-shop)** được thấy trước khi bấm: mục tiêu là CTR, và Lượt hiển thị nếu tiêu đề thêm từ khóa.
- **Mô tả, bộ ảnh chi tiết, giá** được thấy sau khi bấm: mục tiêu là CTOR (bài [khách xem nhưng không mua](/blog/khach-xem-nhung-khong-mua-tiktok-shop)).
- **Mua nhiều giảm nhiều, gói sản phẩm**: mục tiêu là AOV (bài [tăng giá trị đơn hàng trung bình](/blog/tang-gia-tri-don-hang-trung-binh-tiktok-shop)).

Tiêu đề, ảnh bìa và [mô tả](/blog/mo-ta-san-pham-tiktok-shop) chủ yếu được thấy trên Thẻ sản phẩm, nên đo chúng trên luồng Thẻ sản phẩm, không gộp với khách từ video hay LIVE.

“Mình đổi cả ảnh, tiêu đề, giá cùng lúc, giờ không biết cái nào có tác dụng.” Không tách ra được nữa. Một sản phẩm chỉ nên có một chỉ số mục tiêu tại một thời điểm: ảnh bìa và tiêu đề cùng nhắm CTR vẫn đọc được như một gói, nhưng đổi tiêu đề cùng lúc giảm giá thì không biết phần nào của thay đổi nào.

### Các chỉ số còn lại phải giữ ổn định

“Sửa xong lượt xem tăng nhưng đơn không tăng.” Một tiêu đề mới có thể kéo CTR lên nhưng đưa đến những người không định mua, làm CTOR giảm; một tiêu đề gọn hơn có thể mất từ khóa, làm Lượt hiển thị giảm. Vì vậy mỗi chỉ số không phải mục tiêu cần một khoảng được phép dao động: xem trung bình mỗi ngày của nó qua vài khoảng 14 ngày gần đây, khoảng chênh thường gặp là mức dao động bình thường. Ra ngoài khoảng đó là tín hiệu cần xem lại, kể cả khi chỉ số mục tiêu đang lên; GMV cũng không được giảm quá mức dao động của nó.

{{hinh:do-muc-tieu-du-lieu-mau}}

## Ngày 7: kiểm tra giữa chừng, chưa kết luận

“Mấy ngày đầu lên rồi tụt lại, tin được không?” Bảy ngày thường chưa đủ để tách tác động khỏi dao động. Ở ngày 7, so trung bình 7 ngày sau khi sửa với mốc, và chỉ trả lời hai câu:

- **Chỉ số mục tiêu đang lên hay chưa rõ?** Ghi “Đang lên” hoặc “Chưa rõ”, không ghi “thất bại”.
- **Có chỉ số nào ra ngoài ngưỡng không?** Nếu có, đây là lúc cân nhắc quay lại bản cũ, vì chờ thêm có thể mất đơn thật. Nếu vẫn giữ, ghi chú lại để nhớ khi đọc ngày 14.

Sản phẩm dao động mạnh thì chỉ đánh giá ở ngày 14.

## Ngày 14: đặt kết quả cạnh mức dao động

So trung bình 14 ngày sau khi sửa với mốc. Mức thay đổi chỉ có nghĩa khi đặt cạnh mức dao động bình thường của chỉ số, tính trên cả hai khoảng. Quy tắc Juli dùng, bạn áp dụng tay được: lớn hơn **hai lần** mức dao động là thay đổi rõ; từ **một đến hai lần** là có thể đã thay đổi; **dưới một lần** là vẫn trong dao động.

Rồi gắn một trong bốn nhãn: **Đạt** khi chỉ số mục tiêu tăng rõ, chạm mục tiêu và GMV giữ được; **Đạt · chưa chắc chắn** khi chạm mục tiêu nhưng mức tăng chỉ gấp một đến hai lần dao động; **Một phần** khi chỉ tăng rõ hoặc chỉ chạm mục tiêu; **Không đạt** khi không có cả hai. Một kết quả yếu không bao giờ được gắn nhãn mạnh hơn.

{{hinh:do-ba-ket-qua}}

Rõ ràng không có nghĩa là do bạn: kết quả chỉ được tính cho lần sửa khi trong 14 ngày đó không có thay đổi nào khác trên sản phẩm và các chỉ số còn lại vẫn trong ngưỡng.

### Khi nào nói “chưa đủ để kết luận”

“Shop mình ít đơn, bao nhiêu đơn thì đủ?” TikTok không đưa ra con số. Juli dùng quy tắc: một mức thay đổi được gắn nhãn **Rõ** khi cả hai kỳ có khoảng 30 đơn trở lên (khoảng 30 lượt nhấp với CTR) và khoảng tin cậy không chứa 0, còn lại là **Tham khảo**. Sản phẩm bán dưới khoảng 2 đơn mỗi ngày thì 14 ngày chưa có 30 đơn, nên kết quả chỉ để tham khảo. Đó là chưa có câu trả lời, không phải thất bại: đừng sửa tiếp chỉ vì “chưa thấy gì”.

## Những thứ làm hỏng phép đo

Ghi lại mọi thứ sau đây nếu nó xảy ra trong 28 ngày quanh ngày sửa: bạn tự sửa thêm (giá, tiêu đề, khuyến mãi, biến thể); biến thể bán chạy hết hàng, dù chỉ một hai ngày; một video hay buổi LIVE bất thường nhắc đến sản phẩm; và một đợt sale của nền tảng.

### Đợt sale rơi vào cửa sổ đo

Sale làm lệch mạnh nhất. Mốc chứa ngày sale thì mốc bị đẩy lên, thay đổi trông như thất bại; thời gian đo chứa ngày sale thì thay đổi trông như thành công.

{{hinh:do-cua-so-sale}}

Theo bài “Lịch Chiến Dịch TikTok Shop 2026” của Học viện TikTok Shop (đăng 16/10/2026), các mốc cuối năm 2026 là:

| Tháng | Chiến dịch | Thời gian |
|---|---|---|
| 10 | TikTok Shop 10.10 | 07 đến 10/10 |
| 10 | Giữa tháng | 13 đến 15/10 |
| 10, 11, 12 | Lương về | 24 đến 25 hằng tháng |
| 11 | TikTok Shop 11.11 | 03 đến 15/11 |
| 11 | Black Friday | 26 đến 27/11 |
| 12 | TikTok Shop 12.12 | 03 đến 15/12 |

Tính thử: sửa vào khoảng 20/10 thì ngày 14 rơi đúng 03/11, ngày đầu của 11.11. Sửa trong đợt thì cả thời gian đo nằm trong sale. Sửa ngay sau 15/11 thì mốc lại chứa đợt sale, còn thời gian đo chứa Black Friday và chạm 12.12. Từ cuối tháng 10 đến giữa tháng 12 năm nay gần như không có khoảng 28 ngày nào sạch. Nếu lần sửa chỉ để thử và chờ được, để nó sang sau 12.12; nếu phải sửa ngay, ghi rõ đợt sale và so thêm với các sản phẩm không sửa, vì chúng chịu cùng đợt sale. Cách đọc số liệu quanh một đợt sale có trong bài [trước và sau 11.11](/blog/doanh-thu-sau-sale-tiktok-shop).

## So với sản phẩm không sửa

“Có cách nào so với sản phẩm mình không sửa không?” Có, và đây là cách chắc hơn trước và sau. Chọn 2 đến 3 sản phẩm tương tự (cùng nhóm hàng, cùng mức bán, cùng luồng chính) mà bạn không sửa, tính mức thay đổi của chúng trong đúng 28 ngày đó. Sản phẩm bạn sửa tăng CTR 20 % mà các sản phẩm không sửa cũng tăng 15 % thì phần có thể là của lần sửa chỉ khoảng 5 %; phần còn lại là cả shop cùng lên.

Cách làm tay này chưa loại hết may rủi vì bạn tự chọn sản phẩm đối chứng; chắc hơn là chọn ngẫu nhiên, như Juli đang thử nghiệm.

## Bảng theo dõi tự làm

Một dòng cho mỗi thay đổi, mỗi sản phẩm. Ví dụ giả định:

| Cột | Ví dụ |
|---|---|
| Sản phẩm, ngày thay đổi lên shop | Áo thun basic trắng, ngày sửa của bạn |
| Thay đổi | Tiêu đề: thêm chất liệu và kích cỡ |
| Chỉ số mục tiêu, luồng | CTR, Thẻ sản phẩm |
| Mốc 14 ngày (trung bình mỗi ngày) | CTR 2,1 %, 9.500 lượt hiển thị, 6 đơn |
| Ngưỡng giữ ổn định | Lượt hiển thị 9.000 đến 10.000, CTOR không giảm quá mức dao động |
| Ngày 7 | Đang lên hoặc Chưa rõ, chỉ số nào ra ngoài ngưỡng |
| Ngày 14 | CTR 2,5 %, mức tăng so với dao động, nhãn |
| Sản phẩm không sửa | Mức thay đổi trung bình của 2 đến 3 sản phẩm tương tự |
| Thay đổi khác trong 28 ngày | Sale, hết hàng, video, khuyến mãi |

## Juli AI đo một thay đổi như thế nào

Juli AI là trợ lý AI vận hành TMĐT cho nhà bán, hiện kết nối TikTok Shop (Shopee đang tích hợp). Với các thay đổi đi qua Juli, những bước trên được làm tự động:

- **Ngày thay đổi lấy từ lúc áp dụng.** Tiêu đề, mô tả và ảnh bìa chỉ được ghi lên shop sau khi bạn duyệt và xác nhận ([đề xuất và thực thi](/san-pham/de-xuat-va-thuc-thi)); giá và khuyến mãi bạn tự làm trên Seller Center rồi bấm “Đã áp dụng”. Lịch đo ngày 7, ngày 14 được đặt ngay lúc đó.
- **Mốc được chụp lại lúc áp dụng**: 14 ngày số liệu, giá, khuyến mãi, nội dung trang và GMV dự kiến tính lúc đề xuất. Một chỉ số mục tiêu trên đúng luồng, ngưỡng giữ ổn định cho các chỉ số còn lại, nhãn kết quả như trên ([đo lường GMV sau mỗi thay đổi](/san-pham/do-luong-gmv)). Ở ngày 7, nếu một chỉ số ra ngoài ngưỡng, Juli hỏi bạn có muốn hoàn tác không; Juli không tự hoàn tác.
- **Thay đổi bên ngoài được ghi chú.** Bạn tự sửa tiêu đề, đổi giá hay mở, tắt một khuyến mãi trong thời gian đo thì kết quả ghi “Bị ảnh hưởng bởi thay đổi khác” kèm ngày. Juli không tự nhận ra hay loại ngày sale của nền tảng khỏi phép đo, nên bạn vẫn nên tránh đo qua 03 đến 15/11.
- **Nhóm đối chứng đang thử nghiệm**: chọn ngẫu nhiên khoảng một phần ba sản phẩm trong một nhóm thẻ cùng loại nhận thẻ muộn 14 ngày; kết quả nhóm chỉ hiện khi có ít nhất 3 sản phẩm đổi và 2 đối chứng, ghi “Sơ bộ” khi nhóm còn nhỏ.

{{hinh:do-ngay-14-du-lieu-mau}}

Juli chưa công bố mức hiệu quả trung bình của loại thay đổi nào, vì chưa có loại nào đủ kết quả đo nhất quán giữa các shop. Điều Juli làm là ghi rõ mức chắc chắn của từng kết quả. Phễu theo luồng có ở trang [phân tích shop](/san-pham/phan-tich-shop); tổng quan ở [sản phẩm Juli AI](/san-pham), dữ liệu đọc qua [kết nối chính thức với TikTok Shop](/ket-noi/tiktok-shop). Chưa biết sửa gì trước: xem [tối ưu thẻ sản phẩm](/blog/toi-uu-the-san-pham-tiktok-shop), [không có lượt hiển thị](/blog/san-pham-tiktok-shop-khong-co-luot-hien-thi), [không ra đơn](/blog/tiktok-shop-khong-ra-don) và [GMV là gì](/blog/gmv-la-gi-tiktok-shop).

## Những điểm chính

- Ghi ngày sửa, chốt mốc 14 ngày bằng trung bình mỗi ngày; một chỉ số mục tiêu trên đúng luồng, các chỉ số còn lại trong ngưỡng.
- Ngày 7 chỉ là kiểm tra; ngày 14 mới kết luận, và mức thay đổi phải lớn hơn mức dao động.
- Tránh để đợt sale, hết hàng hay một lần sửa khác rơi vào 28 ngày quanh ngày sửa; nếu có, ghi lại và so với sản phẩm không sửa.
- Ít đơn thì kết quả chỉ là tham khảo; “chưa đủ để kết luận” là một câu trả lời hợp lệ.

Nếu bạn muốn mốc, lịch đo và nhãn tin cậy được ghi tự động cho từng thay đổi thay vì tự giữ bảng tính, bạn có thể [đăng ký dùng thử Juli AI](/dang-ky) và kết nối shop khi sẵn sàng.
`;
