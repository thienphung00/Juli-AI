import Link from "next/link";

import { CtaLink } from "../../components/cta-link";
import { LandingHeader } from "../../components/landing-header";
import { SiteFooter } from "../../components/site-footer";
import { StepsSection } from "../../components/steps-section";
import {
  breadcrumbSchema,
  buildMetadata,
  faqPageSchema,
  JsonLd,
  softwareApplicationSchema,
} from "../../lib/seo";
import { COMPANY, DEMO_URL } from "../../lib/site";

/**
 * `/san-pham` — the product overview (D43.1). This is the former `/product`
 * content moved as-is (P33-A); P33-B rewrites it (~1,500 words, D43.4).
 * `/product` 301s here (next.config.ts).
 */
export const metadata = buildMetadata("/san-pham");

const CAPABILITIES = [
  {
    title: "Theo dõi shop",
    body: "Tự động đồng bộ đơn hàng, sản phẩm, tồn kho và đơn hoàn từ TikTok Shop, tổng hợp thành một bảng điều khiển dễ đọc.",
  },
  {
    title: "Phân tích theo luồng truy cập",
    body: "Tách GMV theo Thẻ sản phẩm, Video, Live và các nguồn khác; so sánh Hiển thị, CTR, CTOR, AOV với kỳ trước để tìm đúng chỉ số đang đi xuống.",
  },
  {
    title: "Đề xuất hành động",
    body: "Chỉ ra sản phẩm và nội dung cần tối ưu kèm hành động cụ thể. Bạn có thể xem lý do, chỉnh sửa hoặc đặt câu hỏi trước khi quyết định.",
  },
  {
    title: "Thực hiện khi bạn phê duyệt",
    body: "Sau khi bạn xác nhận, Juli thực hiện thao tác (ví dụ: tạo mã giảm giá). Không có thay đổi nào trên shop nếu chưa có sự đồng ý của bạn.",
  },
  {
    title: "Cảnh báo kịp thời",
    body: "Nhận thông báo khi tồn kho sắp hết hoặc chỉ số giảm bất thường, qua Zalo hoặc thông báo đẩy trên điện thoại.",
  },
  {
    title: "Dùng trên điện thoại và máy tính",
    body: "Giao diện thiết kế cho điện thoại trước, để chủ shop và đội vận hành xem kết quả và phê duyệt ở bất cứ đâu.",
  },
] as const;

const AUDIENCES = [
  {
    title: "Nhà bán hàng",
    body: "Chủ shop nhỏ và vừa muốn tăng GMV mà không tăng thêm nhân sự.",
  },
  {
    title: "Đội vận hành sàn",
    body: "Giảm thời gian tổng hợp số liệu thủ công, tập trung vào việc tối ưu.",
  },
  {
    title: "Affiliate và Agency",
    body: "Có số liệu rõ ràng theo từng luồng truy cập để báo cáo và tối ưu cho shop.",
  },
] as const;

const FAQ = [
  {
    question: "Tôi có thể dùng thử Juli trước khi đăng ký không?",
    answer:
      "Có. Bản Demo chạy trên dữ liệu mẫu, không cần tạo tài khoản, để bạn xem toàn bộ quy trình phân tích, đề xuất và phê duyệt.",
  },
  {
    question: "Juli kết nối với TikTok Shop như thế nào?",
    answer:
      "Bạn uỷ quyền cho Juli qua trang cấp quyền chính thức của TikTok Shop. Juli không bao giờ hỏi mật khẩu shop, và bạn có thể ngắt kết nối bất cứ lúc nào.",
  },
  {
    question: "Juli có tự ý thay đổi shop của tôi không?",
    answer:
      "Không. Mọi thao tác trên shop đều cần bạn phê duyệt từng lần. Juli chỉ đọc dữ liệu cần thiết để phân tích và tạo đề xuất.",
  },
  {
    question: "Dữ liệu của tôi được bảo vệ ra sao?",
    answer:
      "Juli chỉ dùng dữ liệu shop để cung cấp dịch vụ cho chính bạn và không bán dữ liệu cho bên thứ ba.",
  },
] as const;

