/**
 * Inline figures of the blog bodies (D48 additions 7, P39-C). A body places one
 * with a line of its own: `{{hinh:<id>}}` (see `components/blog/markdown.tsx`).
 *
 * - Diagrams: `scripts/blog-diagrams.mjs` renders them from HTML in a 720 px
 *   desktop layout and a 360 px phone layout; `diagram(name, height,
 *   mobileHeight)` takes the CSS heights the script prints. Any number in a
 *   diagram is hypothetical and the image says "Ví dụ giả định".
 * - Screenshots: real Juli screens on the sample shop "Cửa hàng Mẫu Hoa Mai"
 *   (`components/product/screens.ts`, the product pages' files and mobile
 *   crops), captioned "Dữ liệu mẫu · …".
 *
 * `blog.test.tsx` checks every file exists with these sizes, alt and caption.
 */
import type { MediaSource } from "../../lib/media";
import {
  CAP_DL_TANG_THEM,
  CAP_DL_TANG_THEM_MOBILE,
  CAP_DL_TIN_CAY,
  CAP_DL_TIN_CAY_MOBILE,
  CAP_PT_LUONG,
  CAP_PT_LUONG_MOBILE,
  CAP_PT_PHEU,
  CAP_PT_PHEU_MOBILE,
  CAP_PT_XEP_HANG,
  CAP_PT_XEP_HANG_MOBILE,
} from "../../components/product/screens";
import type { BlogFigure } from "./types";

/** Files of `blog-diagrams.mjs` entry `<name>-v<version>`; heights in CSS px (even). */
function diagram(
  name: string,
  height: number,
  mobileHeight: number,
  text: Pick<BlogFigure, "alt" | "caption">,
  version = 1,
): BlogFigure {
  const desktop = `/media/blog-fig-${name}-v${version}`;
  const mobile = `/media/blog-fig-${name}-m-v${version}`;
  const sized = (stem: string, width: number, h: number): MediaSource => ({
    avif: `${stem}-${width}.avif`,
    webp: `${stem}-${width}.webp`,
    width,
    height: h,
  });
  return {
    kind: "diagram",
    variants: [sized(desktop, 720, height), sized(desktop, 1440, height * 2)],
    mobileVariants: [sized(mobile, 540, mobileHeight * 1.5), sized(mobile, 1080, mobileHeight * 3)],
    ...text,
  };
}

function screenshot(
  variants: readonly MediaSource[],
  mobileVariants: readonly MediaSource[],
  text: Pick<BlogFigure, "alt" | "caption">,
): BlogFigure {
  return { kind: "screenshot", variants, mobileVariants, ...text };
}

