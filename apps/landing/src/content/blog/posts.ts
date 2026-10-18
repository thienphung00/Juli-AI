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

/**
 * A competitor or vendor page (D56 G2): cited by name and check date, never
 * linked. `checkedAt` is `YYYY-MM-DD`; the page renders "kiểm tra DD/MM/YYYY".
 */
const vendor = (title: string, checkedAt: string, note?: string): BlogSource => ({
  title,
  checkedAt,
  ...(note ? { note } : {}),
});

export const BLOG_POSTS: readonly BlogPostMeta[] = [
  {
    slug: "chi-so-tiktok-shop-ctr-ctor-aov",
    status: "published",
    title: "Các chỉ số TikTok Shop: Lượt hiển thị, CTR, CTOR, AOV và cách đọc đúng",
    seoTitle: "Chỉ số TikTok Shop: CTR, CTOR, AOV đọc đúng | Juli AI",
    description:
      "Lượt hiển thị, CTR, CTOR, AOV theo đúng định nghĩa của TikTok, công thức GMV theo phễu, cách đọc theo 5 kênh và các lỗi đọc số hay gặp.",
    excerpt:
      "Định nghĩa bốn chỉ số cốt lõi theo đúng cách TikTok công bố, công thức GMV = Lượt hiển thị × CTR × CTOR × AOV, cách đọc theo từng kênh và việc nên làm ở từng điểm nghẽn.",
    breadcrumbName: "Chỉ số TikTok Shop",
    publishedAt: "2026-10-17",
    updatedAt: "2026-10-17",
    category: "metrics",
    format: "pillar",
    cover: blogCover("hero-chi-so-tiktok-shop-ctr-ctor-aov-v1", "Minh hoạ: đồng hồ đo có kim chỉ vào vùng hồng và một chiếc kính lúp, nền hồng nhạt, chữ “Đọc đúng chỉ số”"),
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
    status: "published",
    title: "Tối ưu thẻ sản phẩm TikTok Shop từ A–Z",
    seoTitle: "Tối ưu thẻ sản phẩm TikTok Shop từ A–Z | Juli AI",
    description:
      "Tối ưu ảnh bìa, tiêu đề, mô tả, thuộc tính, giá và khuyến mãi cho thẻ sản phẩm TikTok Shop theo quy định của TikTok, và cách đo kết quả.",
    excerpt:
      "Ảnh bìa, tiêu đề, mô tả, thuộc tính, giá và khuyến mãi: quy định của TikTok, điều nên làm cho từng thành phần, và cách đo một thay đổi bằng cửa sổ trước/sau và ngưỡng dữ liệu.",
    breadcrumbName: "Tối ưu thẻ sản phẩm",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "optimize",
    format: "pillar",
    cover: blogCover("hero-toi-uu-the-san-pham-tiktok-shop-v1", "Minh hoạ: thẻ sản phẩm có ảnh chai, dòng tên và dòng giá xanh lá bên cạnh ba thanh trượt chỉnh, nền xanh lá nhạt, chữ “Tối ưu thẻ sản phẩm”"),
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
    status: "published",
    title: "Top công cụ cho nhà bán TikTok Shop 2026",
    seoTitle: "Top công cụ cho nhà bán TikTok Shop 2026 | Juli AI",
    description:
      "So sánh 4 nhóm công cụ cho nhà bán TikTok Shop 2026: công cụ của TikTok, phần mềm đa kênh, phân tích thị trường và trợ lý AI.",
    excerpt:
      "Công cụ có sẵn của TikTok, phần mềm quản lý đa kênh, công cụ phân tích thị trường và trợ lý AI: mỗi nhóm giải quyết việc gì, mô tả theo thông tin nhà cung cấp công bố (kiểm tra 15/10/2026).",
    breadcrumbName: "Công cụ cho nhà bán 2026",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "tools",
    format: "comparison",
    cover: blogCover("hero-cong-cu-cho-nha-ban-tiktok-shop-2026-v1", "Minh hoạ: hộp đồ nghề xanh ngọc có thước, tua vít và cờ lê nhô lên, nền xanh ngọc nhạt, chữ “Bộ công cụ nhà bán”"),
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
      vendor("BigSeller", "2026-10-15"),
      vendor("KiotViet", "2026-10-15"),
      vendor("Sapo", "2026-10-15"),
      vendor("Haravan", "2026-10-15"),
      vendor("FastMoss", "2026-10-15"),
      vendor("Kalodata", "2026-10-15"),
      { title: "Juli AI", url: "https://app-juli.com", note: "sản phẩm của chúng tôi" },
    ],
  },
  {
    slug: "gmv-la-gi-tiktok-shop",
    status: "published",
    title: "GMV là gì? Cách tính và cách tăng GMV TikTok Shop",
    seoTitle: "GMV là gì? Cách tính, cách tăng GMV TikTok Shop | Juli AI",
    description:
      "GMV là gì theo định nghĩa của TikTok, GMV khác doanh thu thực nhận ra sao, cách tính GMV theo từng luồng truy cập và cách tăng GMV ở bước yếu nhất.",
    excerpt:
      "Định nghĩa GMV theo Học viện TikTok Shop, vì sao GMV lớn hơn số tiền về tài khoản, công thức GMV = Lượt hiển thị × CTR × CTOR × AOV theo năm luồng, và cách tìm bước yếu nhất để tăng GMV.",
    breadcrumbName: "GMV là gì",
    publishedAt: "2026-10-17",
    updatedAt: "2026-10-17",
    category: "metrics",
    format: "pillar",
    cover: blogCover("hero-gmv-la-gi-tiktok-shop-v1", "Minh hoạ: túi mua sắm với ba đồng xu vàng bay lên và mũi tên hồng hướng lên, nền vàng nhạt, chữ “GMV là gì”"),
    author: AUTHOR,
    related: ["chi-so-tiktok-shop-ctr-ctor-aov", "doanh-thu-tiktok-shop-giam", "tiktok-shop-khong-ra-don"],
    faq: [
      {
        question: "GMV là gì?",
        answer:
          "GMV là tổng giá trị hàng hóa giao dịch. Trên TikTok Shop, Học viện TikTok Shop định nghĩa GMV là tổng số tiền thanh toán cho các đơn hàng trong khoảng thời gian đã chọn, bao gồm cả đơn đã hủy và hoàn tiền.",
      },
      {
        question: "GMV có phải là doanh thu thực nhận không?",
        answer:
          "Không. GMV vẫn tính đơn đã hủy và hoàn tiền, và chưa trừ phí. Số tiền về Số dư Nhà bán hàng là số tiền quyết toán, sau khi trừ tất cả các khoản phí, theo chu kỳ tiêu chuẩn (D+6)+1 tính từ ngày giao hàng.",
      },
      {
        question: "Cách tính GMV TikTok Shop theo phễu như thế nào?",
        answer:
          "GMV = Lượt hiển thị sản phẩm × CTR × CTOR × AOV (SKU), với cả bốn chỉ số lấy trên cùng sản phẩm, cùng luồng truy cập và cùng khoảng thời gian. Đẳng thức suy ra trực tiếp từ định nghĩa các chỉ số của TikTok.",
      },
      {
        question: "Cách tăng GMV trên TikTok nhanh nhất là gì?",
        answer:
          "Không có một cách chung cho mọi shop. Hãy tìm luồng truy cập có GMV thay đổi nhiều nhất, rồi tìm chỉ số yếu nhất trong luồng đó: lượt hiển thị thấp thì xem tiêu đề và nội dung, CTR thấp thì xem ảnh bìa và giá, CTOR thấp thì xem mô tả và đánh giá, AOV thấp thì xem chương trình mua nhiều.",
      },
    ],
    sources: [
      academy("Lưu lượng truy cập sản phẩm", "10015238", "định nghĩa GMV, các loại GMV, thời điểm ghi nhận hoàn tiền, khía cạnh theo kênh (17/06/2026)"),
      {
        title: "Học viện TikTok Shop: Tài Chính cho Người Mới Bắt Đầu: Hướng Dẫn về Phương Thức và Thời Điểm Bạn Được Thanh Toán",
        url: "https://seller-vn.tiktok.com/university/essay?knowledge_id=825773561448193",
        note: "quyết toán sau khi trừ phí, chu kỳ (D+6)+1, ghi nhận dồn tích (01/12/2023)",
      },
      academy("Thẻ Sản Phẩm", "6901428203357954", "doanh thu không đến từ LIVE, video được tính cho thẻ sản phẩm"),
      academy("Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 1", "7894389511833345", "ngưỡng vào nhóm đề xuất, vận hành cửa hàng"),
      academy("Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 4", "7905983637079809", "ba nhóm Hiển thị, Lợi ích, Sự tin cậy"),
      academy("Chẩn đoán giá", "7563289900353282"),
      academy("Mua Sỉ Giá Hời (BMSM)", "10013310"),
    ],
  },
  {
    slug: "tiktok-shop-khong-ra-don",
    status: "published",
    title: "TikTok Shop không ra đơn: đọc phễu để tìm nguyên nhân",
    seoTitle: "TikTok Shop không ra đơn: đọc phễu tìm nguyên nhân | Juli AI",
    description:
      "Vì sao TikTok Shop không ra đơn: kiểm tra trạng thái sản phẩm, rồi đọc Lượt hiển thị, CTR, CTOR từng bước, và việc cần xem trước khi tăng quảng cáo.",
    excerpt:
      "Coi \"không ra đơn\" là triệu chứng: loại trừ trạng thái sản phẩm, tồn kho và vận hành, rồi đọc phễu Lượt hiển thị, CTR, CTOR để biết đơn hàng bị chặn ở bước nào, kèm danh sách kiểm tra và câu hỏi trước khi tăng ngân sách quảng cáo.",
    breadcrumbName: "TikTok Shop không ra đơn",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "guide",
    format: "pain",
    cover: blogCover("hero-tiktok-shop-khong-ra-don-v1", "Minh hoạ: chiếc chuông báo đơn trên quầy nằm im với chữ z z và một phiếu đơn trống viền nét đứt, nền xám nhạt, chữ “Shop không ra đơn”"),
    author: AUTHOR,
    guide: "doc-phan-tich-tiktok-shop-theo-luong-truy-cap",
    related: ["khach-xem-nhung-khong-mua-tiktok-shop", "san-pham-tiktok-shop-khong-co-luot-hien-thi", "gmv-la-gi-tiktok-shop"],
    faq: [
      {
        question: "Vì sao bán hàng trên TikTok Shop không ra đơn?",
        answer:
          "Đơn hàng bị chặn ở một trong ba bước: không ai nhìn thấy sản phẩm (Lượt hiển thị thấp), thấy mà không nhấp (CTR thấp), hoặc nhấp mà không mua (CTOR thấp). Trước đó, hãy kiểm tra sản phẩm có ở trạng thái Trực tuyến và còn hàng ở các biến thể chính không.",
      },
      {
        question: "Chạy quảng cáo TikTok Shop mà không ra đơn thì nên làm gì?",
        answer:
          "Trước khi tăng ngân sách, hãy đọc CTR và CTOR ở luồng thẻ sản phẩm. Quảng cáo đưa thêm người xem đến sản phẩm nhưng không sửa được trang sản phẩm; nếu CTOR đang thấp, sửa ảnh, mô tả, giá hay đánh giá trước rồi mới mua thêm traffic.",
      },
      {
        question: "Shop mới bao lâu thì đọc được chỉ số?",
        answer:
          "Hãy dùng cửa sổ ít nhất 14 ngày và chỉ đọc tỷ lệ khi đủ dữ liệu, theo một ngưỡng bạn tự đặt và giữ nguyên, ví dụ trung bình mỗi ngày từ 50 lượt hiển thị mới đọc CTR và từ 20 lượt nhấp mới đọc CTOR. Đó không phải quy định của TikTok; dưới ngưỡng, vấn đề thường là chưa đủ người nhìn thấy sản phẩm.",
      },
      {
        question: "Giảm giá có giúp shop ra đơn không?",
        answer:
          "Chỉ khi bước yếu là CTR do giá hiển thị hoặc CTOR do giá. Giảm giá không làm sản phẩm xuất hiện nhiều hơn trong tìm kiếm, và lấy đi biên lợi nhuận của mọi đơn. Hãy tìm bước nghẽn trước.",
      },
    ],
    sources: [
      academy("Lưu lượng truy cập sản phẩm", "10015238", "định nghĩa chỉ số, Tỷ lệ thêm vào giỏ hàng, khía cạnh theo kênh (17/06/2026)"),
      academy("Quản lý Sản phẩm", "10008556", "trạng thái Trực tuyến, Đã vô hiệu hóa, Đã tạm ngưng, Bản nháp (27/08/2026)"),
      academy("Thẻ Sản Phẩm", "6901428203357954"),
      academy("Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 1", "7894389511833345", "ngưỡng vào nhóm đề xuất, vận hành cửa hàng"),
      academy("Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 4", "7905983637079809", "ba nhóm yếu tố, tồn kho theo SKU"),
      academy("Tiêu đề, mô tả, hình ảnh và video về sản phẩm", "5918681919178512", "Trung tâm chính sách, 23/04/2026"),
      academy("Trình Tối Ưu Hóa Tiêu Đề Sản Phẩm", "8617918787323649"),
      academy("Chẩn đoán giá", "7563289900353282"),
    ],
  },
  {
    slug: "doanh-thu-tiktok-shop-giam",
    status: "published",
    title: "Doanh thu TikTok Shop giảm: checklist tìm nguyên nhân theo từng luồng",
    seoTitle: "Doanh thu TikTok Shop giảm: checklist nguyên nhân | Juli AI",
    description:
      "Phân tích doanh thu TikTok Shop khi GMV giảm: so sánh hai kỳ cho đúng, tách theo năm luồng và bốn chỉ số, danh sách kiểm tra cho từng luồng.",
    excerpt:
      "So sánh hai kỳ cho công bằng, tách mức giảm GMV theo năm luồng truy cập và theo Lượt hiển thị × CTR × CTOR × AOV, rồi đi qua danh sách nguyên nhân cho từng luồng, từng chỉ số và từng sản phẩm.",
    breadcrumbName: "Doanh thu TikTok Shop giảm",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "metrics",
    format: "pain",
    cover: blogCover("hero-doanh-thu-tiktok-shop-giam-v1", "Minh hoạ: biểu đồ đường đi ngang rồi rơi xuống, kính lúp soi điểm rơi màu hồng, nền xanh dương nhạt, chữ “Doanh thu giảm”"),
    author: AUTHOR,
    guide: "tim-san-pham-keo-gmv-xuong-tiktok-shop",
    related: ["doanh-thu-sau-sale-tiktok-shop", "ty-le-hoan-hang-tiktok-shop", "gmv-la-gi-tiktok-shop"],
    faq: [
      {
        question: "Doanh thu TikTok Shop giảm thì kiểm tra gì đầu tiên?",
        answer:
          "Kiểm tra cách so sánh: hai kỳ dài bằng nhau, cùng loại GMV, đánh dấu ngày sale lớn và không tính ngày hôm nay. Sau đó tách GMV theo năm luồng truy cập để biết mức giảm nằm ở đâu.",
      },
      {
        question: "Nên so sánh doanh thu theo tuần hay theo tháng?",
        answer:
          "Với hầu hết shop vừa và nhỏ, 30 ngày gần nhất so với 30 ngày trước đó ổn định hơn so sánh theo tuần. Nếu so theo tuần, hãy bắt đầu hai kỳ cùng một thứ trong tuần.",
      },
      {
        question: "Vì sao tiền về giảm nhưng GMV không giảm?",
        answer:
          "GMV vẫn tính đơn đã hủy và hoàn tiền. Nếu tiền về giảm trong khi GMV giữ nguyên, hãy xem số đơn hủy, hoàn tiền, các khoản phí và đơn chưa đến hạn quyết toán, thay vì sửa trang sản phẩm.",
      },
      {
        question: "Làm sao biết mức giảm là thật hay chỉ là dao động?",
        answer:
          "So mức giảm với mức dao động thường thấy của shop trong vài kỳ gần đây. Chỉ coi một so sánh là rõ khi mỗi kỳ có đủ đơn, ví dụ từ 30 đơn hàng trở lên, và mức giảm lớn hơn mức chênh thường thấy; dưới mức đó là dấu hiệu để theo dõi tiếp.",
      },
    ],
    sources: [
      academy("Lưu lượng truy cập sản phẩm", "10015238", "định nghĩa GMV và chỉ số, thời điểm ghi nhận hoàn tiền, khía cạnh theo kênh (17/06/2026)"),
      {
        title: "Học viện TikTok Shop: Tài Chính cho Người Mới Bắt Đầu: Hướng Dẫn về Phương Thức và Thời Điểm Bạn Được Thanh Toán",
        url: "https://seller-vn.tiktok.com/university/essay?knowledge_id=825773561448193",
        note: "quyết toán sau khi trừ phí, chu kỳ (D+6)+1 (01/12/2023)",
      },
      academy("Quản lý Sản phẩm", "10008556", "trạng thái sản phẩm (27/08/2026)"),
      academy("Thẻ Sản Phẩm", "6901428203357954"),
      academy("Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 1", "7894389511833345"),
      academy("Chẩn đoán giá", "7563289900353282"),
      academy("Mua Sỉ Giá Hời (BMSM)", "10013310"),
    ],
  },
  {
    slug: "phan-mem-quan-ly-ban-hang-da-kenh-2026",
    status: "published",
    title: "Phần mềm quản lý bán hàng đa kênh 2026: 7 lựa chọn có kết nối TikTok Shop",
    seoTitle: "Phần mềm quản lý bán hàng đa kênh 2026 | Juli AI",
    description:
      "So sánh 7 phần mềm bán hàng đa kênh 2026 có kết nối TikTok Shop, Shopee: tính năng, giá công bố, bản miễn phí và cách chọn theo mô hình bán hàng.",
    excerpt:
      "BigSeller, Haravan, KiotViet, MISA eShop, Nhanh.vn, Pancake POS và Sapo: mỗi phần mềm làm gì với TikTok Shop và các sàn, giá như nhà cung cấp công bố (kiểm tra 16/10/2026), và câu hỏi nên kiểm tra khi dùng thử.",
    breadcrumbName: "Phần mềm bán hàng đa kênh 2026",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "tools",
    format: "comparison",
    cover: blogCover("hero-phan-mem-quan-ly-ban-hang-da-kenh-2026-v1", "Minh hoạ: một nút trung tâm màu hồng nối với năm cửa hàng nhỏ, nền xanh dương đậm, chữ “Quản lý đa kênh”"),
    author: AUTHOR,
    related: ["cong-cu-cho-nha-ban-tiktok-shop-2026", "cong-cu-phan-tich-tiktok-shop-2026", "cong-cu-ai-tao-anh-video-san-pham-tiktok-shop"],
    faq: [
      {
        question: "Phần mềm quản lý bán hàng đa kênh nào có bản miễn phí?",
        answer:
          "Theo trang chính thức ngày 16/10/2026, BigSeller có phiên bản miễn phí lâu dài với 1.500 đơn mỗi tháng, và trang Pancake POS ghi là nền tảng miễn phí. Haravan cho dùng thử 14 ngày; Sapo và Nhanh.Ecom cho dùng thử 7 ngày; KiotViet và MISA eShop có dùng thử miễn phí.",
      },
      {
        question: "Chỉ bán trên TikTok Shop có cần phần mềm quản lý bán hàng đa kênh không?",
        answer:
          "Thường là chưa cần trong giai đoạn đầu. Phần mềm đa kênh giải quyết đồng bộ đơn và tồn kho giữa nhiều kênh; nếu bạn chỉ bán trên TikTok Shop với một kho, Trung tâm nhà bán hàng có thể đủ cho phần vận hành.",
      },
      {
        question: "Phần mềm quản lý Shopee, TikTok Shop kết nối với shop như thế nào?",
        answer:
          "Bạn chọn kênh trong phần mềm, đăng nhập tài khoản TikTok Shop hoặc Shopee rồi ủy quyền cho phần mềm. Ví dụ, tài liệu của Pancake POS mô tả các bước chọn kênh bán, cài đặt đồng bộ với kho, đăng nhập TikTok Shop và xác nhận ủy quyền. Hãy đọc kỹ danh sách quyền trước khi đồng ý.",
      },
      {
        question: "Phần mềm đa kênh có cho biết vì sao doanh thu TikTok Shop giảm không?",
        answer:
          "Phần mềm đa kênh có báo cáo doanh thu, lợi nhuận và chi phí theo kênh và sản phẩm. Các chỉ số phễu như Lượt hiển thị sản phẩm, CTR và CTOR theo từng luồng truy cập nằm trong La bàn dữ liệu của TikTok Shop.",
      },
    ],
    sources: [
      vendor("BigSeller: Phần mềm quản lý bán hàng đa kênh miễn phí", "2026-10-16"),
      vendor("BigSeller: Bảng giá", "2026-10-16"),
      vendor("Haravan", "2026-10-16"),
      vendor("Haravan: Bảng giá", "2026-10-16"),
      vendor("KiotViet: Giải pháp bán hàng đa kênh", "2026-10-16"),
      vendor("KiotViet: Phí dịch vụ", "2026-10-16"),
      vendor("MISA eShop", "2026-10-16"),
      vendor("Nhanh.vn: Bảng giá phần mềm", "2026-10-16"),
      vendor("Nhanh.vn: Nhanh.Ecom", "2026-10-16"),
      vendor("Pancake POS", "2026-10-16"),
      vendor("Pancake POS: Kênh bán (tài liệu hướng dẫn)", "2026-10-16"),
      vendor("Sapo: Giải pháp bán hàng trên TikTok Shop", "2026-10-16"),
      vendor("Sapo: Bảng giá", "2026-10-16"),
    ],
  },
  {
    slug: "cong-cu-phan-tich-tiktok-shop-2026",
    status: "published",
    title: "Công cụ phân tích TikTok Shop 2026: soi thị trường và đọc dữ liệu shop của bạn",
    seoTitle: "Công cụ phân tích TikTok Shop 2026 | Juli AI",
    description:
      "Tool phân tích TikTok Shop 2026: La bàn dữ liệu, FastMoss, Kalodata, Metric. Công cụ soi thị trường khác gì công cụ đọc dữ liệu shop của bạn, giá công bố.",
    excerpt:
      "Hai nhóm công cụ phân tích dữ liệu TikTok Shop theo nguồn dữ liệu: soi thị trường và đối thủ (FastMoss, Kalodata, Metric) và đọc dữ liệu shop của bạn (La bàn dữ liệu, Juli AI), mô tả theo trang chính thức (kiểm tra 16/10/2026).",
    breadcrumbName: "Công cụ phân tích TikTok Shop",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "tools",
    format: "comparison",
    cover: blogCover("hero-cong-cu-phan-tich-tiktok-shop-2026-v1", "Minh hoạ: ống nhòm hướng về một đám chấm dữ liệu, một chấm tím nổi bật, nền tím nhạt, chữ “Soi thị trường”"),
    author: AUTHOR,
    related: ["cong-cu-cho-nha-ban-tiktok-shop-2026", "gmv-la-gi-tiktok-shop", "tiktok-shop-khong-ra-don"],
    faq: [
      {
        question: "Công cụ phân tích thị trường có cho biết CTR, CTOR của shop đối thủ không?",
        answer:
          "Không. Các chỉ số phễu như Lượt hiển thị sản phẩm, CTR và CTOR hiển thị trong Trung tâm nhà bán hàng của chủ shop. Công cụ thị trường quan sát từ bên ngoài, nên doanh số của shop khác là số ước tính.",
      },
      {
        question: "Tool phân tích TikTok Shop nào có dữ liệu Việt Nam?",
        answer:
          "Theo trang chính thức ngày 16/10/2026: gói thành viên FastMoss gồm sáu nước Đông Nam Á có Việt Nam; Kalodata có trang xếp hạng sản phẩm Việt Nam bằng tiếng Việt; Metric phân tích các sàn Shopee, Tiki, Lazada, Sendo và TikTok Shop tại Việt Nam.",
      },
      {
        question: "Nên dùng công cụ soi thị trường hay công cụ phân tích shop trước?",
        answer:
          "Nếu shop đã có đơn, hãy đọc dữ liệu shop của bạn trước để tìm luồng và bước yếu nhất, rồi mới nhìn ra thị trường cho đúng câu hỏi đó. Nếu bạn đang chọn sản phẩm mới, công cụ thị trường là điểm bắt đầu.",
      },
      {
        question: "Juli AI có cho xem doanh số của đối thủ không?",
        answer:
          "Không. Juli AI là sản phẩm của chúng tôi và chỉ đọc dữ liệu của shop bạn qua kết nối chính thức mà bạn ủy quyền. Để xem sản phẩm và doanh số ước tính của shop khác, hãy dùng công cụ phân tích thị trường.",
      },
    ],
    sources: [
      academy("Hướng dẫn sử dụng La bàn Dữ liệu trong Trung tâm Người bán", "10008597", "các mô-đun của La bàn dữ liệu (13/12/2022), kiểm tra 16/10/2026"),
      academy("Lưu lượng truy cập sản phẩm", "10015238", "đường dẫn và mục đích của mô-đun (17/06/2026), kiểm tra 16/10/2026"),
      vendor("FastMoss (tiếng Việt)", "2026-10-16"),
      vendor("FastMoss: Bảng giá", "2026-10-16"),
      vendor("Kalodata", "2026-10-16", "câu hỏi thường gặp"),
      vendor("Kalodata: Bảng xếp hạng sản phẩm Việt Nam TikTok", "2026-10-16"),
      vendor("Metric", "2026-10-16"),
      vendor("Metric Analytics: Bảng giá dịch vụ", "2026-10-16"),
      vendor("Metric: Trung tâm hỗ trợ", "2026-10-16"),
      { title: "Juli AI", url: "https://app-juli.com", note: "sản phẩm của chúng tôi" },
    ],
  },
  {
    slug: "cong-cu-ai-tao-anh-video-san-pham-tiktok-shop",
    status: "published",
    title: "Công cụ AI tạo ảnh và video sản phẩm cho nhà bán TikTok Shop",
    seoTitle: "AI tạo ảnh, video sản phẩm cho TikTok Shop | Juli AI",
    description:
      "AI tạo ảnh sản phẩm và video sản phẩm cho nhà bán TikTok Shop: Canva, CapCut, Higgsfield, Photoroom, Pippit, Symphony. Tính năng, giá công bố, cách chọn.",
    excerpt:
      "Sáu công cụ AI cho người bán hàng: xóa nền, tạo cảnh sản phẩm, người mẫu ảo, video từ ảnh và đường liên kết, nhân vật đại diện. Mô tả theo trang chính thức (kiểm tra 16/10/2026), cách chọn theo việc cần làm và cách đo kết quả.",
    breadcrumbName: "AI tạo ảnh, video sản phẩm",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "tools",
    format: "comparison",
    cover: blogCover("hero-cong-cu-ai-tao-anh-video-san-pham-tiktok-shop-v1", "Minh hoạ: bảng clapper quay phim có nút phát hồng và cây đũa phép toả ánh sáng, nền tím mận đậm, chữ “Ảnh và video AI”"),
    author: AUTHOR,
    related: ["cong-cu-cho-nha-ban-tiktok-shop-2026", "toi-uu-the-san-pham-tiktok-shop", "phan-mem-quan-ly-ban-hang-da-kenh-2026"],
    faq: [
      {
        question: "Có công cụ AI tạo video sản phẩm miễn phí không?",
        answer:
          "Có. Theo trang chính thức ngày 16/10/2026, CapCut, Pippit và Canva có gói miễn phí với giới hạn lượt dùng AI hoặc điểm tín dụng, và TikTok gọi Symphony Creative Studio là công cụ tạo miễn phí, có cơ chế tín dụng riêng.",
      },
      {
        question: "Dùng ảnh tạo bằng AI cho thẻ sản phẩm TikTok Shop có được không?",
        answer:
          "Hãy đọc bản hiện hành của chính sách hình ảnh sản phẩm và quy định về nội dung do AI tạo của TikTok trước khi đăng. Dù dùng công cụ nào, ảnh phải đúng với sản phẩm giao cho khách: AI nên thay nền và bối cảnh, không thay màu sắc, kích thước hay số lượng của sản phẩm.",
      },
      {
        question: "Nên làm lại ảnh bìa hay làm video trước?",
        answer:
          "Xem chỉ số trước. Nếu sản phẩm có nhiều lượt hiển thị mà CTR thấp, ảnh bìa là nơi đáng thử đầu tiên. Nếu CTR ổn mà CTOR thấp, hãy xem bộ ảnh chi tiết, mô tả, giá và đánh giá. Video ngắn là một luồng truy cập riêng, nên đọc chỉ số của luồng video.",
      },
    ],
    sources: [
      vendor("Canva: Mức giá", "2026-10-16"),
      vendor("CapCut (tiếng Việt)", "2026-10-16"),
      vendor("CapCut: Giá", "2026-10-16"),
      vendor("Higgsfield: Ads Studio", "2026-10-16"),
      vendor("Higgsfield: Marketing Studio", "2026-10-16"),
      vendor("Higgsfield: Pricing", "2026-10-16"),
      vendor("Photoroom (tiếng Việt)", "2026-10-16"),
      vendor("Photoroom: Bảng giá", "2026-10-16"),
      vendor("Pippit (tiếng Việt)", "2026-10-16"),
      vendor("Pippit: Giá và gói", "2026-10-16"),
      {
        title: "TikTok for Business: Giới thiệu về Symphony Creative Studio",
        url: "https://ads.tiktok.com/help/article/about-symphony-creative-studio?lang=vi",
        note: "cập nhật tháng 6/2026, kiểm tra 16/10/2026",
      },
    ],
  },
  {
    slug: "san-pham-tiktok-shop-khong-co-luot-hien-thi",
    status: "published",
    title: "Sản phẩm TikTok Shop không có lượt hiển thị: bị ẩn hay chỉ ít người thấy",
    seoTitle: "Sản phẩm TikTok Shop không có lượt hiển thị | Juli AI",
    description:
      "Sản phẩm đăng lên mà không ai thấy: kiểm tra trạng thái trước, rồi đọc Lượt hiển thị theo năm luồng cùng CTR, sửa đúng chỗ và đo lại ở ngày 7, ngày 14.",
    excerpt:
      "Tách hai trường hợp: sản phẩm không hiện với người mua (trạng thái, bị từ chối, vi phạm) và sản phẩm có hiện nhưng ít người thấy. Rồi đọc Lượt hiển thị theo luồng truy cập, đọc cùng CTR, và đo lại sau khi sửa.",
    breadcrumbName: "Sản phẩm không có lượt hiển thị",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "guide",
    format: "pain",
    cover: blogCover("hero-san-pham-tiktok-shop-khong-co-luot-hien-thi-v1", "Minh hoạ: đèn chiếu rọi xuống một kệ trống chỉ có khung sản phẩm nét đứt và biểu tượng con mắt bị gạch, nền đen, chữ “Không ai nhìn thấy”"),
    author: AUTHOR,
    guide: "doc-phan-tich-tiktok-shop-theo-luong-truy-cap",
    related: ["tiktok-shop-khong-ra-don", "dat-ten-san-pham-tiktok-shop", "gmv-la-gi-tiktok-shop"],
    faq: [
      {
        question: "Tại sao TikTok Shop không hiện sản phẩm của tôi?",
        answer:
          "Kiểm tra trạng thái trong Quản lý sản phẩm trước. Chỉ sản phẩm Trực tuyến mới đến được người mua; Bản nháp, Đã vô hiệu hóa và Đã tạm ngưng thì không. Nếu sản phẩm Trực tuyến và có Lượt hiển thị, sản phẩm đang hiện, chỉ là ít người thấy.",
      },
      {
        question: "Lượt hiển thị sản phẩm bao nhiêu là thấp?",
        answer:
          "TikTok không công bố một mức chuẩn chung. Hãy so Lượt hiển thị của sản phẩm với chính nó ở kỳ trước và với các sản phẩm khác của shop trên cùng luồng, trên khoảng 28 đến 30 ngày.",
      },
      {
        question: "Sản phẩm bị tạm ngưng thì làm sao?",
        answer:
          "Theo Học viện TikTok Shop, sản phẩm Đã tạm ngưng vì thông tin chưa tuân thủ thì sửa và gửi lại được; sản phẩm bị đóng băng vì hàng cấm hoặc hàng giả thì không. Đọc lý do trong Trung tâm nhà bán hàng, sửa đúng điểm đó rồi gửi lại.",
      },
      {
        question: "Sửa tiêu đề bao lâu thì thấy thay đổi về lượt hiển thị?",
        answer:
          "Không có thời gian cố định. Hãy lấy 14 ngày trước thay đổi làm mốc, đọc sơ bộ ở ngày 7 và chốt ở ngày 14, so với các sản phẩm không thay đổi, để tách tác động của thay đổi khỏi dao động thường ngày.",
      },
      {
        question: "Có nên xóa sản phẩm ít lượt hiển thị rồi đăng lại?",
        answer:
          "Không có trang chính thức nào của TikTok nói việc này giúp tăng lượt hiển thị, và bạn mất lịch sử đánh giá cùng số liệu để so sánh. Hãy tìm luồng đang thiếu và sửa đúng chỗ trước.",
      },
    ],
    sources: [
      academy("Quản lý Sản phẩm", "10008556", "trạng thái Trực tuyến, Đã vô hiệu hóa, Đã tạm ngưng, Bản nháp, Xóa (27/08/2026)"),
      academy("Lưu lượng truy cập sản phẩm", "10015238", "định nghĩa Lượt hiển thị sản phẩm, CTR, khía cạnh theo kênh (17/06/2026)"),
      academy("Thẻ Sản Phẩm", "6901428203357954", "sản phẩm đủ điều kiện làm thẻ, doanh thu không đến từ LIVE, video"),
      academy("Trình Tối Ưu Hoá Sản Phẩm", "6532499267012354", "vị trí công cụ, thông tin chất lượng cao giúp tăng lưu lượng (04/08/2025)"),
      academy("Tiêu đề, mô tả, hình ảnh và video về sản phẩm", "5918681919178512", "Trung tâm chính sách, 23/04/2026"),
      academy("Trình Tối Ưu Hóa Tiêu Đề Sản Phẩm", "8617918787323649"),
    ],
  },
  {
    slug: "thue-ban-hang-tiktok-shop",
    status: "published",
    title: "Thuế bán hàng TikTok Shop 2026: sàn khấu trừ thế nào, người bán cần làm gì",
    seoTitle: "Thuế bán hàng TikTok Shop 2026: sàn khấu trừ | Juli AI",
    description:
      "Từ 01/07/2026 sàn TMĐT khấu trừ thuế GTGT, TNCN cho người bán theo Nghị định 252/2026; ngưỡng 1 tỷ đồng, hoàn thuế, việc cần chuẩn bị.",
    excerpt:
      "Tóm tắt từ văn bản chính thức: sàn có chức năng đặt hàng và thanh toán khấu trừ, nộp thay thuế trên từng giao dịch; doanh thu năm từ 1 tỷ đồng trở xuống không chịu thuế; người bán cần cung cấp gì và khi nào phải tự quyết toán. Cập nhật ngày 17/10/2026.",
    breadcrumbName: "Thuế bán hàng TikTok Shop",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "guide",
    format: "news",
    cover: blogCover("hero-thue-ban-hang-tiktok-shop-v1", "Minh hoạ: tờ văn bản có con dấu tròn đánh dấu đã kiểm, nền màu cát nhạt, chữ “Thuế bán hàng”"),
    author: AUTHOR,
    guide: "doc-phan-tich-tiktok-shop-theo-luong-truy-cap",
    related: ["phi-san-tiktok-shop-2026", "ty-le-hoan-hang-tiktok-shop", "gmv-la-gi-tiktok-shop"],
    faq: [
      {
        question: "Bán hàng trên TikTok Shop có phải đóng thuế không?",
        answer:
          "Hộ, cá nhân kinh doanh có doanh thu cả năm trên 1 tỷ đồng phải nộp thuế GTGT và TNCN; từ 1 tỷ đồng trở xuống thì không (Nghị định 68/2026/NĐ-CP, đã sửa bởi Nghị định 141/2026/NĐ-CP). Từ 01/07/2026, sàn có chức năng đặt hàng và thanh toán khấu trừ, nộp thay thuế trên từng giao dịch (Nghị định 252/2026/NĐ-CP).",
      },
      {
        question: "Sàn đã khấu trừ rồi, tôi có phải khai thuế nữa không?",
        answer:
          "Sàn khai và nộp thay số thuế đã khấu trừ. Người có doanh thu cả năm trên 3 tỷ đồng, hoặc trên 1 tỷ đồng và chọn tính thuế theo thu nhập, vẫn phải tổng hợp doanh thu để quyết toán TNCN theo năm; số sàn đã trừ được trừ vào số phải nộp (Nghị định 68, Điều 11).",
      },
      {
        question: "Doanh thu dưới 1 tỷ đồng mà đã bị trừ thuế thì lấy lại thế nào?",
        answer:
          "Nghị định 68, Điều 12 cho phép làm thủ tục bù trừ, hoàn trả số thuế nộp thừa. Người chỉ bán trên sàn đã được khấu trừ nộp hồ sơ tại cơ quan thuế quản lý nơi cư trú. Hãy hỏi cơ quan thuế về hồ sơ cụ thể.",
      },
      {
        question: "Đơn hủy, hoàn hàng thì thuế đã trừ có được trả lại không?",
        answer:
          "Có. Theo Nghị định 252, sàn bù trừ số thuế của giao dịch bị hủy hoặc trả lại hàng khi khai theo tháng, và phải trả lại đầy đủ, kịp thời số thuế đã khấu trừ của các giao dịch đó.",
      },
    ],
    sources: [
      {
        title: "Nghị định 252/2026/NĐ-CP ngày 30/06/2026 quy định chi tiết một số điều và biện pháp để tổ chức, hướng dẫn thi hành Luật Quản lý thuế",
        url: "https://xdcs.cdnchinhphu.vn/446259493575335936/2026/7/15/252-ndcp-signed-17841052430171897600672.pdf",
        note: "Điều 43 đến 46 (sàn khấu trừ, thời điểm, doanh thu, khai theo tháng, đơn hủy), Điều 74 (hiệu lực 01/07/2026, thay thế Nghị định 117/2025/NĐ-CP); đọc 17/10/2026",
      },
      {
        title: "Nghị định 68/2026/NĐ-CP ngày 05/03/2026 quy định về chính sách thuế và quản lý thuế đối với hộ kinh doanh, cá nhân kinh doanh",
        url: "https://xdcs.cdnchinhphu.vn/446259493575335936/2026/3/6/68-2026-nd-cp-05032026-signed-17727673940151875228819.pdf",
        note: "Điều 3, 4 (ngưỡng, cách tính), 11 (khai, khấu trừ trên sàn), 12 (hoàn thuế), 13 (quyền, trách nhiệm người bán), 19 (hiệu lực); đọc 17/10/2026",
      },
      {
        title: "Nghị định 141/2026/NĐ-CP ngày 29/04/2026 sửa đổi, bổ sung một số điều của Nghị định 68/2026/NĐ-CP và Nghị định 320/2025/NĐ-CP",
        url: "https://xdcs.cdnchinhphu.vn/446259493575335936/2026/5/4/141-ndcp-signed-1777883675606599215477.pdf",
        note: "Điều 1 (500 triệu đồng thành 1 tỷ đồng, hóa đơn điện tử), Điều 3 (hiệu lực 01/01/2026); đọc 17/10/2026",
      },
      {
        title: "Luật 09/2026/QH16 ngày 24/04/2026 sửa đổi, bổ sung một số điều của Luật Thuế thu nhập cá nhân, Luật Thuế giá trị gia tăng, Luật Thuế thu nhập doanh nghiệp và Luật Thuế tiêu thụ đặc biệt",
        url: "https://datafiles.chinhphu.vn/cpp/files/vbpq/2026/5/09-qh.signed.pdf",
        note: "Điều 1, 2 (ngưỡng doanh thu do Chính phủ quy định), Điều 5 (hiệu lực); đọc 17/10/2026",
      },
      {
        title: "Luật Thuế thu nhập cá nhân 109/2025/QH15, thông qua ngày 10/12/2025",
        url: "https://datafiles.chinhphu.vn/cpp/files/vbpq/2026/01/luat109-2025.pdf",
        note: "Điều 7 (thu nhập từ kinh doanh, thuế suất 0,5% với phân phối, cung cấp hàng hóa), Điều 29 (hiệu lực); đọc 17/10/2026",
      },
      {
        title: "Luật Thuế giá trị gia tăng 48/2024/QH15, thông qua ngày 26/11/2024 (văn bản hợp nhất 12/VBHN-VPQH)",
        url: "https://datafiles.chinhphu.vn/cpp/files/vbpq/2026/02/12-vbhn-vpqh.pdf",
        note: "Điều 12 khoản 2 (tỷ lệ 1% với phân phối, cung cấp hàng hóa); đọc 17/10/2026",
      },
    ],
  },
  {
    slug: "video-tiktok-nhieu-view-khong-ra-don",
    status: "published",
    title: "Video nhiều view nhưng không ra đơn: đọc số từng bước để tìm chỗ gãy",
    seoTitle: "Video TikTok nhiều view không ra đơn: vì sao | Juli AI",
    description:
      "Video TikTok nhiều view mà không ra đơn: đọc Lượt hiển thị sản phẩm, CTR, CTOR, AOV của luồng Video để biết đơn gãy ở bước nào và nên sửa gì trước.",
    excerpt:
      "Lượt xem video không nằm trong công thức GMV. Cách TikTok tính đơn cho video (trực tiếp và trong 7 ngày), bảng triệu chứng theo Lượt hiển thị sản phẩm, CTR, CTOR, AOV, cách nhận ra video sai tệp khách và đo lại sau 7, 14 ngày.",
    breadcrumbName: "Video nhiều view không ra đơn",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "guide",
    format: "pain",
    cover: blogCover("hero-video-tiktok-nhieu-view-khong-ra-don-v1", "Minh hoạ: khung video có nút phát và thanh tiến trình bên cạnh chiếc phễu bị gãy đôi làm rơi các giọt ra ngoài, nền hồng, chữ “Nhiều view, ít đơn”"),
    author: AUTHOR,
    guide: "doc-phan-tich-tiktok-shop-theo-luong-truy-cap",
    related: ["live-tiktok-shop-khong-ra-don", "khach-xem-nhung-khong-mua-tiktok-shop", "gmv-la-gi-tiktok-shop"],
    faq: [
      {
        question: "Video TikTok bao nhiêu view thì có đơn?",
        answer:
          "Không có con số chung. Lượt xem video không nằm trong công thức GMV: đơn hàng phụ thuộc vào Lượt hiển thị sản phẩm trong video, tỷ lệ người bấm vào sản phẩm (CTR) và tỷ lệ đặt hàng sau khi bấm (CTOR). Hãy so các tỷ lệ này với những video khác của chính shop gắn cùng sản phẩm.",
      },
      {
        question: "Đơn từ video được tính thế nào?",
        answer:
          "Theo bài Tinh chỉnh GMV của Học viện TikTok Shop, đơn mua ngay sau khi xem video và bấm vào link sản phẩm là GMV video trực tiếp; đơn mua sau đó trong vòng 7 ngày là GMV video gián tiếp. Người xem chỉ xem mà không bấm vào link sản phẩm thì không được tính cho video.",
      },
      {
        question: "Xem đơn và CTR của từng video ở đâu?",
        answer:
          "Trong Trung tâm nhà bán hàng, vào La bàn dữ liệu, Số liệu phân tích sản phẩm, Lưu lượng truy cập sản phẩm, chọn loại nội dung Video cá nhân. Danh sách video hiện ra kèm số liệu, và nút Xem mở trang Chi tiết video.",
      },
      {
        question: "Có nên chạy quảng cáo cho video nhiều view nhưng ít đơn?",
        answer:
          "Hãy đọc CTR và CTOR trước. Quảng cáo đưa thêm người xem đến video nhưng không làm họ bấm vào sản phẩm nhiều hơn hay sửa được trang sản phẩm. Nếu CTR hoặc CTOR đang thấp, sửa bước đó trước.",
      },
      {
        question: "Sửa xong bao lâu thì biết có hiệu quả?",
        answer:
          "Đọc sơ bộ ở ngày 7 và chốt ở ngày 14, mỗi lần chỉ một thay đổi. Đơn gián tiếp có thể đến trong 7 ngày sau khi khách xem video, nên đánh giá sau một hai ngày là quá sớm.",
      },
    ],
    sources: [
      academy("Tinh chỉnh GMV", "4851723979097858", "GMV trực tiếp và gián tiếp, 7 ngày, ghi nhận nội dung cuối cùng (11/05/2026), kiểm tra 17/10/2026"),
      academy("Lưu lượng truy cập sản phẩm", "10015238", "đường dẫn, chỉ số phễu, lọc theo Video cá nhân, AOV (SKU), Tỷ lệ thêm vào giỏ hàng (17/06/2026), kiểm tra 17/10/2026"),
      academy("Hướng dẫn sử dụng La bàn Dữ liệu trong Trung tâm Người bán", "6837786452313858", "số liệu của mục Phân tích Video (13/12/2022), kiểm tra 17/10/2026"),
      academy("Phân Tích Hiệu Suất Video - Hướng Dẫn cho Nhà Sáng Tạo", "6837828965697281", "hồ sơ người xem, nhận biết thương hiệu (22/03/2024), kiểm tra 17/10/2026"),
    ],
  },
  {
    slug: "live-tiktok-shop-khong-ra-don",
    status: "published",
    title: "LIVE đông người xem mà ít đơn: đọc phễu LIVE từ lượt hiển thị đến đơn hàng",
    seoTitle: "LIVE TikTok Shop không ra đơn: đọc phễu LIVE | Juli AI",
    description:
      "LIVE TikTok Shop đông người xem mà không ra đơn: đọc năm bước của phễu LIVE, ERR, CTR, CTOR, GPM hiển thị để tìm chỗ tụt và chọn điều chỉnh cho buổi sau.",
    excerpt:
      "Người xem không phải người mua. Năm bước của phễu LIVE theo TikTok, ba góc độ chỉ số trong Cẩm nang lưu lượng LIVE, vì sao CTR của LIVE khác CTR của thẻ sản phẩm, so các buổi bằng GPM hiển thị và đọc số theo từng phút.",
    breadcrumbName: "LIVE đông người xem mà ít đơn",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "guide",
    format: "pain",
    cover: blogCover("hero-live-tiktok-shop-khong-ra-don-v1", "Minh hoạ: nhãn LIVE, một đám đông người xem và một đường chấm mảnh dẫn tới chiếc giỏ hàng nhỏ, nền xanh lá nhạt, chữ “LIVE đông, ít đơn”"),
    author: AUTHOR,
    guide: "doc-phan-tich-tiktok-shop-theo-luong-truy-cap",
    related: ["video-tiktok-nhieu-view-khong-ra-don", "quy-dinh-livestream-ban-hang", "gmv-la-gi-tiktok-shop"],
    faq: [
      {
        question: "Tại sao LIVE đông người xem mà không chốt được đơn?",
        answer:
          "Người xem đang dừng ở một bước trước khi mua: vào phòng nhưng ít thấy sản phẩm, thấy sản phẩm nhưng không bấm vào, hoặc bấm vào rồi không đặt. So tỷ lệ giữa các bước của phễu LIVE với các buổi trước của chính bạn để tìm bước tụt mạnh nhất.",
      },
      {
        question: "LIVE bao nhiêu người xem thì có đơn?",
        answer:
          "Không có con số chung. Hai buổi cùng số người xem có thể ra số đơn rất khác nhau. Cẩm nang lưu lượng LIVE của TikTok gợi ý so bằng GPM hiển thị, tức GMV trên mỗi 1.000 lượt hiển thị của buổi LIVE, thay vì chỉ đếm người xem.",
      },
      {
        question: "GPM hiển thị và ERR là gì?",
        answer:
          "Theo Cẩm nang lưu lượng LIVE, GPM hiển thị là GMV tạo ra từ phòng LIVE trên mỗi 1.000 lượt hiển thị của buổi LIVE, còn Tỷ lệ vào phòng (ERR) là số lượt xem chia cho số lượt hiển thị của phòng LIVE. ERR cần khoảng 15 đến 30 phút đầu để ổn định.",
      },
      {
        question: "TikTok có bóp LIVE không?",
        answer:
          "Học viện TikTok Shop không công bố cách phân phối lượt hiển thị cho buổi LIVE. Nếu nghi buổi LIVE bị ảnh hưởng do vi phạm, Cẩm nang lưu lượng LIVE hướng dẫn xem Tổng quan dữ liệu LIVE, Xu hướng hiệu suất, Chất lượng nội dung, và đối chiếu Chính sách nội dung TikTok Shop.",
      },
      {
        question: "Bao lâu thì nên đánh giá lại cách LIVE?",
        answer:
          "Cẩm nang lưu lượng LIVE khuyên xem lại dữ liệu cấp tài khoản ít nhất 7 ngày một lần và so 3 chỉ số kém nhất với 5 buổi gần đây. Với một thay đổi cụ thể, hãy đọc sơ bộ ở ngày 7 và chốt ở ngày 14.",
      },
    ],
    sources: [
      academy("Phân tích dữ liệu LIVE của bạn", "6837840206563073", "phễu năm giai đoạn, phát lại theo thời gian, hồ sơ người dùng (03/01/2023), kiểm tra 17/10/2026"),
      academy("Cẩm nang lưu lượng LIVE", "512121839519504", "ba góc độ chỉ số, ERR, CTR, CTOR, GPM hiển thị, quy trình trong và sau LIVE (24/07/2025), kiểm tra 17/10/2026"),
      academy("Hiệu Suất LIVE", "5477287655884545", "đường dẫn, sáu chỉ số mặc định, khác biệt giữa trang nhà bán hàng và nhà sáng tạo (21/05/2024), kiểm tra 17/10/2026"),
      academy("Hướng dẫn sử dụng La bàn Dữ liệu trong Trung tâm Người bán", "6837786452313858", "Lượt hiển thị sản phẩm trong LIVE, C_O (13/12/2022), kiểm tra 17/10/2026"),
      academy("Tinh chỉnh GMV", "4851723979097858", "GMV trực tiếp và gián tiếp theo loại nội dung (11/05/2026), kiểm tra 17/10/2026"),
    ],
  },
  {
    slug: "ty-le-hoan-hang-tiktok-shop",
    status: "published",
    title: "Đơn hủy, hoàn hàng tăng trên TikTok Shop: tách từng loại, đọc đúng tỷ lệ, tính đúng chi phí",
    seoTitle: "Tỷ lệ hoàn hàng TikTok Shop: hủy, trả hàng, phí | Juli AI",
    description:
      "Đơn hủy, hoàn hàng tăng: tách hủy đơn, giao không thành công và trả hàng, đọc SFCR, SFRR, hạn xử lý 1 ngày, ai trả phí ship và phí nào không được hoàn.",
    excerpt:
      "Hoàn hàng là ba chuyện khác nhau: đơn hủy trước khi giao, đơn giao không thành công quay về shop, và đơn khách trả sau khi nhận. Mỗi loại một chỉ số, một hạn xử lý, một khoản phí; bài này tách từng loại theo trang chính thức của TikTok Shop. Cập nhật ngày 17/10/2026.",
    breadcrumbName: "Tỷ lệ hoàn hàng TikTok Shop",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "metrics",
    format: "pain",
    cover: blogCover("hero-ty-le-hoan-hang-tiktok-shop-v1", "Minh hoạ: thùng hàng các-tông với mũi tên vòng ngược lại phía người gửi, nền cam đào nhạt, chữ “Đơn hủy, hoàn hàng”"),
    author: AUTHOR,
    guide: "ctor-thap-viet-lai-mo-ta-san-pham",
    related: ["phi-san-tiktok-shop-2026", "doanh-thu-tiktok-shop-giam", "gmv-la-gi-tiktok-shop"],
    faq: [
      {
        question: "Hủy đơn trên TikTok Shop có sao không?",
        answer:
          "Tùy ai hủy. Khách hủy thì không ảnh hưởng người bán, trừ khi chọn lý do Giao hàng trễ. Người bán hủy, hoặc đơn bị tự động hủy vì không bàn giao kịp, thì tính vào Tỷ lệ hủy do lỗi của người bán (SFCR); mục tiêu là dưới 2,5% trong 7 ngày theo lịch. Người bán không được yêu cầu khách hủy đơn.",
      },
      {
        question: "Hoàn hàng TikTok Shop có mất phí không?",
        answer:
          "Có, tùy trường hợp. Đơn đã giao rồi mới trả hàng vẫn bị thu phí xử lý đơn 3.000 đồng và không được hoàn. Người bán chịu phí trả hàng khi lỗi ở người bán, và phí chuyển hoàn của đơn giao không thành công. Phần tiền hoàn cho khách được trừ khỏi cơ sở tính phí giao dịch.",
      },
      {
        question: "Không phản hồi yêu cầu trả hàng thì sao?",
        answer:
          "Theo trang Trả hàng và Hoàn tiền của Học viện TikTok Shop (cập nhật 15/10/2026), người bán phải xem xét yêu cầu trong 1 ngày theo lịch; quá hạn thì yêu cầu được tự động duyệt. Nếu trong một tháng hơn 90% yêu cầu không được xem đúng hạn, Công cụ phê duyệt tự động có thể được bật.",
      },
      {
        question: "Trả hàng tính vào SFRR hay SFCR?",
        answer:
          "Trả hàng, hoàn tiền sau khi giao tính vào Tỷ lệ trả hàng/hoàn tiền do lỗi của người bán (SFRR), chỉ khi lý do liên quan người bán như không đúng mô tả, gửi sai, sản phẩm lỗi. Đổi ý, đặt sai kích thước không tính. SFCR chỉ dành cho đơn bị hủy trước khi giao.",
      },
      {
        question: "Tỷ lệ hoàn hàng bao nhiêu là bình thường?",
        answer:
          "TikTok không công bố tỷ lệ chung của ngành. Mốc chính thức duy nhất là mục tiêu của chính nền tảng: SFCR dưới 2,5% và SFRR dưới 1,5%. Ngoài hai mốc đó, hãy so shop với chính nó qua các kỳ dài bằng nhau, theo từng loại và từng sản phẩm.",
      },
    ],
    sources: [
      academy("Chính sách hủy đơn hàng, trả hàng và hoàn tiền của khách hàng trên TikTok Shop", "10000852", "ai được hủy, phí ship khi trả hàng theo bên có lỗi, từ chối không hợp lệ (cập nhật 23/09/2026)"),
      academy("Hủy đơn hàng", "578506941728513", "người bán hủy, giao không thành công, COD từ chối nhận, phí chuyển hoàn (cập nhật 22/09/2026)"),
      academy("Trả hàng và Hoàn tiền", "1766935302801169", "thời hạn, lý do ảnh hưởng SFRR, Công cụ phê duyệt tự động (cập nhật 15/10/2026)"),
      academy("Quản lý yêu cầu trả hàng và hoàn tiền", "6819122768905985", "xem xét trong 1 ngày dương lịch, hàng trả về trong 2 ngày (cập nhật 04/11/2025)"),
      academy("Tỷ lệ hủy do lỗi của người bán (SFCR)", "6988439669442305", "định nghĩa 7 ngày, mục tiêu dưới 2,5%, ví dụ, điểm AHR (cập nhật 16/07/2026)"),
      academy("Tỷ lệ trả hàng/hoàn tiền do lỗi của người bán", "89407391336193", "định nghĩa 30 ngày, mục tiêu dưới 1,5%, nơi xem (cập nhật 19/08/2026)"),
      academy("Phí Xử Lý Đơn Hàng", "2968734088120080", "3.000 đồng, không hoàn khi đơn đã giao rồi trả (cập nhật 11/10/2025)"),
      academy("Phí Giao Dịch", "753295858337537", "công thức trừ phần hoàn tiền (cập nhật 13/10/2026)"),
      academy("Phí Vận Hành Logistic", "4723305845458708", "kiện trên 10 kg, chính sách hoàn phí (cập nhật 08/10/2026)"),
      academy("Phí của Nhà Bán Hàng", "8858869405370113", "phí vận chuyển trả hàng thực tế (cập nhật 04/08/2026)"),
      academy("Lưu lượng truy cập sản phẩm", "10015238", "GMV gồm cả đơn đã hủy và hoàn tiền, thời điểm ghi nhận hoàn tiền (cập nhật 17/06/2026)"),
    ],
  },
  {
    slug: "phi-san-tiktok-shop-2026",
    status: "published",
    title: "Phí sàn TikTok Shop 2026: các khoản phí hiện hành và mỗi đơn còn lại bao nhiêu",
    seoTitle: "Phí sàn TikTok Shop 2026: một đơn còn bao nhiêu | Juli AI",
    description:
      "Phí bán hàng TikTok Shop tại 17/10/2026: hoa hồng 14% (Mall 16%), phí giao dịch 6%, phí xử lý 3.000đ, phí kiện trên 10kg, kèm ví dụ lợi nhuận một đơn.",
    excerpt:
      "Khung phí hiện hành theo các trang chính thức của TikTok Shop, kèm ngày hiệu lực: hoa hồng theo ngành, phí giao dịch, phí xử lý đơn, phí vận hành logistic, hai mốc 20/10 và 21/10, và một ví dụ giả định tính phần còn lại của một đơn. Cập nhật ngày 17/10/2026.",
    breadcrumbName: "Phí sàn TikTok Shop 2026",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "guide",
    format: "news",
    cover: blogCover("hero-phi-san-tiktok-shop-2026-v1", "Minh hoạ: đồng xu vàng bị cắt mất một miếng và chồng thẻ phí xếp bên cạnh, nền xám nhạt, chữ “Phí sàn mỗi đơn”"),
    author: AUTHOR,
    guide: "tim-san-pham-keo-gmv-xuong-tiktok-shop",
    related: ["thue-ban-hang-tiktok-shop", "ty-le-hoan-hang-tiktok-shop", "gmv-la-gi-tiktok-shop"],
    faq: [
      {
        question: "Phí hoa hồng TikTok Shop của ngành tôi là bao nhiêu?",
        answer:
          "Mỗi ngành hàng cấp 3 có một phí suất riêng, khác nhau giữa Nhà Bán Hàng Tiêu Chuẩn và Mall. Tải bảng phí suất PDF trên trang Phí Hoa Hồng Nền Tảng của Học viện TikTok Shop và tìm đúng ngành của sản phẩm. Ngành không có trong bảng dùng mức mặc định: 14% (Tiêu Chuẩn) và 16% (Mall).",
      },
      {
        question: "Phí giao dịch 6% có tính cả tiền ship không?",
        answer:
          "Có. Cơ sở tính là số tiền khách thanh toán, gồm phí vận chuyển khách trả, cộng chiết khấu của nền tảng và trừ phần hoàn tiền. Ví dụ trên trang Phí Giao Dịch: cơ sở 105.600 đồng, phí 6.336 đồng.",
      },
      {
        question: "Đơn bị trả hàng có được hoàn phí không?",
        answer:
          "Phí xử lý đơn 3.000 đồng không được hoàn nếu đơn đã giao thành công rồi mới trả hàng, hoàn tiền. Phí giao dịch thì trừ phần hoàn tiền khỏi cơ sở tính. Phí vận hành logistic cho kiện trên 10 kg cũng không hoàn khi đơn đã giao rồi khách trả.",
      },
      {
        question: "Phí TikTok Shop đã bao gồm thuế chưa?",
        answer:
          "Với cá nhân, hộ kinh doanh và tổ chức chưa có mã số thuế được TikTok Shop xác minh: phí đã gồm thuế. Tổ chức có mã số thuế đã xác minh trả phí chưa gồm thuế và tự kê khai 10% GTGT, 5% TNDN. Bảng phí vận hành logistic ghi mức trước thuế.",
      },
    ],
    sources: [
      academy("Phí của Nhà Bán Hàng", "8858869405370113", "tổng quan các loại phí, phí vận chuyển, thuế trên phí (cập nhật 04/08/2026); đọc 17/10/2026"),
      academy("Phí Hoa Hồng Nền Tảng", "3396736626312961", "công thức, phí suất mặc định 14% và 16%, bảng Mall ngành Sách từ 20/10/2026, chương trình hỗ trợ đến 30/09/2026, hai bảng phí suất PDF (cập nhật 30/09/2026); đọc 17/10/2026"),
      academy("Phí Giao Dịch", "753295858337537", "6% cho đơn sau 00:00 ngày 09/05/2026, công thức, Chương trình Tiết Kiệm Phí Giao Dịch từ 21/10/2026 (cập nhật 13/10/2026); đọc 17/10/2026"),
      academy("Phí Xử Lý Đơn Hàng", "2968734088120080", "3.000 đồng mỗi đơn giao thành công, thu từ 27/10/2025 (cập nhật 11/10/2025); đọc 17/10/2026"),
      academy("Phí Vận Hành Logistic", "4723305845458708", "kiện trên 10 kg, 3.000 đến 65.000 VND, từ 12/10/2026 (cập nhật 08/10/2026); đọc 17/10/2026"),
      academy("Thông Tin Cơ Bản về Thuế trên Phí Nền Tảng", "10011442", "10% GTGT, 5% TNDN, phí gồm hay chưa gồm thuế (cập nhật 30/09/2026); đọc 17/10/2026"),
      academy("Lưu lượng truy cập sản phẩm", "10015238", "GMV gồm cả đơn đã hủy và hoàn tiền (cập nhật 17/06/2026); đọc 17/10/2026"),
    ],
  },
  {
    slug: "khach-xem-nhung-khong-mua-tiktok-shop",
    status: "published",
    title: "Khách xem nhưng không mua trên TikTok Shop: kiểm tra từng bước sau cú nhấp",
    seoTitle: "Khách xem nhưng không mua trên TikTok Shop | Juli AI",
    description:
      "Nhiều người bấm vào sản phẩm mà không ai đặt: đọc CTOR theo nguồn, tách trang sản phẩm khỏi bước thanh toán, sửa đúng một chỗ và đo lại ở ngày 7, 14.",
    excerpt:
      "Khách đã bấm vào sản phẩm rồi rời đi: đọc CTOR theo nguồn, dùng Tỷ lệ thêm vào giỏ hàng để tách trang sản phẩm khỏi voucher và phí vận chuyển, tính đến đơn gián tiếp trong 7 ngày, rồi sửa một chỗ và đo lại.",
    breadcrumbName: "Khách xem nhưng không mua",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "metrics",
    format: "pain",
    cover: blogCover("hero-khach-xem-nhung-khong-mua-tiktok-shop-v1", "Minh hoạ: con mắt có tròng là chiếc giỏ hàng trống và con trỏ chuột đang bấm, nền xanh ngọc đậm, chữ “Xem mà không mua”"),
    author: AUTHOR,
    guide: "ctor-thap-viet-lai-mo-ta-san-pham",
    related: ["tang-gia-tri-don-hang-trung-binh-tiktok-shop", "tiktok-shop-khong-ra-don", "gmv-la-gi-tiktok-shop"],
    faq: [
      {
        question: "CTOR bao nhiêu là thấp?",
        answer:
          "TikTok không công bố một mức CTOR chuẩn chung. Hãy so CTOR của sản phẩm với chính nó ở kỳ trước và với các sản phẩm khác của shop trên cùng nguồn, trên khoảng 28 ngày, và chỉ kết luận khi mỗi kỳ có đủ lượt nhấp.",
      },
      {
        question: "Khách thêm vào giỏ hàng nhưng không thanh toán có phải lỗi của shop không?",
        answer:
          "Không phải lúc nào cũng vậy, nhưng đáng kiểm tra. Khi Tỷ lệ thêm vào giỏ hàng ổn mà ít đơn, nghi phạm là bước thanh toán: phí vận chuyển, voucher hết hạn, hoặc giỏ chưa đạt mức chi tối thiểu vì voucher xét trên giá sau giảm giá sản phẩm. Một phần khách cũng có thể mua lại trong vài ngày sau.",
      },
      {
        question: "Giảm giá có phải cách duy nhất để khách đặt hàng không?",
        answer:
          "Không. Nếu khách rời đi vì trang thiếu kích thước, chất liệu, cách dùng, vì biến thể hết hàng hay vì video hứa một ưu đãi đã hết, giảm giá không sửa được nguyên nhân mà chỉ lấy đi biên lợi nhuận. Theo Học viện TikTok Shop, không có hình phạt nào nếu bạn không đổi giá theo Chẩn đoán giá.",
      },
      {
        question: "Sửa trang sản phẩm bao lâu thì biết có hiệu quả?",
        answer:
          "Đọc sơ bộ ở ngày 7 và chốt ở ngày 14, so với 14 ngày trước khi đổi, mỗi lần một thay đổi. Theo bài Tinh chỉnh GMV, đơn có thể đến muộn trong 7 ngày sau khi khách xem nội dung, nên đọc sau một hai ngày là quá sớm.",
      },
    ],
    sources: [
      academy("Lưu lượng truy cập sản phẩm", "10015238", "CTOR, Tỷ lệ thêm vào giỏ hàng, khía cạnh theo kênh, Phí vận chuyển (17/06/2026), kiểm tra 17/10/2026"),
      academy("Tinh chỉnh GMV", "4851723979097858", "GMV trực tiếp và gián tiếp, CTOR, 7 ngày (11/05/2026), kiểm tra 17/10/2026"),
      academy("Voucher Thông Thường Của Nhà Bán Hàng", "5159633199597314", "mức chi tối thiểu, một voucher mỗi đơn, tỷ lệ đổi thấp (13/06/2025), kiểm tra 17/10/2026"),
      academy("Cách Tính Khuyến Mãi Cộng Dồn", "2965628697724674", "mức chi tối thiểu xét trên giá sau giảm giá sản phẩm (29/10/2025), kiểm tra 17/10/2026"),
      academy("Chiết Khấu Phí Vận Chuyển của Nhà Bán Hàng", "6837782308292353", "nhà bán hàng chịu toàn bộ hoặc một phần phí vận chuyển, điều kiện (24/01/2025), kiểm tra 17/10/2026"),
      academy("Chẩn đoán giá", "7563289900353282", "sản phẩm tương tự, đặt lại giá, không có hình phạt (24/07/2026), kiểm tra 17/10/2026"),
      academy("Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 4", "7905983637079809", "Hiển thị, Lợi ích, Sự tin cậy (15/12/2023), kiểm tra 17/10/2026"),
    ],
  },
  {
    slug: "tang-gia-tri-don-hang-trung-binh-tiktok-shop",
    status: "published",
    title: "Bán nhiều đơn mà vẫn ít tiền: cách tăng giá trị đơn hàng trung bình trên TikTok Shop",
    seoTitle: "Tăng giá trị đơn hàng trung bình TikTok Shop | Juli AI",
    description:
      "Bán nhiều đơn mà vẫn ít tiền: đọc AOV theo nguồn, phí 3.000 đồng mỗi đơn, voucher theo bậc, ưu đãi theo gói, khuyến mãi cộng dồn và đo lại sau 7, 14 ngày.",
    excerpt:
      "Phí xử lý đơn tính theo từng đơn nên đơn nhỏ chịu phần trăm phí cao hơn. Đọc AOV theo nguồn, biết khi nào nên tăng giá trị đơn, chọn giữa voucher theo bậc, Mua Sỉ Giá Hời, Ưu đãi theo gói và quà tặng, tránh khuyến mãi chồng nhau và đo AOV cùng CTOR.",
    breadcrumbName: "Tăng giá trị đơn hàng trung bình",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "metrics",
    format: "pain",
    cover: blogCover("hero-tang-gia-tri-don-hang-trung-binh-tiktok-shop-v1", "Minh hoạ: tờ hoá đơn dài bên cạnh ba hộp hàng xếp chồng và dấu cộng, nền hồng phấn, chữ “Tăng giá trị đơn”"),
    author: AUTHOR,
    guide: "doc-phan-tich-tiktok-shop-theo-luong-truy-cap",
    related: ["khach-xem-nhung-khong-mua-tiktok-shop", "gmv-la-gi-tiktok-shop", "doanh-thu-sau-sale-tiktok-shop"],
    faq: [
      {
        question: "AOV bao nhiêu là tốt?",
        answer:
          "TikTok không công bố một mức AOV chuẩn chung, và AOV khác nhau rất nhiều giữa các ngành hàng. Hãy so AOV của shop với chính nó ở kỳ trước, theo từng nguồn, và với các sản phẩm khác trong shop.",
      },
      {
        question: "Nên làm combo hay voucher trước?",
        answer:
          "Tùy sản phẩm. Ưu đãi theo gói hợp với sản phẩm dùng cùng nhau (2 đến 3 sản phẩm), Mua Sỉ Giá Hời hợp với hàng khách hay mua nhiều cái, voucher theo bậc áp dụng cho cả shop. Học viện TikTok Shop gợi ý đặt mức chi tối thiểu của voucher cao hơn 1,2 đến 1,5 lần giá trị đơn hàng trung bình. Chạy một công cụ mỗi lần để đo được tác dụng.",
      },
      {
        question: "Tăng giá trị đơn có làm giảm tỷ lệ chốt đơn không?",
        answer:
          "Có thể. Một điều kiện khó đạt khiến một số khách bỏ đi, nên AOV lên mà CTOR xuống. Hãy đọc AOV cùng CTOR và GMV ở ngày 7 và ngày 14: AOV lên 10 % mà CTOR giảm 15 % thì GMV của luồng đó vẫn giảm.",
      },
      {
        question: "Phí cố định mỗi đơn trên TikTok Shop là bao nhiêu?",
        answer:
          "Theo bài Phí Xử Lý Đơn Hàng của Học viện TikTok Shop (cập nhật 11/10/2025), mỗi đơn giao thành công bị thu 3.000 đồng, đã gồm thuế, với mọi giá trị đơn và số lượng hàng trong đơn, từ ngày 27/10/2025. Đơn bị hoàn tiền hay trả hàng sau khi giao thành công vẫn bị thu.",
      },
    ],
    sources: [
      academy("Phí Xử Lý Đơn Hàng", "2968734088120080", "3.000 đồng mỗi đơn giao thành công, đã gồm thuế, từ 27/10/2025 (11/10/2025), kiểm tra 17/10/2026"),
      academy("Lưu lượng truy cập sản phẩm", "10015238", "định nghĩa AOV (SKU), khía cạnh theo kênh (17/06/2026), kiểm tra 17/10/2026"),
      academy("Voucher Thông Thường Của Nhà Bán Hàng", "5159633199597314", "mức chi tối thiểu 1,2 đến 1,5 lần AOV, voucher nhiều bậc, một voucher mỗi đơn (13/06/2025), kiểm tra 17/10/2026"),
      academy("Mua Sỉ Giá Hời (BMSM)", "10013310", "tối đa hai bậc, số mặt hàng trung bình trên mỗi đơn (09/12/2025), kiểm tra 17/10/2026"),
      academy("Ưu Đãi Theo Gói", "1823467559126785", "2 đến 3 sản phẩm, giá gói thấp hơn giá gốc, không cộng dồn với BMSM (16/04/2024), kiểm tra 17/10/2026"),
      academy("Quà Tặng Khi Mua Hàng", "338556929509122", "không trực tiếp giảm giá, phí vận chuyển của quà, ngưỡng 1.500.000 đồng (05/01/2026), kiểm tra 17/10/2026"),
      academy("Chiết Khấu Phí Vận Chuyển của Nhà Bán Hàng", "6837782308292353", "mức chi tối thiểu cao hơn một chút so với AOV (24/01/2025), kiểm tra 17/10/2026"),
      academy("Cách Tính Khuyến Mãi Cộng Dồn", "2965628697724674", "ba lớp khuyến mãi, Phân tích hiểu sâu về định giá (29/10/2025), kiểm tra 17/10/2026"),
      academy("Tiêu đề, mô tả, hình ảnh và video về sản phẩm", "5918681919178512", "số lượng trong tiêu đề, không đưa khuyến mãi vào tiêu đề (23/04/2026), kiểm tra 17/10/2026"),
    ],
  },
  {
    slug: "mo-ta-san-pham-tiktok-shop",
    status: "published",
    title: "Khách hỏi mãi một câu: viết mô tả sản phẩm TikTok Shop để trả lời trước khi khách hỏi",
    seoTitle: "Mô tả sản phẩm TikTok Shop: trả lời trước | Juli AI",
    description:
      "Khách hỏi mãi một câu về size, chất liệu, cách dùng: gom câu hỏi lặp lại, viết mô tả theo chính sách TikTok Shop, tránh lỗi bị gỡ và đo CTOR ngày 7, 14.",
    excerpt:
      "Câu hỏi lặp lại là thông tin còn thiếu trên trang sản phẩm. Cách gom câu hỏi trong một tuần, TikTok yêu cầu gì ở mô tả (không dưới 30 từ, phụ kiện, bảng kích cỡ), những gì không được viết, mô tả và trả hàng vì không đúng mô tả, và cách đo lại.",
    breadcrumbName: "Mô tả sản phẩm TikTok Shop",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "optimize",
    format: "pain",
    cover: blogCover("hero-mo-ta-san-pham-tiktok-shop-v1", "Minh hoạ: bong bóng câu trả lời có dấu tích nằm phía trên bong bóng dấu hỏi của khách, nền trắng kẻ ô, chữ “Trả lời trước khi hỏi”"),
    author: AUTHOR,
    guide: "ctor-thap-viet-lai-mo-ta-san-pham",
    related: ["khach-xem-nhung-khong-mua-tiktok-shop", "ty-le-hoan-hang-tiktok-shop", "dat-ten-san-pham-tiktok-shop"],
    faq: [
      {
        question: "Mô tả sản phẩm TikTok Shop phải dài ít nhất bao nhiêu từ?",
        answer:
          "Theo trang chính sách Tiêu đề, mô tả, hình ảnh và video về sản phẩm (cập nhật 23/04/2026), mô tả không dưới 30 từ. TikTok không công bố độ dài tối ưu; hãy viết đủ để trả lời các câu khách hay hỏi, không thêm câu quảng cáo cho dài.",
      },
      {
        question: "Có được để số điện thoại hoặc Zalo trong mô tả cho khách hỏi thêm không?",
        answer:
          "Không. Trang Thông tin đặt hàng thay thế (Chuyển hướng truy cập) của TikTok Shop không cho phép liên kết, số điện thoại, tài khoản mạng xã hội, email hay mã QR có thể đưa khách rời nền tảng để đặt hàng hoặc liên hệ. Hãy trả lời câu hỏi ngay trong mô tả.",
      },
      {
        question: "Có được ghi \"tốt nhất\", \"đảm bảo 100%\" trong mô tả không?",
        answer:
          "Không, trừ khi tuyên bố chính xác và xác minh được. Trang Mô tả sản phẩm phóng đại là gì? liệt kê \"số 1\", \"tốt nhất\", \"duy nhất\", \"100% tự nhiên\" và kết quả \"ngay tức thì\"; với tuyên bố tuyệt đối, người bán cần tài liệu của cơ quan có thẩm quyền ghi đúng tuyên bố đó.",
      },
      {
        question: "Dùng AI viết mô tả sản phẩm có được không?",
        answer:
          "Được. Công cụ Tối Ưu Hoá Sản Phẩm của TikTok có tính năng Tối ưu hóa bằng AI cho tiêu đề và mô tả, nhưng người bán chịu trách nhiệm thông tin chính xác, trung thực. Hãy đọc lại từng câu và đối chiếu với hàng thật trước khi đăng.",
      },
      {
        question: "Sửa mô tả bao lâu thì biết có hiệu quả?",
        answer:
          "Đọc CTOR sơ bộ ở ngày 7 và chốt ở ngày 14, so với 14 ngày trước khi sửa và với các sản phẩm không sửa, mỗi lần một thay đổi. Sản phẩm ít lượt nhấp cần đo lâu hơn, và kết quả chỉ để tham khảo. Gom câu hỏi thêm một tuần sau khi sửa cũng cho biết câu nào khách không còn phải hỏi.",
      },
    ],
    sources: [
      academy("Tiêu đề, mô tả, hình ảnh và video về sản phẩm", "5918681919178512", "mô tả không dưới 30 từ, đặc điểm, an toàn, phụ kiện đi kèm, thương hiệu (cập nhật 23/04/2026); đọc 18/10/2026"),
      academy("Hướng dẫn đăng bán sản phẩm tại TikTok Shop", "10008395", "mục 3.1.1 đến 3.1.5: thông tin sai, phóng đại, so sánh, giá khuyến mại, khẳng định sai (cập nhật 05/10/2026); đọc 18/10/2026"),
      academy("Mô tả sản phẩm phóng đại là gì?", "6837770400581377", "ví dụ khẳng định tuyệt đối, tài liệu cơ quan có thẩm quyền, cách viết với dược mỹ phẩm (29/06/2025); đọc 18/10/2026"),
      academy("Thông tin đặt hàng thay thế (Chuyển hướng truy cập)", "7213979802060545", "không để liên kết, số điện thoại, mạng xã hội, email, mã QR (10/06/2026); đọc 18/10/2026"),
      academy("Mặt hàng khác biệt lớn so với mô tả (SNAD)", "6837791128831746", "định nghĩa SNAD, màu ngẫu nhiên, biểu đồ cỡ (18/06/2025); đọc 18/10/2026"),
      academy("Hướng dẫn bảng kích cỡ cho Nhà bán hàng Thời trang", "7378934985099029", "số đo kèm đơn vị, phủ mọi SKU kích cỡ, tránh cụm mơ hồ (01/10/2026); đọc 18/10/2026"),
      academy("Hiển thị thông tin sai lệch và hướng dẫn về nội dung đăng bán tạo bởi AI", "7224191560681232", "mô tả chính xác và trung thực, ví dụ thông tin sai lệch, AIGC (30/09/2026); đọc 18/10/2026"),
      academy("Trình Tối Ưu Hoá Sản Phẩm", "6532499267012354", "Tối ưu hóa bằng AI cho tiêu đề và mô tả, mô tả quá ngắn (04/08/2025); đọc 18/10/2026"),
      academy("Chính sách hủy đơn hàng, trả hàng và hoàn tiền của khách hàng trên TikTok Shop", "10000852", "không khớp mô tả là lỗi người bán, người bán chịu phí trả hàng (cập nhật 23/09/2026); đọc 18/10/2026"),
      academy("Trả hàng và Hoàn tiền", "1766935302801169", "lý do Sản phẩm không đúng mô tả ảnh hưởng SFRR (cập nhật 15/10/2026); đọc 18/10/2026"),
    ],
  },
  {
    slug: "quy-dinh-livestream-ban-hang",
    status: "published",
    title: "Quy định mới về livestream bán hàng và quảng cáo: người bán và người livestream cần biết gì",
    seoTitle: "Quy định livestream bán hàng mới nhất 2026 | Juli AI",
    description:
      "Luật Thương mại điện tử từ 01/07/2026: việc của người bán, người livestream, nền tảng; mức phạt người có ảnh hưởng theo NĐ 87/2026; chính sách LIVE TikTok.",
    excerpt:
      "Tóm tắt từ văn bản gốc: Luật Thương mại điện tử 122/2025/QH15 và Nghị định 248/2026/NĐ-CP về livestream bán hàng, Luật Quảng cáo sửa đổi và Nghị định 87/2026/NĐ-CP về người có ảnh hưởng, và các chính sách LIVE riêng của TikTok Shop Việt Nam. Cập nhật ngày 18/10/2026.",
    breadcrumbName: "Quy định livestream bán hàng",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "guide",
    format: "news",
    cover: blogCover("hero-quy-dinh-livestream-ban-hang-v1", "Minh hoạ: micro đứng và chiếc búa của toà gõ xuống bục, nền xanh lá đậm, chữ “Quy định livestream”"),
    author: AUTHOR,
    guide: "duyet-de-xuat-toi-uu-san-pham-tiktok-shop",
    related: ["live-tiktok-shop-khong-ra-don", "thue-ban-hang-tiktok-shop", "mo-ta-san-pham-tiktok-shop"],
    faq: [
      {
        question: "Livestream bán hàng trên TikTok Shop có phải xác thực danh tính không?",
        answer:
          "Luật Thương mại điện tử 122/2025/QH15 (Điều 22) yêu cầu nền tảng xác thực điện tử danh tính người livestream trước khi cho phát; Nghị định 248/2026/NĐ-CP đặt mốc 01/01/2027 cho nghĩa vụ này. Theo chính sách riêng của TikTok Shop, từ 01/07/2026 người bán mới quét NFC trên CCCD gắn chip, nhà sáng tạo xác minh NFC khi được yêu cầu.",
      },
      {
        question: "Nền tảng lưu video livestream bán hàng bao lâu?",
        answer:
          "Ít nhất 01 năm từ thời điểm bắt đầu truyền phát, theo Điều 22 khoản 7 Luật Thương mại điện tử 122/2025/QH15, có hiệu lực từ 01/07/2026.",
      },
      {
        question: "Bán thực phẩm bổ sung trên LIVE cần giấy gì?",
        answer:
          "Theo thông báo của TikTok Shop (hiệu lực 08/07/2026), với thực phẩm như thực phẩm bảo vệ sức khỏe, thực phẩm bổ sung và với sữa, dinh dưỡng cho trẻ từ 36 tháng tuổi trở xuống, người bán tải Giấy xác nhận nội dung quảng cáo do cơ quan có thẩm quyền cấp; không có thì có thể bị hạn chế quảng bá trong LIVE. Người bán tự xác định sản phẩm có thuộc diện không.",
      },
      {
        question: "Người có ảnh hưởng giới thiệu sản phẩm chưa dùng bị phạt bao nhiêu?",
        answer:
          "Theo Điều 51 khoản 3 Nghị định 87/2026/NĐ-CP (hiệu lực 15/05/2026), 80 đến 100 triệu đồng với cá nhân; tổ chức bị phạt gấp 2 lần. Mức này áp dụng cho người thuộc diện người có ảnh hưởng theo quy định của Chính phủ.",
      },
      {
        question: "Có được phát LIVE TikTok Shop đồng thời trên nền tảng khác không?",
        answer:
          "Không, theo chính sách của TikTok Shop: không phát cùng một phiên LIVE trên TikTok Shop và nền tảng khác cùng lúc, hay trên nhiều tài khoản TikTok Shop cùng lúc. LIVE ở nền tảng khác vào thời điểm khác thì được. Đây là quy định của nền tảng, không phải của luật.",
      },
    ],
    sources: [
      {
        title: "Luật Thương mại điện tử số 122/2025/QH15, thông qua ngày 10/12/2025 (Công báo số 41, ngày 22/01/2026)",
        url: "https://congbao.chinhphu.vn/van-ban/luat-so-122-2025-qh15-468683/61714.htm",
        note: "Điều 3 khoản 10, 11 (định nghĩa), Điều 22, 23, 24 (nền tảng, người bán, người livestream; lưu dữ liệu ít nhất 01 năm), Điều 40 (hiệu lực 01/07/2026); đọc bản PDF 18/10/2026",
      },
      {
        title: "Nghị định 248/2026/NĐ-CP ngày 30/06/2026 quy định chi tiết một số điều của Luật Thương mại điện tử (Công báo số 407, ngày 18/07/2026)",
        url: "https://congbao.chinhphu.vn/van-ban/nghi-dinh-so-248-2026-nd-cp-469983/66872.htm",
        note: "Điều 12 (quy chế livestream), Điều 52 (hiệu lực 01/07/2026, xác thực danh tính điện tử từ 01/01/2027, thay Nghị định 52/2013 và 85/2021); đọc bản PDF 18/10/2026",
      },
      {
        title: "Luật số 75/2025/QH15 sửa đổi, bổ sung một số điều của Luật Quảng cáo, thông qua ngày 16/06/2025 (Công báo số 967 + 968, ngày 24/07/2025)",
        url: "https://congbao.chinhphu.vn/van-ban/luat-so-75-2025-qh15-45566.htm",
        note: "Điều 15a mới (người chuyển tải quảng cáo, người có ảnh hưởng), Điều 3 (hiệu lực 01/01/2026); đọc bản PDF 18/10/2026",
      },
      {
        title: "Nghị định 87/2026/NĐ-CP ngày 27/03/2026 quy định xử phạt vi phạm hành chính trong lĩnh vực văn hóa và quảng cáo (Công báo số 243, ngày 22/04/2026)",
        url: "https://congbao.chinhphu.vn/van-ban/nghi-dinh-so-87-2026-nd-cp-469359/64268.htm",
        note: "Điều 6 (tổ chức gấp 2 lần), Điều 51 (40 đến 100 triệu đồng), Điều 93 (hiệu lực 15/05/2026, thay Nghị định 38/2021); đọc bản PDF 18/10/2026",
      },
      {
        title: "Luật Bảo vệ quyền lợi người tiêu dùng số 19/2023/QH15, thông qua ngày 20/06/2023 (Công báo số 865 + 866, ngày 30/07/2023)",
        url: "https://congbao.chinhphu.vn/van-ban/luat-so-19-2023-qh15-39843.htm",
        note: "Điều 3 khoản 9 (người có ảnh hưởng), Điều 22 khoản 3 (thông báo được tài trợ), Điều 79 (hiệu lực 01/07/2024); đọc bản PDF 18/10/2026",
      },
      academy("Cập nhật Chính sách mới nhất", "8831988245645057", "chính sách của TikTok Shop, không phải luật: Giấy xác nhận nội dung quảng cáo từ 08/07/2026; NFC cho người bán mới và nhà sáng tạo, mã số thuế từ 01/07/2026; không phát song song; Mồi giá - đổi giá (cập nhật 01/07/2026); đọc 18/10/2026"),
    ],
  },
  {
    slug: "dat-ten-san-pham-tiktok-shop",
    status: "published",
    title: "Ít người bấm vào sản phẩm: cách đặt tên sản phẩm TikTok Shop theo đúng chính sách",
    seoTitle: "Đặt tên sản phẩm TikTok Shop khi ít người bấm | Juli AI",
    description:
      "Sản phẩm có lượt hiển thị mà ít người bấm: đọc CTR ở Thẻ sản phẩm, đặt tên theo 5 thành phần của chính sách TikTok, tránh từ cấm, đo lại ở ngày 7, 14.",
    excerpt:
      "Khi sản phẩm có lượt hiển thị mà CTR ở Thẻ sản phẩm thấp: xác nhận tiêu đề là nguyên nhân, viết lại theo năm thành phần của chính sách TikTok, bỏ khuyến mãi, tên shop và ký tự đặc biệt, chọn từ khóa đúng sản phẩm, rồi đo lại ở ngày 7 và 14.",
    breadcrumbName: "Đặt tên sản phẩm",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "optimize",
    format: "pain",
    cover: blogCover("hero-dat-ten-san-pham-tiktok-shop-v1", "Minh hoạ: nhãn tên treo bằng dây có dòng chữ chính được gạch chân hồng, nền màu cát, chữ “Đặt tên sản phẩm”"),
    author: AUTHOR,
    guide: "ctr-the-san-pham-thap-doi-tieu-de-anh-bia",
    related: ["anh-bia-san-pham-tiktok-shop", "san-pham-tiktok-shop-khong-co-luot-hien-thi", "gmv-la-gi-tiktok-shop"],
    faq: [
      {
        question: "Tiêu đề sản phẩm TikTok Shop dài bao nhiêu ký tự?",
        answer:
          "Bài Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 4 của Học viện TikTok Shop ghi tiêu đề phải dài hơn 25 ký tự. Các trang chính sách không nêu độ dài tối đa hay một độ dài tốt nhất. Một tiêu đề đủ loại sản phẩm, chất liệu, đặc điểm và quy cách thường dài từ 40 ký tự trở lên.",
      },
      {
        question: "Có được ghi \"giảm giá\", \"freeship\" trong tên sản phẩm không?",
        answer:
          "Không nên. Trang chính sách Tiêu đề, mô tả, hình ảnh và video về sản phẩm liệt kê thông tin tiếp thị, khuyến mãi như \"giảm giá x%\" trong những thứ không đưa vào tiêu đề, cùng với URL, tên người bán, tên nền tảng khác và ký tự đặc biệt. Ưu đãi hãy tạo bằng công cụ khuyến mãi.",
      },
      {
        question: "Có được ghi tên thương hiệu vào tiêu đề không?",
        answer:
          "Chỉ khi bạn được ủy quyền bán sản phẩm của thương hiệu đó. Từ ngày 28/05/2026, việc che giấu tên thương hiệu bằng cách viết sai, chèn ký hiệu, số hoặc khoảng cách được tính là gian lận thương hiệu và có thể khiến sản phẩm bị gỡ.",
      },
      {
        question: "Dùng AI viết tiêu đề sản phẩm được không?",
        answer:
          "Được, Công cụ Tối Ưu Hoá Sản Phẩm của TikTok có sẵn tính năng Tối ưu hóa bằng AI cho tiêu đề và mô tả. Bạn vẫn chịu trách nhiệm tiêu đề mô tả chính xác sản phẩm, nên hãy đọc lại trước khi gửi và giữ nguyên văn tiêu đề cũ để quay lại được.",
      },
      {
        question: "Sửa tiêu đề bao lâu thì biết có hiệu quả?",
        answer:
          "Đọc sơ bộ ở ngày 7 và chốt ở ngày 14, so với 14 ngày trước khi sửa, trên luồng Thẻ sản phẩm, và so với các sản phẩm không sửa. Đọc Lượt hiển thị cùng CTR, vì tiêu đề tác động đến cả hai.",
      },
    ],
    sources: [
      academy("Tiêu đề, mô tả, hình ảnh và video về sản phẩm", "5918681919178512", "năm thành phần, những gì không đưa vào tiêu đề, nhiều biến thể (23/04/2026), kiểm tra 18/10/2026"),
      academy("Hướng dẫn đăng bán sản phẩm tại TikTok Shop", "10008395", "mục 3.1.2, 3.1.3, 3.1.7, 4.1 (05/10/2026), kiểm tra 18/10/2026"),
      academy("Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 4", "7905983637079809", "tiêu đề dài hơn 25 ký tự, tránh lặp từ (15/12/2023), kiểm tra 18/10/2026"),
      academy("Chẩn Đoán Thẻ Sản Phẩm", "5792290376255233", "Cơ hội tăng trưởng, Tiêu đề có thể được tối ưu hóa (21/02/2024), kiểm tra 18/10/2026"),
      academy("Trình Tối Ưu Hóa Tiêu Đề Sản Phẩm", "8617918787323649", "từ khóa đề xuất, điểm số lượng tìm kiếm, tab Sản phẩm được tối ưu hóa (23/11/2023), kiểm tra 18/10/2026"),
      academy("Trình Tối Ưu Hoá Sản Phẩm", "6532499267012354", "Tối ưu hóa bằng AI, thao tác hàng loạt (04/08/2025), kiểm tra 18/10/2026"),
      academy("Thủ thuật Clickbait trong đăng bán sản phẩm", "7213979802994433", "thao túng lưu lượng truy cập, số lượng bất thường (29/06/2025), kiểm tra 18/10/2026"),
      academy("Mô tả sản phẩm phóng đại là gì?", "6837770400581377", "khẳng định tuyệt đối (29/06/2025), kiểm tra 18/10/2026"),
      academy("Cập nhật Chính sách mới nhất", "8831988245645057", "gian lận thương hiệu dựa trên văn bản từ 28/05/2026 (01/07/2026), kiểm tra 18/10/2026"),
      academy("Lưu lượng truy cập sản phẩm", "10015238", "CTR theo khía cạnh thẻ sản phẩm (17/06/2026), kiểm tra 18/10/2026"),
    ],
  },
  {
    slug: "anh-bia-san-pham-tiktok-shop",
    status: "published",
    title: "Ảnh bìa sản phẩm TikTok Shop khiến người mua lướt qua: đọc CTR và đổi hình ảnh chính",
    seoTitle: "Ảnh bìa sản phẩm TikTok Shop bị lướt qua | Juli AI",
    description:
      "Hình ảnh chính bị lướt qua: đọc CTR ở Thẻ sản phẩm, yêu cầu ảnh của TikTok (600 × 600, nền đồng nhất, 60 % khung), lỗi hay gặp, đổi một ảnh, đo ngày 7, 14.",
    excerpt:
      "Ảnh bìa là hình ảnh chính, ảnh đầu tiên trên thẻ sản phẩm. Xác nhận CTR ở Thẻ sản phẩm thấp, đối chiếu yêu cầu chính thức của TikTok, tránh chữ khuyến mãi và ảnh hứa quá mức, đổi một ảnh, ghi lại ngày và so với sản phẩm không đổi ở ngày 7, 14.",
    breadcrumbName: "Ảnh bìa sản phẩm",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "optimize",
    format: "pain",
    cover: blogCover("hero-anh-bia-san-pham-tiktok-shop-v1", "Minh hoạ: khung ảnh núi và mặt trời với bốn góc lấy nét và tâm ngắm màu hồng, nền xanh da trời nhạt, chữ “Ảnh bìa sản phẩm”"),
    author: AUTHOR,
    guide: "ctr-the-san-pham-thap-doi-tieu-de-anh-bia",
    related: ["dat-ten-san-pham-tiktok-shop", "do-hieu-qua-sau-khi-sua-san-pham-tiktok-shop", "gmv-la-gi-tiktok-shop"],
    faq: [
      {
        question: "Kích thước ảnh sản phẩm TikTok Shop là bao nhiêu?",
        answer:
          "Theo trang chính sách Tiêu đề, mô tả, hình ảnh và video về sản phẩm, mọi hình ảnh phải có độ phân giải tối thiểu 600 × 600 pixel, và bạn tải lên tối đa 9 hình ảnh vuông. Bài Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 4 khuyến nghị thêm lớn hơn 1200 × 1200 và có ít nhất 3 hình ảnh.",
      },
      {
        question: "Ảnh bìa nên nền trắng hay có người mẫu?",
        answer:
          "Chính sách yêu cầu hình ảnh chính có nền màu đồng nhất, nên dùng màu trắng, sản phẩm chiếm ít nhất 60 % khung và hiện toàn bộ. TikTok không công bố kiểu ảnh nào được bấm nhiều hơn, nên trong khuôn khổ đó hãy thử từng phương án trên chính shop và đo CTR ở Thẻ sản phẩm.",
      },
      {
        question: "Ghi chữ giảm giá lên ảnh bìa có được không?",
        answer:
          "Không nên. Chính sách yêu cầu sản phẩm không bị nhãn dán hay hình mờ che phía trước, và chữ khuyến mãi thành sai khi đợt giảm giá kết thúc. Giá giảm và voucher đã có chỗ riêng trên thẻ khi bạn tạo bằng công cụ khuyến mãi.",
      },
      {
        question: "Dùng ảnh tạo bằng AI làm ảnh chính được không?",
        answer:
          "Được, nhưng bạn chịu trách nhiệm. Theo hướng dẫn về nội dung đăng bán tạo bởi AI (30/09/2026), ảnh AI phải phản ánh chính xác sản phẩm thực tế, gồm SKU, chất liệu, số lượng, đặc điểm và tình trạng khi giao, không phóng đại sản phẩm, và phải được kiểm tra trước khi đăng.",
      },
      {
        question: "Đổi ảnh bìa bao lâu thì biết ảnh mới tốt hơn?",
        answer:
          "Đọc CTR ở Thẻ sản phẩm sơ bộ ở ngày 7 và chốt ở ngày 14, so với 14 ngày trước ngày đổi và với các sản phẩm không đổi ảnh trong cùng thời gian. Trong 14 ngày đó đừng đổi tiêu đề, giá hay khuyến mãi của sản phẩm, và lưu lại ảnh cũ để quay về nếu ảnh mới không tốt hơn.",
      },
    ],
    sources: [
      academy("Tiêu đề, mô tả, hình ảnh và video về sản phẩm", "5918681919178512", "600 × 600, tối đa 9 ảnh vuông, hình ảnh chính, video tối đa 5 MB (23/04/2026), kiểm tra 18/10/2026"),
      academy("Hướng dẫn đăng bán sản phẩm tại TikTok Shop", "10008395", "mục 4.5 Hình ảnh và Video (05/10/2026), kiểm tra 18/10/2026"),
      academy("Chẩn Đoán Thẻ Sản Phẩm hoạt động như thế nào 4", "7905983637079809", "lớn hơn 1200 × 1200, ít nhất 3 hình ảnh, không lặp lại (15/12/2023), kiểm tra 18/10/2026"),
      academy("Trình Tối Ưu Hoá Sản Phẩm", "6532499267012354", "công cụ chỉnh ảnh, Tối ưu hóa bằng AI (04/08/2025), kiểm tra 18/10/2026"),
      academy("Đăng Sản Phẩm và Chỉnh Sửa Ảnh trên App", "7363289882281729", "chọn hình ảnh chính, xóa nền, nhiều hơn 1 hình ảnh (06/06/2025), kiểm tra 18/10/2026"),
      academy("Hiển thị thông tin sai lệch và hướng dẫn về nội dung đăng bán tạo bởi AI", "7224191560681232", "ảnh do AI tạo (30/09/2026), kiểm tra 18/10/2026"),
      academy("Thủ thuật Clickbait trong đăng bán sản phẩm", "7213979802994433", "đổi hình ảnh để trông như sản phẩm khác (29/06/2025), kiểm tra 18/10/2026"),
      academy("Mô tả sản phẩm phóng đại là gì?", "6837770400581377", "hình ảnh trước và sau (29/06/2025), kiểm tra 18/10/2026"),
      academy("Lưu lượng truy cập sản phẩm", "10015238", "CTR theo khía cạnh thẻ sản phẩm (17/06/2026), kiểm tra 18/10/2026"),
    ],
  },
  {
    slug: "do-hieu-qua-sau-khi-sua-san-pham-tiktok-shop",
    status: "published",
    title: "Sửa sản phẩm xong, làm sao biết có hiệu quả: cách đo trước và sau một thay đổi trên TikTok Shop",
    seoTitle: "Đo hiệu quả sau khi sửa sản phẩm TikTok Shop | Juli AI",
    description:
      "Sửa sản phẩm xong, làm sao biết có hiệu quả: chốt mốc 14 ngày, một chỉ số mục tiêu, đọc ngày 7, chốt ngày 14, so với mức dao động và tránh đợt sale.",
    excerpt:
      "So số hôm nay với hôm qua sau khi sửa gần như luôn cho kết luận sai. Ghi ngày sửa, chốt mốc 14 ngày, theo dõi một chỉ số mục tiêu trên đúng luồng, đọc sơ bộ ở ngày 7, kết luận ở ngày 14 và biết khi nào chưa đủ dữ liệu.",
    breadcrumbName: "Đo hiệu quả sau khi sửa sản phẩm",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "metrics",
    format: "pain",
    cover: blogCover("hero-do-hieu-qua-sau-khi-sua-san-pham-tiktok-shop-v1", "Minh hoạ: cây thước phía trên tờ lịch có một tuần và thêm một ngày tô hồng, nền đen, chữ “Đo trước và sau”"),
    author: AUTHOR,
    guide: "do-ket-qua-ngay-7-ngay-14-hoan-tac",
    related: ["doanh-thu-sau-sale-tiktok-shop", "doanh-thu-tiktok-shop-giam", "gmv-la-gi-tiktok-shop"],
    faq: [
      {
        question: "Sửa sản phẩm bao lâu thì biết có hiệu quả?",
        answer:
          "Đọc sơ bộ ở ngày 7 (đang lên, đi ngang hay đang giảm) và quyết định ở ngày 14, so với trung bình 14 ngày trước khi sửa. Đây là một phương pháp thực hành, không phải quy định của TikTok. Sản phẩm ít đơn hay dao động mạnh cần lâu hơn, và kết quả ngày 14 của chúng chỉ để tham khảo.",
      },
      {
        question: "Sửa nhiều thứ cùng lúc thì đo thế nào?",
        answer:
          "Không tách được tác dụng của từng thứ. Mỗi sản phẩm chỉ nên có một chỉ số mục tiêu tại một thời điểm: ảnh bìa và tiêu đề cùng nhắm CTR có thể đọc như một gói, nhưng đổi tiêu đề cùng lúc với giảm giá thì không biết phần nào của thay đổi nào.",
      },
      {
        question: "Sửa tiêu đề xong lượt xem tăng mà đơn không tăng là sửa hỏng?",
        answer:
          "Chưa chắc. Nếu mục tiêu là CTR và CTR tăng rõ, xem tiếp CTOR và GMV có nằm trong mức dao động bình thường không. CTOR giảm quá mức dao động nghĩa là tiêu đề mới đưa đến khách không định mua; lúc đó cân nhắc quay lại bản cũ.",
      },
      {
        question: "Cần bao nhiêu đơn để tin kết quả?",
        answer:
          "TikTok không đưa ra con số. Một quy tắc thực hành: chỉ coi kết quả là chắc khi mỗi kỳ có khoảng 30 đơn trở lên (khoảng 30 lượt nhấp nếu chỉ số là CTR) và mức thay đổi vượt mức dao động; dưới đó chỉ để tham khảo. Sản phẩm bán dưới khoảng 2 đơn mỗi ngày vì vậy cần hơn 14 ngày.",
      },
      {
        question: "Nên sửa sản phẩm trước hay sau đợt sale 11.11?",
        answer:
          "Theo lịch TikTok Shop đăng ngày 16/10/2026, 11.11 chạy từ 03 đến 15/11 và 12.12 từ 03 đến 15/12. Một lần sửa để thử nên tránh để mốc 14 ngày hoặc 14 ngày đo chạm các đợt này; nếu phải sửa gần đợt sale, ghi chú lại và so thêm với các sản phẩm không sửa.",
      },
    ],
    sources: [
      academy("Lịch Chiến Dịch TikTok Shop 2026", "6210902215264001", "lịch chiến dịch cuối năm 2026: 10.10, giữa tháng, lương về, 11.11, Black Friday, 12.12 (16/10/2026), kiểm tra 18/10/2026"),
      academy("Lưu lượng truy cập sản phẩm", "10015238", "Lượt hiển thị, CTR, CTOR, GMV theo khoảng thời gian đã chọn và theo định dạng nội dung (17/06/2026), kiểm tra 18/10/2026"),
      academy("Trình Tối Ưu Hoá Sản Phẩm", "6532499267012354", "hiển thị hiệu suất trước đây (số đơn, lượt xem) và điểm cần cải thiện, không nêu mức tăng sau tối ưu (04/08/2025), kiểm tra 18/10/2026"),
      academy("Chẩn Đoán Thẻ Sản Phẩm", "5792290376255233", "nguồn lưu lượng của Thẻ sản phẩm, nút Xuất (21/02/2024), kiểm tra 18/10/2026"),
    ],
  },
  {
    slug: "doanh-thu-sau-sale-tiktok-shop",
    status: "published",
    title: "Trước và sau 11.11: đọc số liệu sale TikTok Shop cho đúng",
    seoTitle: "Sale 11.11 TikTok Shop: đọc doanh thu sau sale | Juli AI",
    description:
      "11.11 TikTok Shop chạy 03 đến 15/11/2026: ghi mốc gì trước sale, đọc GMV theo luồng, vì sao doanh thu tụt sau sale, đơn hủy, hoàn tiền và phí.",
    excerpt:
      "Theo lịch chính thức, 11.11 chạy từ 03 đến 15/11 và 12.12 từ 03 đến 15/12. Chốt mốc 14 ngày trước đợt, đọc GMV theo luồng trong đợt, chờ đủ 14 ngày sau đợt và tính cả đơn hủy, hoàn tiền đến muộn trước khi kết luận sản phẩm nào đáng giữ.",
    breadcrumbName: "Doanh thu sau sale",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "metrics",
    format: "pain",
    cover: blogCover("hero-doanh-thu-sau-sale-tiktok-shop-v1", "Minh hoạ: tờ lịch xé ghi 11.11 với vài mảnh giấy màu, nền hồng đậm, chữ “Đọc số sau sale”"),
    author: AUTHOR,
    guide: "doc-phan-tich-tiktok-shop-theo-luong-truy-cap",
    related: ["do-hieu-qua-sau-khi-sua-san-pham-tiktok-shop", "doanh-thu-tiktok-shop-giam", "gmv-la-gi-tiktok-shop"],
    faq: [
      {
        question: "Sale 11.11 trên TikTok Shop năm 2026 diễn ra khi nào?",
        answer:
          "Theo bài Lịch Chiến Dịch TikTok Shop 2026 của Học viện TikTok Shop (đăng 16/10/2026), TikTok Shop 11.11 chạy từ 03 đến 15/11/2026. Một số trang không chính thức ghi khác; hãy theo lịch của TikTok và kiểm tra lại trong Seller Center.",
      },
      {
        question: "Sau sale doanh thu tụt có bình thường không?",
        answer:
          "TikTok không công bố một mức tụt chuẩn. Trước khi kết luận, chờ đủ 14 ngày sau đợt, so với mốc 14 ngày trước đợt chứ không với trong đợt, xem luồng nào tụt, giá đã về và hàng còn đủ chưa, và tính cả đơn hủy, hoàn tiền đến muộn.",
      },
      {
        question: "Nên so 11.11 với 10.10 hay với tháng trước?",
        answer:
          "So đợt sale với đợt sale, kỳ thường với kỳ thường, bằng trung bình mỗi ngày. 10.10 năm 2026 dài 4 ngày, 11.11 dài 13 ngày, nên so tổng GMV của hai đợt sẽ sai.",
      },
      {
        question: "Có nên sửa sản phẩm ngay trước sale không?",
        answer:
          "Nếu muốn biết lần sửa có tác dụng thì không: lượng khách tăng vì sale sẽ che mất tác dụng đó. Sửa vì thông tin sai thì cứ sửa, nhưng ghi lại ngày và đừng coi số liệu trong đợt là kết quả của lần sửa.",
      },
      {
        question: "Đăng ký tham gia chiến dịch 11.11 ở đâu?",
        answer:
          "Theo trang lịch chiến dịch của TikTok Shop, người bán cập nhật thông tin chi tiết và đăng ký tại Seller Center hoặc liên hệ quản lý gian hàng. Điều kiện, hạn chót và mức ưu đãi của từng đợt xem trong Seller Center; bài này không nêu vì trang lịch không có các thông tin đó.",
      },
    ],
    sources: [
      academy("Lịch Chiến Dịch TikTok Shop 2026", "6210902215264001", "lịch chiến dịch cuối năm 2026: 10.10 07 đến 10/10, 11.11 03 đến 15/11, Black Friday 26 đến 27/11, 12.12 03 đến 15/12, lương về 24 đến 25; đăng ký tại Seller Center hoặc quản lý gian hàng (16/10/2026), kiểm tra 18/10/2026"),
      academy("Lưu lượng truy cập sản phẩm", "10015238", "GMV gồm cả đơn đã hủy và hoàn tiền, hoàn tiền phát sinh sau ngày mua (17/06/2026), kiểm tra 18/10/2026"),
      academy("Trả hàng và Hoàn tiền", "1766935302801169", "yêu cầu trả hàng trong 15 ngày theo lịch, 6 ngày với một số danh mục (15/10/2026), kiểm tra 18/10/2026"),
      academy("Phí Xử Lý Đơn Hàng", "2968734088120080", "khoản cố định cho mỗi đơn giao thành công (11/10/2025), kiểm tra 18/10/2026"),
    ],
  },
  {
    slug: "dung-thu-juli-ai-mien-phi-3-thang",
    status: "published",
    title: "Dùng thử Juli AI miễn phí 3 tháng: đăng ký, kết nối shop và 14 ngày đầu tiên",
    seoTitle: "Dùng thử miễn phí 3 tháng: đăng ký, bắt đầu | Juli AI",
    description:
      "Dùng thử Juli AI 3 tháng miễn phí, không cần thẻ: điền đăng ký, chuẩn bị Quy tắc, kết nối TikTok Shop, đọc thẻ đề xuất đầu tiên, ngày 7 và ngày 14.",
    excerpt:
      "3 tháng miễn phí kể từ ngày đăng ký, không cần thẻ thanh toán, sau đó 500.000đ/tháng. Hai cách bắt đầu, những gì nên chuẩn bị trước cuộc gọi, ngày đầu sau khi kết nối và cách đọc kết quả ngày 7, ngày 14.",
    breadcrumbName: "Dùng thử Juli AI",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "guide",
    format: "guide",
    cover: blogCover("hero-dung-thu-juli-ai-mien-phi-3-thang-v1", "Minh hoạ: ba chậu cây trên một kệ, mầm cây cao dần, chậu thứ ba nở một bông hoa hồng, nền hồng nhạt, chữ “Dùng thử miễn phí”"),
    author: AUTHOR,
    related: ["tim-san-pham-keo-gmv-xuong-tiktok-shop", "ctor-thap-viet-lai-mo-ta-san-pham", "gmv-la-gi-tiktok-shop"],
    faq: [
      {
        question: "Dùng thử Juli có cần thẻ thanh toán không?",
        answer:
          "Không. Theo Điều khoản dịch vụ, tài khoản mới được dùng thử miễn phí 3 tháng kể từ ngày đăng ký, không cần thẻ thanh toán.",
      },
      {
        question: "Sau 3 tháng dùng thử thì tính phí thế nào?",
        answer:
          "Sau thời gian dùng thử, phí dịch vụ Juli là 500.000đ/tháng, và bạn có thể huỷ bất cứ lúc nào. Câu hỏi về phí gửi tới lienhe@app-juli.com.",
      },
      {
        question: "Đăng ký xong có bắt buộc kết nối shop ngay không?",
        answer:
          "Không. Bạn có thể chờ đội Juli gọi hoặc nhắn Zalo để kết nối cùng, hoặc tự kết nối từ trang cảm ơn. Trước khi kết nối, bạn cũng có thể xem bản dữ liệu mẫu, không cần tài khoản.",
      },
      {
        question: "Dùng thử có thay đổi gì trên shop của tôi không?",
        answer:
          "Không, cho đến khi bạn duyệt một thẻ đề xuất và xác nhận nội dung cụ thể. Kết nối chỉ cho phép Juli đọc dữ liệu và tạo đề xuất. Juli không đổi giá và không tạo khuyến mãi.",
      },
      {
        question: "Bản xem thử với dữ liệu mẫu khác gì dùng thử?",
        answer:
          "Bản xem thử chạy trên Cửa hàng Mẫu Hoa Mai, một shop minh hoạ, và không ghi gì lên TikTok Shop. Dùng thử chạy trên shop thật của bạn sau khi bạn kết nối.",
      },
    ],
    sources: [],
  },
  {
    slug: "tim-san-pham-keo-gmv-xuong-tiktok-shop",
    status: "published",
    title: "Tìm sản phẩm đang kéo GMV TikTok Shop xuống: từ chỉ số nghẽn đến thẻ đề xuất",
    seoTitle: "Tìm sản phẩm kéo GMV TikTok Shop xuống | Juli AI",
    description:
      "Cách Juli tìm sản phẩm đang kéo GMV TikTok Shop xuống: từ luồng và chỉ số nghẽn, bảng Kéo xuống theo đồng mỗi ngày, nhãn Rõ, Tham khảo đến thẻ đề xuất.",
    excerpt:
      "Sắp theo doanh thu giảm thường chỉ sai chỗ. Juli tìm luồng và chỉ số lấy đi nhiều GMV nhất, chia con số đó cho từng sản phẩm theo đồng mỗi ngày, rồi biến dòng đủ cơ sở thành thẻ đề xuất.",
    breadcrumbName: "Sản phẩm kéo GMV xuống",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "metrics",
    format: "guide",
    cover: blogCover("hero-tim-san-pham-keo-gmv-xuong-tiktok-shop-v1", "Minh hoạ: hai quả bóng bay vàng và xanh bay lên, một quả bóng hồng bị một chiếc mỏ neo giữ thấp, nền xám đậm kẻ ô, chữ “Sản phẩm kéo GMV xuống”"),
    author: AUTHOR,
    related: ["doanh-thu-tiktok-shop-giam", "ctr-the-san-pham-thap-doi-tieu-de-anh-bia", "ctor-thap-viet-lai-mo-ta-san-pham"],
    faq: [
      {
        question: "Juli xếp sản phẩm theo doanh thu giảm hay theo gì?",
        answer:
          "Theo số tiền GMV mỗi ngày mà sản phẩm mất ở chỉ số đó, trên đúng luồng đó. Vì vậy một sản phẩm bán chạy mất vài phần trăm CTOR có thể đứng trên một sản phẩm nhỏ mất một nửa.",
      },
      {
        question: "Vì sao sản phẩm của tôi ghi Chưa có đề xuất?",
        answer:
          "Sản phẩm chưa đủ cơ sở cho một thẻ: thường là dữ liệu còn ít hoặc mức giảm chưa vượt mức dao động (nhãn Tham khảo), hoặc sản phẩm đang có một thay đổi khác được đo, hoặc cùng thay đổi vừa bị từ chối hay hoàn tác gần đây.",
      },
      {
        question: "Các dòng trong bảng có cộng bằng con số trên ô không?",
        answer:
          "Có. Bảng chia con số của ô cho từng sản phẩm; các dòng đầu cộng với dòng Còn lại bằng đúng con số trên ô, nên không có đồng GMV nào bị đếm hai lần.",
      },
      {
        question: "Juli có xếp theo lợi nhuận không?",
        answer:
          "Không. Giá vốn hoặc biên lợi nhuận bạn nhập trong Quy tắc được dùng để giữ mọi đề xuất giảm giá trong biên lợi nhuận bạn cho phép; một đề xuất như vậy chỉ xuất hiện khi Juli biết giá vốn.",
      },
    ],
    sources: [
      academy("Lưu lượng truy cập sản phẩm", "10015238", "GMV theo luồng, định nghĩa CTR, CTOR, AOV (SKU) (17/06/2026), kiểm tra 18/10/2026"),
    ],
  },
  {
    slug: "ctr-the-san-pham-thap-doi-tieu-de-anh-bia",
    status: "published",
    title: "CTR Thẻ sản phẩm thấp: Juli đề xuất đổi tiêu đề và ảnh bìa như thế nào, và bạn cần làm gì",
    seoTitle: "CTR Thẻ sản phẩm thấp: đề xuất tiêu đề, ảnh bìa | Juli AI",
    description:
      "CTR Thẻ sản phẩm TikTok Shop thấp: khi nào Juli mở thẻ, Juli soạn tiêu đề, ảnh bìa chỉ bằng ảnh của bạn, GMV dự kiến, đo ngày 7, 14 và hoàn tác.",
    excerpt:
      "Người mua thấy mà không bấm: Juli đề xuất đổi tiêu đề hoặc ảnh bìa. Tiêu đề do Juli soạn và chỉ ghi khi bạn xác nhận; ảnh bìa là ảnh bạn gửi, Juli tải lên sau khi bạn xác nhận và giữ ảnh cũ để hoàn tác.",
    breadcrumbName: "CTR Thẻ sản phẩm thấp",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "optimize",
    format: "guide",
    cover: blogCover("hero-ctr-the-san-pham-thap-doi-tieu-de-anh-bia-v1", "Minh hoạ: một nam châm hình móng ngựa màu hồng đậm hút ba con trỏ chuột về phía nó, nền vàng, chữ “Nâng CTR thẻ sản phẩm”"),
    author: AUTHOR,
    related: ["dat-ten-san-pham-tiktok-shop", "anh-bia-san-pham-tiktok-shop", "ctor-thap-viet-lai-mo-ta-san-pham"],
    faq: [
      {
        question: "Juli có tự tạo ảnh bìa cho sản phẩm không?",
        answer:
          "Không. Juli phân tích ảnh bìa hiện tại và nói cần đổi gì, nhưng ảnh mới là ảnh bạn gửi. Juli chỉ tải ảnh lên TikTok Shop sau khi bạn xác nhận, và giữ ảnh cũ để có thể hoàn tác.",
      },
      {
        question: "Đổi tiêu đề có làm sản phẩm mất thứ hạng không?",
        answer:
          "Juli không hứa trước điều đó. Lượt hiển thị là một chỉ số giữ ổn định của thẻ CTR: nếu ở ngày 7 nó ra ngoài khoảng cho phép, Juli hỏi bạn có muốn hoàn tác về tiêu đề cũ không.",
      },
      {
        question: "Bao lâu thì biết CTR có tăng không?",
        answer:
          "Ngày 7 là kiểm tra giữa chừng (Đang lên hoặc Chưa rõ), ngày 14 là kết quả chốt (Đạt, Đạt · chưa chắc chắn, Một phần hoặc Không đạt), so với mốc 14 ngày trước khi áp dụng, đo trên luồng Thẻ sản phẩm.",
      },
      {
        question: "Có nên đổi cả tiêu đề và ảnh bìa cùng lúc không?",
        answer:
          "Không. Juli không thực hiện hai thay đổi cùng lúc trên một sản phẩm, vì khi chúng chồng lên nhau, không ai biết thay đổi nào tạo ra kết quả. Thay đổi tiếp theo chỉ được thực hiện sau khi thay đổi trước chốt ở ngày 14.",
      },
    ],
    sources: [
      academy("Lưu lượng truy cập sản phẩm", "10015238", "CTR = lượt nhấp ÷ lượt hiển thị, theo từng luồng (17/06/2026), kiểm tra 18/10/2026"),
    ],
  },
  {
    slug: "ctor-thap-viet-lai-mo-ta-san-pham",
    status: "published",
    title: "CTOR thấp, khách bấm vào mà không đặt hàng: Juli đề xuất mô tả sản phẩm như thế nào",
    seoTitle: "CTOR thấp: đề xuất mô tả sản phẩm | Juli AI",
    description:
      "CTOR TikTok Shop thấp: Juli tách trước hay sau giỏ hàng, soạn mô tả mới chỉ ghi khi bạn xác nhận, khuyến mãi do bạn làm trên Seller Center, đo ngày 7, 14.",
    excerpt:
      "Khách bấm vào mà không đặt: trước giỏ hàng, Juli đề xuất viết lại mô tả và chỉ ghi sau khi bạn xác nhận; sau giỏ hàng, Juli hướng dẫn và bạn làm trên Seller Center. Đo ngày 7, chốt ngày 14, hoàn tác được.",
    breadcrumbName: "CTOR thấp: viết lại mô tả",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "optimize",
    format: "guide",
    cover: blogCover("hero-ctor-thap-viet-lai-mo-ta-san-pham-v1", "Minh hoạ: một cuộn giấy mở, hai dòng cũ bị gạch, các dòng mới và một dòng hồng, cây bút đang viết, nền nâu chấm bi, chữ “Viết lại mô tả”"),
    author: AUTHOR,
    related: ["mo-ta-san-pham-tiktok-shop", "khach-xem-nhung-khong-mua-tiktok-shop", "ctr-the-san-pham-thap-doi-tieu-de-anh-bia"],
    faq: [
      {
        question: "Juli có đổi giá sản phẩm để tăng CTOR không?",
        answer:
          "Không. Juli không thay đổi giá. Với giảm giá hay flash sale, Juli đề xuất mức giảm nằm trong biên lợi nhuận bạn đặt (chỉ khi biết giá vốn), bạn tạo trên Seller Center, rồi Juli kiểm tra lại bằng quyền chỉ đọc và bắt đầu đo.",
      },
      {
        question: "Mô tả do AI soạn có thể sai thông tin sản phẩm không?",
        answer:
          "Bản soạn được kiểm tra độ dài, từ không được dùng và đối chiếu với thông tin của chính sản phẩm trước khi bạn xem, nhưng bạn vẫn là người đọc lại và quyết định ở bước xác nhận. Nếu sai, bạn sửa trước khi áp dụng hoặc hoàn tác sau đó.",
      },
      {
        question: "Vì sao Juli không đề xuất giảm giá cho sản phẩm của tôi?",
        answer:
          "Một đề xuất giảm giá chỉ xuất hiện khi Juli biết giá vốn của sản phẩm, và luôn nằm trong biên lợi nhuận bạn đặt trong Quy tắc. Nếu chưa nhập giá vốn, Juli chỉ đề xuất mô tả cho sản phẩm đó.",
      },
      {
        question: "CTOR được đo trên kênh nào?",
        answer:
          "TikTok không tách đơn hàng SKU theo từng luồng cho từng sản phẩm, nên CTOR của một thay đổi được đo trên tất cả các kênh, so với mốc 14 ngày trước khi áp dụng.",
      },
    ],
    sources: [
      academy("Lưu lượng truy cập sản phẩm", "10015238", "CTOR = đơn hàng SKU ÷ lượt nhấp, theo từng luồng (17/06/2026), kiểm tra 18/10/2026"),
      academy("Tiêu đề, mô tả, hình ảnh và video về sản phẩm", "5918681919178512", "mô tả không dưới 30 từ (23/04/2026), kiểm tra 18/10/2026"),
    ],
  },
  {
    slug: "huong-dan-ket-noi-tiktok-shop-voi-juli",
    status: "published",
    title: "Hướng dẫn kết nối TikTok Shop với Juli: 4 bước và những gì diễn ra trong giờ đầu",
    seoTitle: "Hướng dẫn kết nối TikTok Shop với Juli | Juli AI",
    description:
      "Kết nối TikTok Shop với Juli trong 4 bước, không cần mật khẩu shop: các nhóm quyền, quét nhanh 14 ngày, đọc 60 ngày, khi thiếu quyền và cách ngắt kết nối.",
    excerpt:
      "Đăng nhập Juli, bấm Kết nối TikTok Shop, đồng ý cấp quyền trên trang của TikTok, quay lại Juli. Bài này đi qua từng bước, giải thích từng nhóm quyền và cách đọc dải tiến trình trong giờ đầu.",
    breadcrumbName: "Kết nối TikTok Shop với Juli",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "guide",
    format: "guide",
    cover: blogCover("hero-huong-dan-ket-noi-tiktok-shop-voi-juli-v1", "Minh hoạ: phích cắm màu tím nhạt có dây trắng cắm vào ổ điện, hai tia sáng hồng ở chỗ nối, nền chàm đậm với các vòng tròn, chữ “Kết nối shop”"),
    author: AUTHOR,
    related: ["doc-phan-tich-tiktok-shop-theo-luong-truy-cap", "duyet-de-xuat-toi-uu-san-pham-tiktok-shop", "gmv-la-gi-tiktok-shop"],
    faq: [
      {
        question: "Juli có cần mật khẩu TikTok Shop của tôi không?",
        answer:
          "Không. Bạn đăng nhập trên trang uỷ quyền của chính TikTok Shop và đồng ý cấp quyền cho ứng dụng Juli. Juli chỉ nhận mã truy cập do TikTok cấp, được mã hoá trước khi lưu, và không bao giờ thấy mật khẩu của bạn.",
      },
      {
        question: "Kết nối TikTok Shop với Juli mất bao lâu?",
        answer:
          "Bước uỷ quyền mất một hai phút. Sau đó Juli tự đọc dữ liệu: quét nhanh 14 ngày trong vài phút đầu, rồi đọc 60 ngày và chẩn đoán đầy đủ, thời gian tuỳ số sản phẩm của shop. Lịch sử cũ hơn được tải dần vào ban đêm, đến 180 ngày hoặc giới hạn TikTok cho phép.",
      },
      {
        question: "Kết nối xong Juli có thay đổi gì trên shop không?",
        answer:
          "Không. Kết nối chỉ cho phép Juli đọc dữ liệu và tạo đề xuất. Một thay đổi chỉ được ghi lên shop khi bạn duyệt một thẻ đề xuất và xác nhận nội dung cụ thể; giá và khuyến mãi Juli không bao giờ ghi.",
      },
      {
        question: "Làm sao hủy kết nối TikTok Shop với Juli?",
        answer:
          "Bạn liên hệ Juli qua email lienhe@app-juli.com hoặc trang Liên hệ; đội Juli ngắt kết nối shop giúp bạn. Juli ngừng lấy dữ liệu và ngừng tạo đề xuất ngay, còn lịch sử, quy tắc và kết quả đo được giữ để bạn kết nối lại khi cần.",
      },
      {
        question: "Juli có kết nối được Shopee không?",
        answer:
          "Chưa. Shopee đang được tích hợp qua Shopee Open Platform và chưa thể kết nối. Hiện Juli hoạt động với TikTok Shop.",
      },
    ],
    sources: [
      { title: "Juli AI: Kết nối TikTok Shop", url: "https://app-juli.com/ket-noi/tiktok-shop", note: "các bước, nhóm quyền, dữ liệu đọc và ghi, ngắt kết nối" },
      { title: "Juli AI: Chính sách bảo mật", url: "https://app-juli.com/privacy", note: "dữ liệu thu thập, điều kiện ghi lên shop, thời gian lưu" },
    ],
  },
  {
    slug: "doc-phan-tich-tiktok-shop-theo-luong-truy-cap",
    status: "published",
    title: "Cách đọc màn hình Phân tích TikTok Shop theo luồng truy cập: Thẻ sản phẩm, Tab cửa hàng, Video, LIVE, Liên kết",
    seoTitle: "Đọc phân tích TikTok Shop theo luồng | Juli AI",
    description:
      "Đọc màn hình Phân tích của Juli từ trên xuống: năm luồng truy cập, bốn ô chỉ số và số đồng mỗi ngày, nhãn Rõ hay Tham khảo, khuyến mãi và ngày sale.",
    excerpt:
      "Dòng kết luận ở đầu trang, bốn ô Lượt hiển thị, CTR, CTOR, AOV của từng luồng, bảng sản phẩm, khuyến mãi và ngày sale: đọc một màn hình mẫu từng phần, và biết khi nào chưa nên sửa gì.",
    breadcrumbName: "Đọc Phân tích theo luồng",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "guide",
    format: "guide",
    cover: blogCover("hero-doc-phan-tich-tiktok-shop-theo-luong-truy-cap-v1", "Minh hoạ: một tia sáng đi qua lăng kính tam giác và tách thành năm dải màu hồng, tím và đen, nền xanh chanh nhạt, chữ “Đọc theo từng luồng”"),
    author: AUTHOR,
    related: ["huong-dan-ket-noi-tiktok-shop-voi-juli", "duyet-de-xuat-toi-uu-san-pham-tiktok-shop", "chi-so-tiktok-shop-ctr-ctor-aov"],
    faq: [
      {
        question: "Juli lấy số liệu phân tích từ đâu?",
        answer:
          "Từ chính TikTok Shop của bạn, qua API chính thức mà bạn uỷ quyền khi kết nối: hiệu suất sản phẩm theo từng luồng, đơn hàng, sản phẩm, video, LIVE và khuyến mãi. Juli không cào trang web và không dùng số ước đoán của bên thứ ba cho phần Phân tích.",
      },
      {
        question: "Số trên Juli có khớp với Seller Center không?",
        answer:
          "Juli dùng đúng định nghĩa của TikTok cho CTR, CTOR, AOV (SKU) và GMV, gồm cả đơn đã huỷ và hoàn tiền, và tính tỷ lệ của kỳ từ tổng của kỳ như Seller Center. Khác biệt nhỏ vẫn có thể xảy ra khi hai bên chốt số liệu ở thời điểm khác nhau.",
      },
      {
        question: "Bao lâu màn hình Phân tích được cập nhật?",
        answer:
          "Số liệu phân tích được lấy mỗi ngày một lần, khi TikTok công bố ngày dữ liệu mới, nên ngày mới nhất thường là hôm qua. Đơn hàng, sản phẩm và tồn kho được đồng bộ nhiều lần trong ngày. Giờ cập nhật gần nhất ghi ở góc trên màn hình.",
      },
      {
        question: "Shop ít đơn thì đọc Phân tích có ý nghĩa không?",
        answer:
          "Có, nhưng Juli nói rõ mức chắc chắn. Khi số đơn ít, dòng sản phẩm mang nhãn Tham khảo thay vì Rõ và Juli gợi ý theo dõi thêm. Sản phẩm còn quá ít dữ liệu được ghi là ít dữ liệu.",
      },
      {
        question: "Có dùng luồng Liên kết để kết luận về một sản phẩm không?",
        answer:
          "Không. Luồng Liên kết, tức video và LIVE của nhà sáng tạo, được theo dõi ở Trang chủ để bạn thấy toàn cảnh, nhưng phần lớn biến động ở đó đến từ nội dung của nhà sáng tạo chứ không từ trang sản phẩm của bạn.",
      },
    ],
    sources: [
      academy("Lưu lượng truy cập sản phẩm", "10015238", "năm luồng, Lượt hiển thị, CTR, CTOR, GMV theo định dạng nội dung (17/06/2026), kiểm tra 18/10/2026"),
      { title: "Juli AI: Phân tích shop", url: "https://app-juli.com/san-pham/phan-tich-shop", note: "năm luồng, phễu từng luồng, nhãn tin cậy, nhịp dữ liệu" },
    ],
  },
  {
    slug: "duyet-de-xuat-toi-uu-san-pham-tiktok-shop",
    status: "published",
    title: "Duyệt một thẻ đề xuất của Juli: từ lý do, sửa nội dung đến xác nhận lần cuối",
    seoTitle: "Duyệt đề xuất tối ưu sản phẩm TikTok Shop | Juli AI",
    description:
      "Đi qua một thẻ đề xuất của Juli: thẻ nói gì, GMV dự kiến nghĩa là gì, Duyệt rồi Xác nhận, phần Juli làm và phần bạn làm, từ chối kèm lý do, nhịp thẻ.",
    excerpt:
      "Duyệt chưa đổi gì trên shop: thay đổi chỉ được ghi khi bạn xem bản cũ, bản mới và xác nhận trong lượt chạy. Bài này đi qua một thẻ từ lý do đến bước xác nhận, kể cả ảnh bìa, giá và từ chối.",
    breadcrumbName: "Duyệt thẻ đề xuất",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "guide",
    format: "guide",
    cover: blogCover("hero-duyet-de-xuat-toi-uu-san-pham-tiktok-shop-v1", "Minh hoạ: hai chiếc chìa khoá từ hai bên cùng cắm vào một ổ khoá móc, dấu tích hồng phía trên, nền xanh bạc hà chấm bi, chữ “Duyệt rồi mới đổi”"),
    author: AUTHOR,
    related: ["do-ket-qua-ngay-7-ngay-14-hoan-tac", "doc-phan-tich-tiktok-shop-theo-luong-truy-cap", "toi-uu-the-san-pham-tiktok-shop"],
    faq: [
      {
        question: "Juli có tự thay đổi shop của tôi mà không hỏi không?",
        answer:
          "Không. Một thay đổi chỉ được ghi lên TikTok Shop sau hai bước của bạn: bấm Duyệt trên thẻ, rồi xác nhận nội dung cụ thể trong lượt chạy. Không duyệt và xác nhận, không có gì thay đổi.",
      },
      {
        question: "Juli có đổi giá sản phẩm không?",
        answer:
          "Không. Với giá, Juli chỉ đề xuất. Giảm giá sản phẩm, flash sale hay giảm phí vận chuyển do bạn tạo trên Seller Center theo hướng dẫn của Juli, trong biên lợi nhuận bạn đặt; Juli kiểm tra lại bằng quyền chỉ đọc rồi bắt đầu đo.",
      },
      {
        question: "Nội dung AI viết có được kiểm tra trước không?",
        answer:
          "Có. Tiêu đề hay mô tả mới được kiểm tra độ dài, giọng văn và danh sách từ không được dùng trong Quy tắc của bạn, và được đối chiếu với thông tin của chính sản phẩm, trước khi hiện ra để bạn xác nhận. Bạn sửa được nội dung trước khi áp dụng.",
      },
      {
        question: "Từ chối một thẻ thì nó có quay lại không?",
        answer:
          "Không quay lại ngay. Juli ghi nhận lý do bạn chọn để các đề xuất sau hợp với shop của bạn hơn.",
      },
      {
        question: "Mỗi ngày tôi nhận bao nhiêu thẻ đề xuất?",
        answer:
          "Juli giữ số thẻ mới mỗi ngày ở mức bạn duyệt kịp, và chỉ đưa ra thẻ khi có việc đáng làm. Bạn có thể giảm số thẻ đang mở cùng lúc trong Quy tắc. Thẻ có thời hạn; hết hạn thì Juli đề xuất lại khi thay đổi đó vẫn còn phù hợp.",
      },
    ],
    sources: [
      academy("Chẩn Đoán Thẻ Sản Phẩm", "5792290376255233", "chẩn đoán TikTok trả về cho trang sản phẩm (21/02/2024), kiểm tra 18/10/2026"),
      { title: "Juli AI: Đề xuất và thực thi", url: "https://app-juli.com/san-pham/de-xuat-va-thuc-thi", note: "thẻ đề xuất, hai bước đồng ý, hoàn tác" },
    ],
  },
  {
    slug: "do-ket-qua-ngay-7-ngay-14-hoan-tac",
    status: "published",
    title: "Đo kết quả sau khi sửa sản phẩm: đọc ngày 7, ngày 14 và biết khi nào nên hoàn tác",
    seoTitle: "Đo kết quả ngày 7, ngày 14 và hoàn tác | Juli AI",
    description:
      "Đọc kết quả đo lường của Juli sau khi sửa sản phẩm TikTok Shop: mốc 14 ngày, ngưỡng giữ ổn định, ngày 7 Đang lên hay Chưa rõ, bốn nhãn ngày 14, hoàn tác.",
    excerpt:
      "Ngày 7 là kiểm tra giữa chừng, ngày 14 là kết quả chốt, và Juli không bao giờ tự hoàn tác. Đọc từng nhãn trên một thẻ mẫu, hiểu câu hỏi “Hoàn tác?” và biết khi nào nên chờ.",
    breadcrumbName: "Đo kết quả ngày 7, ngày 14",
    publishedAt: "2026-10-18",
    updatedAt: "2026-10-18",
    category: "guide",
    format: "guide",
    cover: blogCover("hero-do-ket-qua-ngay-7-ngay-14-hoan-tac-v1", "Minh hoạ: đồng hồ cát có mũi tên hồng vòng ngược bao quanh, nền xanh ô liu đậm, chữ “Đo xong mới chốt”"),
    author: AUTHOR,
    related: ["duyet-de-xuat-toi-uu-san-pham-tiktok-shop", "do-hieu-qua-sau-khi-sua-san-pham-tiktok-shop", "doc-phan-tich-tiktok-shop-theo-luong-truy-cap"],
    faq: [
      {
        question: "Vì sao phải chờ đến ngày 14 mới chốt kết quả?",
        answer:
          "Số liệu TikTok Shop dao động mạnh theo ngày trong tuần, theo đợt sale và theo cách TikTok phân phối. Bảy ngày thường chưa đủ để tách tác động của một thay đổi khỏi dao động đó, nên ngày 7 chỉ là kiểm tra giữa chừng, ngày 14 mới là kết quả chốt.",
      },
      {
        question: "Ngày 7 mà kết quả xấu thì sao?",
        answer:
          "Nếu một chỉ số bạn muốn giữ ổn định ra ngoài ngưỡng, Juli hỏi bạn có muốn hoàn tác không, kèm số liệu cụ thể. Bạn chọn Hoàn tác hoặc Giữ thay đổi để đo tiếp đến ngày 14. Juli không tự hoàn tác.",
      },
      {
        question: "Juli có nhận công cho mọi lần GMV tăng không?",
        answer:
          "Không. Kết quả chỉ là Đạt khi chỉ số mục tiêu tăng rõ hơn mức dao động bình thường, chạm mục tiêu và GMV giữ được. Nếu trong thời gian đo có thay đổi khác như bạn tự sửa tiêu đề hay mở khuyến mãi, kết quả ghi là bị ảnh hưởng bởi thay đổi khác.",
      },
      {
        question: "GMV dự kiến trên thẻ có phải cam kết không?",
        answer:
          "Không. GMV dự kiến là ước tính từ số liệu gần đây của sản phẩm. Kết quả thật đo được ở ngày 14 được đặt cạnh con số này để bạn so sánh.",
      },
      {
        question: "Hoàn tác có xoá chỉnh sửa tôi tự làm không?",
        answer:
          "Không. Trước khi khôi phục, Juli đọc lại sản phẩm trên TikTok Shop; nếu nội dung đã bị sửa bên ngoài Juli sau lần thay đổi, Juli không ghi đè và báo cho bạn. Lượt hoàn tác cũng dừng ở bước xác nhận trước khi ghi.",
      },
    ],
    sources: [
      academy("Lưu lượng truy cập sản phẩm", "10015238", "chỉ số theo luồng dùng để đo, GMV gồm cả đơn huỷ và hoàn tiền (17/06/2026), kiểm tra 18/10/2026"),
      { title: "Juli AI: Đo lường GMV", url: "https://app-juli.com/san-pham/do-luong-gmv", note: "mốc so sánh, ngày 7, ngày 14, nhãn kết quả" },
    ],
  },
];
