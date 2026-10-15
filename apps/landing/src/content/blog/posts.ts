import { blogCover } from "./covers";
import type { BlogPostMeta, BlogSource } from "./types";

/**
 * Every blog post (D43.7). To approve a post for production, the owner changes
 * its `status` from "draft" to "published" — see ./README.md. Nothing else is
 * needed: the sitemap, robots, the `/blog` index and related-post lists all
 * read this field.
 */

const AUTHOR = "Đội ngũ Juli AI";

const academy = (title: string, knowledgeId: string, note?: string): BlogSource => ({
  title: `Học viện TikTok Shop: ${title}`,
  url: `https://seller-vn.tiktok.com/university/essay?knowledge_id=${knowledgeId}`,
  ...(note ? { note } : {}),
});

export const BLOG_POSTS: readonly BlogPostMeta[] = [
  {
    slug: "chi-so-tiktok-shop-ctr-ctor-aov",
    status: "draft",
    title: "Các chỉ số TikTok Shop: Lượt hiển thị, CTR, CTOR, AOV và cách đọc đúng",
    seoTitle: "Chỉ số TikTok Shop: CTR, CTOR, AOV đọc đúng | Juli AI",
    description:
      "Lượt hiển thị, CTR, CTOR, AOV theo đúng định nghĩa của TikTok, công thức GMV theo phễu, cách đọc theo 5 kênh và các lỗi đọc số hay gặp.",
    excerpt:
      "Định nghĩa bốn chỉ số cốt lõi theo đúng cách TikTok công bố, công thức GMV = Lượt hiển thị × CTR × CTOR × AOV, cách đọc theo từng kênh và việc nên làm ở từng điểm nghẽn.",
    breadcrumbName: "Chỉ số TikTok Shop",
    publishedAt: "2026-10-15",
    updatedAt: "2026-10-15",
    category: "metrics",
    cover: blogCover("chi-so-ctr-ctor-aov-v1", "Minh hoạ: bốn cột biểu đồ trên nền hồng nhạt, cột thứ ba thấp nhất tô màu hồng"),
    author: AUTHOR,
    related: ["toi-uu-the-san-pham-tiktok-shop", "cong-cu-cho-nha-ban-tiktok-shop-2026"],
    faq: [
      {
        question: "CTOR khác gì tỷ lệ chuyển đổi?",
        answer:
          "CTOR (Tỷ lệ từ nhấp đến đặt hàng) là tên TikTok đặt năm 2026 cho chỉ số trước đây gọi là Tỷ lệ chuyển đổi trong phân tích sản phẩm. Cách tính không đổi: Đơn hàng SKU chia cho Lượt nhấp vào sản phẩm.",
      },
      {
        question: "Vì sao GMV trên La bàn dữ liệu cao hơn số tiền tôi thực nhận?",
        answer:
          "Theo định nghĩa của TikTok, GMV là tổng số tiền thanh toán cho các đơn hàng trong khoảng thời gian đã chọn, bao gồm cả đơn đã hủy và hoàn tiền. Hãy xem thêm chỉ số Hoàn tiền, và nhớ rằng hoàn tiền thường phát sinh muộn hơn GMV.",
      },
      {
        question: "Nên so sánh chỉ số theo ngày, tuần hay tháng?",
        answer:
          "Với hầu hết shop vừa và nhỏ, so sánh 30 ngày gần nhất với 30 ngày trước đó là ổn định nhất. Cộng tổng lượt hiển thị, lượt nhấp, đơn hàng SKU và GMV của cả kỳ rồi mới tính tỷ lệ, và đánh dấu các ngày sale lớn trong mỗi kỳ.",
      },
      {
        question: "CTR bao nhiêu là tốt?",
        answer:
          "TikTok không công bố một mức CTR chuẩn chung, và CTR khác nhau nhiều giữa các ngành hàng và các kênh. Hãy so CTR của một sản phẩm với chính nó trong kỳ trước và với các sản phẩm khác trong shop, trên cùng một kênh.",
      },
    ],
    sources: [
      academy("Lưu lượng truy cập sản phẩm", "10015238", "định nghĩa chỉ số, đổi tên CTOR, khía cạnh theo kênh (17/06/2026)"),
      academy("Thẻ Sản Phẩm", "6901428203357954", "thẻ sản phẩm và doanh thu không đến từ LIVE, video"),
      academy("Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 1", "7894389511833345"),
      academy("Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 4", "7905983637079809", "ba nhóm Hiển thị, Lợi ích, Sự tin cậy"),
      academy("Chẩn đoán giá", "7563289900353282"),
      academy("Mua Sỉ Giá Hời (BMSM)", "10013310"),
    ],
  },
  {
    slug: "toi-uu-the-san-pham-tiktok-shop",
    status: "draft",
    title: "Tối ưu thẻ sản phẩm TikTok Shop từ A–Z",
    seoTitle: "Tối ưu thẻ sản phẩm TikTok Shop từ A–Z | Juli AI",
    description:
      "Tối ưu ảnh bìa, tiêu đề, mô tả, thuộc tính, giá và khuyến mãi cho thẻ sản phẩm TikTok Shop theo quy định của TikTok, và cách đo kết quả.",
    excerpt:
      "Ảnh bìa, tiêu đề, mô tả, thuộc tính, giá và khuyến mãi: quy định của TikTok, điều nên làm cho từng thành phần, và cách đo một thay đổi bằng cửa sổ trước/sau và ngưỡng dữ liệu.",
    breadcrumbName: "Tối ưu thẻ sản phẩm",
    publishedAt: "2026-10-15",
    updatedAt: "2026-10-15",
    category: "optimize",
    cover: blogCover("the-san-pham-v1", "Minh hoạ: một thẻ sản phẩm viền đen trên nền xanh lá nhạt, dòng giá tô màu xanh lá"),
    author: AUTHOR,
    related: ["chi-so-tiktok-shop-ctr-ctor-aov", "cong-cu-cho-nha-ban-tiktok-shop-2026"],
    faq: [
      {
        question: "Ảnh bìa sản phẩm TikTok Shop cần kích thước bao nhiêu?",
        answer:
          "Chính sách của TikTok yêu cầu hình ảnh tối thiểu 600 × 600 pixel, và bài chẩn đoán thẻ sản phẩm khuyến nghị lớn hơn 1200 × 1200. Hình ảnh chính nên có nền đồng nhất (ưu tiên màu trắng) và sản phẩm chiếm ít nhất 60 % khung hình.",
      },
      {
        question: "Tiêu đề sản phẩm TikTok Shop nên dài bao nhiêu?",
        answer:
          "Bài chẩn đoán thẻ sản phẩm của TikTok ghi tiêu đề phải dài hơn 25 ký tự. Một tiêu đề có loại sản phẩm, đặc điểm chính và quy cách thường dài khoảng 40 ký tự trở lên; không đưa khuyến mãi, tên người bán hay ký tự đặc biệt vào tiêu đề.",
      },
      {
        question: "Sau khi sửa thẻ sản phẩm bao lâu thì đánh giá được kết quả?",
        answer:
          "Juli so sánh 14 ngày trước thay đổi với 7 ngày sau (đọc sơ bộ) và 14 ngày sau (kết luận), chỉ khi sản phẩm đủ ngưỡng dữ liệu, và so với nhóm sản phẩm không thay đổi trong cùng thời gian.",
      },
      {
        question: "Có bắt buộc giảm giá theo đề xuất của Chẩn đoán giá không?",
        answer:
          "Không. Theo Học viện TikTok Shop, không có hình phạt nếu bạn không điều chỉnh theo giá đề xuất; nếu không đạt mức đề xuất, bạn chỉ không nhận được lợi ích traffic bổ sung từ nền tảng.",
      },
    ],
    sources: [
      academy("Tiêu đề, mô tả, hình ảnh và video về sản phẩm", "5918681919178512", "Trung tâm chính sách, 23/04/2026"),
      academy("Thẻ Sản Phẩm", "6901428203357954"),
      academy("Chẩn Đoán Thẻ Sản Phẩm", "5792290376255233"),
      academy("Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 4", "7905983637079809"),
      academy("Trình Tối Ưu Hoá Sản Phẩm", "6532499267012354"),
      academy("Trình Tối Ưu Hóa Tiêu Đề Sản Phẩm", "8617918787323649"),
      academy("Chẩn đoán giá", "7563289900353282"),
      academy("Mua Sỉ Giá Hời (BMSM)", "10013310"),
    ],
  },
  {
    slug: "cong-cu-cho-nha-ban-tiktok-shop-2026",
    status: "draft",
    title: "Top công cụ cho nhà bán TikTok Shop 2026",
    seoTitle: "Top công cụ cho nhà bán TikTok Shop 2026 | Juli AI",
    description:
      "So sánh 4 nhóm công cụ cho nhà bán TikTok Shop 2026: công cụ của TikTok, phần mềm đa kênh, phân tích thị trường và trợ lý AI.",
    excerpt:
      "Công cụ có sẵn của TikTok, phần mềm quản lý đa kênh, công cụ phân tích thị trường và trợ lý AI: mỗi nhóm giải quyết việc gì, mô tả theo thông tin nhà cung cấp công bố (kiểm tra 15/10/2026).",
    breadcrumbName: "Công cụ cho nhà bán 2026",
    publishedAt: "2026-10-15",
    updatedAt: "2026-10-15",
    category: "tools",
    cover: blogCover("cong-cu-2026-v1", "Minh hoạ: sáu ô công cụ xếp hai hàng trên nền xanh dương nhạt, một ô tô màu xanh dương"),
    author: AUTHOR,
    related: ["chi-so-tiktok-shop-ctr-ctor-aov", "toi-uu-the-san-pham-tiktok-shop"],
    faq: [
      {
        question: "Nhà bán TikTok Shop có những công cụ miễn phí nào?",
        answer:
          "Trung tâm nhà bán hàng có sẵn La bàn dữ liệu, Công cụ Tối Ưu Hoá Sản Phẩm, Chẩn Đoán Thẻ Sản Phẩm, Trình Tối Ưu Hóa Tiêu Đề Sản Phẩm và Chẩn đoán giá. Nhiều công cụ bên thứ ba cũng có bản dùng thử.",
      },
      {
        question: "Chỉ bán trên TikTok Shop có cần phần mềm quản lý đa kênh không?",
        answer:
          "Thường là chưa cần trong giai đoạn đầu. Phần mềm đa kênh giải quyết đồng bộ đơn hàng và tồn kho giữa nhiều kênh; nếu bạn chỉ bán trên TikTok Shop với một kho, công cụ có sẵn của TikTok có thể đủ cho phần vận hành.",
      },
      {
        question: "Công cụ phân tích thị trường có cho biết CTR, CTOR của đối thủ không?",
        answer:
          "Không. Lượt hiển thị, CTR và CTOR của từng sản phẩm chỉ chủ shop thấy trong La bàn dữ liệu. Công cụ thị trường quan sát từ bên ngoài, nên doanh số của shop khác là số ước tính.",
      },
      {
        question: "Juli AI có tự thay đổi shop của tôi không?",
        answer:
          "Không. Juli đề xuất hành động kèm lý do, và chỉ thực hiện sau khi bạn phê duyệt. Không có thay đổi nào trên shop nếu bạn chưa đồng ý.",
      },
    ],
    sources: [
      academy("Hướng dẫn sử dụng La bàn Dữ liệu trong Trung tâm Người bán", "10008597"),
      academy("Lưu lượng truy cập sản phẩm", "10015238"),
      academy("Trình Tối Ưu Hoá Sản Phẩm", "6532499267012354"),
      academy("Chẩn Đoán Thẻ Sản Phẩm", "5792290376255233"),
      academy("Trình Tối Ưu Hóa Tiêu Đề Sản Phẩm", "8617918787323649"),
      academy("Chẩn đoán giá", "7563289900353282"),
      academy("Hướng Dẫn Sử Dụng Cửa Hàng Ứng Dụng 2.0", "3068668506670849"),
      academy("Hướng dẫn về Sàn dịch vụ", "10014506"),
      { title: "BigSeller", url: "https://www.bigseller.com", note: "kiểm tra 15/10/2026" },
      { title: "KiotViet", url: "https://www.kiotviet.vn", note: "kiểm tra 15/10/2026" },
      { title: "Sapo", url: "https://www.sapo.vn", note: "kiểm tra 15/10/2026" },
      { title: "Haravan", url: "https://www.haravan.com", note: "kiểm tra 15/10/2026" },
      { title: "FastMoss", url: "https://www.fastmoss.com", note: "kiểm tra 15/10/2026" },
      { title: "Kalodata", url: "https://www.kalodata.com", note: "kiểm tra 15/10/2026" },
      { title: "Juli AI", url: "https://app-juli.com", note: "sản phẩm của chúng tôi" },
    ],
  },
];