export const BLOG_FIGURES: Readonly<Record<string, BlogFigure>> = {
  /* ————— gmv-la-gi-tiktok-shop ————— */
  "gmv-pheu": diagram("gmv-pheu", 430, 432, {
    alt: "Sơ đồ phễu GMV, ví dụ giả định cho một sản phẩm trong 30 ngày: 50.000 lượt hiển thị sản phẩm nhân CTR 3 % ra 1.500 lượt nhấp, nhân CTOR 4 % ra 60 đơn hàng SKU, nhân AOV 180.000 đồng ra GMV 10.800.000 đồng. Dòng cuối: GMV bằng Lượt hiển thị sản phẩm nhân CTR nhân CTOR nhân AOV (SKU).",
    caption:
      "Ví dụ giả định: mỗi bước của phễu nhân với một chỉ số, từ Lượt hiển thị đến GMV.",
  }),
  "nam-luong": diagram("nam-luong", 356, 590, {
    alt: "Sơ đồ năm luồng truy cập cộng lại thành GMV của shop: Thẻ sản phẩm (tìm kiếm, đề xuất, trang mua sắm), Tab cửa hàng (khách chủ động vào trang shop, tính từ Lượt nhấp nhân CTOR nhân AOV), Video (video do tài khoản shop đăng), LIVE (buổi LIVE của shop) và Liên kết (video và LIVE của nhà sáng tạo). Các luồng còn lại tính bằng Hiển thị nhân CTR nhân CTOR nhân AOV; Thẻ sản phẩm được tô nổi bật.",
    caption:
      "Năm luồng truy cập Juli dùng để tách GMV. Tab cửa hàng tính từ Lượt nhấp vì TikTok không chia Lượt hiển thị cho luồng này.",
  }),
  "pt-luong": screenshot(CAP_PT_LUONG, CAP_PT_LUONG_MOBILE, {
    alt: "Màn hình Phân tích của Juli trên Cửa hàng Mẫu Hoa Mai: kết luận Thẻ sản phẩm: CTOR giảm 7 %, so 30 ngày với 30 ngày trước, hai tab Sản phẩm và Nội dung, dòng chia luồng Sản phẩm gồm Thẻ sản phẩm và Tab cửa hàng, Nội dung gồm Video và LIVE, Liên kết theo dõi ở Trang chủ (dữ liệu mẫu)",
    caption:
      "Dữ liệu mẫu · Đầu trang Phân tích: kết luận chính của 30 ngày và cách năm luồng được chia vào các tab.",
  }),
  "buoc-yeu-nhat": diagram("buoc-yeu-nhat", 378, 586, {
    alt: "Sơ đồ bốn câu hỏi để tìm bước yếu nhất trong phễu: 1, luồng nào thay đổi nhiều nhất, so theo số tiền; 2, hệ số nào trong luồng đó, Lượt hiển thị, CTR, CTOR hay AOV; 3, so với mốc nào, chính sản phẩm đó kỳ trước và sản phẩm khác cùng luồng; 4, đủ dữ liệu chưa. Kết quả: một điểm nghẽn ở một luồng, một hệ số, trên vài sản phẩm cụ thể.",
    caption: "Bốn câu hỏi theo thứ tự, từ cả shop xuống một hệ số trên vài sản phẩm.",
  }),
  "dl-tang-them": screenshot(CAP_DL_TANG_THEM, CAP_DL_TANG_THEM_MOBILE, {
    alt: "Bảng kết quả ngày 7 của một thay đổi trong Juli: CTOR chỉ số chính từ 5,4 %, mục tiêu 5,9 %, thực tế 5,7 %, đánh giá Đang lên; Lượt hiển thị mỗi ngày, CTR và AOV nằm trong khoảng cho phép, đánh giá Giữ ổn định; GMV mỗi ngày tăng 48 nghìn đồng, ghi Sơ bộ; nút Hoàn tác (dữ liệu mẫu)",
    caption:
      "Dữ liệu mẫu · Đo lại ở ngày 7: chỉ số mục tiêu so với mục tiêu, các chỉ số khác so với khoảng cho phép.",
  }),

  /* ————— tiktok-shop-khong-ra-don ————— */
  "ba-buoc-nghen": diagram("ba-buoc-nghen", 376, 704, {
    alt: "Sơ đồ ba chỗ nghẽn khi không ra đơn, dưới dòng Lượt hiển thị nhân CTR nhân CTOR bằng Đơn hàng SKU: 1, không ai thấy, Lượt hiển thị thấp, sửa tiêu đề đúng từ khóa, thuộc tính và ngành hàng, video, LIVE, nhà sáng tạo; 2, thấy mà không nhấp, CTR thấp, sửa ảnh bìa, tiêu đề, giá hiển thị; 3, nhấp mà không mua, CTOR thấp, sửa mô tả và bộ ảnh, đánh giá và giá, phí vận chuyển và voucher.",
    caption: "Ba bước của phễu, ba nhóm việc khác nhau: tìm đúng bước trước, rồi mới chọn việc.",
  }),
  "truoc-gio-sau-gio": diagram("truoc-gio-sau-gio", 414, 670, {
    alt: "Sơ đồ tách CTOR làm hai nửa: Lượt nhấp vào sản phẩm, qua Tỷ lệ thêm vào giỏ hàng, đến Thêm vào giỏ hàng, qua Thanh toán, đến Đơn hàng SKU. Trước giỏ, khách chưa bị thuyết phục: xem lại bộ ảnh chi tiết, mô tả sản phẩm, đánh giá, giá so với sản phẩm tương tự. Sau giỏ, khách bỏ ở bước thanh toán: xem lại phí vận chuyển, voucher đã hết hạn, khách chờ đợt ưu đãi tiếp theo.",
    caption:
      "Tỷ lệ thêm vào giỏ hàng chia CTOR thành hai nửa; mỗi nửa có những nguyên nhân riêng.",
  }),
  "quang-cao-ab": diagram("quang-cao-ab", 408, 606, {
    alt: "Sơ đồ ví dụ giả định cho một sản phẩm mỗi tuần. Hiện tại: 10.000 lượt hiển thị nhân CTR 1 % nhân CTOR 1 % được 1 đơn. Phương án A, gấp đôi traffic: 20.000 lượt hiển thị, được 2 đơn, thường ít hơn. Phương án B, sửa trang sản phẩm: giữ 10.000 lượt hiển thị, CTOR lên 3 %, được 3 đơn. Kết luận: sửa phễu trước, rồi mới mua thêm traffic.",
    caption:
      "Ví dụ giả định: sửa trang sản phẩm trước có thể ra nhiều đơn hơn gấp đôi traffic.",
  }),
  "checklist-khong-ra-don": diagram("checklist-khong-ra-don", 372, 488, {
    alt: "Danh sách kiểm tra mười mục chia ba nhóm. Sản phẩm có bán được không: 1 trạng thái Trực tuyến, 2 biến thể chính còn hàng, 3 giao đúng hạn và xử lý đơn nhanh. Phễu nghẽn ở bước nào: 4 Lượt hiển thị đủ ngưỡng, 5 CTR so với chính nó và sản phẩm khác, 6 CTR chỉ giảm ở luồng vừa tăng traffic, 7 Tỷ lệ thêm vào giỏ hàng, 8 đơn trên mỗi lượt thêm vào giỏ. Đo cho đúng: 9 đủ dữ liệu ở mỗi kỳ, 10 một thay đổi, một ngày bắt đầu.",
    caption: "Mười mục của bảng kiểm tra ở trên, gom theo ba câu hỏi.",
  }),
  "truoc-khi-doc-pheu": diagram("truoc-khi-doc-pheu", 458, 650, {
    alt: "Sơ đồ ba kiểm tra trước khi đọc phễu. 1, trạng thái sản phẩm: chỉ Trực tuyến là bán được, khách mua được; Đã vô hiệu hóa (người bán cho ngừng hiển thị), Đã tạm ngưng (ví dụ bị từ chối khi duyệt) và Bản nháp (chưa gửi đi) đều không bán được. 2, tồn kho từng biến thể: biến thể khách chọn nhiều nhất còn hàng, không chỉ tổng tồn kho. 3, vận hành shop: giao đúng hạn, xử lý nhanh đơn mới để thẻ sản phẩm giữ vị trí trong nhóm đề xuất. Cả ba đều ổn mới bắt đầu đọc phễu.",
    caption: "Năm phút kiểm tra trước khi đọc chỉ số: sản phẩm không bán được thì phễu tốt đến đâu cũng không ra đơn.",
  }),
  "doc-pheu-o-dau": diagram("doc-pheu-o-dau", 418, 746, {
    alt: "Sơ đồ đường dẫn đến phễu của từng sản phẩm: Trung tâm nhà bán hàng, rồi La bàn dữ liệu, rồi Số liệu phân tích sản phẩm, rồi trang Lưu lượng truy cập sản phẩm. Rồi đọc theo ba quy tắc: 1, chọn luồng, đọc Thẻ sản phẩm trước vì không có người dẫn LIVE hay nhà sáng tạo bán hộ; 2, chọn khoảng thời gian, ít nhất 14 ngày, tốt hơn 28 hoặc 30 ngày, cộng tổng cả kỳ rồi mới chia ra tỷ lệ; 3, đủ dữ liệu chưa, Juli đọc CTR từ 50 lượt hiển thị mỗi ngày và CTOR từ 20 lượt nhấp mỗi ngày. Ngưỡng này là quy tắc của Juli, không phải quy định của TikTok.",
    caption: "Đường dẫn đến phễu trong Trung tâm nhà bán hàng, mô tả bằng chữ, và ba quy tắc khi đọc.",
  }),
  "luong-noi-dung": diagram("luong-noi-dung", 456, 732, {
    alt: "Sơ đồ ba luồng nội dung không ra đơn và việc cần kiểm tra. Video có lượt xem nhưng ít lượt nhấp vào sản phẩm: kiểm tra video có cho thấy rõ sản phẩm, công dụng, giá và sản phẩm có được gắn đúng. LIVE có người xem nhưng không ra đơn: thời điểm giới thiệu sản phẩm, ưu đãi trong phiên, sản phẩm được ghim còn hàng. Liên kết có lượt hiển thị nhưng ít đơn: khán giả của nhà sáng tạo có khớp với sản phẩm. Ở ba luồng này chỉ số chính là Lượt hiển thị sản phẩm và GMV, CTOR chỉ để tham khảo. Mọi lượt nhấp đều về trang sản phẩm: nếu CTOR ở Thẻ sản phẩm cũng thấp, sửa trang trước.",
    caption: "Video, LIVE và Liên kết: mỗi luồng một triệu chứng, một nhóm việc cần xem.",
  }),
  "pt-xep-hang": screenshot(CAP_PT_XEP_HANG, CAP_PT_XEP_HANG_MOBILE, {
    alt: "Bảng 5 sản phẩm kéo CTOR xuống trong Juli: Son môi số 12, Mặt nạ đất sét 100g, Kem dưỡng ẩm ceramide, Kem chống nắng SPF50+, Sữa rửa mặt amino 150ml, mỗi dòng có CTOR trước và nay, số đồng GMV mỗi ngày bị mất, nhãn tin cậy Rõ hoặc Tham khảo và liên kết Xem đề xuất; dòng tổng bằng số của ô CTOR (dữ liệu mẫu)",
    caption:
      "Dữ liệu mẫu · Juli xếp các sản phẩm theo mức kéo CTOR xuống: sản phẩm ảnh hưởng nhiều nhất đứng đầu.",
  }),

  /* ————— doanh-thu-tiktok-shop-giam ————— */
  "so-sanh-hai-ky": diagram("so-sanh-hai-ky", 318, 406, {
    alt: "Sơ đồ so sánh hai kỳ cho công bằng: kỳ trước và kỳ này đều từ thứ Hai đến Chủ nhật; một ngày sale trong kỳ trước được đánh dấu để ghi chú riêng; ngày hôm nay nằm ngoài kỳ này vì chưa hết ngày. Năm quy tắc: hai kỳ dài bằng nhau, bắt đầu cùng một thứ trong tuần, đánh dấu ngày sale lớn, không tính ngày hôm nay, cùng một loại GMV.",
    caption: "Trước khi tìm nguyên nhân: hai kỳ phải so được với nhau.",
  }),
  "giam-theo-luong": diagram("giam-theo-luong", 378, 566, {
    alt: "Biểu đồ thanh ví dụ giả định, thay đổi GMV theo luồng giữa 30 ngày và 30 ngày trước: Thẻ sản phẩm giảm 2.700.000 đồng, bằng 90 % mức giảm; Tab cửa hàng giảm 200.000 đồng; Video tăng 200.000 đồng; LIVE tăng 400.000 đồng; Liên kết giảm 700.000 đồng; toàn shop giảm 3.000.000 đồng.",
    caption:
      "Ví dụ giả định: bảng ở trên vẽ thành thanh. Gần như toàn bộ mức giảm nằm ở luồng Thẻ sản phẩm.",
  }),
  "pt-pheu": screenshot(CAP_PT_PHEU, CAP_PT_PHEU_MOBILE, {
    alt: "Khối Thẻ sản phẩm trong Phân tích của Juli: GMV 3,6 triệu đồng mỗi ngày, năm ô Lượt hiển thị mỗi ngày, CTR, CTOR, AOV và GMV mỗi ngày, mỗi ô ghi phần trăm thay đổi và số đồng mỗi ngày mà chỉ số đó kéo GMV lên hoặc xuống; ô CTOR được đánh dấu Juli gợi ý (dữ liệu mẫu)",
    caption:
      "Dữ liệu mẫu · Phép chia này trong Juli: mỗi ô ghi số đồng mỗi ngày mà chỉ số đó kéo GMV của luồng lên hoặc xuống.",
  }),
  "pt-video": screenshot(CAP_DL_TIN_CAY, CAP_DL_TIN_CAY_MOBILE, {
    alt: "Khối Video trong Phân tích của Juli: GMV 1,9 triệu đồng mỗi ngày, giảm 6,1 %; Lượt hiển thị mỗi ngày tăng 2,0 %, CTR giảm 4,8 % và được đánh dấu Juli gợi ý; bên dưới là các video tác động CTR nhiều nhất, mỗi dòng có CTR trước và nay, số đồng mất mỗi ngày và nhãn tin cậy Rõ hoặc Tham khảo (dữ liệu mẫu)",
    caption:
      "Dữ liệu mẫu · Luồng Video giảm vì CTR, không vì Lượt hiển thị: video vẫn được phân phối nhưng ít người nhấp vào sản phẩm.",
  }),
  "kiem-tra-theo-chi-so": diagram("kiem-tra-theo-chi-so", 502, 872, {
    alt: "Sơ đồ GMV bằng Lượt hiển thị nhân CTR nhân CTOR nhân AOV, và chỉ số nào giảm nhiều nhất thì tìm nguyên nhân ở đó. Lượt hiển thị sản phẩm giảm: trạng thái, hết hàng, tiêu đề mất từ khóa; ít video, buổi LIVE, nhà sáng tạo hơn; kỳ trước có ngày sale; vận hành xấu đi. CTR giảm: traffic loãng, kiểm tra đầu tiên; ảnh bìa, tiêu đề, giá hiển thị vừa đổi; chiết khấu hay nhãn khuyến mãi vừa hết; sản phẩm cạnh tranh mới giá thấp hơn. CTOR giảm: Tỷ lệ thêm vào giỏ hàng giảm thì xem giá, bộ ảnh, mô tả, đánh giá mới; thêm vào giỏ vẫn vậy mà ít đơn thì xem phí vận chuyển, voucher, khách chờ ưu đãi. AOV giảm: Mua Sỉ Giá Hời vừa kết thúc, khách chuyển sang biến thể rẻ hơn, vừa giảm giá sâu hơn, ưu đãi theo gói hay quà tặng kèm vừa tắt.",
    caption: "Bốn chỉ số, bốn nhóm nguyên nhân: bắt đầu từ chỉ số giảm nhiều nhất trong luồng đã khoanh vùng.",
  }),
  "ngoai-pheu": diagram("ngoai-pheu", 510, 760, {
    alt: "Sơ đồ nguyên nhân nằm ngoài phễu. GMV tính cả đơn đã hủy và hoàn tiền; tiền về là sau hủy, hoàn và các khoản phí. Bốn nguyên nhân: 1, mùa vụ, ngành hàng có tháng cao điểm và thấp điểm, xem so với cùng kỳ năm trước nếu shop đủ lâu; 2, đơn hủy và hoàn tiền tăng, tiền về giảm mạnh hơn GMV, xem lý do hủy và hoàn; 3, hoàn tiền đến muộn, ghi vào ngày yêu cầu được xử lý chứ không phải ngày mua, tỷ lệ hoàn của tuần gần nhất thường trông thấp hơn thực tế; 4, sản phẩm chủ lực ngừng bán, hết hàng dài ngày, ngừng nhập hay bị tạm ngưng, xem trạng thái và tồn kho. Bốn nguyên nhân này không nằm ở trang sản phẩm: kiểm tra trước khi sửa phễu.",
    caption: "Không phải mức giảm nào cũng do phễu: bốn chỗ cần xem trước khi sửa trang sản phẩm.",
  }),
  "pt-xep-hang-doanh-thu": screenshot(CAP_PT_XEP_HANG, CAP_PT_XEP_HANG_MOBILE, {
    alt: "Bảng 5 sản phẩm kéo CTOR xuống trong Juli, sắp theo số đồng GMV mỗi ngày bị mất: Son môi số 12 mất nhiều nhất, tiếp theo Mặt nạ đất sét 100g và Kem dưỡng ẩm ceramide, rồi Kem chống nắng SPF50+ và Sữa rửa mặt amino 150ml; mỗi dòng có CTOR trước và nay và nhãn tin cậy Rõ hoặc Tham khảo; dòng Còn lại 3 dòng và dòng tổng (dữ liệu mẫu)",
    caption:
      "Dữ liệu mẫu · Vài sản phẩm đầu bảng thường giải thích phần lớn mức giảm của một chỉ số.",
  }),
  "quy-trinh-30-phut": diagram("quy-trinh-30-phut", 460, 682, {
    alt: "Sơ đồ quy trình 30 phút khi doanh thu giảm, bảy bước: 1 kiểm tra cách so sánh; 2 tách GMV theo năm luồng; 3 tách luồng đó thành bốn chỉ số Lượt hiển thị, CTR, CTOR, AOV; 4 đi qua danh sách kiểm tra của đúng luồng và chỉ số; 5 tìm năm sản phẩm giải thích nhiều nhất mức giảm; 6 kiểm tra ngoài phễu: mùa vụ, hủy, hoàn, sản phẩm ngừng bán; 7, được tô nổi bật, ghi một kết luận và một hành động kèm ngày bắt đầu.",
    caption: "Bảy bước theo thứ tự. Bước cuối hay bị bỏ qua nhất.",
  }),
};
