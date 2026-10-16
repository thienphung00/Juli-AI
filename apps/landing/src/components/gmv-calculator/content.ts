import type { FaqItem } from "../../lib/seo";
import type { FactorKey } from "./calc";

/**
 * Copy of `/cong-cu/tinh-gmv` (D49.1, P43). Facts come from the "GMV là gì"
 * post and the metric definitions it cites (Học viện TikTok Shop, "Lưu lượng
 * truy cập sản phẩm"). No benchmark, no industry average: TikTok publishes
 * none, so the page never calls a number "low".
 */

export const TOOL_PATH = "/cong-cu/tinh-gmv";

/** The "GMV là gì" post; linked only once the owner publishes it (it is a noindex draft today). */
export const GMV_POST_SLUG = "gmv-la-gi-tiktok-shop";

/** Heading ids in that post (`slugify` of its H2/H3, pinned by the tool's test). */
export const GMV_POST_ANCHORS = {
  formula: "cach-tinh-gmv-cong-thuc-pheu",
  revenue: "gmv-khac-doanh-thu-thuc-nhan-nhu-the-nao",
  weakest: "tim-buoc-yeu-nhat-trong-pheu",
  enoughData: "buoc-4-du-du-lieu-de-ket-luan-chua",
  impressions: "tang-luot-hien-thi-san-pham",
  ctr: "tang-ctr",
  ctor: "tang-ctor",
  aov: "tang-aov",
} as const;

export type GmvPostAnchor = keyof typeof GMV_POST_ANCHORS;

export const TOOL_H1 = "Công cụ tính GMV TikTok Shop miễn phí";

export const TOOL_LEAD =
  "Nhập Lượt hiển thị sản phẩm, CTR, CTOR và AOV, hoặc số lượt nhấp và đơn hàng, để xem GMV, phễu từng bước và GMV thay đổi ra sao khi một chỉ số tăng.";

export const PRIVACY_LINE =
  "Mọi phép tính chạy ngay trên trình duyệt của bạn: số liệu bạn nhập không được gửi đi, không được lưu lại.";

export const EXAMPLE_NOTE = "Ví dụ giả định, không phải số liệu của một shop thật.";

/** One step of the funnel: the question it answers and where to look (no benchmark). */
export interface StepGuide {
  factor: FactorKey;
  question: string;
  look: string[];
  anchor: GmvPostAnchor;
}

export const STEP_GUIDES: readonly StepGuide[] = [
  {
    factor: "impressions",
    question: "Có đủ người nhìn thấy sản phẩm không?",
    look: [
      "Tiêu đề có chứa từ khoá người mua thật sự tìm không.",
      "Video của shop, buổi LIVE và nhà sáng tạo tiếp thị liên kết có đang đưa sản phẩm ra không.",
      "Vận hành có ổn định không: giao đúng hạn, ít huỷ đơn.",
    ],
    anchor: "impressions",
  },
  {
    factor: "ctr",
    question: "Người thấy sản phẩm có nhấp vào không?",
    look: [
      "Ảnh bìa có rõ ở kích thước nhỏ trên điện thoại không.",
      "Tiêu đề có nói rõ sản phẩm là gì và quy cách ngay ở đầu không.",
      "Giá hiển thị: công cụ Chẩn đoán giá xếp sản phẩm ở mức nào so với sản phẩm tương tự.",
    ],
    anchor: "ctr",
  },
  {
    factor: "ctor",
    question: "Người nhấp vào có đặt hàng không?",
    look: [
      "Tỷ lệ thêm vào giỏ hàng: khách dừng trước giỏ hay sau giỏ.",
      "Mô tả, bộ ảnh chi tiết và đánh giá có trả lời câu khách hay hỏi không.",
      "Phí vận chuyển và voucher ở bước thanh toán.",
    ],
    anchor: "ctor",
  },
  {
    factor: "aov",
    question: "Mỗi đơn hàng SKU được bao nhiêu tiền?",
    look: [
      "Mua Sỉ Giá Hời: ngưỡng số lượng có đặt ở mức một phần khách đã mua không.",
      "Ưu đãi theo gói, quà tặng kèm với những sản phẩm hay được mua cùng nhau.",
      "Quy cách lớn hơn hoặc combo cho khách mua lặp lại.",
    ],
    anchor: "aov",
  },
];

export const TOOL_FAQ: readonly FaqItem[] = [
  {
    question: "Công cụ tính GMV này dùng công thức nào?",
    answer:
      "GMV = Lượt hiển thị sản phẩm × CTR × CTOR × AOV (SKU). Đẳng thức suy ra từ chính định nghĩa của TikTok: CTR là Lượt nhấp chia Lượt hiển thị, CTOR là Đơn hàng SKU chia Lượt nhấp, AOV (SKU) là GMV chia Đơn hàng SKU. Nó đúng khi cả bốn số lấy trên cùng một sản phẩm hoặc nhóm sản phẩm, cùng luồng truy cập và cùng khoảng thời gian.",
  },
  {
    question: "Lấy Lượt hiển thị, CTR, CTOR và AOV ở đâu?",
    answer:
      "Trong Trung tâm nhà bán hàng, mục La bàn dữ liệu, phần Số liệu phân tích sản phẩm. Hãy lọc theo một luồng truy cập và một khoảng thời gian, rồi tính tỷ lệ từ tổng của cả kỳ, không lấy trung bình tỷ lệ của từng ngày.",
  },
  {
    question: "Vì sao GMV tính ra lớn hơn số tiền tôi nhận được?",
    answer:
      "Theo định nghĩa của TikTok, GMV là tổng số tiền thanh toán cho các đơn hàng trong kỳ, bao gồm cả đơn đã huỷ và hoàn tiền, và chưa trừ phí. Số tiền về Số dư Nhà bán hàng là số tiền quyết toán sau khi trừ các khoản phí.",
  },
  {
    question: "Công cụ có cho biết CTR của tôi cao hay thấp không?",
    answer:
      "Không. TikTok không công bố một mức CTR hay CTOR chuẩn chung, và các chỉ số này khác nhau nhiều giữa ngành hàng và giữa các luồng truy cập. Hãy so một chỉ số với chính sản phẩm đó ở kỳ trước và với các sản phẩm khác trong shop, trên cùng luồng.",
  },
  {
    question: "Vì sao tăng 10 % ở bước nào thì GMV cũng tăng 10 %?",
    answer:
      "Vì GMV là tích của bốn chỉ số: nhân một chỉ số với 1,1 thì cả tích cũng nhân với 1,1. Trên giấy, không bước nào đáng giá hơn bước nào. Bước nên làm trước là bước bạn có thể cải thiện nhiều nhất với công sức bỏ ra, và điều đó chỉ thấy được khi so với kỳ trước hoặc với sản phẩm khác.",
  },
  {
    question: "Số liệu tôi nhập có được gửi đi đâu không?",
    answer:
      "Không. Công cụ tính hoàn toàn trên trình duyệt của bạn, không cần đăng nhập, không gửi số liệu về máy chủ và không lưu lại sau khi bạn đóng trang.",
  },
];
