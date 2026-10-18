/**
 * Homepage copy (D43.2 P33-B; D44 layout P34-B). Product facts only — sources:
 * - what Juli reads: /privacy §4; how it connects: TikTok Shop Open API (OAuth);
 * - what Juli executes: D13 (title / description / attributes; cover image only
 *   from a photo the seller supplies; price is a recommendation only), D24.5
 *   (promotions are done by the seller in Seller Center), D24.4/18 (video and
 *   LIVE: Juli drafts, the seller films);
 * - measurement: D12/D14 (day 7 check-in, day 14 final, revert), ADR-077 (vs
 *   comparable products the seller did not change), D34 (opt-in delayed control);
 * - Shopee: D42.6 ("đang tích hợp qua Shopee Open Platform", never live);
 * - price: /terms §5 (500.000đ/tháng) and the 3-month trial already on the site.
 * No testimonial, no case study, no outcome figure (D43.3).
 */
import type { FaqItem } from "../../lib/seo";
import type { IconName } from "../ui";

/**
 * The three zig-zag capability rows (Main.dc.html cap1–cap3). Headings and body
 * from the approved mockup (D44); the bullets keep D13 / D24.5 scope explicit.
 */
export const CAPABILITY_ROWS = {
  analysis: {
    eyebrow: "Phân tích shop",
    title: "Biết GMV tăng hay giảm vì luồng nào, chỉ số nào.",
    body: "Juli tách GMV thành 5 luồng truy cập và đọc phễu Lượt hiển thị × CTR × CTOR × AOV của từng luồng, để bạn thấy đúng bước đang nghẽn.",
    points: [
      "So 30 ngày gần nhất với 30 ngày trước",
      "Xếp hạng sản phẩm theo tác động lên GMV",
      "Đánh dấu ngày sale và khuyến mãi",
    ],
  },
  actions: {
    eyebrow: "Đề xuất và thực thi",
    title: "Mỗi đề xuất là một thay đổi cụ thể. Juli chỉ làm khi bạn duyệt.",
    body: "Thẻ đề xuất nêu sản phẩm, chỉ số mục tiêu, bằng chứng và nội dung trước–sau. Bạn duyệt, sửa hoặc từ chối; Juli cập nhật lên TikTok Shop qua Open API và lưu lại giá trị cũ.",
    // D13 / D24.5 / D24.4: what Juli executes vs. what stays the seller's.
    points: [
      "Juli thực thi: tiêu đề, mô tả, thuộc tính sản phẩm",
      "Ảnh bìa: Juli đề xuất, chỉ tải lên khi bạn cung cấp ảnh",
      "Giá và khuyến mãi: Juli đề xuất, bạn làm trong Seller Center",
      "Video và LIVE: Juli soạn kịch bản, bạn quay",
    ],
  },
  measurement: {
    eyebrow: "Đo lường GMV",
    title: "Kiểm tra ngày 7, chốt kết quả ngày 14.",
    body: "Juli so mỗi thay đổi với mốc 14 ngày trước khi áp dụng và đặt nó cạnh mức dao động bình thường của chỉ số. Nếu ở ngày 7 một chỉ số ra ngoài ngưỡng bạn cho phép, Juli hỏi bạn có muốn hoàn tác không.",
    points: [],
  },
} as const;

/** Data-safety cards (mockup titles + icons; bodies from /privacy and D43 additions.3). */
export const SAFETY: ReadonlyArray<{ icon: IconName; title: string; body: string }> = [
  {
    icon: "shield-check",
    title: "Kết nối chính thức",
    body: "Bạn cấp quyền trên trang uỷ quyền của TikTok Shop. Juli đọc dữ liệu qua TikTok Shop Open API và không bao giờ hỏi mật khẩu shop.",
  },
  {
    icon: "check-square",
    title: "Chỉ chạy khi bạn duyệt",
    body: "Mỗi thay đổi trên shop cần bạn duyệt riêng. Juli không tự đổi giá, không tự tạo khuyến mãi và không đăng nội dung thay bạn.",
  },
  {
    icon: "undo",
    title: "Hoàn tác được",
    body: "Giá trị cũ được lưu trước mỗi thay đổi. Nếu kết quả ngày 7 kém rõ rệt, Juli đề xuất hoàn tác.",
  },
  {
    icon: "mail",
    title: "Ngắt kết nối khi bạn yêu cầu",
    body: "Muốn ngắt kết nối shop, bạn liên hệ Juli qua email hoặc trang Liên hệ; đội Juli ngắt kết nối và Juli ngừng đồng bộ dữ liệu mới ngay lập tức.",
  },
];

/** Dark pricing card (price: /terms §5). */
export const PRICING_POINTS = [
  "Phân tích 5 luồng truy cập mỗi ngày",
  "Thẻ đề xuất có lý do và trước–sau",
  "Thực thi sau khi bạn duyệt, hoàn tác được",
  "Đo kết quả ngày 7 và ngày 14",
] as const;

