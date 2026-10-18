/**
 * Pain post (D56, P46-C2): "Đơn huỷ, hoàn hàng tăng". Main keyword "tỷ lệ hoàn
 * hàng tiktok shop" (Google autocomplete VN 2026-10-17 suggests only "tỷ lệ trả
 * hàng hoàn tiền tiktok shop"; "hoàn hàng tiktok shop" has 10 suggestions incl.
 * "có mất phí không", "phí hoàn hàng"; "tỷ lệ hủy đơn tiktok shop" exists).
 * Policy facts only from Học viện TikTok Shop pages, Vietnamese versions, re-read
 * 2026-10-17: "Chính sách hủy đơn hàng, trả hàng và hoàn tiền" (23/09/2026), "Hủy
 * đơn hàng" (22/09/2026), "Trả hàng và Hoàn tiền" (15/10/2026), "Quản lý yêu cầu
 * trả hàng và hoàn tiền" (04/11/2025), SFCR (16/07/2026), SFRR (19/08/2026), fee
 * pages (Phí Xử Lý Đơn Hàng 11/10/2025, Phí Giao Dịch 13/10/2026, Phí Vận Hành
 * Logistic 08/10/2026, Phí của Nhà Bán Hàng 04/08/2026), "Lưu lượng truy cập sản
 * phẩm" (17/06/2026, GMV incl. cancelled / refunded). Resolved: review window is
 * "1 ngày theo lịch" (15/10/2026 and 04/11/2025 pages; the 2024 FAQ said working
 * day). Left out: the SFCR order-limit (OVL) tier thresholds, which differ between
 * the Vietnamese page and the English multi-country page. Reach tier (D59): no
 * Juli; the weekly sheet uses only the Seller Center data named above.
 */
