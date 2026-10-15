import Link from "next/link";

import { CtaLink } from "../../components/cta-link";
import { LandingHeader } from "../../components/landing-header";
import { SiteFooter } from "../../components/site-footer";
import {
  breadcrumbSchema,
  buildMetadata,
  type FaqItem,
  faqPageSchema,
  JsonLd,
  softwareApplicationSchema,
} from "../../lib/seo";
import { COMPANY, DEMO_URL, LOGIN_URL, PRODUCT_PAGES } from "../../lib/site";

/**
 * `/san-pham` — product overview (D43.1, D43.4 ~1,500 words, AC-33.6). Rewritten
 * by P33-B from the former `/product` content (`/product` 301s here). Facts:
 * D13 (what Juli executes), D24.4/5/17 (content cards, promotions by the
 * seller, at most 5 new cards a day), D12/D14 (day 7 / day 14, revert),
 * ADR-077 + D34 (comparison with unchanged products, delayed control groups),
 * D42.6 (Shopee being integrated), /privacy §4 (data read), /terms §5 (price).
 * The capability pages it links are P33-C's.
 */
export const metadata = buildMetadata("/san-pham");

const LOOP = [
  {
    title: "1. Phân tích",
    body: "Mỗi ngày, khi TikTok Shop có số liệu mới, Juli tính lại GMV của từng sản phẩm theo công thức của TikTok: GMV = Lượt hiển thị × CTR × CTOR × AOV. Juli tách số liệu theo luồng truy cập (Thẻ sản phẩm, Video, LIVE) và so với 30 ngày trước cũng như với các sản phẩm khác trong shop. Bước nào thấp hơn mức tham chiếu là bước đang làm hụt GMV.",
  },
  {
    title: "2. Đề xuất",
    body: "Từ bước yếu nhất, Juli chọn việc cần làm. CTR thấp thường là chuyện ảnh bìa và tiêu đề. CTOR thấp thường là mô tả, thuộc tính, giá hoặc khuyến mãi. Mỗi thẻ đề xuất ghi rõ sản phẩm, chỉ số, lý do và mức GMV có thể lấy lại mỗi ngày. Juli đưa ra tối đa 5 đề xuất mới mỗi ngày, xếp theo GMV có thể tăng thêm.",
  },
  {
    title: "3. Duyệt",
    body: "Bạn mở thẻ, xem nội dung Juli soạn và so với nội dung hiện tại. Bạn có thể sửa câu chữ, đặt câu hỏi, hoặc từ chối kèm lý do. Lý do từ chối giúp Juli xếp hạng những đề xuất sau cho đúng với shop của bạn hơn.",
  },
  {
    title: "4. Thực thi",
    body: "Khi bạn duyệt một thẻ tiêu đề, mô tả hoặc thuộc tính, Juli gửi thay đổi lên TikTok Shop qua API chính thức và lưu lại giá trị cũ. TikTok Shop có thể duyệt lại trang sản phẩm như mọi lần chỉnh sửa khác. Với giá, khuyến mãi và video, Juli chuẩn bị sẵn và bạn thực hiện.",
  },
  {
    title: "5. Đo lường",
    body: "Juli ghi mức GMV dự kiến trước khi thay đổi, đọc kết quả sơ bộ ở ngày 7 và kết quả chốt ở ngày 14. Kết quả được so với các sản phẩm tương tự chưa thay đổi. Nếu ở ngày 7 kết quả kém rõ rệt so với dự kiến, Juli đề xuất hoàn tác ngay.",
  },
] as const;

