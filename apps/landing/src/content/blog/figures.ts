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
  CAP_DL_NGAY_14_V2,
  CAP_DL_NGAY_14_V2_MOBILE,
  CAP_DL_NGAY_7_V2,
  CAP_DL_NGAY_7_V2_MOBILE,
  CAP_DX_ANH_BIA,
  CAP_DX_ANH_BIA_TAI_LEN,
  CAP_DX_CTR_TIEU_DE,
  CAP_DX_HOAN_TAC_V2,
  CAP_DX_THE_V2,
  CAP_KN_DANG_NHAP_V2,
  CAP_KN_DANG_NHAP_V2_MOBILE,
  CAP_KN_QUET_NHANH_V2,
  CAP_KN_QUET_NHANH_V2_MOBILE,
  CAP_PT_KHUYEN_MAI,
  CAP_PT_KHUYEN_MAI_MOBILE,
  CAP_PT_NGHEN_V2,
  CAP_PT_NGHEN_V2_MOBILE,
  CAP_DL_TANG_THEM,
  CAP_DL_TANG_THEM_MOBILE,
  CAP_DL_TIN_CAY,
  CAP_DL_TIN_CAY_MOBILE,
  CAP_DX_HANG_CHO,
  CAP_DX_QUY_TAC,
  CAP_DX_QUY_TAC_MOBILE,
  CAP_DX_TU_CHOI,
  CAP_DX_XAC_NHAN,
  CAP_DX_XAC_NHAN_MOBILE,
  CAP_KN_KET_NOI,
  CAP_KN_KET_NOI_MOBILE,
  CAP_PT_LUONG,
  CAP_PT_LUONG_MOBILE,
  CAP_PT_PHEU,
  CAP_PT_PHEU_MOBILE,
  CAP_PT_XEP_HANG,
  CAP_PT_XEP_HANG_MOBILE,
} from "../../components/product/screens";
import type { BlogFigure } from "./types";

/** The 640 px variant as the phone source, for shots whose UI text is already large (no mobile crop). */
const phone = (variants: readonly MediaSource[]): readonly MediaSource[] => variants.filter((v) => v.width === 640);

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

/**
 * Phone variant for a shot with no mobile crop in `screens.ts` (its UI text is
 * already large): the smallest desktop file.
 */
