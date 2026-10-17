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
  CAP_DX_XAC_NHAN,
  CAP_DX_XAC_NHAN_MOBILE,
  CAP_PT_KHUYEN_MAI,
  CAP_PT_KHUYEN_MAI_MOBILE,
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

  /* ————— san-pham-tiktok-shop-khong-co-luot-hien-thi (P46-B2) ————— */
  "an-hay-it-thay": diagram("an-hay-it-thay", 380, 594, {
    alt: "Sơ đồ hai trường hợp. Không hiện với người mua: dấu hiệu là trạng thái không phải Trực tuyến và không có Lượt hiển thị ở luồng nào; xem trạng thái và lý do trong Quản lý sản phẩm, sửa theo chính sách rồi gửi lại. Đang hiện nhưng ít người thấy, được tô nổi bật: dấu hiệu là sản phẩm Trực tuyến, còn hàng ở biến thể chính, có Lượt hiển thị nhưng thấp so với chính shop; xem Lượt hiển thị theo năm luồng, luồng nào thiếu, luồng nào có mà ít nhấp. Kết luận: sửa lỗi hiển thị trước, rồi mới đọc Lượt hiển thị.",
    caption: "Hai vấn đề khác nhau: sản phẩm bị ẩn cần sửa trạng thái, sản phẩm ít người thấy cần đọc số liệu.",
  }),
  "hien-thi-theo-luong": diagram("hien-thi-theo-luong", 482, 746, {
    alt: "Sơ đồ năm luồng của Lượt hiển thị và câu hỏi cho từng luồng. 1, Thẻ sản phẩm: tìm kiếm, đề xuất, trang mua sắm; tiêu đề có từ khóa người mua tìm, thuộc tính và ngành hàng đã đúng chưa. 2, Tab cửa hàng: khách tự vào trang shop; TikTok không chia Lượt hiển thị cho luồng này, đọc Lượt nhấp. 3, Video: video của shop có gắn sản phẩm này không, có đăng đều không. 4, LIVE: sản phẩm có được giới thiệu và ghim trong buổi LIVE không. 5, Liên kết: có nhà sáng tạo nào đang gắn sản phẩm này không. Kết luận: luồng không có lượt hiển thị là chỗ thiếu, luồng có mà ít nhấp là chuyện của CTR.",
    caption: "Năm luồng, năm câu hỏi: tìm luồng đang thiếu trước khi sửa bất cứ thứ gì.",
  }),
  "hien-thi-ctr": diagram("hien-thi-ctr", 488, 784, {
    alt: "Bảng bốn ô đọc Lượt hiển thị cùng CTR. Ít hiển thị, CTR cao, được tô nổi bật: người thấy thì nhấp, sản phẩm thiếu chỗ xuất hiện; xem từ khóa trong tiêu đề, video, LIVE, nhà sáng tạo. Ít hiển thị, CTR thấp: kéo thêm người xem lúc này dễ phí; sửa ảnh bìa và tiêu đề trước, rồi mới thêm chỗ xuất hiện. Hiển thị ổn, CTR thấp: Lượt hiển thị không phải điểm nghẽn; xem ảnh bìa, tiêu đề, giá hiển thị. Hiển thị ổn, CTR ổn: xem CTOR, trang sản phẩm có thuyết phục người đã nhấp. Ghi chú: ít và ổn là so với chính sản phẩm đó ở kỳ trước và sản phẩm khác cùng luồng, TikTok không công bố mức chuẩn chung.",
    caption: "Lượt hiển thị chỉ có nghĩa khi đọc cùng CTR: bốn trường hợp, bốn việc khác nhau.",
  }),
  "dx-xac-nhan-tieu-de": screenshot(CAP_DX_XAC_NHAN, CAP_DX_XAC_NHAN_MOBILE, {
    alt: "Màn hình một lượt chạy của Juli cho sản phẩm Son môi số 12: các bước đọc chẩn đoán TikTok, đọc thông tin sản phẩm, phân tích từ khóa, phân tích ảnh sản phẩm đã xong, bước Xác nhận một lần đang chờ người bán; bên dưới là đề xuất đổi tiêu đề từ Son môi số 12 thành Son môi lì cao cấp số 12 màu đỏ ruby và mô tả dài hơn, với nút Không thực hiện và Xác nhận thay đổi này (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Một lượt chạy của Juli dừng ở bước Xác nhận một lần: tiêu đề mới chỉ được ghi lên shop sau khi người bán xác nhận.",
  }),
  "theo-doi-7-14": diagram("theo-doi-7-14", 388, 698, {
    alt: "Sơ đồ mốc thời gian sau khi sửa: 14 ngày trước làm mốc so sánh, ngày duyệt là ngày thay đổi lên shop, ngày 7 đọc sơ bộ, ngày 14 chốt kết quả. Ba quy tắc: một thay đổi một lúc trên một sản phẩm; đọc đúng chỉ số được nhắm, sửa tiêu đề để thêm từ khóa thì đọc Lượt hiển thị ở Thẻ sản phẩm trước; so với sản phẩm không đổi, cả shop cùng tăng thì chưa chắc là nhờ thay đổi. Kết luận: không sửa tiếp sản phẩm đó cho đến ngày 14 chốt kết quả.",
    caption: "Một thay đổi, một ngày bắt đầu, hai lần đọc kết quả.",
  }),

  /* ————— thue-ban-hang-tiktok-shop (P46-B2) ————— */
  "khau-tru-san": diagram("khau-tru-san", 414, 712, {
    alt: "Sơ đồ khấu trừ thuế trên từng giao dịch: khách đặt hàng và thanh toán, giao dịch thành công và sàn chấp nhận thanh toán, sàn khấu trừ thuế GTGT và TNCN, người bán nhận phần còn lại. Sàn làm: khai và nộp thay số thuế đã khấu trừ theo tháng, bù trừ thuế của đơn bị hủy hoặc trả hàng, trả lại cho người bán số thuế đã trừ của các đơn đó. Người bán làm: cung cấp cho sàn mã số thuế hoặc số định danh cá nhân, báo cơ quan thuế các tài khoản thanh toán dùng để kinh doanh, giữ sổ kế toán và dùng hóa đơn theo quy định. Ghi chú: tỷ lệ khấu trừ do luật thuế quy định, không do sàn tự đặt.",
    caption: "Ai làm gì khi sàn khấu trừ thuế, theo các nghị định đang có hiệu lực.",
  }),
  "nguong-1-ty": diagram("nguong-1-ty", 368, 584, {
    alt: "Sơ đồ ba mức doanh thu cả năm của hộ, cá nhân kinh doanh. Từ 1 tỷ đồng trở xuống, được tô nổi bật: không chịu thuế GTGT, không nộp thuế TNCN; đã bị sàn khấu trừ thì làm thủ tục bù trừ hoặc hoàn số nộp thừa. Trên 1 tỷ đến 3 tỷ đồng: tính thuế trên doanh thu, hoặc chọn tính TNCN theo thu nhập; chọn theo thu nhập thì tổng hợp doanh thu, quyết toán TNCN theo năm. Trên 3 tỷ đồng: tính TNCN theo thu nhập, doanh thu trừ chi phí; tổng hợp doanh thu, quyết toán theo năm. Ghi chú: khi quyết toán, doanh thu trên sàn được tổng hợp cùng doanh thu bán ngoài sàn, số TNCN sàn đã trừ được trừ vào số phải nộp; trên 1 tỷ đồng phải dùng hóa đơn điện tử.",
    caption: "Ngưỡng doanh thu năm áp dụng từ kỳ tính thuế 2026, sau khi Nghị định 141/2026/NĐ-CP nâng mức lên 1 tỷ đồng.",
  }),

  /* ————— video-tiktok-nhieu-view-khong-ra-don (P46-B1) ————— */
  "video-view-den-don": diagram("video-view-den-don", 504, 512, {
    alt: "Sơ đồ ví dụ giả định cho một video trong 28 ngày: 100.000 lượt xem video, ghi chú đây là chỉ số của video và không có trong công thức GMV. Bên dưới là phễu: 20.000 lượt hiển thị sản phẩm nhân CTR 1 % ra 200 lượt nhấp vào sản phẩm, nhân CTOR 4 % ra 8 đơn hàng SKU, nhân AOV 150.000 đồng ra GMV 1.200.000 đồng. Bước CTR được tô nổi bật: cứ 100 lần sản phẩm hiện ra thì 99 lần không ai bấm vào.",
    caption:
      "Ví dụ giả định: lượt xem video đứng ngoài công thức GMV; đơn hàng đi qua bốn hệ số, và ở đây CTR là chỗ gãy.",
  }),
  "video-trieu-chung": diagram("video-trieu-chung", 516, 848, {
    alt: "Bảng bốn triệu chứng khi video nhiều lượt xem mà ít đơn. 1, nhiều lượt xem nhưng ít Lượt hiển thị sản phẩm: sản phẩm ít được nhìn thấy, xem sản phẩm có được gắn đúng vào video và video có nói về sản phẩm hay chỉ giải trí. 2, Lượt hiển thị sản phẩm ổn nhưng CTR thấp: thấy mà không bấm, xem video có cho thấy rõ sản phẩm, công dụng, giá và người xem có phải người cần sản phẩm. 3, CTR ổn nhưng CTOR thấp: bấm vào mà không mua, xem ảnh, mô tả, đánh giá trên trang sản phẩm và giá, ưu đãi có khớp điều video nói. 4, có đơn nhưng GMV vẫn thấp: AOV thấp, xem khách có chọn biến thể rẻ nhất và có ưu đãi mua nhiều hay mua theo gói. Ghi chú: so với chính video đó ở kỳ trước và các video khác của shop, trên cùng luồng Video.",
    caption:
      "Bốn triệu chứng, bốn bước nghi ngờ: đọc số trước, rồi mới quyết định sửa video hay sửa trang sản phẩm.",
  }),
  "video-truc-tiep-gian-tiep": diagram("video-truc-tiep-gian-tiep", 354, 600, {
    alt: "Sơ đồ ba trường hợp ghi nhận đơn cho video. 1, xem video, bấm vào sản phẩm, mua ngay: GMV video trực tiếp, được tô nổi bật. 2, xem video, bấm vào sản phẩm, vài ngày sau tự tìm lại và mua: GMV video gián tiếp, nếu mua trong 7 ngày. 3, chỉ xem video, không bấm vào sản phẩm: không ghi nhận cho video. Ghi chú theo bài Tinh chỉnh GMV của Học viện TikTok Shop: người mua phải xem và bấm vào link sản phẩm thì video mới được tính; nếu xem nhiều nội dung, đơn được ghi nhận cho nội dung cuối cùng.",
    caption:
      "Theo Học viện TikTok Shop: video chỉ được tính đơn khi người xem đã bấm vào sản phẩm, mua ngay hoặc trong 7 ngày sau.",
  }),
  "video-ctr-du-lieu-mau": screenshot(CAP_DL_TIN_CAY, CAP_DL_TIN_CAY_MOBILE, {
    alt: "Khối Video trong Phân tích của Juli: GMV 1,9 triệu đồng mỗi ngày, giảm 6,1 %; Lượt hiển thị mỗi ngày 5.630, tăng 2,0 %; CTR 2,92 %, giảm 4,8 %, được đánh dấu Juli gợi ý; CTOR và AOV ghi Phụ thuộc sản phẩm; bên dưới là ba video tác động CTR nhiều nhất, mỗi dòng có ngày đăng, mã sản phẩm được gắn, CTR trước và nay, số đồng mất mỗi ngày, nhãn Rõ hoặc Tham khảo và liên kết Xem sản phẩm được gắn (dữ liệu mẫu)",
    caption:
      "Dữ liệu mẫu · Lượt hiển thị của luồng Video vẫn tăng nhưng CTR giảm: Juli chỉ ra những video kéo CTR xuống nhiều nhất.",
  }),
  "video-sua-va-do": diagram("video-sua-va-do", 398, 644, {
    alt: "Sơ đồ sáu bước: 1, đọc luồng Video 28 ngày, cộng tổng cả kỳ rồi mới chia ra tỷ lệ; 2, tìm bước gãy, Lượt hiển thị sản phẩm, CTR, CTOR hay AOV; 3, chọn một thay đổi, video mới do bạn quay hoặc trang sản phẩm, không làm cả hai cùng lúc; 4, ghi ngày bắt đầu; 5, ngày 7 đọc sơ bộ chỉ số mục tiêu đang lên, đi ngang hay giảm; 6, được tô nổi bật, ngày 14 chốt: giữ thay đổi, sửa tiếp hoặc quay lại bản cũ.",
    caption: "Sửa một chỗ mỗi lần, ghi ngày bắt đầu, đọc sơ bộ ở ngày 7 và chốt ở ngày 14.",
  }),

  /* ————— live-tiktok-shop-khong-ra-don (P46-B1) ————— */
  "live-pheu": diagram("live-pheu", 534, 530, {
    alt: "Sơ đồ ví dụ giả định cho một buổi LIVE theo năm bước của TikTok: 60.000 lượt hiển thị LIVE, tỷ lệ vào phòng ERR 8 % ra 4.800 lượt xem LIVE, qua sản phẩm được ghim và giỏ hàng ra 3.600 lượt hiển thị sản phẩm, còn 2,5 % ra 90 lượt nhấp vào sản phẩm, còn 6,7 % ra 6 đơn hàng đã thanh toán. Bước lượt nhấp được tô nổi bật: 4.800 lượt xem nhưng chỉ 90 lượt nhấp, chỗ tụt mạnh nhất là từ thấy sản phẩm đến bấm vào sản phẩm.",
    caption: "Ví dụ giả định: năm bước của phễu LIVE, và bước tụt mạnh nhất là chỗ cần sửa trước.",
  }),
  "live-ba-goc-do": diagram("live-ba-goc-do", 358, 640, {
    alt: "Sơ đồ ba góc độ của chỉ số LIVE theo Cẩm nang lưu lượng LIVE. Phạm vi tiếp cận: Lượt hiển thị, Lượt xem, Tỷ lệ vào phòng ERR, Thời lượng xem trung bình. Tương tác: Tỷ lệ bình luận, Tỷ lệ theo dõi, Tỷ lệ chia sẻ, Tỷ lệ thích. Chuyển đổi, được tô nổi bật: CTR, CTOR, GPM hiển thị, GPM lượt xem. Ghi chú: đông người xem chỉ nói về góc độ đầu tiên, đơn hàng nằm ở góc độ thứ ba; CTR của LIVE là lượt bấm vào sản phẩm chia cho lượt xem LIVE, khác cách tính CTR của thẻ sản phẩm.",
    caption:
      "Ba nhóm chỉ số LIVE của TikTok: người xem đông thuộc Phạm vi tiếp cận, còn đơn hàng nằm ở nhóm Chuyển đổi.",
  }),
  "live-gpm": diagram("live-gpm", 360, 562, {
    alt: "Sơ đồ ví dụ giả định so sánh hai buổi LIVE của cùng một shop. Buổi A, đông người xem: 50.000 lượt hiển thị, 3.000 lượt xem, GMV 4.000.000 đồng, GPM hiển thị 80.000 đồng. Buổi B, ít người xem hơn, được tô nổi bật: 20.000 lượt hiển thị, 1.200 lượt xem, GMV 3.000.000 đồng, GPM hiển thị 150.000 đồng. Công thức: GPM hiển thị bằng GMV phòng LIVE chia cho lượt hiển thị nhân 1.000. Kết luận: buổi B ít người hơn nhưng mỗi 1.000 lượt hiển thị bán được gần gấp đôi.",
    caption: "Ví dụ giả định: đếm người xem thì buổi A thắng, đo GPM hiển thị thì buổi B bán tốt hơn.",
  }),
  "live-trong-sau": diagram("live-trong-sau", 390, 572, {
    alt: "Sơ đồ hai cột theo Cẩm nang lưu lượng LIVE. Trong khi LIVE, theo dõi: xu hướng Lượt hiển thị và ERR; chỉ số đổi ra sao khi đổi sản phẩm ghim, flash sale, tặng phẩm; ERR cần khoảng 15 đến 30 phút đầu để ổn định. Sau khi LIVE, xem lại: 3 chỉ số kém nhất so với các buổi gần đây; lúc chỉ số giảm thì sản phẩm nào đang ghim, ưu đãi nào đang chạy, có vi phạm không; dữ liệu cấp tài khoản ít nhất 7 ngày một lần. Kết luận: chọn một thay đổi cho buổi sau, rồi so lại trên cùng các chỉ số.",
    caption:
      "Trong buổi theo dõi xu hướng, sau buổi tìm ba chỉ số kém nhất: tóm tắt từ Cẩm nang lưu lượng LIVE của TikTok.",
  }),
  "live-luong-du-lieu-mau": screenshot(CAP_PT_LUONG, CAP_PT_LUONG_MOBILE, {
    alt: "Màn hình Phân tích của Juli trên Cửa hàng Mẫu Hoa Mai: kết luận Thẻ sản phẩm: CTOR giảm 7 %, so 30 ngày với 30 ngày trước, hai tab Sản phẩm và Nội dung, dòng chia luồng Sản phẩm gồm Thẻ sản phẩm và Tab cửa hàng, Nội dung gồm Video và LIVE, Liên kết theo dõi ở Trang chủ (dữ liệu mẫu)",
    caption:
      "Dữ liệu mẫu · Juli đọc LIVE như một luồng riêng trong tab Nội dung, tách khỏi Thẻ sản phẩm và Tab cửa hàng.",
  }),

  /* ————— khach-xem-nhung-khong-mua-tiktok-shop (P46-C1) ————— */
  "sau-cu-nhap": diagram("sau-cu-nhap", 552, 984, {
    alt: "Sơ đồ đường đi sau cú nhấp: Lượt nhấp vào sản phẩm, Trang sản phẩm, Giỏ hàng, Thanh toán và thành đơn. Ba chỗ khách có thể rời đi. 1, Trang sản phẩm, đo bằng Tỷ lệ thêm vào giỏ hàng: ảnh thật, kích thước, chất liệu; biến thể khách cần còn hàng; đánh giá, điểm xếp hạng; giá sau giảm so với sản phẩm tương tự. 2, Giỏ hàng, từ giỏ đến đơn: voucher khách thấy có áp dụng được không, giỏ đã đạt mức chi tối thiểu chưa. 3, Thanh toán, từ giỏ đến đơn: phí vận chuyển, tổng tiền cuối cùng khách phải trả. Ghi chú: CTOR bằng Đơn hàng SKU chia cho Lượt nhấp vào sản phẩm và gộp cả ba chỗ; Tỷ lệ thêm vào giỏ hàng tách chỗ đầu khỏi hai chỗ sau; khách xem video hay LIVE có thể đặt ngay mà không qua giỏ, nên cách tách này rõ nhất ở Thẻ sản phẩm và Tab cửa hàng.",
    caption: "Ba chỗ khách đi qua sau cú nhấp. Tỷ lệ thêm vào giỏ hàng cho biết khách rời đi ở trang sản phẩm hay ở bước thanh toán.",
  }),
  "ctor-hai-luong": diagram("ctor-hai-luong", 336, 536, {
    alt: "Sơ đồ ví dụ giả định cho một sản phẩm ở hai nguồn, cùng một trang sản phẩm. Thẻ sản phẩm, khách tự tìm đến: 1.200 lượt nhấp, 60 đơn hàng SKU, CTOR 5 %. Video, được tô nổi bật, khách đến từ một video: 800 lượt nhấp, 8 đơn hàng SKU, CTOR 1 %. Gộp hai nguồn: 2.000 lượt nhấp, 68 đơn hàng SKU, CTOR 3,4 %. Kết luận: trang giữ được khách tự tìm đến, xem video hứa gì trước khi sửa trang.",
    caption: "Ví dụ giả định: CTOR gộp 3,4 % che mất việc khách từ video gần như không mua, trong khi trang vẫn chốt tốt khách tự tìm đến.",
  }),
  "ctor-trieu-chung": diagram("ctor-trieu-chung", 600, 976, {
    alt: "Bảng bốn triệu chứng sau cú nhấp. 1, Tỷ lệ thêm vào giỏ hàng thấp: trang sản phẩm chưa thuyết phục; xem ảnh, mô tả thiếu kích thước, chất liệu, cách dùng; ít đánh giá hoặc đánh giá mới bị chê; giá cao hơn sản phẩm tương tự theo Chẩn đoán giá. 2, Thêm vào giỏ nhiều mà ít đơn: vướng ở bước thanh toán; xem phí vận chuyển, voucher hết hạn hoặc giỏ chưa đạt mức chi tối thiểu, khách chờ một đợt giảm giá. 3, CTOR thấp ở một nguồn, ổn ở nguồn khác: nội dung hứa khác trang; xem giá, ưu đãi nói trong video, LIVE còn hiệu lực không, biến thể được giới thiệu có đúng biến thể trên trang. 4, CTOR thấp ở mọi nguồn: vấn đề nằm ở chính trang; sửa trang trước, một thay đổi mỗi lần. Ghi chú: so với chính sản phẩm đó ở kỳ trước và sản phẩm khác của shop trên cùng nguồn, TikTok không công bố một mức CTOR chuẩn chung.",
    caption: "Bốn triệu chứng, bốn nhóm nghi phạm: đọc số trước, rồi mới quyết định sửa trang, sửa ưu đãi hay sửa nội dung.",
  }),
  "ctor-xep-hang-du-lieu-mau": screenshot(CAP_PT_XEP_HANG, CAP_PT_XEP_HANG_MOBILE, {
    alt: "Bảng 5 sản phẩm kéo CTOR xuống trong Juli: Son môi số 12 từ 6,3 % xuống 5,4 %, mất 112 nghìn đồng GMV mỗi ngày; Mặt nạ đất sét 100g và Kem dưỡng ẩm ceramide tiếp theo; Kem chống nắng SPF50+ và Sữa rửa mặt amino 150ml nhãn Tham khảo; mỗi dòng có nhãn tin cậy Rõ hoặc Tham khảo và liên kết Xem đề xuất khi có; dòng tổng bằng số của ô CTOR (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Juli xếp sản phẩm theo số đồng GMV mỗi ngày mà CTOR giảm đang lấy đi, để bạn biết sửa trang nào trước.",
  }),
  "ctor-do-luong-du-lieu-mau": screenshot(CAP_DL_TANG_THEM, CAP_DL_TANG_THEM_MOBILE, {
    alt: "Bảng kết quả ngày 7 trong Juli: CTOR là chỉ số chính, trước 5,4 %, mục tiêu 5,9 %, thực tế 5,7 %, đánh giá Đang lên; Lượt hiển thị mỗi ngày, CTR và AOV nằm trong khoảng cho phép, đánh giá Giữ ổn định; GMV mỗi ngày tăng 48 nghìn đồng, ghi Sơ bộ; nút Hoàn tác (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Ngày 7 sau khi sửa trang: CTOR đang lên, các chỉ số còn lại phải giữ trong khoảng cho phép.",
  }),

  /* ————— tang-gia-tri-don-hang-trung-binh-tiktok-shop (P46-C1) ————— */
  "aov-hai-shop": diagram("aov-hai-shop", 372, 584, {
    alt: "Sơ đồ ví dụ giả định: Lượt hiển thị nhân CTR nhân CTOR nhân AOV bằng GMV, ô AOV được tô đậm. Shop A, nhiều đơn nhỏ: 1.000 đơn nhân 60.000 đồng bằng 60.000.000 đồng, phí xử lý đơn 1.000 nhân 3.000 đồng bằng 3.000.000 đồng. Shop B, được tô nổi bật, ít đơn hơn mà mỗi đơn lớn hơn: 400 đơn nhân 150.000 đồng bằng 60.000.000 đồng, phí xử lý đơn 1.200.000 đồng. Kết luận: cùng GMV, shop A cần gấp 2,5 lần số đơn và trả gấp 2,5 lần phí xử lý đơn.",
    caption: "Ví dụ giả định: hai shop cùng GMV, nhưng shop có giá trị mỗi đơn thấp phải xử lý và trả phí cho nhiều đơn hơn.",
  }),
  "aov-phi-co-dinh": diagram("aov-phi-co-dinh", 310, 488, {
    alt: "Biểu đồ thanh ví dụ giả định: phí xử lý đơn 3.000 đồng chiếm 6 % đơn 50.000 đồng, 3 % đơn 100.000 đồng, 1,5 % đơn 200.000 đồng và 0,75 % đơn 400.000 đồng. Ghi chú theo bài Phí Xử Lý Đơn Hàng của Học viện TikTok Shop: 3.000 đồng cố định cho mỗi đơn giao thành công, đã gồm thuế, với mọi giá trị đơn và số lượng hàng; hình chỉ tính khoản phí này, chưa có các khoản phí và chi phí khác.",
    caption: "Ví dụ giả định: cùng 3.000 đồng phí xử lý, đơn càng nhỏ thì phần bị trừ càng lớn.",
  }),
  "aov-pheu-du-lieu-mau": screenshot(CAP_PT_PHEU, CAP_PT_PHEU_MOBILE, {
    alt: "Khối Thẻ sản phẩm trong Phân tích của Juli: GMV 3,6 triệu đồng mỗi ngày, tăng 7,5 %; Lượt hiển thị mỗi ngày tăng 19,4 %, CTR giảm 0,3 %, CTOR giảm 6,9 % và được đánh dấu Juli gợi ý, AOV 160 nghìn đồng giảm 3,0 % và kéo GMV xuống 105 nghìn đồng mỗi ngày (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · AOV đứng cạnh ba chỉ số kia, kèm số đồng mỗi ngày mà nó kéo GMV của luồng lên hoặc xuống.",
  }),
  "aov-cong-cu": diagram("aov-cong-cu", 518, 834, {
    alt: "Bảng bốn công cụ khuyến mãi mà Học viện TikTok Shop mô tả là để tăng giá trị đơn hàng trung bình. Voucher thông thường: giảm theo số tiền hoặc phần trăm khi giỏ đạt mức chi tối thiểu; mẹo của TikTok là đặt mức chi tối thiểu cao hơn 1,2 đến 1,5 lần AOV; mỗi đơn chỉ dùng một voucher của nhà bán hàng. Mua Sỉ Giá Hời: mua đủ số lượng thì được giảm phần trăm, tối đa hai bậc, hợp với hàng mua nhiều cái, nhiều màu. Ưu đãi theo gói: hai đến ba sản phẩm mua cùng nhau, giá cố định hoặc phần trăm giảm, giá ưu đãi của từng SKU phải thấp hơn giá gốc, không cộng dồn với Mua Sỉ Giá Hời. Quà tặng khi mua hàng: mua đủ số món hoặc chi đủ mức thì được quà, không giảm giá trực tiếp, khách trả phí vận chuyển cả quà nên chọn quà nhẹ. Ghi chú: cả bốn do nhà bán hàng trợ giá và tự tạo trong Trung tâm nhà bán hàng; tóm tắt từ Học viện TikTok Shop.",
    caption: "Bốn công cụ, bốn cách để khách mua thêm, tóm tắt từ Học viện TikTok Shop.",
  }),
  "aov-cong-don": diagram("aov-cong-don", 488, 738, {
    alt: "Sơ đồ ví dụ giả định về khuyến mãi cộng dồn theo ba lớp: giá sản phẩm, chỉ một mức có hiệu lực; khuyến mãi cấp giỏ hàng; voucher, một voucher mỗi đơn; rồi đến giá khách trả. Hai sản phẩm giá gốc 100.000 đồng mỗi cái là 200.000 đồng; giảm giá sản phẩm còn 90.000 đồng mỗi cái là 180.000 đồng; Mua Sỉ Giá Hời mua 2 giảm 10 % còn 162.000 đồng; voucher chi tối thiểu 150.000 đồng giảm 15.000 đồng còn 147.000 đồng. Kết luận: ba lớp cộng lại, khách trả 147.000 đồng cho 200.000 đồng giá gốc, tức giảm 26,5 %. Ghi chú theo bài Cách Tính Khuyến Mãi Cộng Dồn: các lớp khác nhau cộng dồn được, mức chi tối thiểu của voucher xét trên giá sau giảm giá sản phẩm.",
    caption: "Ví dụ giả định: ba khuyến mãi nhỏ, mỗi cái trông vừa phải, cộng lại thành mức giảm hơn một phần tư.",
  }),
  "aov-khuyen-mai-du-lieu-mau": screenshot(CAP_PT_KHUYEN_MAI, CAP_PT_KHUYEN_MAI_MOBILE, {
    alt: "Khối Khuyến mãi trong Phân tích của Juli, 60 ngày: flash sale 8 trên 60 ngày với 3 sản phẩm tham gia, giảm thật trung bình 9 % so với giá đang bán trước flash sale, voucher 14 % đơn đạt ngưỡng với 2 voucher đang chạy; bảng năm sản phẩm với loại khuyến mãi, mức giảm thật và GMV mỗi ngày trong và ngoài khuyến mãi, Son môi số 12 giảm 2 % bị đánh dấu quá nông (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Juli đọc khuyến mãi ở chế độ chỉ đọc: bao nhiêu đơn đạt ngưỡng voucher, mức giảm thật của từng đợt.",
  }),
};