const CAPABILITIES = [
  {
    page: PRODUCT_PAGES.analysis,
    title: "Phân tích shop theo luồng truy cập",
    body: "Trang Phân tích cho bạn thấy GMV của shop đến từ đâu: Thẻ sản phẩm, Video hay LIVE, và trong mỗi luồng, bước nào của phễu đang yếu. Bạn không cần ghép nhiều báo cáo từ Seller Center; Juli dùng đúng tên chỉ số của TikTok Shop để bạn đối chiếu.",
    points: [
      "Lượt hiển thị, CTR, CTOR, AOV và GMV theo từng sản phẩm",
      "So với 30 ngày trước và với các sản phẩm cùng shop",
      "Ước tính GMV có thể lấy lại mỗi ngày ở từng bước",
    ],
  },
  {
    page: PRODUCT_PAGES.actions,
    title: "Đề xuất và thực thi sau khi bạn duyệt",
    body: "Trang Quyết định gom các việc nên làm thành thẻ, mỗi thẻ một sản phẩm và một hành động. Juli soạn sẵn nội dung mới; bạn duyệt là Juli cập nhật lên TikTok Shop. Việc cần bạn tự làm được ghi rõ là việc của bạn.",
    points: [
      "Juli tự cập nhật: tiêu đề, mô tả, thuộc tính",
      "Ảnh bìa: Juli phân tích và đề xuất, chỉ tải lên ảnh do bạn cung cấp",
      "Giá và khuyến mãi: Juli đề xuất trong giới hạn biên lợi nhuận bạn đặt",
      "Video và LIVE: Juli soạn kịch bản, bạn quay hoặc lên LIVE",
    ],
  },
  {
    page: PRODUCT_PAGES.measurement,
    title: "Đo lường GMV tăng thêm",
    body: "Trang Đo lường theo dõi từng thay đổi đã thực thi. Juli không chỉ so trước và sau, vì GMV có thể tăng do mùa vụ, do thuật toán hay do đối thủ. Juli so với nhóm sản phẩm tương tự chưa thay đổi để ước tính phần GMV tăng thêm thật sự do thay đổi tạo ra.",
    points: [
      "Kết quả sơ bộ ngày 7, kết quả chốt ngày 14",
      "Tuỳ chọn nhóm thử nghiệm có đối chứng chậm khi shop đủ sản phẩm",
      "Kết quả đo được dùng để điều chỉnh thứ tự đề xuất sau",
    ],
  },
] as const;

const SCOPE = [
  {
    title: "Juli thực thi sau khi bạn duyệt",
    items: [
      "Cập nhật tiêu đề sản phẩm",
      "Cập nhật mô tả sản phẩm",
      "Bổ sung hoặc sửa thuộc tính sản phẩm",
      "Tải lên ảnh bìa mới, khi bạn cung cấp ảnh",
      "Hoàn tác về giá trị cũ khi bạn yêu cầu",
    ],
  },
  {
    title: "Juli đề xuất, bạn thực hiện",
    items: [
      "Điều chỉnh giá bán",
      "Tạo khuyến mãi, mã giảm giá, đăng ký chiến dịch trong Seller Center",
      "Quay video và lên LIVE theo kịch bản Juli soạn",
    ],
  },
  {
    title: "Juli không làm",
    items: [
      "Thay đổi bất cứ điều gì khi bạn chưa duyệt",
      "Hỏi hay lưu mật khẩu shop của bạn",
      "Đọc tin nhắn của bạn với người mua",
      "Bán dữ liệu shop cho bên thứ ba",
    ],
  },
] as const;