const smallest = (variants: readonly MediaSource[]): readonly MediaSource[] => variants.slice(-1);

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
  "truoc-khi-doc-pheu": diagram("truoc-khi-doc-pheu", 458, 650, {
    alt: "Sơ đồ ba kiểm tra trước khi đọc phễu. 1, trạng thái sản phẩm: chỉ Trực tuyến là bán được, khách mua được; Đã vô hiệu hóa (người bán cho ngừng hiển thị), Đã tạm ngưng (ví dụ bị từ chối khi duyệt) và Bản nháp (chưa gửi đi) đều không bán được. 2, tồn kho từng biến thể: biến thể khách chọn nhiều nhất còn hàng, không chỉ tổng tồn kho. 3, vận hành shop: giao đúng hạn, xử lý nhanh đơn mới để thẻ sản phẩm giữ vị trí trong nhóm đề xuất. Cả ba đều ổn mới bắt đầu đọc phễu.",
    caption: "Năm phút kiểm tra trước khi đọc chỉ số: sản phẩm không bán được thì phễu tốt đến đâu cũng không ra đơn.",
  }),
  "doc-pheu-o-dau": diagram(
    "doc-pheu-o-dau",
    440,
    800,
    {
      alt: "Sơ đồ ví dụ giả định về đường dẫn đến phễu của từng sản phẩm: Trung tâm nhà bán hàng, rồi La bàn dữ liệu, rồi Số liệu phân tích sản phẩm, rồi trang Lưu lượng truy cập sản phẩm. Rồi đọc theo ba quy tắc: 1, chọn luồng, đọc Thẻ sản phẩm trước vì không có người dẫn LIVE hay nhà sáng tạo bán hộ; 2, chọn khoảng thời gian, ít nhất 14 ngày, tốt hơn 28 hoặc 30 ngày, cộng tổng cả kỳ rồi mới chia ra tỷ lệ; 3, đủ dữ liệu chưa, chỉ đọc tỷ lệ khi số liệu đủ nhiều để không bị nhiễu và giữ cùng một cách đọc cho mọi lần so sánh. Ghi chú: TikTok không đưa ra ngưỡng chính thức; khi số liệu còn quá ít, ghi chưa đủ dữ liệu.",
      caption: "Đường dẫn đến phễu trong Trung tâm nhà bán hàng, mô tả bằng chữ, và ba quy tắc khi đọc.",
    },
    3,
  ),
  "luong-noi-dung": diagram("luong-noi-dung", 456, 732, {
    alt: "Sơ đồ ba luồng nội dung không ra đơn và việc cần kiểm tra. Video có lượt xem nhưng ít lượt nhấp vào sản phẩm: kiểm tra video có cho thấy rõ sản phẩm, công dụng, giá và sản phẩm có được gắn đúng. LIVE có người xem nhưng không ra đơn: thời điểm giới thiệu sản phẩm, ưu đãi trong phiên, sản phẩm được ghim còn hàng. Liên kết có lượt hiển thị nhưng ít đơn: khán giả của nhà sáng tạo có khớp với sản phẩm. Ở ba luồng này chỉ số chính là Lượt hiển thị sản phẩm và GMV, CTOR chỉ để tham khảo. Mọi lượt nhấp đều về trang sản phẩm: nếu CTOR ở Thẻ sản phẩm cũng thấp, sửa trang trước.",
    caption: "Video, LIVE và Liên kết: mỗi luồng một triệu chứng, một nhóm việc cần xem.",
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
  "kiem-tra-theo-chi-so": diagram("kiem-tra-theo-chi-so", 502, 872, {
    alt: "Sơ đồ GMV bằng Lượt hiển thị nhân CTR nhân CTOR nhân AOV, và chỉ số nào giảm nhiều nhất thì tìm nguyên nhân ở đó. Lượt hiển thị sản phẩm giảm: trạng thái, hết hàng, tiêu đề mất từ khóa; ít video, buổi LIVE, nhà sáng tạo hơn; kỳ trước có ngày sale; vận hành xấu đi. CTR giảm: traffic loãng, kiểm tra đầu tiên; ảnh bìa, tiêu đề, giá hiển thị vừa đổi; chiết khấu hay nhãn khuyến mãi vừa hết; sản phẩm cạnh tranh mới giá thấp hơn. CTOR giảm: Tỷ lệ thêm vào giỏ hàng giảm thì xem giá, bộ ảnh, mô tả, đánh giá mới; thêm vào giỏ vẫn vậy mà ít đơn thì xem phí vận chuyển, voucher, khách chờ ưu đãi. AOV giảm: Mua Sỉ Giá Hời vừa kết thúc, khách chuyển sang biến thể rẻ hơn, vừa giảm giá sâu hơn, ưu đãi theo gói hay quà tặng kèm vừa tắt.",
    caption: "Bốn chỉ số, bốn nhóm nguyên nhân: bắt đầu từ chỉ số giảm nhiều nhất trong luồng đã khoanh vùng.",
  }),
  "ngoai-pheu": diagram("ngoai-pheu", 510, 760, {
    alt: "Sơ đồ nguyên nhân nằm ngoài phễu. GMV tính cả đơn đã hủy và hoàn tiền; tiền về là sau hủy, hoàn và các khoản phí. Bốn nguyên nhân: 1, mùa vụ, ngành hàng có tháng cao điểm và thấp điểm, xem so với cùng kỳ năm trước nếu shop đủ lâu; 2, đơn hủy và hoàn tiền tăng, tiền về giảm mạnh hơn GMV, xem lý do hủy và hoàn; 3, hoàn tiền đến muộn, ghi vào ngày yêu cầu được xử lý chứ không phải ngày mua, tỷ lệ hoàn của tuần gần nhất thường trông thấp hơn thực tế; 4, sản phẩm chủ lực ngừng bán, hết hàng dài ngày, ngừng nhập hay bị tạm ngưng, xem trạng thái và tồn kho. Bốn nguyên nhân này không nằm ở trang sản phẩm: kiểm tra trước khi sửa phễu.",
    caption: "Không phải mức giảm nào cũng do phễu: bốn chỗ cần xem trước khi sửa trang sản phẩm.",
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

  /* ————— ty-le-hoan-hang-tiktok-shop (P46-C2) ————— */
  "ba-loai-hoan-hang": diagram("ba-loai-hoan-hang", 480, 874, {
    alt: "Sơ đồ ba loại đơn mà người bán hay gọi chung là hoàn hàng. 1, Hủy đơn: xảy ra trước khi đơn ở trạng thái đang vận chuyển; chỉ số SFCR nếu do lỗi người bán như hết hàng, sai giá, không bàn giao kịp; hàng chưa rời shop. 2, Giao không thành công: đơn hủy khi đang vận chuyển hoặc khách COD từ chối nhận; không có chỉ số riêng; hàng quay về shop, người bán chịu phí chuyển hoàn. 3, Trả hàng, hoàn tiền: sau khi đơn đã giao, khách gửi yêu cầu; chỉ số SFRR nếu lý do liên quan người bán như không đúng mô tả, gửi sai, lỗi, thiếu; trả hàng về shop hoặc chỉ hoàn tiền. Kết luận: tách ba loại trước, rồi mới xem loại nào đang tăng.",
    caption: "Ba loại đơn không thành tiền, mỗi loại một chỉ số và một cách xử lý.",
  }),
  "dong-thoi-gian-tra-hang": diagram("dong-thoi-gian-tra-hang", 484, 770, {
    alt: "Sơ đồ các mốc thời gian của một yêu cầu trả hàng theo Học viện TikTok Shop: khách gửi yêu cầu trong 15 ngày theo lịch sau khi nhận, 6 ngày với một số danh mục; người bán xem xét yêu cầu trong 1 ngày theo lịch, bước này được tô đậm; người bán xem hàng trả về trong 2 ngày theo lịch sau khi nhận; khiếu nại nếu cần trong 7 ngày, 15 ngày với trả hàng tự sắp xếp. Ở bước xem xét, người bán chọn một trong ba: duyệt yêu cầu hợp lệ; từ chối kèm bằng chứng hợp lệ như video đóng gói; đề nghị hoàn một phần, khách chấp nhận thì đơn không tính vào SFRR. Quá hạn ở bước xem xét yêu cầu hoặc xem hàng trả về thì yêu cầu được tự động duyệt.",
    caption: "Các mốc theo trang Trả hàng và Hoàn tiền của Học viện TikTok Shop; ngày cập nhật ghi trong bài.",
  }),
  "ai-tra-phi-ship": diagram("ai-tra-phi-ship", 514, 784, {
    alt: "Sơ đồ bốn trường hợp và bên trả phí ship khi hàng quay về. Lỗi người bán, được tô nổi bật, gồm gửi sai, hàng giả, thiếu bộ phận, sản phẩm lỗi, đóng gói kém, không khớp mô tả: người bán chịu phí trả hàng. Khách đổi ý: nền tảng trả phí trả hàng, người bán trả phí chiều đi đến mức trần, phần vượt nền tảng trả. Lỗi kho vận, ví dụ kiện hỏng khi vận chuyển: đơn vị kho vận chịu phí trả hàng, hoa hồng nền tảng liên quan được hoàn cho người bán. Giao không thành công, đơn bị hủy khi đang vận chuyển: người bán chịu phí vận chuyển trả hàng. Ghi chú: TikTok quyết định bên nào có lỗi dựa trên bằng chứng các bên gửi.",
    caption: "Ai trả phí ship chiều về, theo chính sách hủy, trả hàng và hoàn tiền của TikTok Shop.",
  }),
  "chi-phi-mot-don-hoan": diagram("chi-phi-mot-don-hoan", 316, 548, {
    alt: "Bảng ví dụ giả định chi phí ngoài tiền hàng của một đơn 200.000 đồng bị trả. Khách đổi ý sau khi nhận: phí xử lý đơn 3.000 đồng không hoàn, phí chiều đi người bán trả 22.000 đồng, cộng 25.000 đồng, không tính vào SFRR. Không đúng mô tả, lỗi người bán, được tô nổi bật: phí xử lý đơn 3.000 đồng không hoàn, phí trả hàng người bán chịu 22.000 đồng, cộng 25.000 đồng, tính vào SFRR. Ghi chú: tiền hàng 200.000 đồng hoàn cho khách, phần hoàn tiền không bị tính phí giao dịch; hàng trả về đã mở có thể không bán lại được như hàng mới.",
    caption: "Ví dụ giả định: hai đơn trả cùng giá, cùng chi phí, nhưng chỉ đơn lỗi người bán tính vào SFRR.",
  }),

  /* ————— phi-san-tiktok-shop-2026 (P46-C2) ————— */
  "phi-mot-don-200k": diagram("phi-mot-don-200k", 370, 574, {
    alt: "Biểu đồ thác nước ví dụ giả định cho một đơn 200.000 đồng ở phí suất mặc định, khách trả 20.000 đồng ship: giá bán 200.000 đồng; trừ phí hoa hồng 14 % là 28.000 đồng; trừ phí giao dịch 6 % là 13.200 đồng; trừ phí xử lý đơn 3.000 đồng; còn lại sau phí sàn 155.800 đồng; trừ giá vốn và đóng gói 114.000 đồng; lãi trước quảng cáo và thuế 41.800 đồng. Ghi chú: phí giao dịch tính trên 220.000 đồng vì ship khách trả nằm trong cơ sở tính; ba khoản phí sàn cộng lại 44.200 đồng, tức 22,1 % giá bán.",
    caption: "Ví dụ giả định: từ giá bán đến phần lãi trước quảng cáo và thuế, theo khung phí hiện hành.",
  }),
  "gmv-den-tien-ve": diagram("gmv-den-tien-ve", 412, 646, {
    alt: "Sơ đồ từ GMV đến tiền thực nhận: GMV là tổng tiền khách thanh toán, gồm cả đơn hủy và hoàn tiền; trừ đơn hủy và hoàn tiền; trừ phí sàn gồm hoa hồng, giao dịch, xử lý đơn, vận hành logistic nếu có; còn lại là tiền thực nhận theo từng đơn đã quyết toán. Đọc GMV để thấy nhu cầu của khách ngay trong ngày và tìm luồng, sản phẩm, chỉ số đang kéo doanh thu xuống. Đọc tiền thực nhận để biết lãi thật sau phí và hoàn tiền, lên kế hoạch nhập hàng và giá bán. Ghi chú: hoàn tiền được ghi vào lúc yêu cầu được xử lý, không phải ngày mua, nên tuần gần nhất thường trông ít hoàn hơn thực tế.",
    caption: "GMV đo nhu cầu, tiền thực nhận đo tiền: đọc cả hai, mỗi số cho một việc.",
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

  /* ————— tang-gia-tri-don-hang-trung-binh-tiktok-shop (P46-C1) ————— */
  "aov-hai-shop": diagram("aov-hai-shop", 372, 584, {
    alt: "Sơ đồ ví dụ giả định: Lượt hiển thị nhân CTR nhân CTOR nhân AOV bằng GMV, ô AOV được tô đậm. Shop A, nhiều đơn nhỏ: 1.000 đơn nhân 60.000 đồng bằng 60.000.000 đồng, phí xử lý đơn 1.000 nhân 3.000 đồng bằng 3.000.000 đồng. Shop B, được tô nổi bật, ít đơn hơn mà mỗi đơn lớn hơn: 400 đơn nhân 150.000 đồng bằng 60.000.000 đồng, phí xử lý đơn 1.200.000 đồng. Kết luận: cùng GMV, shop A cần gấp 2,5 lần số đơn và trả gấp 2,5 lần phí xử lý đơn.",
    caption: "Ví dụ giả định: hai shop cùng GMV, nhưng shop có giá trị mỗi đơn thấp phải xử lý và trả phí cho nhiều đơn hơn.",
  }),
  "aov-phi-co-dinh": diagram("aov-phi-co-dinh", 310, 488, {
    alt: "Biểu đồ thanh ví dụ giả định: phí xử lý đơn 3.000 đồng chiếm 6 % đơn 50.000 đồng, 3 % đơn 100.000 đồng, 1,5 % đơn 200.000 đồng và 0,75 % đơn 400.000 đồng. Ghi chú theo bài Phí Xử Lý Đơn Hàng của Học viện TikTok Shop: 3.000 đồng cố định cho mỗi đơn giao thành công, đã gồm thuế, với mọi giá trị đơn và số lượng hàng; hình chỉ tính khoản phí này, chưa có các khoản phí và chi phí khác.",
    caption: "Ví dụ giả định: cùng 3.000 đồng phí xử lý, đơn càng nhỏ thì phần bị trừ càng lớn.",
  }),
  "aov-cong-cu": diagram("aov-cong-cu", 518, 834, {
    alt: "Bảng bốn công cụ khuyến mãi mà Học viện TikTok Shop mô tả là để tăng giá trị đơn hàng trung bình. Voucher thông thường: giảm theo số tiền hoặc phần trăm khi giỏ đạt mức chi tối thiểu; mẹo của TikTok là đặt mức chi tối thiểu cao hơn 1,2 đến 1,5 lần AOV; mỗi đơn chỉ dùng một voucher của nhà bán hàng. Mua Sỉ Giá Hời: mua đủ số lượng thì được giảm phần trăm, tối đa hai bậc, hợp với hàng mua nhiều cái, nhiều màu. Ưu đãi theo gói: hai đến ba sản phẩm mua cùng nhau, giá cố định hoặc phần trăm giảm, giá ưu đãi của từng SKU phải thấp hơn giá gốc, không cộng dồn với Mua Sỉ Giá Hời. Quà tặng khi mua hàng: mua đủ số món hoặc chi đủ mức thì được quà, không giảm giá trực tiếp, khách trả phí vận chuyển cả quà nên chọn quà nhẹ. Ghi chú: cả bốn do nhà bán hàng trợ giá và tự tạo trong Trung tâm nhà bán hàng; tóm tắt từ Học viện TikTok Shop.",
    caption: "Bốn công cụ, bốn cách để khách mua thêm, tóm tắt từ Học viện TikTok Shop.",
  }),
  "aov-cong-don": diagram("aov-cong-don", 488, 738, {
    alt: "Sơ đồ ví dụ giả định về khuyến mãi cộng dồn theo ba lớp: giá sản phẩm, chỉ một mức có hiệu lực; khuyến mãi cấp giỏ hàng; voucher, một voucher mỗi đơn; rồi đến giá khách trả. Hai sản phẩm giá gốc 100.000 đồng mỗi cái là 200.000 đồng; giảm giá sản phẩm còn 90.000 đồng mỗi cái là 180.000 đồng; Mua Sỉ Giá Hời mua 2 giảm 10 % còn 162.000 đồng; voucher chi tối thiểu 150.000 đồng giảm 15.000 đồng còn 147.000 đồng. Kết luận: ba lớp cộng lại, khách trả 147.000 đồng cho 200.000 đồng giá gốc, tức giảm 26,5 %. Ghi chú theo bài Cách Tính Khuyến Mãi Cộng Dồn: các lớp khác nhau cộng dồn được, mức chi tối thiểu của voucher xét trên giá sau giảm giá sản phẩm.",
    caption: "Ví dụ giả định: ba khuyến mãi nhỏ, mỗi cái trông vừa phải, cộng lại thành mức giảm hơn một phần tư.",
  }),

  /* ————— mo-ta-san-pham-tiktok-shop (P46-D2) ————— */
  "mo-ta-nam-nhom-cau-hoi": diagram("mo-ta-nam-nhom-cau-hoi", 752, 1300, {
    alt: "Sơ đồ ví dụ giả định về năm nhóm câu hỏi khách hỏi lặp lại, mỗi nhóm một câu ví dụ cho thời trang và mỹ phẩm, kèm chỗ trả lời trong mô tả. 1, Kích thước, biến thể: cao 1m60, nặng 50kg mặc size nào; chai này bao nhiêu ml; trả lời ở thông số, bảng kích cỡ. 2, Chất liệu, thành phần: vải có co giãn không; có cồn, có hương liệu không; trả lời ở thông số, thành phần chính. 3, Cách dùng, bảo quản: giặt máy được không; thoa trước hay sau kem dưỡng; trả lời ở cách dùng, lưu ý an toàn. 4, Trong hộp có gì: có kèm thắt lưng không; mua 1 hay cả bộ 3 chai; trả lời ở phần trong hộp có gì. 5, Giao nhận, đổi trả: không vừa có đổi size được không; hết hạn khi nào; trả lời ở chính sách của shop, hạn sử dụng. Ô được tô nổi bật, chưa cần vào mô tả: câu chỉ một người hỏi trong cả tuần, câu về giá, mã giảm giá, phí vận chuyển, câu về điều video hay LIVE đã hứa. Ghi chú: gom câu hỏi từ tin nhắn, bình luận video và LIVE, đánh giá và lý do trả hàng trong 7 ngày, giữ năm câu nhiều nhất cho mỗi sản phẩm.",
    caption: "Ví dụ giả định: xếp câu hỏi lặp lại vào năm nhóm để thấy mô tả đang thiếu phần nào.",
  }),
  "mo-ta-truoc-sau": diagram("mo-ta-truoc-sau", 612, 862, {
    alt: "Sơ đồ ví dụ giả định, một mô tả kem chống nắng trước và sau khi trả lời câu hỏi lặp lại. Trước: kem chống nắng thấm nhanh, không bết, ai dùng cũng thích, giá tốt, mua ngay; khách vẫn hỏi da dầu dùng được không, tuýp bao nhiêu ml, thoa trước hay sau kem dưỡng, có kèm quà không. Sau, được tô nổi bật: mở đầu, kem chống nắng dạng sữa cho da dầu, dùng hằng ngày dưới lớp trang điểm; thông số, dung tích 50 ml, thành phần chính ghi trên nhãn, xuất xứ ghi trên bao bì; cách dùng, thoa sau kem dưỡng, trước trang điểm, thoa lại sau khi ra mồ hôi nhiều; lưu ý, tránh vùng mắt, ngưng dùng nếu kích ứng, bảo quản nơi khô, tránh nắng; trong hộp có gì, 1 tuýp 50 ml, không kèm quà tặng. Bốn phần mỗi phần trả lời một câu hỏi. Ghi chú: bản sau bỏ câu ai dùng cũng thích vì không kiểm chứng được, và đưa câu trả lời cho câu hỏi hay gặp nhất lên dòng đầu.",
    caption: "Ví dụ giả định: mỗi câu khách còn hỏi lại có một chỗ trả lời trong bản mô tả mới.",
  }),
  "mo-ta-duoc-khong-duoc": diagram("mo-ta-duoc-khong-duoc", 444, 774, {
    alt: "Bảng hai cột về mô tả sản phẩm. Nên có, theo chính sách, được tô nổi bật: đặc điểm chính gồm đặc tính, chức năng, thành phần, số lượng; độ dài không dưới 30 từ; thông tin an toàn, thông số kỹ thuật, cảnh báo; sản phẩm và tất cả phụ kiện đi kèm; bảng kích cỡ có số đo và đơn vị với hàng thời trang; màu ngẫu nhiên thì nói rõ. Không được: số 1, tốt nhất, duy nhất, một trăm phần trăm tự nhiên, ngay tức thì, trừ khi chính xác và xác minh được; so sánh với sản phẩm hoặc trang thương mại điện tử khác; giá khuyến mại phóng đại, giải thưởng hay chứng nhận không có; số điện thoại, Zalo, mạng xã hội, email, đường dẫn, mã QR; thông tin không khớp tiêu đề, ảnh, thuộc tính hay hàng thật. Nguồn: các trang của Trung tâm chính sách TikTok Shop về tiêu đề, mô tả, hình ảnh, hướng dẫn đăng bán, mô tả phóng đại, chuyển hướng truy cập, SNAD và bảng kích cỡ.",
    caption: "Những gì nên có và không được viết trong mô tả, tóm tắt từ Trung tâm chính sách TikTok Shop.",
  }),

  /* ————— quy-dinh-livestream-ban-hang (P46-D2) ————— */
  "livestream-ba-vai": diagram("livestream-ba-vai", 578, 1080, {
    alt: "Sơ đồ ba vai trong một buổi livestream bán hàng theo Luật Thương mại điện tử. Nền tảng, Điều 22 và nghị định hướng dẫn: công khai quy chế livestream; nhận, giải quyết khiếu nại của người xem trong và sau buổi phát; công cụ hiển thị cảnh báo hàng có nguy cơ mất an toàn; xác thực điện tử danh tính người livestream; dừng phát, gỡ nội dung vi phạm; lưu hình ảnh, âm thanh ít nhất 01 năm. Người bán, được tô nổi bật, Điều 23: đưa giấy tờ điều kiện kinh doanh và chất lượng hàng cho người livestream trước buổi phát; đưa văn bản xác nhận nội dung quảng cáo cho nền tảng và người livestream khi luật yêu cầu; nội dung bán hàng khớp nội dung đã xác nhận; dừng hợp tác, gỡ thông tin khi có vi phạm. Người livestream, Điều 24: cung cấp thông tin để xác thực danh tính; làm theo quy chế livestream của nền tảng; từ chối khi người bán không đưa đủ giấy tờ; không nói gian dối về công dụng, xuất xứ, chất lượng, giá, khuyến mại, bảo hành; không trái đạo đức xã hội, thuần phong mỹ tục. Kết luận: người bán đưa giấy tờ, người livestream nói đúng, nền tảng lưu và xử lý khiếu nại.",
    caption: "Ai làm gì trong một buổi livestream bán hàng, theo Điều 22 đến 24 Luật Thương mại điện tử.",
  }),
  "livestream-luat-va-tiktok": diagram("livestream-luat-va-tiktok", 486, 774, {
    alt: "Bảng hai cột. Luật và nghị định, áp dụng cho mọi nền tảng: livestream bán hàng có định nghĩa và trách nhiệm riêng cho nền tảng, người bán, người livestream; văn bản xác nhận nội dung quảng cáo với hàng luật yêu cầu; nền tảng xác thực điện tử danh tính người bán và người livestream; người có ảnh hưởng thông báo quảng cáo, kiểm tra tài liệu, không giới thiệu sản phẩm chưa dùng. Chính sách của TikTok Shop, được tô nổi bật, là quy định của nền tảng, không phải của luật: tải Giấy xác nhận nội dung quảng cáo cho thực phẩm, sữa và dinh dưỡng cho trẻ từ 36 tháng tuổi trở xuống, không có thì có thể bị hạn chế quảng bá trong LIVE; quét NFC trên CCCD gắn chip cho người bán mới, nhà sáng tạo xác minh NFC và cung cấp mã số thuế khi được yêu cầu; không phát cùng một phiên LIVE trên TikTok Shop và nền tảng khác cùng lúc; flash sale trên LIVE chạy bằng công cụ Flash Sale, không hứa voucher không có, không bịa nhầm giá.",
    caption: "Điều luật đặt ra và điều TikTok Shop quy định thêm cho LIVE; ngày hiệu lực ghi trong bài.",
  }),
  /* ————— dat-ten-san-pham-tiktok-shop (P46-D1) ————— */
  "tieu-de-hai-viec": diagram("tieu-de-hai-viec", 396, 590, {
    alt: "Sơ đồ tiêu đề làm hai việc trên Thẻ sản phẩm. Chuỗi Lượt hiển thị nhân CTR nhân CTOR nhân AOV bằng GMV, hai ô Lượt hiển thị và CTR được tô đậm. Việc 1, Lượt hiển thị, được tìm ra: có những từ người mua thật sự gõ khi tìm; đúng loại sản phẩm, khớp ngành hàng và thuộc tính; không lặp từ, không nhồi từ khóa không liên quan. Việc 2, CTR, được tô nổi bật, được hiểu ngay: nhìn là biết đây là gì, loại nào, bao nhiêu; quy cách khớp với giá đang hiện trên thẻ; phần đầu tiêu đề nói điều quan trọng nhất. Ghi chú: đọc hai chỉ số cùng lúc trên riêng luồng Thẻ sản phẩm, vì tiêu đề mới có thể kéo thêm lượt hiển thị từ những người ít liên quan hơn nên CTR giảm dù tiêu đề không kém đi.",
    caption: "Tiêu đề tác động đến hai hệ số đầu của phễu: được tìm ra và được hiểu ngay.",
  }),
  "tieu-de-nam-thanh-phan": diagram("tieu-de-nam-thanh-phan", 614, 940, {
    alt: "Bảng ví dụ giả định năm thành phần chính sách TikTok gợi ý cho tiêu đề, cho một sản phẩm thời trang và một sản phẩm mỹ phẩm. Thương hiệu, chỉ khi được ủy quyền: thời trang không ghi vì chưa được ủy quyền, mỹ phẩm Thương hiệu X. Loại sản phẩm: áo thun nam cổ tròn, sữa rửa mặt. Chất liệu, thành phần chính, nếu có: cotton, trà xanh. Đặc điểm chính như màu, chức năng, biến thể: tay ngắn, đen, trắng, xám; dạng gel. Số lượng, quy cách, nêu đủ mọi tùy chọn: size M, L, XL; 100 ml và 150 ml. Hai tiêu đề ghép lại: Áo thun nam cổ tròn cotton tay ngắn, đen / trắng / xám, size M / L / XL, 71 ký tự; Sữa rửa mặt trà xanh dạng gel Thương hiệu X 100 ml / 150 ml, 59 ký tự. Ghi chú: thành phần theo trang chính sách Tiêu đề, mô tả, hình ảnh và video về sản phẩm, 23/04/2026; hai sản phẩm và tên Thương hiệu X là giả định.",
    caption: "Ví dụ giả định: cùng năm thành phần của chính sách, ghép cho hai ngành hàng khác nhau.",
  }),
  "tieu-de-truoc-sau": diagram("tieu-de-truoc-sau", 482, 790, {
    alt: "Ví dụ giả định một tiêu đề trước và sau khi viết lại. Trước, 54 ký tự: ngôi sao SALE SỐC ngôi sao Áo thun nam đẹp rẻ nhất Shop ABC FREESHIP. Các lỗi: hai ngôi sao là ký hiệu, ký tự đặc biệt; SALE SỐC, FREESHIP là khuyến mãi, không mô tả sản phẩm; rẻ nhất là khẳng định tuyệt đối không xác minh được; Shop ABC là tên người bán; thiếu chất liệu, màu, size nên người mua không biết đang mua gì. Sau, được tô nổi bật, 71 ký tự: Áo thun nam cổ tròn cotton tay ngắn, đen / trắng / xám, size M / L / XL; loại sản phẩm đứng đầu, chất liệu cotton, đặc điểm tay ngắn và ba màu, quy cách đủ ba size; ưu đãi đặt bằng công cụ khuyến mãi, không viết vào tiêu đề. Kết luận: bỏ những gì không mô tả sản phẩm, thêm những gì người mua cần để bấm.",
    caption: "Ví dụ giả định: năm lỗi hay gặp trong một tiêu đề, và cùng sản phẩm đó sau khi viết lại theo chính sách.",
  }),

  /* ————— anh-bia-san-pham-tiktok-shop (P46-D1) ————— */
  "anh-bia-tren-the": diagram("anh-bia-tren-the", 552, 772, {
    alt: "Hình vẽ minh họa, không phải giao diện thật, các thẻ sản phẩm trên trang tìm kiếm; thẻ đầu tiên được tô nổi bật với ba số. 1, hình ảnh chính: ảnh đầu tiên người dùng thấy, phần lớn nhất của thẻ, quyết định người lướt có dừng lại và bấm không, đó là CTR. 2, tiêu đề: trên thẻ nhỏ, phần cuối của tiêu đề dễ bị cắt. 3, giá: người mua đọc giá cùng với ảnh, ảnh 1 chai cạnh giá của 3 chai trông như đắt gấp ba. Ảnh thứ 2 đến 9 và video chỉ thấy sau khi bấm vào trang sản phẩm, chúng tác động đến CTOR. Ghi chú: ảnh bìa ở đây là hình ảnh chính của thẻ sản phẩm, không phải ảnh bìa của một video TikTok.",
    caption: "Hình ảnh chính là phần người mua thấy đầu tiên trên thẻ; các ảnh còn lại chỉ hiện sau cú nhấp.",
  }),
  "anh-bia-ba-phuong-an": diagram("anh-bia-ba-phuong-an", 540, 968, {
    alt: "Hình vẽ ví dụ giả định ba phương án hình ảnh chính cho một combo 3 chai dầu gội. A, một chai nhỏ giữa khung: chưa đạt, sản phẩm dưới 60 % khung và khách tưởng giá trên thẻ là của một chai. B, được tô nổi bật, đủ ba chai chiếm gần hết khung: đúng yêu cầu, nền trắng, thấy toàn bộ, cho thấy đúng quy cách đang bán. C, ba chai với dải chữ GIẢM 50 % phía trước: không nên, chữ che phía trước sản phẩm và thành sai khi đợt giảm giá kết thúc. Kết luận: lọc theo yêu cầu trước; kiểu ảnh nào được bấm nhiều hơn thì chỉ số của shop bạn mới trả lời được.",
    caption: "Ví dụ giả định: chỉ một trong ba phương án vừa đúng yêu cầu vừa cho thấy đúng thứ khách sẽ nhận.",
  }),
  "anh-bia-doi-chung": diagram("anh-bia-doi-chung", 406, 630, {
    alt: "Sơ đồ ví dụ giả định đọc CTR Thẻ sản phẩm sau khi đổi ảnh. Các mốc: 14 ngày trước là mốc so sánh; ngày bạn thay ảnh, ghi lại ngày này; ngày 7 đọc sơ bộ; ngày 14 chốt kết quả. Sản phẩm đổi ảnh: CTR từ 2,0 % lên 2,6 %, tăng 30 %. Nhóm không đổi: CTR từ 2,0 % lên 2,2 %, tăng 10 %. Kết luận: phần có thể gán cho ảnh mới khoảng 18 %, bằng 1,30 chia 1,10, không phải 30 %. Ghi chú: cả shop cùng tăng 10 % trong hai tuần đó, có thể do một đợt sale; chỉ phần vượt lên trên nhóm không đổi mới là của ảnh.",
    caption: "Ví dụ giả định: khi những sản phẩm chưa đổi ảnh cũng tăng, phần tăng nhờ ảnh mới nhỏ hơn con số thô.",
  }),
  /* ————— do-hieu-qua-sau-khi-sua-san-pham-tiktok-shop (P46-E) ————— */
  "do-lich-14-ngay": diagram(
    "do-lich-14-ngay",
    440,
    772,
    {
      alt: "Sơ đồ lịch đo một thay đổi. 14 ngày trước khi sửa là mốc so sánh, chốt cố định từ ngày sửa. Ngày sửa: ghi ngày, giá, khuyến mãi, nội dung trang và mức mong đợi. Ngày 1 đến 7: không sửa thêm gì trên sản phẩm này; ngày 7 đọc sơ bộ, chỉ số đang lên, đi ngang hay đang giảm. Ngày 8 đến 14: vẫn không sửa thêm; ngày 14 chốt: giữ, đo thêm, sửa tiếp hay quay lại bản cũ. Ba nguyên tắc: so bằng trung bình mỗi ngày của hai khoảng dài bằng nhau; một chỉ số mục tiêu trên đúng luồng thay đổi tác động; các chỉ số còn lại giữ ổn định, không lệch quá mức dao động bình thường.",
      caption: "Một thay đổi, một mốc 14 ngày, hai lần đọc: ngày 7 để kiểm tra, ngày 14 để quyết định.",
    },
    2,
  ),
  "do-doc-sai-doc-dung": diagram(
    "do-doc-sai-doc-dung",
    500,
    632,
    {
      alt: "Biểu đồ cột ví dụ giả định: số đơn mỗi ngày của một sản phẩm trong 14 ngày trước khi sửa, trung bình 4,1 đơn mỗi ngày, và 14 ngày sau khi sửa, trung bình 4,9 đơn mỗi ngày; đường gạch ngang là mức trung bình của từng khoảng. Đọc sai: ngày 2 có 3 đơn, ngày 3 có 6 đơn, gọi là tăng gấp đôi, trong khi hai ngày lẻ nằm trong dao động thường ngày. Đọc đúng: so hai trung bình 14 ngày thì tăng 0,8 đơn mỗi ngày, chưa vượt hẳn dao động thường ngày của sản phẩm, nghĩa là có thể đã thay đổi nhưng chưa chắc chắn.",
      caption: "Ví dụ giả định: so hai ngày lẻ cho ra “gấp đôi”, so hai trung bình 14 ngày cho ra một mức tăng còn chưa chắc chắn.",
    },
    2,
  ),
  "do-ba-ket-qua": diagram(
    "do-ba-ket-qua",
    516,
    938,
    {
      alt: "Bốn thẻ ví dụ giả định về kết quả ngày 14 với chỉ số mục tiêu CTR Thẻ sản phẩm, mức mong đợi 2,5 %. Sản phẩm A, giữ thay đổi, được tô nổi bật: CTR 2,0 % lên 2,6 %, chạm mức mong đợi, vượt hẳn mức dao động nên rõ, GMV giữ được. Sản phẩm B, giữ và đo thêm 14 ngày: 2,0 % lên 2,5 %, chạm mức mong đợi, chỉ nhỉnh hơn dao động nên chỉ là có thể. Sản phẩm C, giữ và sửa tiếp cùng hướng: 2,0 % lên 2,3 %, chưa chạm mức mong đợi, vượt hẳn mức dao động nên rõ. Sản phẩm D, quay lại bản cũ: 2,0 % lên 2,1 %, chưa chạm mức mong đợi, nằm trong mức dao động. Ghi chú: đừng đọc một kết quả yếu thành mạnh hơn; có thay đổi khác trong 14 ngày thì kết quả không dùng được để quyết định, đo lại từ đầu.",
      caption: "Ví dụ giả định: cùng một mức mong đợi, bốn quyết định khác nhau tùy chạm mức đó hay không và mức tăng so với dao động.",
    },
    3,
  ),
  "do-cua-so-sale": diagram("do-cua-so-sale", 358, 472, {
    alt: "Sơ đồ ba hàng, mỗi hàng 28 ô ngày: 14 ngày trước khi sửa và 14 ngày sau khi sửa, ngày sale tô hồng. Hàng một, mốc so sánh chứa ngày sale: mốc bị đẩy lên, thay đổi dễ trông như thất bại. Hàng hai, thời gian đo chứa ngày sale: số sau khi sửa bị đẩy lên, thay đổi dễ trông như thành công. Hàng ba, cả hai khoảng đều là ngày thường: so được với nhau. Kết luận: sửa khi cả 14 ngày trước và 14 ngày sau đều không có đợt sale lớn.",
    caption: "Một đợt sale trong mốc hay trong thời gian đo đều làm lệch kết quả, theo hai hướng ngược nhau.",
  }),

  /* ————— doanh-thu-sau-sale-tiktok-shop (P46-E) ————— */
  "sale-ba-pha": diagram("sale-ba-pha", 462, 574, {
    alt: "Biểu đồ cột ví dụ giả định: GMV mỗi ngày của một shop quanh một đợt sale. Trước đợt sale, 14 ngày làm mốc, trung bình 10,0 triệu đồng mỗi ngày. Trong đợt sale, 13 ngày, trung bình 18,5 triệu đồng, có một ngày cao điểm. 7 ngày đầu sau đợt, trung bình 8,2 triệu đồng, dưới mốc. Ngày 8 đến 14 sau đợt, trung bình 9,9 triệu đồng, gần về mốc. Đường gạch ngang là mức trung bình của 14 ngày trước đợt; đọc trung bình cả đợt, không đọc riêng ngày cao nhất.",
    caption: "Ví dụ giả định: ba pha của một đợt sale. Tuần đầu sau đợt thấp hơn mốc chưa có nghĩa là shop có vấn đề.",
  }),
  "sale-ghi-truoc": diagram("sale-ghi-truoc", 428, 660, {
    alt: "Danh sách kiểm tra bốn thời điểm. Trước ngày bắt đầu, được tô nổi bật: trung bình mỗi ngày của 14 ngày gần nhất theo luồng; giá và khuyến mãi đang chạy của từng sản phẩm; danh sách sản phẩm tham gia đợt sale; tồn kho của các biến thể bán chạy. Trong đợt: GMV theo luồng mỗi ngày; ngày nào, sản phẩm nào hết hàng; không sửa tiêu đề, ảnh, mô tả để thử. 7 ngày đầu sau đợt: đơn hủy, yêu cầu trả hàng; luồng nào về dưới mốc; chưa kết luận gì. Ngày 14 sau đợt: so với mốc trước đợt; chia sản phẩm thành ba nhóm; chọn một thay đổi đầu tiên để đo.",
    caption: "Những gì cần ghi trước, trong và sau đợt sale, để lúc đọc lại còn có cái để so.",
  }),
  "sale-theo-luong": diagram("sale-theo-luong", 454, 686, {
    alt: "Bảng ví dụ giả định GMV mỗi ngày theo luồng, triệu đồng, trước đợt, trong đợt, 7 ngày sau và so với mốc. Thẻ sản phẩm 4,0, 6,5, 3,5, giảm 12 %. Tab cửa hàng 1,0, 2,4, 0,9, giảm 10 %. Video 2,5, 4,0, 2,3, giảm 8 %. LIVE, được tô nổi bật, 1,5, 4,0, 0,7, giảm 53 %. Liên kết 1,0, 1,6, 0,8, giảm 20 %. Toàn shop 10,0, 18,5, 8,2, giảm 18 %. Ghi chú: gần một nửa mức tụt, 0,8 trong 1,8 triệu đồng mỗi ngày, nằm ở LIVE; xem lịch LIVE sau đợt trước khi sửa trang sản phẩm.",
    caption: "Ví dụ giả định: mức tụt sau đợt sale thường dồn vào một hai luồng, không chia đều cho cả shop.",
  }),
  "sale-ba-nhom": diagram("sale-ba-nhom", 312, 602, {
    alt: "Ba thẻ ví dụ giả định về nhóm sản phẩm sau đợt sale, GMV mỗi ngày trước đợt, trong đợt và ngày 8 đến 14 sau đợt. Giữ nhịp: 1,0, 2,2, 1,2 triệu đồng; CTR và CTOR sau đợt cao hơn mốc; giữ nguyên, ưu tiên cho đợt sale sau. Về mốc cũ: 1,0, 2,0, 1,0 triệu đồng; bán thêm nhờ ưu đãi rồi về như trước; không cần sửa gấp. Dưới mốc cũ, được tô nổi bật: 1,0, 1,8, 0,7 triệu đồng; thấp hơn cả trước đợt; kiểm tra hủy, hoàn, hết hàng, giá đã về chưa.",
    caption: "Ví dụ giả định: chia sản phẩm theo chỗ chúng đứng sau đợt sale so với trước đợt, rồi mới quyết định làm gì.",
  }),
  "sale-gmv-con-lai": diagram("sale-gmv-con-lai", 332, 410, {
    alt: "Bảng ví dụ giả định: GMV trong đợt sale, gồm cả đơn hủy và hoàn tiền, 100.000.000 đồng; trừ đơn hủy trước khi giao 6.000.000 đồng; trừ trả hàng, hoàn tiền ghi nhận sau đợt 4.000.000 đồng; tiền hàng còn lại trước phí 90.000.000 đồng. Ghi chú: từ phần còn lại mới trừ phí sàn và phí xử lý đơn tính theo từng đơn giao thành công; hoàn tiền thường ghi nhận sau ngày mua nên con số này chỉ rõ sau vài tuần.",
    caption: "Ví dụ giả định: GMV của đợt sale chưa phải tiền về; đơn hủy và hoàn tiền đến sau còn trừ tiếp.",
  }),

  /* ————— dung-thu-juli-ai-mien-phi-3-thang (P49-A2, C5) ————— */
  "dung-thu-dang-nhap": screenshot(CAP_KN_DANG_NHAP_V2, CAP_KN_DANG_NHAP_V2_MOBILE, {
    alt: "Màn hình đăng nhập của Juli: liên kết đăng nhập bằng tài khoản đối tác ở trên cùng, tiêu đề Đăng nhập vào Juli, nút Tiếp tục với Google, ô email với nút Gửi mã đăng nhập, liên kết Xem thử với dữ liệu mẫu không cần tài khoản và Dùng thử miễn phí 3 tháng; bên phải một thẻ đề xuất mẫu và các dòng Kết nối chính thức qua TikTok Shop Open API, Chỉ thực hiện khi bạn duyệt, Miễn phí 3 tháng (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Màn hình đăng nhập: tạo tài khoản bằng Google hoặc email, hoặc xem thử với dữ liệu mẫu.",
  }),
  "dung-thu-quet-nhanh": screenshot(CAP_KN_QUET_NHANH_V2, CAP_KN_QUET_NHANH_V2_MOBILE, {
    alt: "Trang Quyết định ngay sau khi kết nối: dải tiến trình Juli đang đọc dữ liệu shop bước 2 trên 3, quét nhanh 14 ngày xong, đọc 60 ngày và chẩn đoán đầy đủ đang chạy 40 % còn khoảng 9 phút, tải lịch sử nền đang chờ; bên dưới một thẻ Kem dưỡng ẩm ceramide ghi Đề xuất nhanh dựa trên 14 ngày, CTR Thẻ sản phẩm 3,7 % lên 3,9 %, độ tin cậy Tham khảo (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Ngày đầu: dải tiến trình ba bước và một đề xuất nhanh dựa trên 14 ngày, độ tin cậy Tham khảo.",
  }),
  "dung-thu-the-dau-tien": screenshot(CAP_DX_THE_V2, phone(CAP_DX_THE_V2), {
    alt: "Thẻ đề xuất Mặt nạ đất sét 100g, chờ duyệt: CTOR Thẻ sản phẩm từ 5,4 % lên 5,9 %, GMV dự kiến thêm 2,1 triệu đồng mỗi tháng, lý do mô tả quá ngắn, thay đổi đề xuất Mô tả, lý do đầy đủ mô tả 180 ký tự một đoạn và TikTok báo mô tả quá ngắn, nút Duyệt và Từ chối (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Một thẻ đề xuất: chỉ số mục tiêu, GMV dự kiến, lý do, thay đổi đề xuất và hai nút Duyệt, Từ chối.",
  }),
  "dung-thu-ngay-7": screenshot(CAP_DL_NGAY_7_V2, CAP_DL_NGAY_7_V2_MOBILE, {
    alt: "Kết quả ngày 7 của Toner rau má 200ml, nhãn Ngày 7 trong khoảng: chỉ số mục tiêu CTOR 5,4 % lên 5,9 %, ngưỡng giữ ổn định cộng trừ 3 % cho Lượt hiển thị, CTR và AOV, các bước đọc dữ liệu 7 ngày, so chỉ số mục tiêu đang lên, so ngưỡng giữ ổn định, báo kết quả sơ bộ, chờ chốt ngày 14; bảng CTOR thực tế 5,7 % Đang lên, ba chỉ số Giữ ổn định, GMV mỗi ngày Sơ bộ, nút Hoàn tác (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Ngày 7: chỉ số mục tiêu Đang lên, các chỉ số khác trong khoảng cho phép, kết quả còn là sơ bộ.",
  }),
  "dung-thu-ngay-14": screenshot(CAP_DL_NGAY_14_V2, CAP_DL_NGAY_14_V2_MOBILE, {
    alt: "Kết quả chốt ngày 14 của Toner rau má 200ml, nhãn Đạt: CTOR 5,95 % so với mục tiêu 5,9 %, GMV thực tế 63 nghìn đồng mỗi ngày bằng 90 % dự kiến, mở khoá đề xuất tiếp theo; hộp kết luận GMV thực tế 1,9 triệu đồng mỗi tháng so với dự kiến 2,1 triệu, thay đổi được giữ; dòng cách chốt các nhãn Đạt, Đạt chưa chắc chắn, Một phần, Không đạt (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Ngày 14: nhãn chốt đặt cạnh GMV dự kiến ban đầu, kèm cách chốt từng nhãn.",
  }),

  /* ————— tim-san-pham-keo-gmv-xuong-tiktok-shop (P49-A2, C6) ————— */
  "keo-xuong-luong": screenshot(CAP_PT_LUONG, CAP_PT_LUONG_MOBILE, {
    alt: "Đầu trang Phân tích của Cửa hàng Mẫu Hoa Mai: kết luận Thẻ sản phẩm: CTOR giảm 7 %, so 30 ngày với 30 ngày trước, thanh Juli gợi ý CTOR kéo GMV giảm 250 nghìn đồng mỗi ngày với nút Xem 4 đề xuất, dòng chia luồng Sản phẩm, Nội dung và Liên kết (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Đầu trang Phân tích: luồng và chỉ số lấy đi nhiều GMV nhất, nói trong một câu.",
  }),
  "keo-xuong-pheu": screenshot(CAP_PT_PHEU, CAP_PT_PHEU_MOBILE, {
    alt: "Phễu luồng Thẻ sản phẩm: Lượt hiển thị mỗi ngày 9.913 tăng 19,4 % thêm 620 nghìn đồng mỗi ngày, CTR 4,44 % giảm 0,3 % bớt 12 nghìn, CTOR 5,14 % giảm 6,9 % bớt 250 nghìn được đánh dấu Juli gợi ý, AOV 160 nghìn giảm 3,0 % bớt 105 nghìn, GMV mỗi ngày 3,6 triệu tăng 7,5 % là tổng của 4 ô (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Mỗi ô ghi số đồng mỗi ngày mà chỉ số đó kéo GMV lên hoặc xuống; ô CTOR lấy đi nhiều nhất.",
  }),
  "keo-xuong-bang": screenshot(CAP_PT_XEP_HANG, CAP_PT_XEP_HANG_MOBILE, {
    alt: "Bảng 5 sản phẩm kéo CTOR xuống, chế độ Kéo xuống: Son môi số 12 CTOR 6,3 % xuống 5,4 % mất 112 nghìn đồng mỗi ngày, Mặt nạ đất sét 100g 6,0 % xuống 5,4 % mất 64 nghìn, Kem dưỡng ẩm ceramide 5,1 % xuống 4,2 % mất 58 nghìn, ba dòng Rõ với liên kết Xem đề xuất; Kem chống nắng SPF50+ và Sữa rửa mặt amino 150ml nhãn Tham khảo, Chưa có đề xuất; dòng Còn lại 3 dòng và dòng Tổng bằng số của ô CTOR (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Con số của ô CTOR chia cho từng sản phẩm, xếp theo số đồng mỗi ngày, kèm nhãn tin cậy.",
  }),
  "keo-xuong-the": screenshot(CAP_DX_THE_V2, phone(CAP_DX_THE_V2), {
    alt: "Thẻ đề xuất Mặt nạ đất sét 100g mở từ bảng kéo xuống: CTOR Thẻ sản phẩm từ 5,4 % lên 5,9 %, GMV dự kiến thêm 2,1 triệu đồng mỗi tháng, lý do mô tả quá ngắn, thay đổi đề xuất Mô tả (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Từ dòng thứ hai của bảng đến thẻ đề xuất: cùng sản phẩm, cùng chỉ số, một thay đổi.",
  }),

  /* ————— ctr-the-san-pham-thap-doi-tieu-de-anh-bia (P49-A2, C7) ————— */
  "ctr-the-pheu": screenshot(CAP_PT_PHEU, CAP_PT_PHEU_MOBILE, {
    alt: "Phễu luồng Thẻ sản phẩm với năm ô: Lượt hiển thị mỗi ngày 9.913, CTR 4,44 % giảm 0,3 % bớt 12 nghìn đồng mỗi ngày, CTOR 5,14 %, AOV 160 nghìn, GMV mỗi ngày 3,6 triệu là tổng của 4 ô (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Ô CTR của luồng Thẻ sản phẩm, đọc riêng với video và LIVE.",
  }),
  "ctr-the-tieu-de": screenshot(CAP_DX_CTR_TIEU_DE, phone(CAP_DX_CTR_TIEU_DE), {
    alt: "Thẻ đề xuất Kem dưỡng ẩm ceramide, chờ duyệt: CTR Thẻ sản phẩm từ 3,7 % lên 3,9 %, GMV dự kiến thêm 150 nghìn đồng mỗi tháng, lý do tiêu đề thiếu từ khoá, lý do đầy đủ CTR giảm từ 3,9 % xuống 3,7 % so với 30 ngày trước và tiêu đề chưa có từ khoá phục hồi da, da khô; tiêu đề cũ bị gạch và tiêu đề mới Kem dưỡng ẩm ceramide phục hồi da khô, cấp ẩm 50ml (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Thẻ tiêu đề nhắm CTR: lý do đầy đủ, tiêu đề cũ và tiêu đề đề xuất.",
  }),
  "ctr-the-anh-bia": screenshot(CAP_DX_ANH_BIA, phone(CAP_DX_ANH_BIA), {
    alt: "Thẻ đề xuất Sữa rửa mặt amino 150ml, chờ duyệt: CTR Thẻ sản phẩm từ 2,1 % lên 2,8 %, GMV dự kiến thêm 1,4 triệu đồng mỗi tháng, lý do ảnh bìa kém nổi bật, thay đổi đề xuất Ảnh bìa, lý do đầy đủ nền rối, sản phẩm chỉ chiếm 35 % khung, 600 nhân 600 px, TikTok báo ảnh chính chất lượng thấp; nhãn Juli tải lên, cần ảnh từ bạn; dòng Duyệt, Juli hỏi ảnh, bạn tải ảnh, xác nhận, Juli thay ảnh bìa (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Thẻ ảnh bìa: Juli phân tích ảnh hiện tại, ảnh mới là ảnh bạn gửi.",
  }),
  "ctr-the-tai-anh": screenshot(CAP_DX_ANH_BIA_TAI_LEN, phone(CAP_DX_ANH_BIA_TAI_LEN), {
    alt: "Lượt chạy ảnh bìa của Sữa rửa mặt amino 150ml đang chờ bạn: đọc chẩn đoán TikTok và phân tích ảnh hiện tại đã xong, bước chờ ảnh từ bạn, các bước sau kiểm tra ảnh mới, xác nhận một lần, tải ảnh lên TikTok Shop, TikTok duyệt lại trang sản phẩm, kết thúc và đặt lịch đo; hộp Juli cần ảnh bìa mới từ bạn, Juli không tự chọn hay tạo ảnh, tỷ lệ 1:1 tối thiểu 800 nhân 800 px, nền trắng hoặc trơn, sản phẩm chiếm từ 70 % khung, yêu cầu còn hiệu lực 3 ngày, ô chọn ảnh từ máy JPG hoặc PNG tối đa 5 MB (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Lượt chạy chờ ảnh của bạn; Juli chỉ tải ảnh lên sau bước xác nhận một lần.",
  }),
  "ctr-the-hoan-tac": screenshot(CAP_DX_HOAN_TAC_V2, phone(CAP_DX_HOAN_TAC_V2), {
    alt: "Hộp thoại Hoàn tác thay đổi này: Juli sẽ khôi phục tiêu đề cũ của Toner rau má 200ml, bạn xác nhận lần cuối trước khi Juli ghi, kết quả đo của thay đổi sẽ dừng; chọn một lý do bắt buộc: doanh số hoặc chỉ số giảm, khách phản hồi không tốt, nội dung sai thông tin sản phẩm, không hợp giọng thương hiệu, TikTok cảnh báo sản phẩm, khác; ô ghi chú; nút Huỷ, giữ thay đổi và Bắt đầu hoàn tác (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Hoàn tác: chọn lý do, Juli khôi phục tiêu đề cũ qua một bước xác nhận nữa.",
  }),

  /* ————— ctor-thap-viet-lai-mo-ta-san-pham (P49-A2, C8) ————— */
  "ctor-mo-ta-o-va-bang": screenshot(CAP_PT_NGHEN_V2, CAP_PT_NGHEN_V2_MOBILE, {
    alt: "Khối Thẻ sản phẩm trong Phân tích: ô CTOR 5,14 % giảm 6,9 % kéo GMV giảm 250 nghìn đồng mỗi ngày được đánh dấu Juli gợi ý, cạnh các ô Lượt hiển thị, CTR, AOV và GMV; bên dưới bảng 5 sản phẩm kéo CTOR xuống, ba dòng đầu Son môi số 12, Mặt nạ đất sét 100g, Kem dưỡng ẩm ceramide với CTOR trước và nay, GMV mỗi ngày bị mất, nhãn Rõ và Xem đề xuất (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Ô CTOR được đánh dấu và bảng sản phẩm gây ra nó, ngay bên dưới.",
  }),
  "ctor-mo-ta-the": screenshot(CAP_DX_THE_V2, phone(CAP_DX_THE_V2), {
    alt: "Thẻ đề xuất mô tả cho Mặt nạ đất sét 100g: CTOR Thẻ sản phẩm từ 5,4 % lên 5,9 %, GMV dự kiến thêm 2,1 triệu đồng mỗi tháng, lý do mô tả quá ngắn, lý do đầy đủ mô tả 180 ký tự một đoạn và TikTok báo mô tả quá ngắn, nút Duyệt và Từ chối (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Thẻ mô tả nhắm CTOR: lý do lấy từ chính trang sản phẩm và chẩn đoán của TikTok.",
  }),
  "ctor-mo-ta-khuyen-mai": screenshot(CAP_PT_KHUYEN_MAI, CAP_PT_KHUYEN_MAI_MOBILE, {
    alt: "Khối Khuyến mãi 60 ngày: flash sale 8 trên 60 ngày với 3 sản phẩm, giảm thật trung bình 9 % so với giá đang bán trước flash sale, voucher 14 % đơn đạt ngưỡng với 2 voucher đang chạy; bảng từng sản phẩm với loại khuyến mãi, giảm thật và GMV mỗi ngày trong và ngoài khuyến mãi, Son môi số 12 giảm giá sản phẩm 2 % ghi quá nông (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Giảm thật so với giá đang bán, không với giá niêm yết; đợt giảm quá nông được đánh dấu.",
  }),
  /* ————— huong-dan-ket-noi-tiktok-shop-voi-juli (P49-A1, guide C1) ————— */
  "hd-kn-dang-nhap": screenshot(CAP_KN_DANG_NHAP_V2, CAP_KN_DANG_NHAP_V2_MOBILE, {
    alt: "Màn hình đăng nhập của Juli: dòng Đối tác thẩm định ở trên cùng, tiêu đề Đăng nhập vào Juli, chưa có tài khoản thì Juli tự tạo ở bước này, nút Tiếp tục với Google, hoặc nhập email và bấm Gửi mã đăng nhập, đường dẫn Xem thử với dữ liệu mẫu, không cần tài khoản và Mới dùng Juli? Dùng thử miễn phí 3 tháng; bên phải là một thẻ đề xuất mẫu Mặt nạ đất sét 100g, CTOR Thẻ sản phẩm 5,4 % lên 5,9 %, GMV dự kiến +2,1 triệu đồng mỗi tháng, lý do Mô tả quá ngắn, kèm dòng Kết nối chính thức qua TikTok Shop Open API, Chỉ thực hiện khi bạn duyệt, Miễn phí 3 tháng (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Bước 1: đăng nhập bằng Google hoặc mã gửi về email; tài khoản mới được tạo ngay ở bước này.",
  }),
  "hd-kn-nut-ket-noi": screenshot(CAP_KN_KET_NOI, CAP_KN_KET_NOI_MOBILE, {
    alt: "Màn hình Kết nối TikTok Shop của Cửa hàng Mẫu Hoa Mai: bạn đã đăng nhập bằng chushop@vi-du.vn, bạn chưa kết nối shop TikTok nào, nút Kết nối TikTok Shop, và ghi chú: khi kết nối, bạn đồng ý để nhân viên Juli xem dữ liệu shop, không gồm dữ liệu người mua, để hỗ trợ và vận hành dịch vụ, mọi lần truy cập đều được ghi nhật ký, kèm liên kết Chính sách bảo mật (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Bước 2: kiểm tra email đang đăng nhập, rồi bấm Kết nối TikTok Shop để sang trang uỷ quyền của TikTok.",
  }),
  "hd-kn-quet-nhanh": screenshot(CAP_KN_QUET_NHANH_V2, CAP_KN_QUET_NHANH_V2_MOBILE, {
    alt: "Trang Quyết định của Cửa hàng Mẫu Hoa Mai ngay sau khi kết nối: dải tiến trình Juli đang đọc dữ liệu shop bước 2 trên 3, bước 1 Quét nhanh 14 ngày đã xong, bước 2 Đọc 60 ngày và chẩn đoán đầy đủ đang chạy 40 % còn khoảng 9 phút, bước 3 Tải lịch sử nền đang chờ; bên dưới là ô Giữ ổn định với Lượt hiển thị, CTR, AOV cùng ngưỡng ±3 %, ô Quy tắc do bạn đặt, và một thẻ Kem dưỡng ẩm ceramide mang nhãn Đề xuất nhanh dựa trên 14 ngày, CTR Thẻ sản phẩm 3,7 % lên 3,9 %, GMV dự kiến +150 nghìn đồng mỗi tháng, độ tin cậy Tham khảo (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Vài phút sau khi kết nối: quét nhanh 14 ngày đã xong, một đề xuất nhanh đã có, chẩn đoán đầy đủ đang chạy.",
  }),
  "hd-kn-phan-tich-dau-tien": screenshot(CAP_PT_LUONG, CAP_PT_LUONG_MOBILE, {
    alt: "Đầu trang Phân tích của Cửa hàng Mẫu Hoa Mai: kết luận Thẻ sản phẩm: CTOR giảm 7 %, so 30 ngày với 30 ngày trước, ô Juli gợi ý CTOR kéo GMV đi 250 nghìn đồng mỗi ngày với nút Xem 4 đề xuất, hai tab Sản phẩm và Nội dung, dòng chia luồng Sản phẩm gồm Thẻ sản phẩm và Tab cửa hàng, Nội dung gồm Video và LIVE, Liên kết chỉ theo dõi ở Trang chủ (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Việc đầu tiên sau khi kết nối: đọc dòng kết luận ở đầu trang Phân tích.",
  }),

  /* ————— doc-phan-tich-tiktok-shop-theo-luong-truy-cap (P49-A1, guide C2) ————— */
  "hd-pt-dau-trang": screenshot(CAP_PT_LUONG, CAP_PT_LUONG_MOBILE, {
    alt: "Đầu trang Phân tích của Juli trên Cửa hàng Mẫu Hoa Mai: kết luận Thẻ sản phẩm: CTOR giảm 7 %, nhãn 30 ngày so với 30 ngày trước, ô Juli gợi ý CTOR kéo GMV đi 250 nghìn đồng mỗi ngày và nút Xem 4 đề xuất, hai tab Sản phẩm và Nội dung, dòng chia luồng: Sản phẩm gồm Thẻ sản phẩm và Tab cửa hàng, Nội dung gồm Video và LIVE, Liên kết chỉ theo dõi ở Trang chủ (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Một câu kết luận cho 30 ngày, số tiền chỉ số đó kéo đi mỗi ngày, và cách năm luồng được xếp vào hai tab.",
  }),
  "hd-pt-pheu-luong": screenshot(CAP_PT_NGHEN_V2, CAP_PT_NGHEN_V2_MOBILE, {
    alt: "Luồng Thẻ sản phẩm trong Phân tích của Juli: GMV 3,6 triệu đồng mỗi ngày, tăng 7,5 %; năm ô: Lượt hiển thị mỗi ngày 9.913, tăng 19,4 %, cộng 620 nghìn đồng mỗi ngày; CTR 4,44 %, giảm 0,3 %, trừ 12 nghìn đồng mỗi ngày; CTOR 5,14 %, giảm 6,9 %, trừ 250 nghìn đồng mỗi ngày, được đánh dấu Juli gợi ý; AOV 160 nghìn đồng, giảm 3,0 %, trừ 105 nghìn đồng mỗi ngày; GMV mỗi ngày là tổng của 4 ô. Bên dưới: 5 sản phẩm kéo CTOR xuống, nút Kéo xuống và Kéo lên, ba dòng đầu Son môi số 12 từ 6,3 % xuống 5,4 %, trừ 112 nghìn đồng, Mặt nạ đất sét 100g từ 6,0 % xuống 5,4 %, trừ 64 nghìn đồng, Kem dưỡng ẩm ceramide từ 5,1 % xuống 4,2 %, trừ 58 nghìn đồng, cả ba nhãn Rõ và nút Xem đề xuất (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Bốn ô cộng lại bằng mức thay đổi GMV của luồng: GMV tăng, nhưng CTOR vẫn lấy đi 250 nghìn đồng mỗi ngày.",
  }),
  "hd-pt-video-tin-cay": screenshot(CAP_DL_TIN_CAY, CAP_DL_TIN_CAY_MOBILE, {
    alt: "Luồng Video trong tab Nội dung của Juli: GMV 1,9 triệu đồng mỗi ngày, giảm 6,1 %; ô Lượt hiển thị 5.630, CTR 2,92 % giảm 4,8 %, trừ 96 nghìn đồng mỗi ngày, được đánh dấu Juli gợi ý; ô CTOR 6,68 % và AOV 173 nghìn đồng màu xám, ghi Phụ thuộc sản phẩm. Bảng Video tác động CTR nhiều nhất: Mặt nạ đất sét trước và sau, CTR 3,2 % xuống 1,9 %, trừ 58 nghìn đồng, nhãn Rõ; Routine sáng 3 bước, 3,2 % xuống 2,6 %, trừ 24 nghìn đồng, nhãn Rõ; Unbox toner rau má, 3,2 % xuống 2,9 %, trừ 9 nghìn đồng, nhãn Tham khảo; mỗi dòng có ngày đăng, sản phẩm được gắn và nút Xem sản phẩm được gắn; dòng Còn lại 12 video ít lượt nhấp (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Tab Nội dung: ô phụ thuộc trang sản phẩm để xám, mỗi video mang nhãn Rõ hoặc Tham khảo.",
  }),
  "hd-pt-khuyen-mai": screenshot(CAP_PT_KHUYEN_MAI, CAP_PT_KHUYEN_MAI_MOBILE, {
    alt: "Phần Khuyến mãi trong Phân tích của Juli, 60 ngày: flash sale 8 trên 60 ngày với 3 sản phẩm tham gia; giảm thật trung bình 9 % so với giá đang bán trước flash sale; voucher 14 % đơn, 2 voucher đang chạy, đơn đạt ngưỡng. Bảng sản phẩm: Son môi số 12, giảm giá sản phẩm, giảm thật 2 %, ghi quá nông, GMV mỗi ngày trong và ngoài khuyến mãi 1,3 và 1,2 triệu đồng; Toner rau má 200ml, flash sale, 12 %; Mặt nạ đất sét 100g, flash sale, 10 %; Kem dưỡng ẩm ceramide, giảm giá sản phẩm, 7 %; Kem chống nắng SPF50+, flash sale, 8 % (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Giảm thật so với giá đang bán ngay trước đó, và một đợt giảm quá nông được đánh dấu.",
  }),

  /* ————— duyet-de-xuat-toi-uu-san-pham-tiktok-shop (P49-A1, guide C3) ————— */
  "hd-dx-the-mo-ta": screenshot(CAP_DX_THE_V2, smallest(CAP_DX_THE_V2), {
    alt: "Thẻ đề xuất của Juli đang mở: SKU MN-015 Mặt nạ đất sét 100g, nhãn Chờ duyệt, Tối ưu sản phẩm, cập nhật 18/10/2026; chỉ số mục tiêu CTOR Thẻ sản phẩm 5,4 % lên 5,9 %, tăng 9,3 %; GMV dự kiến +2,1 triệu đồng mỗi tháng; lý do Mô tả quá ngắn; thay đổi đề xuất Mô tả; lý do đầy đủ: mô tả 180 ký tự, một đoạn, TikTok báo Mô tả quá ngắn; nút Duyệt, Từ chối, Thu gọn và Xem phân tích (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Một sản phẩm, một chỉ số, một thay đổi: thẻ mô tả với lý do đầy đủ và GMV dự kiến.",
  }),
  "hd-dx-quy-tac": screenshot(CAP_DX_QUY_TAC, CAP_DX_QUY_TAC_MOBILE, {
    alt: "Đầu trang Quyết định của Juli: 4 thẻ tối ưu để nâng CTOR Thẻ sản phẩm, ghi chú dữ liệu mẫu, ba tab Đề xuất, Đang thực hiện, Đo lường; ô Giữ ổn định: ngày thứ 7, chỉ số nào lệch quá ngưỡng giữ ổn định thì Juli hỏi bạn có muốn hoàn tác không, với Lượt hiển thị, CTR và AOV ±3 %; ô Quy tắc do bạn đặt: Juli không tự chọn các con số này, giọng văn thân thiện, xưng mình, gọi khách là bạn, không nói quá, 2 từ không được dùng, nút Sửa quy tắc; nhóm thẻ với GMV dự kiến +9,3 triệu đồng mỗi tháng, nút Duyệt 2 thẻ và Sửa (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Trước khi duyệt: ngưỡng giữ ổn định và quy tắc của bạn nằm ngay trên các thẻ.",
  }),
  "hd-dx-the-tieu-de": screenshot(CAP_DX_CTR_TIEU_DE, smallest(CAP_DX_CTR_TIEU_DE), {
    alt: "Thẻ đề xuất tiêu đề của Juli: SKU KD-030 Kem dưỡng ẩm ceramide, Chờ duyệt; CTR Thẻ sản phẩm 3,7 % lên 3,9 %, tăng 5,4 %; GMV dự kiến +150 nghìn đồng mỗi tháng; lý do Tiêu đề thiếu từ khoá; thay đổi đề xuất Tiêu đề; lý do đầy đủ: CTR giảm từ 3,9 % xuống 3,7 % so với 30 ngày trước, tiêu đề chưa có từ khoá khách hay tìm: phục hồi da, da khô; tiêu đề cũ gạch ngang Kem dưỡng ẩm ceramide, tiêu đề mới Kem dưỡng ẩm ceramide phục hồi da khô, cấp ẩm 50ml; nút Duyệt và Từ chối (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Thẻ nhắm CTR: GMV dự kiến còn phụ thuộc CTOR, vì lượt nhấp tăng thêm chỉ thành tiền khi có người đặt hàng.",
  }),
  "hd-dx-the-anh-bia": screenshot(CAP_DX_ANH_BIA, smallest(CAP_DX_ANH_BIA), {
    alt: "Thẻ đề xuất ảnh bìa của Juli: SKU SR-007 Sữa rửa mặt amino 150ml, Chờ duyệt; CTR Thẻ sản phẩm 2,1 % lên 2,8 %, tăng 33,3 %; GMV dự kiến +1,4 triệu đồng mỗi tháng; lý do Ảnh bìa kém nổi bật; thay đổi đề xuất Ảnh bìa; lý do đầy đủ: ảnh bìa nền rối, sản phẩm chỉ chiếm 35 % khung, 600 × 600 px, TikTok báo Ảnh chính chất lượng thấp; chip Juli tải lên, cần ảnh từ bạn; dòng cuối: Duyệt, Juli hỏi ảnh, bạn tải ảnh, xác nhận, Juli thay ảnh bìa (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Thẻ ảnh bìa ghi rõ Juli cần ảnh từ bạn: Juli phân tích ảnh hiện tại, không tự tạo ảnh mới.",
  }),
  "hd-dx-cho-anh": screenshot(CAP_DX_ANH_BIA_TAI_LEN, smallest(CAP_DX_ANH_BIA_TAI_LEN), {
    alt: "Lượt chạy SR-007 Sữa rửa mặt amino 150ml, trạng thái Đang chờ bạn, các chặng Phân tích và Đề xuất đã xong, đang ở Duyệt, tiếp theo Thực thi và Đo lường. Các bước: Đọc chẩn đoán TikTok, Ảnh chính chất lượng thấp; Phân tích ảnh hiện tại, nền rối, sản phẩm chiếm 35 % khung, 600 × 600 px; Chờ ảnh từ bạn, đang chờ; rồi Kiểm tra ảnh mới, Xác nhận một lần, Tải ảnh lên TikTok Shop, TikTok duyệt lại trang sản phẩm, Kết thúc và đặt lịch đo. Hộp Juli cần ảnh bìa mới từ bạn: Juli không tự chọn hay tạo ảnh cho sản phẩm; ảnh cần tỷ lệ 1:1, tối thiểu 800 × 800 px, nền trắng hoặc trơn, không chữ, không khung viền, sản phẩm chiếm từ 70 % khung ảnh; yêu cầu còn hiệu lực 3 ngày, sau đó lượt chạy dừng, không thay đổi gì; ô Chọn ảnh từ máy, JPG hoặc PNG, tối đa 5 MB (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Lượt chạy ảnh bìa dừng ở bước chờ ảnh của bạn; chỉ sau khi bạn xác nhận, Juli mới tải ảnh lên.",
  }),
  "hd-dx-tu-choi": screenshot(CAP_DX_TU_CHOI, smallest(CAP_DX_TU_CHOI), {
    alt: "Hộp thoại Từ chối thẻ này? của Juli: thẻ sẽ rời khỏi Đề xuất, Juli không thay đổi gì trên sản phẩm. Vì sao, chọn một: thay đổi không hợp thương hiệu hoặc giọng văn; lý do hoặc số liệu chưa thuyết phục; tôi đang tự sửa sản phẩm này; sản phẩm sắp ngừng bán hoặc hết hàng; đang chạy chiến dịch khác cho sản phẩm này; khác. Ô ghi chú thêm không bắt buộc, ví dụ shop không dùng từ cao cấp trong tên sản phẩm; nút Quay lại và Từ chối thẻ (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Từ chối kèm một lý do: thẻ rời đi, shop không đổi gì, và lý do giúp đề xuất sau tốt hơn.",
  }),
  "hd-dx-hang-cho": screenshot(CAP_DX_HANG_CHO, CAP_DX_HANG_CHO, {
    alt: "Ô Hàng chờ thẻ tối ưu của Juli: Juli chạy lần lượt, không bao giờ hai thay đổi cùng lúc trên một sản phẩm; SM-012 Son môi số 12 ở trạng thái Đang chờ bạn; TN-021 Toner rau má 200ml ở trạng thái Đã áp dụng (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Hàng chờ: mỗi sản phẩm chỉ có một thay đổi tại một thời điểm.",
  }),

  /* ————— do-ket-qua-ngay-7-ngay-14-hoan-tac (P49-A1, guide C4) ————— */
  "hd-dl-quy-tac-on-dinh": screenshot(CAP_DX_QUY_TAC, CAP_DX_QUY_TAC_MOBILE, {
    alt: "Ô Giữ ổn định trên trang Quyết định của Juli: ngày thứ 7, chỉ số nào lệch quá ngưỡng giữ ổn định thì Juli hỏi bạn có muốn hoàn tác không; ba chỉ số Lượt hiển thị, CTR và AOV, mỗi chỉ số ±3 %; bên cạnh là ô Quy tắc do bạn đặt với giọng văn, 2 từ không được dùng và nút Sửa quy tắc; phía trên là ba tab Đề xuất, Đang thực hiện, Đo lường (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Ngưỡng giữ ổn định do Juli gợi ý theo mức dao động của từng chỉ số; bạn chỉnh được trong Quy tắc.",
  }),
  "hd-dl-ngay-7": screenshot(CAP_DL_NGAY_7_V2, CAP_DL_NGAY_7_V2_MOBILE, {
    alt: "Thẻ Đo lường của Juli ở ngày 7: SKU TN-021 Toner rau má 200ml, thay đổi vào 10/10/2026, đã đổi Tiêu đề, nhãn Ngày 7 trong khoảng. Mục tiêu và ngưỡng giữ ổn định, trung bình mỗi ngày so với 14 ngày trước khi áp dụng: chỉ số mục tiêu CTOR Thẻ sản phẩm 5,4 % lên 5,9 %, đạt khi từ 5,9 % trở lên, đang tiến triển từ 5,5 %; GMV dự kiến +70 nghìn đồng mỗi ngày, +2,1 triệu đồng mỗi tháng; chỉ số không được lệch: Lượt hiển thị mỗi ngày 9.910, ±3 %, khoảng 9.613 đến 10.207; CTR 4,44 %, khoảng 4,31 % đến 4,57 %; AOV 160 nghìn đồng, khoảng 155 đến 165 nghìn đồng. Các bước ngày 17/10: đọc dữ liệu 7 ngày sau thay đổi, so với 14 ngày trước; so chỉ số mục tiêu, CTOR 5,4 % lên 5,7 %, mục tiêu 5,9 %, đang lên; so ngưỡng giữ ổn định, cả ba chỉ số trong khoảng; báo kết quả sơ bộ, đã gửi, không cần bạn làm gì; chờ chốt ngày 14 vào 24/10/2026. Bảng: CTOR chỉ số chính thực tế 5,7 %, Đang lên; Lượt hiển thị 10.029, tăng 1,2 %, Giữ ổn định; CTR 4,40 %, giảm 0,9 %, Giữ ổn định; AOV 161 nghìn đồng, tăng 0,6 %, Giữ ổn định; GMV mỗi ngày +48 nghìn đồng, Sơ bộ; nút Hoàn tác (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Ngày 7: chỉ số mục tiêu đang lên, các chỉ số khác trong ngưỡng, nên Juli chỉ báo kết quả sơ bộ và chờ ngày 14.",
  }),
  "hd-dl-ngay-14": screenshot(CAP_DL_NGAY_14_V2, CAP_DL_NGAY_14_V2_MOBILE, {
    alt: "Thẻ Đo lường của Juli ở ngày 14: SKU TN-021 Toner rau má 200ml, thay đổi vào 10/10/2026, đã đổi Tiêu đề, nhãn Đạt. Mục tiêu CTOR Thẻ sản phẩm 5,4 % lên 5,9 %, GMV dự kiến +70 nghìn đồng mỗi ngày, +2,1 triệu đồng mỗi tháng, cùng bảng ngưỡng giữ ổn định. Các bước ngày 24/10: đọc dữ liệu 14 ngày sau thay đổi; so chỉ số mục tiêu, CTOR 5,4 % lên 5,95 %, mục tiêu 5,9 %; tính GMV thực tế, +63 nghìn đồng mỗi ngày, 90 % dự kiến; chốt kết quả Đạt; mở khoá đề xuất tiếp theo, sản phẩm có thể nhận thẻ mới ở Đề xuất. Bảng: CTOR thực tế 5,95 %, Đạt; Lượt hiển thị, CTR, AOV giữ ổn định. Ô kết luận: Đạt, CTOR 5,95 % từ mục tiêu 5,9 % trở lên, GMV thực tế +1,9 triệu đồng mỗi tháng so với dự kiến +2,1 triệu đồng mỗi tháng, thay đổi được giữ, liên kết Đề xuất tiếp theo cho sản phẩm này. Dòng cách chốt: Đạt khi chỉ số mục tiêu tăng rõ, chạm mục tiêu và GMV giữ được; Đạt chưa chắc chắn khi đạt nhưng mức tăng chưa đủ rõ; Một phần khi chỉ tăng rõ hoặc chỉ chạm mục tiêu, hoặc khi dữ liệu quá ít; Không đạt khi không tăng rõ và không chạm mục tiêu (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Ngày 14: kết quả chốt, GMV thực tế đặt cạnh GMV dự kiến.",
  }),
  "hd-dl-hoan-tac": screenshot(CAP_DX_HOAN_TAC_V2, smallest(CAP_DX_HOAN_TAC_V2), {
    alt: "Hộp thoại Hoàn tác thay đổi này? của Juli: Juli sẽ khôi phục Tiêu đề cũ của Toner rau má 200ml, bạn xác nhận lần cuối trước khi Juli ghi, kết quả đo của thay đổi này sẽ dừng. Vì sao bạn muốn hoàn tác, chọn một, bắt buộc: doanh số hoặc chỉ số giảm; khách phản hồi không tốt; nội dung sai thông tin sản phẩm; không hợp giọng thương hiệu; TikTok cảnh báo sản phẩm; khác. Ô ghi chú thêm không bắt buộc, ví dụ khách nhắn hỏi về tên sản phẩm mới; nút Huỷ, giữ thay đổi và Bắt đầu hoàn tác (dữ liệu mẫu)",
    caption: "Dữ liệu mẫu · Hoàn tác cần một lý do và một lần xác nhận cuối; Juli không bao giờ tự hoàn tác.",
  }),
};