export const body = `
Khi đơn hủy và hoàn hàng tăng, việc đầu tiên là tách ra ba chuyện khác nhau: đơn bị hủy trước khi giao, đơn giao không thành công rồi quay về shop, và đơn khách đã nhận rồi yêu cầu trả hàng, hoàn tiền. TikTok Shop theo dõi mỗi loại bằng một chỉ số riêng, với hạn xử lý và chi phí riêng, nên gộp chung thành "tỷ lệ hoàn hàng" sẽ không chỉ ra được phải sửa gì. Tách xong, bạn mới biết shop đang tăng ở loại nào, ở sản phẩm nào, và phần nào nằm trong tay mình.

> **Cập nhật ngày 17/10/2026.** Các mốc, tỷ lệ và mức phí trong bài lấy từ các trang Học viện TikTok Shop bản tiếng Việt, ghi kèm ngày cập nhật của từng trang. Chính sách có thể thay đổi: trước khi quyết định, hãy kiểm tra lại trên trang gốc và trong Trung tâm nhà bán hàng.

## Hoàn hàng nghĩa là gì: ba loại đơn không thành tiền

Người bán hay gọi chung là "hoàn hàng", nhưng trên TikTok Shop đó là ba trường hợp:

| Loại | Xảy ra khi | Chỉ số liên quan | Hàng có quay về shop không |
|---|---|---|---|
| Hủy đơn | Trước khi đơn ở trạng thái đang vận chuyển | Tỷ lệ hủy do lỗi của người bán (SFCR), nếu lỗi ở người bán | Không, hàng chưa rời shop |
| Giao không thành công | Đơn bị hủy khi đang vận chuyển, hoặc khách COD từ chối nhận | Không có chỉ số riêng trong các trang đã dẫn | Có, đơn vị vận chuyển trả về |
| Trả hàng, hoàn tiền | Sau khi đơn đã giao, khách gửi yêu cầu | Tỷ lệ trả hàng/hoàn tiền do lỗi của người bán (SFRR), nếu lý do liên quan người bán | Tùy yêu cầu: trả hàng hoặc chỉ hoàn tiền |

{{hinh:ba-loai-hoan-hang}}

## Hủy đơn TikTok Shop có sao không: tùy ai hủy

Theo "Chính sách hủy đơn hàng, trả hàng và hoàn tiền của khách hàng trên TikTok Shop" (cập nhật 23/09/2026), người bán, khách hàng hoặc nền tảng đều có thể hủy đơn, và hậu quả khác nhau:

- **Người bán hủy**: được hủy bất kỳ lúc nào trước khi đơn ở trạng thái "Đã vận chuyển - Đang vận chuyển", nhưng việc hủy được tính vào SFCR. Người bán **không được yêu cầu khách hủy đơn**. Khi buộc phải hủy, bài "Hủy đơn hàng" (cập nhật 22/09/2026) yêu cầu báo khách qua tin nhắn, nêu lý do và hoàn toàn bộ tiền đơn.
- **Khách hủy**: hầu hết đơn hủy được trước khi đang vận chuyển. Việc này không gây hậu quả cho người bán, trừ khi khách chọn lý do "Giao hàng trễ".
- **Nền tảng hủy**: khi thanh toán thất bại, có hoạt động đáng ngờ (kể cả "tần suất hủy đơn hàng cao"), người bán gửi hàng trễ quá hạn (tự động hủy), hoặc kho vận báo mất, hư hỏng (người bán được bồi hoàn).

### Tỷ lệ hủy đơn TikTok Shop (SFCR) tính thế nào

Trang "Tỷ lệ hủy do lỗi của người bán (SFCR)" (cập nhật 16/07/2026) định nghĩa SFCR là phần trăm tất cả đơn trong 7 ngày theo lịch bị người bán hủy hoặc bị hủy do lỗi người bán. Gồm hai nhóm: người bán tự hủy vì lỗi của mình (hết hàng, niêm yết sai giá) và đơn bị tự động hủy vì không chuẩn bị, bàn giao hàng kịp thời hạn của nền tảng. Mục tiêu là **dưới 2,5%**.

Ví dụ trên trang: 100 đơn, 20 đơn hủy do lỗi người bán, 5 đơn tự động hủy, SFCR là 25%. Xem SFCR ở mục Tình trạng cửa hàng.

Khi SFCR cao, nền tảng có thể áp Giới hạn số đơn hàng (OVL), mức giới hạn tăng theo SFCR, và trừ điểm tình trạng tài khoản (AHR): SFCR từ 10% bị trừ 5 điểm, từ 10% kèm từ 30 đơn hủy do lỗi người bán bị trừ 10 điểm. Bảng bậc OVL xem trên trang gốc.

## Giao không thành công: hàng quay về shop

Đây là nghĩa "hoàn hàng" mà nhiều người bán COD gặp nhất. Theo bài "Hủy đơn hàng" (22/09/2026):

- **Đơn bị hủy sau khi đã giao cho đơn vị vận chuyển** được đơn vị vận chuyển trả lại cho người bán, và **người bán chịu phí vận chuyển trả hàng** của đơn hủy khi đang vận chuyển (giao hàng không thành công).
- **Khách COD từ chối nhận** (người bán dùng J&T, chính sách đang thử nghiệm): khách được mở bao bì ngoài để kiểm tra rồi từ chối; đơn hiện là "Giao hàng không thành công" và quay về đã mở bao bì. Đơn trên 500.000 VND và thực phẩm tươi sống, đông lạnh không được mở.

Trang khuyên loại đơn đã hủy ra trước khi đơn vị vận chuyển lấy hàng và giữ bằng chứng bàn giao mỗi ngày; kiện quay về bị hỏng, thất lạc thì kháng nghị ở mục Quản lý đơn hàng.

## Tỷ lệ trả hàng hoàn tiền TikTok Shop (SFRR)

Theo trang "Tỷ lệ trả hàng/hoàn tiền do lỗi của người bán" (cập nhật 19/08/2026), SFRR là phần trăm trên tổng số đơn trong 30 ngày gần nhất theo lịch bị khách hoàn trả với lý do liên quan đến người bán. Mục tiêu là **dưới 1,5%**. Vượt mục tiêu thì không có biện pháp xử lý trực tiếp, nhưng có thể ảnh hưởng đến điểm Xếp hạng cửa hàng và quyền dùng marketing liên kết.

Không phải đơn trả nào cũng tính vào SFRR. Trang "Trả hàng và Hoàn tiền" (cập nhật 15/10/2026) ghi rõ lý do nào có ảnh hưởng:

| Lý do khách chọn | Tính vào SFRR |
|---|---|
| Đổi ý; sản phẩm quá lớn hoặc quá nhỏ; đặt sai kích thước | Không |
| Thiếu sản phẩm; sản phẩm không đúng mô tả; hư, thối, mốc; lỗi hoặc không hoạt động; gửi sai sản phẩm; nghi ngờ hàng giả | Có |
| Kiện hàng hoặc sản phẩm hư hỏng; không nhận được kiện hàng | Có thể, trừ khi do đơn vị kho vận |

Trang SFRR cũng không tính: yêu cầu bị khách hủy, khách không gửi hàng về trong hạn, và yêu cầu người bán thắng khi phân xử. Nếu bạn đề nghị hoàn tiền một phần và khách chấp nhận, đơn đó không tính vào SFRR. Xem SFRR ở Tình trạng tài khoản, Xếp hạng cửa hàng, phần Sự hài lòng về sản phẩm; mục Chi tiết cho thấy lý do và sản phẩm dẫn đầu.

## Hạn xử lý yêu cầu trả hàng: 1 ngày theo lịch

Bảng thời gian trên trang "Trả hàng và Hoàn tiền" (15/10/2026):

1. **Khách gửi yêu cầu** sau khi đơn ở trạng thái đã giao: trong 15 ngày theo lịch, hoặc 6 ngày với một số danh mục (Mẹ & Bé, Thực phẩm & Đồ uống, Điện thoại & Điện tử, Cải thiện nhà cửa).
2. **Người bán xem xét yêu cầu trong 1 ngày theo lịch**: duyệt, từ chối kèm bằng chứng hợp lệ, hoặc đề nghị hoàn một phần. Quá hạn thì yêu cầu được tự động duyệt.
3. **Người bán xem hàng trả về**: trong 2 ngày theo lịch sau khi nhận (lấy hàng, gửi bưu cục); với trả hàng tự sắp xếp là 14 ngày sau khi khách tải thông tin vận chuyển hoặc 2 ngày sau khi hàng trả được giao, tùy điều kiện nào đến trước. Quá hạn cũng tự động duyệt.
4. **Khiếu nại**: 7 ngày với yêu cầu chỉ hoàn tiền hoặc sau khi nhận hàng trả (lấy hàng, bưu cục); 15 ngày với trả hàng tự sắp xếp.

{{hinh:dong-thoi-gian-tra-hang}}

Một bài hỏi đáp cũ (2024) ghi "1 ngày làm việc", nhưng bài mới nhất và bài "Quản lý yêu cầu trả hàng và hoàn tiền" (04/11/2025) đều ghi ngày theo lịch: hãy tính cả cuối tuần.

Nếu trong 1 tháng hơn 90% yêu cầu không được xem đúng hạn, "Công cụ phê duyệt tự động" có thể được bật: tự duyệt yêu cầu dưới 790.000 VND (trừ lý do "Nghi ngờ hàng giả"), tối đa 3 lần mỗi khách mỗi tháng, trong ít nhất 15 ngày.

## Ai trả tiền ship khi trả hàng

Chính sách hủy, trả, hoàn (23/09/2026) chia theo bên có lỗi, và TikTok là bên quyết định lỗi thuộc về ai dựa trên bằng chứng các bên gửi:

- **Lỗi người bán** (gửi sai, hàng giả, thiếu bộ phận, sản phẩm lỗi, hư hỏng do đóng gói kém, **không khớp mô tả trong bài niêm yết**): người bán chịu phí trả hàng.
- **Khách đổi ý**: phí vận chuyển trả hàng do nền tảng chi trả; phí chiều đi người bán trả, tối đa 40.000₫ mỗi đơn không giao hỏa tốc và 20.000₫ mỗi đơn giao hỏa tốc, phần vượt do nền tảng trả.
- **Lỗi kho vận** (ví dụ kiện hỏng khi vận chuyển): đơn vị kho vận chịu phí trả hàng, và hoa hồng nền tảng liên quan được hoàn lại cho người bán khi áp dụng.
- **Giao không thành công**: như ở trên, người bán chịu phí chuyển hoàn của đơn hủy khi đang vận chuyển.

{{hinh:ai-tra-phi-ship}}

Từ chối trả hàng vô lý, như tự đặt điều kiện "Đổi ý" ngoài danh sách của nền tảng, có thể bị thực thi, kể cả bồi thường cho người mua.

## Hoàn hàng TikTok Shop có mất phí không

Có, tùy loại. Các trang phí của Học viện ghi:

- **Phí xử lý đơn hàng 3.000 đồng** (trang cập nhật 11/10/2025): chỉ thu khi đơn giao thành công. Đơn đã giao rồi mới trả hàng, hoàn tiền thì **vẫn thu, không hoàn lại**. Đơn chưa giao thành công mà bị hủy, hoàn toàn bộ thì không thu.
- **Phí giao dịch** (13/10/2026): công thức trừ "Phần hoàn tiền" khỏi cơ sở tính, nên phần đã hoàn cho khách không bị tính phí giao dịch.
- **Phí vận hành logistic** (08/10/2026), chỉ cho kiện trên 10 kg từ đơn đặt sau 00:00 ngày 12/10/2026: giao thành công rồi khách trả hàng thì không hoàn; giao không thành công thì không tính.
- **Phí vận chuyển trả hàng thực tế** (trang "Phí của Nhà Bán Hàng", 04/08/2026): tính khi người bán là bên chịu trách nhiệm trả hàng.

Ngoài bảng phí còn hàng trả về không bán lại được và thời gian xử lý. Với thuế, theo Nghị định 252/2026/NĐ-CP, thuế sàn đã khấu trừ của đơn hủy, trả hàng được bù trừ; xem bài [Thuế bán hàng TikTok Shop 2026](/blog/thue-ban-hang-tiktok-shop).

Ví dụ giả định dưới đây đặt hai đơn trả cùng giá cạnh nhau: chi phí ngoài tiền hàng có thể giống nhau, nhưng chỉ đơn lỗi người bán làm tăng SFRR.

{{hinh:chi-phi-mot-don-hoan}}

Toàn bộ khung phí hiện hành và một ví dụ tính lợi nhuận mỗi đơn có trong bài [Phí sàn TikTok Shop 2026](/blog/phi-san-tiktok-shop-2026).

## Đơn hủy, hoàn có thật sự tăng không

Không có trang chính thức nào công bố tỷ lệ hủy hay hoàn "bình thường" của ngành; mốc duy nhất là mục tiêu của chính TikTok: SFCR dưới 2,5%, SFRR dưới 1,5%. Vì vậy "tăng" chỉ có nghĩa khi so shop với chính nó:

- **So hai kỳ dài bằng nhau**, từng loại riêng: gộp chung dễ che mất loại đang tăng.
- **Nhớ hoàn tiền đến muộn.** Theo trang "Lưu lượng truy cập sản phẩm" (17/06/2026), khoản hoàn tiền được ghi vào lúc yêu cầu được xử lý, không phải ngày mua. Tuần gần nhất vì vậy thường trông ít hoàn hơn thực tế.
- **Đọc theo sản phẩm và lý do.** Mục Chi tiết của SFRR cho thấy lý do và sản phẩm đứng đầu. Nếu một sản phẩm chiếm phần lớn đơn trả, và lý do là "không đúng mô tả" hay sai kích thước, chỗ cần sửa nằm ở trang sản phẩm đó.
- **Đọc cạnh GMV.** GMV trong La bàn dữ liệu tính cả đơn đã hủy và hoàn tiền, nên khi hủy, hoàn tăng, GMV có thể đứng yên trong khi tiền về giảm. Bài [GMV là gì](/blog/gmv-la-gi-tiktok-shop) giải thích khoảng cách này, và bài [Doanh thu TikTok Shop giảm](/blog/doanh-thu-tiktok-shop-giam) có cách so hai kỳ cho công bằng.

## Giảm tỷ lệ hoàn hàng TikTok Shop: việc nên làm trước

1. **Đơn hủy**: đồng bộ tồn kho từng biến thể và kiểm tra giá trước khi chạy ưu đãi; bàn giao đúng hạn để tránh tự động hủy.
2. **Giao không thành công**: loại đơn đã hủy trước khi giao cho đơn vị vận chuyển, giữ bằng chứng bàn giao.
3. **Trả hàng do lỗi người bán**: quay video đóng gói (đây cũng là bằng chứng khi khiếu nại), kiểm tra hàng trước khi gửi, và sửa mô tả, ảnh, kích thước cho đúng sản phẩm thật.
4. **Hạn xử lý**: có người xem yêu cầu trả hàng mỗi ngày, kể cả cuối tuần. Khi hợp lý, đề nghị hoàn một phần và có sự đồng ý của khách.
5. **Một thay đổi, rồi đo.** Sửa mô tả một sản phẩm, ghi ngày bắt đầu, đọc lại sau 7 và 14 ngày. SFRR tính trên 30 ngày nên kết quả hiện chậm.

Trang sản phẩm thiếu thông tin cũng làm khách nhấp vào mà không mua, xem bài [TikTok Shop không ra đơn](/blog/tiktok-shop-khong-ra-don); sản phẩm ít người thấy thì xem bài [Sản phẩm TikTok Shop không có lượt hiển thị](/blog/san-pham-tiktok-shop-khong-co-luot-hien-thi).

## Bảng theo dõi hủy và hoàn mỗi tuần

Ba loại đơn ở đầu bài chỉ tách được nếu bạn ghi chúng riêng. Một bảng tính cập nhật mỗi tuần từ Trung tâm nhà bán hàng là đủ:

1. **Ba nhóm cột, mỗi loại một nhóm**: đơn hủy, đơn giao không thành công, yêu cầu trả hàng và hoàn tiền. Với mỗi nhóm, ghi số đơn và lý do đứng đầu.
2. **SFCR và SFRR** đúng như trang chỉ số hiển thị, cạnh mục tiêu của TikTok (dưới 2,5% và dưới 1,5%).
3. **Một dòng cho mỗi sản phẩm** đứng đầu trong mục Chi tiết của SFRR, kèm lý do trả hàng chính.
4. **Một cột thay đổi**: ngày bạn sửa mô tả, ảnh, bảng kích thước, cách đóng gói hay đơn vị vận chuyển.

Ví dụ giả định: trong ba tuần liền, cùng một chiếc áo đứng đầu danh sách trả hàng với lý do sai kích thước. Việc đầu tiên là thêm bảng kích cỡ có số đo vào mô tả và ảnh, ghi ngày sửa, rồi theo dõi số yêu cầu trả hàng của riêng sản phẩm đó trong các tuần sau. Vì hoàn tiền được ghi vào lúc yêu cầu được xử lý, hãy đọc kết quả sau vài tuần, không đọc ngay tuần sau.

Cách viết mô tả trả lời đúng câu hỏi khách hay hỏi có trong bài [Mô tả sản phẩm TikTok Shop](/blog/mo-ta-san-pham-tiktok-shop). Để xem một đơn còn lại bao nhiêu sau phí và hoàn, đối chiếu với ví dụ trong bài phí sàn ở trên.
`;