export const AUDIENCES = [
  {
    title: "Nhà bán hàng",
    body: "Chủ shop nhỏ và vừa tự vận hành, cần biết mỗi ngày nên sửa sản phẩm nào trước mà không phải thuê thêm người phân tích.",
  },
  {
    title: "Affiliate",
    body: "Người làm affiliate cùng shop, cần biết sản phẩm nào đang chuyển đổi tốt qua Video và LIVE để chọn sản phẩm và chuẩn bị kịch bản.",
  },
  {
    title: "Đội vận hành sàn",
    body: "Bớt thời gian tổng hợp số liệu thủ công; mỗi việc cần làm đã có lý do, nội dung soạn sẵn và kết quả đo sau 14 ngày.",
  },
  {
    title: "Agency",
    body: "Theo dõi nhiều shop với cùng một cách đo, có số liệu rõ ràng theo từng luồng truy cập để báo cáo cho khách hàng.",
  },
] as const;

/** Rendered on `/` and passed verbatim to `faqPageSchema` (D43.5: only shown questions). */
export const HOME_FAQ: readonly FaqItem[] = [
  {
    question: "GMV là gì, tăng GMV TikTok Shop bằng cách nào?",
    answer:
      "GMV (tổng giá trị hàng hoá) là tổng giá trị các đơn hàng của shop trong một kỳ; theo cách TikTok tính, GMV gồm cả đơn đã huỷ và hoàn tiền. TikTok Shop tách GMV thành bốn chỉ số: GMV = Lượt hiển thị × CTR × CTOR × AOV. Muốn tăng GMV, hãy tìm bước yếu nhất: ít người thấy sản phẩm, thấy mà không bấm, bấm mà không mua, hay đơn có giá trị thấp. Juli đọc bốn chỉ số này theo từng luồng truy cập và từng sản phẩm, chỉ ra bước đang kéo GMV xuống và đề xuất việc cần làm.",
  },
  {
    question: "Juli đọc những dữ liệu nào của shop?",
    answer:
      "Sau khi bạn cấp quyền, Juli đọc qua TikTok Shop Open API: đơn hàng, sản phẩm, tồn kho, đơn hoàn và huỷ, số liệu hiệu suất theo luồng truy cập, hiệu suất video và LIVE, chương trình khuyến mãi. Juli không đọc tin nhắn của bạn. Chi tiết ở Chính sách bảo mật.",
  },
  {
    question: "Juli có tự thay đổi shop khi tôi chưa duyệt không?",
    answer:
      "Không. Mỗi thay đổi đều chờ bạn duyệt. Trước khi duyệt, bạn thấy đúng nội dung sẽ được gửi lên TikTok Shop và có thể sửa hoặc từ chối.",
  },
  {
    question: "Juli thực hiện được những thay đổi nào?",
    answer:
      "Juli cập nhật tiêu đề, mô tả và thuộc tính sản phẩm. Ảnh bìa chỉ được tải lên khi bạn cung cấp ảnh. Giá và khuyến mãi là đề xuất để bạn tự làm trong Seller Center. Với video và LIVE, Juli soạn kịch bản để bạn quay.",
  },
  {
    question: "Juli đã hỗ trợ Shopee chưa?",
    answer:
      "Chưa. Juli đang tích hợp qua Shopee Open Platform. Hiện bạn chỉ kết nối được TikTok Shop; trang này sẽ cập nhật khi kết nối Shopee mở.",
  },
  {
    question: "Juli đo hiệu quả của một thay đổi như thế nào?",
    answer:
      "Juli so chỉ số mục tiêu của sản phẩm với mốc 14 ngày trước khi áp dụng, đọc sơ bộ ở ngày 7 và chốt ở ngày 14. Mỗi mức thay đổi được đặt cạnh mức dao động bình thường của chỉ số, và những thay đổi bên ngoài Juli trong thời gian đo được ghi rõ, để không ghi công nhầm cho đề xuất.",
  },
  {
    question: "Chi phí bao nhiêu và dùng thử thế nào?",
    answer:
      "Tài khoản mới được dùng thử miễn phí 3 tháng kể từ ngày đăng ký, không cần thẻ thanh toán. Sau đó 500.000đ/tháng. Bạn cũng có thể xem bản Demo với dữ liệu mẫu mà không cần đăng ký.",
  },
  {
    question: "Tôi muốn ngừng dùng thì sao?",
    answer:
      "Bạn huỷ bất cứ lúc nào. Để ngắt kết nối shop, bạn liên hệ Juli qua email lienhe@app-juli.com hoặc trang Liên hệ; đội Juli ngắt kết nối shop và Juli ngừng đồng bộ dữ liệu mới ngay sau đó. Khi bạn yêu cầu xoá tài khoản, dữ liệu được xoá trong vòng 30 ngày, trừ chứng từ pháp luật yêu cầu lưu.",
  },
];