export default function ProductPage() {
  return (
    <>
      <JsonLd
        data={[
          breadcrumbSchema("/san-pham"),
          softwareApplicationSchema({ path: "/san-pham" }),
          faqPageSchema(FAQ),
        ]}
      />
      <LandingHeader />
      <main className="lp-main">
        <section aria-labelledby="product-heading" className="lp-page-hero">
          <p className="lp-page-hero__eyebrow">Sản phẩm</p>
          <h1 className="lp-page-hero__heading" id="product-heading">
            Juli AI — trợ lý tăng trưởng cho người bán TikTok Shop
          </h1>
          <p className="lp-page-hero__lead">
            Juli AI là phần mềm dạng dịch vụ (SaaS) do {COMPANY.name} phát triển. Juli kết
            nối với TikTok Shop của bạn, phân tích hiệu suất theo từng luồng truy cập và đề
            xuất hành động cụ thể để tăng GMV. Bạn phê duyệt, Juli thực hiện.
          </p>
          <div className="lp-page-hero__actions">
            <CtaLink data-testid="product-demo-cta" href={DEMO_URL} size="large">
              Trải nghiệm Demo
            </CtaLink>
            <CtaLink href="/contact" size="large" variant="secondary">
              Liên hệ tư vấn
            </CtaLink>
          </div>
        </section>

        <section aria-labelledby="problem-heading" className="lp-page-section">
          <h2 className="lp-page-section__heading" id="problem-heading">
            Juli giải quyết vấn đề gì
          </h2>
          <p className="lp-page-section__body">
            Người bán TikTok Shop phải theo dõi nhiều luồng truy cập cùng lúc — Thẻ sản
            phẩm, Video, Live — mỗi luồng có chỉ số riêng. Khi GMV giảm, rất khó biết
            nguyên nhân nằm ở đâu và nên sửa gì trước. Thuê agency thì chi phí cao, tự làm
            thì tốn thời gian. Juli tự động làm phần phân tích đó mỗi ngày và trả lời câu
            hỏi: luồng nào, chỉ số nào, sản phẩm nào cần cải thiện.
          </p>
        </section>

        <section aria-labelledby="how-heading" className="lp-page-section">
          <h2 className="lp-page-section__heading" id="how-heading">
            Cách Juli hoạt động
          </h2>
        </section>
        <StepsSection />

        <section aria-labelledby="capabilities-heading" className="lp-page-section">
          <h2 className="lp-page-section__heading" id="capabilities-heading">
            Tính năng chính
          </h2>
          <div className="lp-page-grid">
            {CAPABILITIES.map((item) => (
              <article className="lp-page-card" key={item.title}>
                <h3 className="lp-page-card__title">{item.title}</h3>
                <p className="lp-page-card__body">{item.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section aria-labelledby="data-heading" className="lp-page-section">
          <h2 className="lp-page-section__heading" id="data-heading">
            Kết nối TikTok Shop và dữ liệu
          </h2>
          <ul aria-label="Cách Juli dùng dữ liệu shop" className="lp-page-list">
            <li>Kết nối qua trang uỷ quyền chính thức của TikTok Shop; Juli không nhận mật khẩu shop.</li>
            <li>Juli đọc đơn hàng, sản phẩm, tồn kho và đơn hoàn để phân tích và tạo đề xuất.</li>
            <li>Mỗi thao tác ghi lên shop cần bạn phê duyệt riêng, có thời hạn, cho từng trường hợp.</li>
            <li>Bạn có thể ngắt kết nối bất cứ lúc nào; Juli ngừng đồng bộ dữ liệu mới ngay sau đó.</li>
          </ul>
          <p className="lp-page-section__body">
            Chi tiết xem tại{" "}
            <Link className="lp-legal__contact-link" href="/privacy">
              Chính sách bảo mật
            </Link>{" "}
            và{" "}
            <Link className="lp-legal__contact-link" href="/terms">
              Điều khoản dịch vụ
            </Link>
            .
          </p>
        </section>

        <section aria-labelledby="audience-heading" className="lp-page-section">
          <h2 className="lp-page-section__heading" id="audience-heading">
            Dành cho ai
          </h2>
          <div className="lp-page-grid lp-page-grid--three">
            {AUDIENCES.map((item) => (
              <article className="lp-page-card" key={item.title}>
                <h3 className="lp-page-card__title">{item.title}</h3>
                <p className="lp-page-card__body">{item.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section aria-labelledby="pricing-heading" className="lp-page-section">
          <h2 className="lp-page-section__heading" id="pricing-heading">
            Bảng giá
          </h2>
          <div>
            <article className="lp-page-card lp-page-card--highlight" data-testid="product-pricing">
            <h3 className="lp-page-card__title">Juli AI</h3>
            <p className="lp-page-card__price">500.000đ/tháng</p>
            <ul className="lp-page-list">
              <li>Miễn phí thử nghiệm 3 tháng đầu</li>
              <li>Đầy đủ tính năng phân tích, đề xuất và thực hiện</li>
              <li>Huỷ bất cứ lúc nào</li>
            </ul>
            </article>
          </div>
        </section>

        <section aria-labelledby="faq-heading" className="lp-page-section">
          <h2 className="lp-page-section__heading" id="faq-heading">
            Câu hỏi thường gặp
          </h2>
          <dl className="lp-page-faq">
            {FAQ.map((item) => (
              <div className="lp-page-faq__item" key={item.question}>
                <dt className="lp-page-faq__question">{item.question}</dt>
                <dd className="lp-page-faq__answer">{item.answer}</dd>
              </div>
            ))}
          </dl>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
