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
