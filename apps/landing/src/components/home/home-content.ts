/**
 * Homepage copy (D43.2, P33-B). Product facts only — sources:
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

export const HOW_IT_WORKS = [
  {
    key: "phan-tich",
    title: "Phân tích",
    body: "Juli đọc dữ liệu shop mỗi ngày và tách GMV theo từng luồng truy cập: Thẻ sản phẩm, Video, LIVE. Với mỗi sản phẩm, Juli so Lượt hiển thị, CTR, CTOR và AOV với kỳ trước và với các sản phẩm cùng shop.",
  },
  {
    key: "de-xuat",
    title: "Đề xuất",
    body: "Chỉ số yếu nhất quyết định việc cần làm: đổi tiêu đề, viết lại mô tả, bổ sung thuộc tính, thay ảnh bìa, điều chỉnh giá hay soạn kịch bản video. Mỗi thẻ đề xuất ghi rõ lý do và GMV dự kiến.",
  },
  {
    key: "duyet",
    title: "Duyệt",
    body: "Bạn xem nội dung sẽ thay đổi trước khi đồng ý. Bạn có thể sửa, hỏi lại hoặc từ chối. Không có gì được gửi lên shop khi bạn chưa duyệt.",
  },
  {
    key: "thuc-thi",
    title: "Thực thi",
    body: "Với tiêu đề, mô tả và thuộc tính, Juli cập nhật trang sản phẩm qua API chính thức và lưu lại giá trị cũ. Giá, khuyến mãi và video vẫn do bạn thực hiện; Juli chuẩn bị sẵn nội dung và kiểm tra lại.",
  },
  {
    key: "do-luong",
    title: "Đo lường",
    body: "Juli đọc kết quả sơ bộ ở ngày 7 và chốt ở ngày 14, so với các sản phẩm tương tự chưa thay đổi. Nếu kết quả kém rõ rệt, Juli đề xuất hoàn tác.",
  },
] as const;

export const PROBLEMS = [
  {
    title: "Số liệu nằm rải rác",
    body: "Doanh thu ở Seller Center, hiệu suất video ở một trang khác, quảng cáo ở một trang nữa. Ghép lại bằng Excel mất nhiều giờ mỗi tuần.",
  },
  {
    title: "Không biết GMV hụt ở bước nào",
    body: "GMV = Lượt hiển thị × CTR × CTOR × AOV. Khi GMV giảm, có thể do ít người thấy sản phẩm, ít người bấm vào, hay bấm rồi không mua. Mỗi nguyên nhân cần một cách sửa khác.",
  },
  {
    title: "Sửa xong không biết có hiệu quả",
    body: "Đổi ảnh bìa hay tiêu đề xong, GMV tuần sau tăng có thể do mùa vụ hoặc do thuật toán. Thiếu nhóm so sánh, rất khó biết thay đổi nào thật sự có tác dụng.",
  },
] as const;

export const CAPABILITIES = [
  {
    key: "analysis",
    title: "Phân tích shop theo luồng truy cập",
    body: "Bức tranh GMV của shop theo Thẻ sản phẩm, Video và LIVE, đến từng sản phẩm. Juli chỉ ra bước đang làm hụt GMV và mức GMV có thể lấy lại mỗi ngày.",
    points: [
      "Lượt hiển thị, CTR, CTOR, AOV theo đúng cách TikTok Shop định nghĩa",
      "So với 30 ngày trước và với các sản phẩm cùng shop",
      "Cập nhật mỗi ngày khi TikTok Shop có số liệu mới",
    ],
  },
  {
    key: "actions",
    title: "Đề xuất và thực thi sau khi bạn duyệt",
    body: "Mỗi ngày tối đa 5 đề xuất mới, xếp theo GMV có thể tăng thêm. Juli soạn sẵn nội dung; bạn duyệt, Juli cập nhật lên TikTok Shop.",
    points: [
      "Juli thực thi: tiêu đề, mô tả, thuộc tính sản phẩm",
      "Ảnh bìa: Juli đề xuất, chỉ tải lên khi bạn cung cấp ảnh",
      "Giá và khuyến mãi: Juli đề xuất, bạn làm trong Seller Center",
      "Video và LIVE: Juli soạn kịch bản, bạn quay",
    ],
  },
  {
    key: "measurement",
    title: "Đo lường GMV tăng thêm",
    body: "Mỗi thay đổi được đo bằng GMV tăng thêm so với nhóm sản phẩm tương tự chưa thay đổi, không chỉ so trước và sau.",
    points: [
      "Kết quả sơ bộ ngày 7, kết quả chốt ngày 14",
      "Hoàn tác được nếu kết quả kém hơn kỳ vọng",
      "Kết quả của shop dùng để xếp hạng các đề xuất sau",
    ],
  },
] as const;

export const SAFETY = [
  {
    title: "Đọc qua API chính thức",
    body: "Bạn cấp quyền trên trang uỷ quyền của TikTok Shop. Juli đọc dữ liệu qua TikTok Shop Open API và không bao giờ hỏi mật khẩu shop.",
  },
  {
    title: "Chỉ thực thi khi bạn duyệt",
    body: "Mỗi thay đổi trên shop cần bạn duyệt riêng. Juli không tự đổi giá, không tự tạo khuyến mãi và không đăng nội dung thay bạn.",
  },
  {
    title: "Hoàn tác và ngắt kết nối bất cứ lúc nào",
    body: "Giá trị cũ được lưu trước mỗi thay đổi để bạn hoàn tác. Bạn có thể thu hồi quyền của Juli trong Seller Center bất cứ lúc nào; Juli ngừng đồng bộ dữ liệu mới ngay lập tức.",
  },
  {
    title: "Không bán dữ liệu",
    body: "Dữ liệu shop chỉ dùng để phục vụ chính shop của bạn. Khi bạn yêu cầu xoá tài khoản, dữ liệu được xoá trong vòng 30 ngày.",
  },
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
      "Juli so GMV của sản phẩm đã thay đổi với các sản phẩm tương tự trong shop chưa thay đổi, đọc sơ bộ ở ngày 7 và chốt ở ngày 14. Cách này loại bớt ảnh hưởng của mùa vụ và thuật toán so với chỉ nhìn trước và sau.",
  },
  {
    question: "Chi phí bao nhiêu và dùng thử thế nào?",
    answer:
      "Bạn được dùng thử miễn phí 3 tháng, sau đó từ 500K/tháng. Bạn cũng có thể xem bản Demo với dữ liệu mẫu mà không cần đăng ký.",
  },
  {
    question: "Tôi muốn ngừng dùng thì sao?",
    answer:
      "Bạn huỷ bất cứ lúc nào. Để ngắt kết nối, bạn thu hồi quyền của Juli trong Seller Center của TikTok Shop hoặc email cho Juli; Juli ngừng đồng bộ dữ liệu mới ngay sau đó. Khi bạn yêu cầu xoá tài khoản, dữ liệu được xoá trong vòng 30 ngày, trừ chứng từ pháp luật yêu cầu lưu.",
  },
];