const FAQ: readonly FaqItem[] = [
  {
    question: "Tôi có thể xem Juli hoạt động trước khi đăng ký không?",
    answer:
      "Có. Bản Demo chạy trên một shop mẫu, có nhãn dữ liệu mẫu, không cần tạo tài khoản. Bạn đi được hết các bước Phân tích, Đề xuất, Duyệt, Thực thi và Đo lường.",
  },
  {
    question: "Juli kết nối với TikTok Shop như thế nào?",
    answer:
      "Bạn đăng nhập Juli bằng Google hoặc email, rồi cấp quyền cho Juli trên trang uỷ quyền chính thức của TikTok Shop. Juli không bao giờ hỏi mật khẩu shop. Sau khi kết nối, Juli bắt đầu đọc dữ liệu và đưa ra những đề xuất đầu tiên.",
  },
  {
    question: "Juli có tự ý thay đổi shop của tôi không?",
    answer:
      "Không. Mọi thay đổi trên shop đều cần bạn duyệt từng thẻ. Giá và khuyến mãi Juli chỉ đề xuất; bạn tự thực hiện trong Seller Center.",
  },
  {
    question: "Juli có hỗ trợ Shopee không?",
    answer:
      "Juli đang tích hợp qua Shopee Open Platform. Hiện bạn chỉ kết nối được TikTok Shop.",
  },
  {
    question: "Một thay đổi bị đo là kém hiệu quả thì sao?",
    answer:
      "Nếu kết quả ngày 7 kém rõ rệt so với dự kiến, Juli đề xuất hoàn tác về giá trị cũ đã lưu. Kết quả này cũng làm Juli ưu tiên thấp hơn cho cùng loại hành động ở shop của bạn.",
  },
  {
    question: "Dữ liệu của tôi được bảo vệ ra sao?",
    answer:
      "Dữ liệu được mã hoá khi truyền và khi lưu, mỗi tài khoản chỉ xem được dữ liệu của shop mình. Juli chỉ dùng dữ liệu để phục vụ chính shop của bạn và không bán cho bên thứ ba.",
  },
];

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
      <main className="lp-main lp-home">
        <section aria-labelledby="product-heading" className="lp-home-hero lp-home-hero--single">
          <div className="lp-home-inner">
            <nav aria-label="Đường dẫn" className="lp-breadcrumb">
              <Link href="/">Trang chủ</Link> <span aria-hidden="true">›</span>{" "}
              <span aria-current="page">Sản phẩm</span>
            </nav>
            <h1 className="lp-home-hero__heading" id="product-heading">
              Juli AI: phần mềm AI vận hành TikTok Shop, từ phân tích đến đo GMV tăng thêm
            </h1>
            <p className="lp-home-hero__lead">
              Juli AI là phần mềm dạng dịch vụ (SaaS) do {COMPANY.name} phát triển cho nhà bán
              TikTok Shop tại Việt Nam. Juli đọc dữ liệu shop, tìm chỗ GMV đang hụt, đề xuất việc
              cụ thể, thực thi khi bạn duyệt và đo kết quả của từng thay đổi.
            </p>
            <div className="lp-home-hero__actions">
              <CtaLink data-testid="product-trial-cta" href={LOGIN_URL} size="large">
                Dùng thử 3 tháng
              </CtaLink>
              <CtaLink
                data-testid="product-demo-cta"
                href={DEMO_URL}
                size="large"
                variant="secondary"
              >
                Xem demo
              </CtaLink>
            </div>
          </div>
        </section>

        <section aria-labelledby="what-heading" className="lp-home-section">
          <div className="lp-home-inner">
            <h2 className="lp-home-section__heading" id="what-heading">
              Juli AI là gì
            </h2>
            <p className="lp-home-section__body">
              Người bán TikTok Shop có rất nhiều số liệu nhưng ít thời gian để đọc chúng. Mỗi
              sản phẩm có Lượt hiển thị, CTR, CTOR và AOV riêng, lại chia theo Thẻ sản phẩm,
              Video và LIVE. Khi GMV giảm, câu hỏi khó nhất là: giảm ở bước nào, ở sản phẩm nào,
              và nên sửa gì trước.
            </p>
            <p className="lp-home-section__body">
              Juli trả lời câu hỏi đó mỗi ngày. Juli là một trợ lý AI vận hành: Juli phân tích dữ
              liệu của chính shop bạn, chọn những việc có khả năng mang lại nhiều GMV nhất, soạn
              sẵn nội dung, và chỉ gửi thay đổi lên shop sau khi bạn duyệt. Sau đó Juli đo xem
              thay đổi đó có thật sự giúp GMV tăng hay không.
            </p>
            <p className="lp-home-section__body">
              Juli không thay thế người bán. Những quyết định về giá, khuyến mãi và nội dung
              video vẫn là của bạn. Juli làm phần việc tốn thời gian: đọc số liệu, tìm nguyên
              nhân, soạn nội dung và theo dõi kết quả.
            </p>
          </div>
        </section>

        <section
          aria-labelledby="loop-heading"
          className="lp-home-section lp-home-section--tinted"
        >
          <div className="lp-home-inner">
            <h2 className="lp-home-section__heading" id="loop-heading">
              Vòng làm việc: Phân tích → Đề xuất → Duyệt → Thực thi → Đo lường
            </h2>
            <ol className="lp-home-steps lp-home-steps--wide">
              {LOOP.map((step) => (
                <li className="lp-home-step" key={step.title}>
                  <h3 className="lp-home-step__title">{step.title}</h3>
                  <p className="lp-home-step__body">{step.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section aria-labelledby="capabilities-heading" className="lp-home-section">
          <div className="lp-home-inner">
            <h2 className="lp-home-section__heading" id="capabilities-heading">
              Ba năng lực chính
            </h2>
            <div className="lp-home-grid lp-home-grid--three">
              {CAPABILITIES.map((item) => (
                <article className="lp-home-card lp-home-card--capability" key={item.page.href}>
                  <h3 className="lp-home-card__title">{item.title}</h3>
                  <p className="lp-home-card__body">{item.body}</p>
                  <ul className="lp-home-list">
                    {item.points.map((point) => (
                      <li key={point}>{point}</li>
                    ))}
                  </ul>
                  <Link className="lp-home-link lp-home-card__more" href={item.page.href}>
                    Xem chi tiết: {item.page.label} ›
                  </Link>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section
          aria-labelledby="scope-heading"
          className="lp-home-section lp-home-section--tinted"
        >
          <div className="lp-home-inner">
            <h2 className="lp-home-section__heading" id="scope-heading">
              Juli làm gì và không làm gì trên shop của bạn
            </h2>
            <div className="lp-home-grid lp-home-grid--three">
              {SCOPE.map((group) => (
                <article className="lp-home-card" key={group.title}>
                  <h3 className="lp-home-card__title">{group.title}</h3>
                  <ul className="lp-home-list">
                    {group.items.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section aria-labelledby="integrations-heading" className="lp-home-section">
          <div className="lp-home-inner">
            <h2 className="lp-home-section__heading" id="integrations-heading">
              Kết nối và tích hợp
            </h2>
            <div className="lp-home-grid lp-home-grid--three">
              <article className="lp-home-card">
                <h3 className="lp-home-card__title">TikTok Shop: đang hoạt động</h3>
                <p className="lp-home-card__body">
                  Kết nối chính thức qua TikTok Shop Open API. Juli đọc đơn hàng, sản phẩm, tồn
                  kho, đơn hoàn và huỷ, số liệu hiệu suất theo luồng truy cập, hiệu suất video và
                  LIVE, chương trình khuyến mãi của shop.
                </p>
                <Link className="lp-home-link" href={PRODUCT_PAGES.tiktokShop.href}>
                  Cách kết nối TikTok Shop ›
                </Link>
              </article>
              <article className="lp-home-card">
                <h3 className="lp-home-card__title">Shopee: đang tích hợp</h3>
                <p className="lp-home-card__body">
                  Juli đang tích hợp qua Shopee Open Platform. Hiện chưa kết nối được shop Shopee.
                  Cách Juli sẽ dùng dữ liệu Shopee đã được nêu trước trong Chính sách bảo mật.
                </p>
                <Link className="lp-home-link" href="/privacy#shopee-data">
                  Dữ liệu Shopee trong Chính sách bảo mật ›
                </Link>
              </article>
              <article className="lp-home-card">
                <h3 className="lp-home-card__title">Đăng nhập và thiết bị</h3>
                <p className="lp-home-card__body">
                  Đăng nhập bằng Google hoặc mã gửi qua email. Giao diện thiết kế cho điện thoại
                  trước, nên chủ shop và đội vận hành duyệt đề xuất được ở bất cứ đâu, trên điện
                  thoại hoặc máy tính.
                </p>
              </article>
            </div>
          </div>
        </section>

        <section
          aria-labelledby="data-heading"
          className="lp-home-section lp-home-section--tinted"
        >
          <div className="lp-home-inner">
            <h2 className="lp-home-section__heading" id="data-heading">
              Dữ liệu và quyền kiểm soát
            </h2>
            <ul className="lp-home-list lp-home-list--loose">
              <li>Kết nối qua trang uỷ quyền chính thức của TikTok Shop; Juli không nhận mật khẩu shop.</li>
              <li>Mỗi thay đổi ghi lên shop cần bạn duyệt riêng, và giá trị cũ được lưu để hoàn tác.</li>
              <li>Bạn có thể thu hồi quyền của Juli trong Seller Center bất cứ lúc nào; Juli ngừng đồng bộ dữ liệu mới ngay sau đó.</li>
              <li>Khi bạn yêu cầu xoá tài khoản, dữ liệu tài khoản và dữ liệu shop được xoá trong vòng 30 ngày.</li>
            </ul>
            <p className="lp-home-section__body">
              Chi tiết xem tại{" "}
              <Link className="lp-home-link" href="/privacy">
                Chính sách bảo mật
              </Link>{" "}
              và{" "}
              <Link className="lp-home-link" href="/terms">
                Điều khoản dịch vụ
              </Link>
              .
            </p>
          </div>
        </section>

        <section aria-labelledby="audience-heading" className="lp-home-section">
          <div className="lp-home-inner">
            <h2 className="lp-home-section__heading" id="audience-heading">
              Dành cho ai
            </h2>
            <p className="lp-home-section__body">
              Juli dành cho nhà bán TikTok Shop nhỏ và vừa muốn tăng GMV mà không thêm người
              phân tích; cho đội vận hành sàn muốn bớt thời gian tổng hợp số liệu; cho người làm
              affiliate cùng shop cần biết sản phẩm nào đang chuyển đổi tốt qua Video và LIVE; và
              cho agency cần một cách đo thống nhất khi báo cáo cho nhiều shop.
            </p>
          </div>
        </section>

        <section
          aria-labelledby="pricing-heading"
          className="lp-home-section lp-home-section--tinted"
          id="bang-gia"
        >
          <div className="lp-home-inner">
            <h2 className="lp-home-section__heading" id="pricing-heading">
              Bảng giá
            </h2>
            <article className="lp-home-card lp-home-card--price" data-testid="product-pricing">
              <h3 className="lp-home-card__title">Juli AI</h3>
              <p className="lp-home-price">500.000đ/tháng</p>
              <ul className="lp-home-list">
                <li>Miễn phí dùng thử 3 tháng đầu</li>
                <li>Đầy đủ phân tích, đề xuất, thực thi và đo lường</li>
                <li>Huỷ bất cứ lúc nào</li>
              </ul>
            </article>
          </div>
        </section>

        <section aria-labelledby="faq-heading" className="lp-home-section">
          <div className="lp-home-inner">
            <h2 className="lp-home-section__heading" id="faq-heading">
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
          </div>
        </section>

        <section aria-labelledby="start-heading" className="lp-home-final">
          <h2 className="lp-home-final__heading" id="start-heading">
            Bắt đầu với dữ liệu thật của shop bạn
          </h2>
          <p className="lp-home-final__body">
            Dùng thử miễn phí 3 tháng, hoặc xem bản Demo với dữ liệu mẫu trước.
          </p>
          <div className="lp-home-hero__actions lp-home-final__actions">
            <CtaLink href={LOGIN_URL} size="large">
              Dùng thử 3 tháng
            </CtaLink>
            <CtaLink href={DEMO_URL} size="large" variant="secondary">
              Xem demo
            </CtaLink>
            <CtaLink href="/contact" size="large" variant="ghost">
              Liên hệ tư vấn
            </CtaLink>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
