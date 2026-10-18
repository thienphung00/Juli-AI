import Link from "next/link";

import {
  CAP_DL_TANG_THEM,
  CAP_DL_TANG_THEM_MOBILE,
  CAP_DX_LUOT_CHAY_MOBILE as CAP_DX_LUOT_CHAY_CROP,
  CAP_DX_THE,
  CAP_PT_XEP_HANG,
  CAP_PT_XEP_HANG_MOBILE,
} from "../../components/product/screens";
import {
  Breadcrumb,
  Card,
  CheckList,
  Container,
  Eyebrow,
  FaqList,
  Heading,
  LinkButton,
  Section,
  SectionIntro,
  Shot,
  type ShotImage,
  StatusPill,
  type Step,
  StepList,
  TextLink,
} from "../../components/ui";
import { SiteFooter } from "../../components/ui/site-footer";
import { SiteHeader } from "../../components/ui/site-header";
import {
  breadcrumbSchema,
  buildMetadata,
  type FaqItem,
  faqPageSchema,
  JsonLd,
  serviceSchema,
} from "../../lib/seo";
import { COMPANY, DEMO_URL, PRODUCT_PAGES, SIGNUP_URL, TRIAL_CTA_LABEL } from "../../lib/site";
import styles from "./overview.module.css";

/**
 * `/san-pham` — product overview (D43.1, D43.4 ~1,500 words, AC-33.6; layout
 * P34-C, D44 / Product.dc.html). Content by P33-B from the former `/product`
 * (`/product` 301s here). Facts: D13 (what Juli executes), D24.4/5/17 (content
 * cards, promotions by the seller, at most 5 new cards a day), D12/D14 (day 7 /
 * day 14, revert), D29 / D31.7 (bands, change strength; no control-group
 * claim, D60.3), D42.6 (Shopee being integrated),
 * /privacy §4 (data read), /terms §5 (price).
 */
export const metadata = buildMetadata("/san-pham");

/**
 * The loop as a compact stepper (D46.3): a short title and one line each. The
 * long explanations live on the capability pages (lever per metric, TikTok's
 * re-review, rejection reasons, the five streams, the measurement method).
 * Facts: D13 (what Juli writes), D24.5/D24.17 (5 new cards a day, promotions
 * by the seller), D14 + P34-C (day 7 / day 14, Juli asks before a revert).
 */
const LOOP: readonly Step[] = [
  {
    title: "Phân tích",
    icon: "chart",
    body: "Mỗi ngày, Juli tính lại GMV = Lượt hiển thị × CTR × CTOR × AOV cho từng luồng.",
    note: "Năm luồng: Thẻ sản phẩm, Tab cửa hàng, Video, LIVE, Liên kết",
  },
  {
    title: "Đề xuất",
    icon: "bulb",
    body: "Tối đa 5 đề xuất mới mỗi ngày, xếp theo GMV có thể lấy lại.",
  },
  {
    title: "Duyệt",
    icon: "check-square",
    body: "Bạn duyệt, sửa nội dung hoặc từ chối kèm lý do.",
    you: true,
  },
  {
    title: "Thực thi",
    icon: "send",
    body: "Juli cập nhật tiêu đề, mô tả, thuộc tính qua API chính thức và lưu giá trị cũ.",
    note: "Giá, khuyến mãi và video: Juli chuẩn bị, bạn thực hiện",
  },
  {
    title: "Đo lường",
    icon: "target",
    body: "Đọc kết quả sơ bộ ở ngày 7, kết quả chốt ở ngày 14.",
    note: "Nếu ngày 7 có chỉ số ra ngoài ngưỡng bạn cho phép, Juli hỏi bạn có muốn hoàn tác không",
  },
];

/** One shape for the three card shots (cropped from the top on desktop). */
const CARD_CROP = 2.4;

const CAPABILITIES: ReadonlyArray<{
  page: { href: string; label: string };
  eyebrow: string;
  title: string;
  body: string;
  points: readonly string[];
  shot: ShotImage;
}> = [
  {
    page: PRODUCT_PAGES.analysis,
    eyebrow: "Phân tích",
    title: "Phân tích shop theo luồng truy cập",
    body: "Trang Phân tích cho bạn thấy GMV của shop đến từ đâu: Thẻ sản phẩm, Tab cửa hàng, Video, LIVE hay Liên kết, và trong mỗi luồng, bước nào của phễu đang yếu. Bạn không cần ghép nhiều báo cáo từ Seller Center; Juli dùng đúng tên chỉ số của TikTok Shop để bạn đối chiếu.",
    points: [
      "Lượt hiển thị, CTR, CTOR, AOV và GMV theo từng sản phẩm",
      "So với 30 ngày trước và với các sản phẩm cùng shop",
      "Ước tính GMV có thể lấy lại mỗi ngày ở từng bước",
    ],
    shot: {
      alt: "Bảng 5 sản phẩm kéo CTOR xuống, mỗi dòng có CTOR trước và nay, GMV mỗi ngày bị mất và nhãn tin cậy (dữ liệu mẫu)",
      crop: CARD_CROP,
      mobileVariants: CAP_PT_XEP_HANG_MOBILE,
      variants: CAP_PT_XEP_HANG,
    },
  },
  {
    page: PRODUCT_PAGES.actions,
    eyebrow: "Đề xuất và thực thi",
    title: "Đề xuất và thực thi sau khi bạn duyệt",
    body: "Trang Quyết định gom các việc nên làm thành thẻ, mỗi thẻ một sản phẩm và một hành động. Juli soạn sẵn nội dung mới; bạn duyệt và xác nhận là Juli cập nhật lên TikTok Shop. Việc cần bạn tự làm được ghi rõ là việc của bạn.",
    points: [
      "Juli tự cập nhật: tiêu đề, mô tả, thuộc tính",
      "Ảnh bìa: Juli phân tích và đề xuất, chỉ tải lên ảnh do bạn cung cấp",
      "Giá và khuyến mãi: Juli đề xuất trong giới hạn biên lợi nhuận bạn đặt",
      "Video và LIVE: Juli soạn kịch bản, bạn quay hoặc lên LIVE",
    ],
    shot: {
      alt: "Thẻ đề xuất cho Son môi số 12: chỉ số mục tiêu CTOR, GMV dự kiến, lý do và tiêu đề trước và sau (dữ liệu mẫu)",
      crop: CARD_CROP,
      variants: CAP_DX_THE,
    },
  },
  {
    page: PRODUCT_PAGES.measurement,
    eyebrow: "Đo lường",
    title: "Đo lường GMV tăng thêm",
    body: "Trang Đo lường theo dõi từng thay đổi đã thực thi. Juli không chỉ làm một phép trừ trước và sau, vì chỉ số dao động theo ngày, theo đợt sale và thường tự hồi lại sau một đợt giảm. Juli đặt mỗi mức thay đổi cạnh mức dao động bình thường của chỉ số, và ghi chú những thay đổi bên ngoài Juli để không ghi công nhầm cho đề xuất.",
    points: [
      "Kết quả sơ bộ ngày 7, kết quả chốt ngày 14",
      "Mỗi kết quả ghi rõ mức chắc chắn và thay đổi bên ngoài Juli trong thời gian đo",
      "Kết quả đo được dùng để điều chỉnh thứ tự đề xuất sau",
    ],
    shot: {
      alt: "Bảng kết quả ngày 7: chỉ số chính Đang lên, các chỉ số khác Giữ ổn định, GMV mỗi ngày ghi Sơ bộ (dữ liệu mẫu)",
      crop: CARD_CROP,
      mobileVariants: CAP_DL_TANG_THEM_MOBILE,
      variants: CAP_DL_TANG_THEM,
    },
  },
];

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
    answer: "Juli đang tích hợp qua Shopee Open Platform. Hiện bạn chỉ kết nối được TikTok Shop.",
  },
  {
    question: "Một thay đổi bị đo là kém hiệu quả thì sao?",
    answer:
      "Nếu ở ngày 7 một chỉ số ra ngoài ngưỡng bạn cho phép, Juli hỏi bạn có muốn hoàn tác về giá trị cũ đã lưu; Juli không tự hoàn tác. Kết quả này cũng làm Juli ưu tiên thấp hơn cho cùng loại hành động ở shop của bạn.",
  },
  {
    question: "Dùng thử miễn phí thế nào, khi nào bắt đầu tính phí?",
    answer:
      "Tài khoản mới được dùng thử miễn phí 3 tháng kể từ ngày đăng ký, không cần thẻ thanh toán. Sau thời gian dùng thử, phí dịch vụ là 500.000đ/tháng và bạn huỷ được bất cứ lúc nào.",
  },
  {
    question: "Làm sao để ngắt kết nối shop?",
    answer:
      "Bạn liên hệ Juli qua email lienhe@app-juli.com hoặc trang Liên hệ. Đội Juli ngắt kết nối shop, và Juli ngừng đồng bộ dữ liệu mới ngay sau đó.",
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
          serviceSchema({ path: "/san-pham" }),
          faqPageSchema(FAQ),
        ]}
      />
      <SiteHeader />
      <main className={styles.main}>
        <section aria-labelledby="product-heading" className={styles.hero}>
          <Container>
            <Breadcrumb current="Sản phẩm" items={[{ href: "/", label: "Trang chủ" }]} />
            <div className={styles.heroSplit}>
              <div className={styles.heroCopy}>
                <Eyebrow>Sản phẩm</Eyebrow>
                <Heading className={styles.heroHeading} id="product-heading" level={1} size="page">
                  Juli AI: phần mềm AI vận hành TMĐT, từ phân tích đến đo GMV tăng thêm
                </Heading>
                <p className="ui-lead">
                  Juli AI là phần mềm dạng dịch vụ (SaaS) do {COMPANY.name} phát triển cho nhà bán
                  TMĐT tại Việt Nam; hiện Juli kết nối TikTok Shop và đang tích hợp Shopee. Juli đọc dữ liệu shop, tìm chỗ GMV đang hụt, đề xuất việc
                  cụ thể, thực thi khi bạn duyệt và đo kết quả của từng thay đổi.
                </p>
                <div className={styles.actions}>
                  <LinkButton data-testid="product-trial-cta" href={SIGNUP_URL} size="md">
                    {TRIAL_CTA_LABEL}
                  </LinkButton>
                  <LinkButton data-testid="product-demo-cta" href={DEMO_URL} size="md" variant="secondary">
                    Xem demo
                  </LinkButton>
                </div>
              </div>
              {/* Not `priority`: on phones the H1 is the LCP; an eager hero shot cost 0.9 s (P34 LOG, D46.2). */}
              <Shot
                caption="Dữ liệu mẫu"
                chrome="Quyết định · Juli"
                className={styles.heroShot}
                images={{
                  alt: "Lượt chạy của một thẻ đề xuất: Phân tích, Đề xuất, Duyệt và Thực thi đã xong, Đo lường đang chờ; Juli đã ghi tiêu đề lên TikTok Shop và lưu giá trị cũ (dữ liệu mẫu)",
                  // The 640 px crop at every width: the full 1280 capture shrinks its text
                  // below readable in a half-width hero column.
                  variants: CAP_DX_LUOT_CHAY_CROP,
                }}
                sizes="(min-width: 960px) 600px, 100vw"
              />
            </div>
          </Container>
        </section>

        <Section labelledBy="what-heading" width="reading">
          <div className={styles.prose}>
            <Heading id="what-heading" level={2} size="feature">
              Juli AI là gì
            </Heading>
            <p className="ui-body">
              Nhà bán TMĐT có rất nhiều số liệu nhưng ít thời gian để đọc chúng. Trên TikTok Shop, mỗi sản
              phẩm có Lượt hiển thị, CTR, CTOR và AOV riêng, lại chia theo Thẻ sản phẩm, Video và LIVE. Khi GMV
              giảm, câu hỏi khó nhất là: giảm ở bước nào, ở sản phẩm nào, và nên sửa gì trước.
            </p>
            <p className="ui-body">
              Juli trả lời câu hỏi đó mỗi ngày. Juli là một trợ lý AI vận hành: Juli phân tích dữ liệu của
              chính shop bạn, chọn những việc có khả năng mang lại nhiều GMV nhất, soạn sẵn nội dung, và
              chỉ gửi thay đổi lên shop sau khi bạn duyệt. Sau đó Juli đo xem thay đổi đó có thật sự giúp
              GMV tăng hay không.
            </p>
            <p className="ui-body">
              Juli không thay thế người bán. Những quyết định về giá, khuyến mãi và nội dung video vẫn là
              của bạn. Juli làm phần việc tốn thời gian: đọc số liệu, tìm nguyên nhân, soạn nội dung và
              theo dõi kết quả.
            </p>
          </div>
        </Section>

        <Section labelledBy="loop-heading" tone="alt">
          <SectionIntro
            eyebrow="Cách Juli làm việc"
            lead="Mỗi thay đổi đi qua năm bước. Không có gì được ghi lên shop khi bạn chưa duyệt."
            title="Vòng làm việc của Juli"
            titleId="loop-heading"
          />
          <StepList className={styles.loop} steps={LOOP} variant="stepper" />
        </Section>

        <Section labelledBy="capabilities-heading">
          <SectionIntro
            eyebrow="Năng lực"
            lead="Mỗi năng lực có một trang riêng, giải thích cách Juli làm và ảnh màn hình thật với dữ liệu mẫu."
            title="Ba năng lực chính"
            titleId="capabilities-heading"
          />
          <div className={styles.capGrid}>
            {CAPABILITIES.map((item) => (
              <Card as="article" className={styles.capCard} key={item.page.href}>
                <Shot backdrop={false} images={item.shot} sizes="(min-width: 960px) 360px, 100vw" />
                <Eyebrow>{item.eyebrow}</Eyebrow>
                <Heading level={3} size="card">
                  {item.title}
                </Heading>
                <p>{item.body}</p>
                <CheckList items={item.points} />
                <TextLink className={styles.capLink} href={item.page.href}>
                  {`Xem ${item.page.label}`}
                </TextLink>
              </Card>
            ))}
          </div>
        </Section>

        <Section labelledBy="scope-heading" tone="alt">
          <SectionIntro title="Juli làm gì và không làm gì trên shop của bạn" titleId="scope-heading" />
          <div className={styles.grid3}>
            {SCOPE.map((group) => (
              <Card key={group.title}>
                <Heading level={3} size="card">
                  {group.title}
                </Heading>
                <ul className={styles.list}>
                  {group.items.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </Card>
            ))}
          </div>
        </Section>

        <Section labelledBy="integrations-heading">
          <SectionIntro
            eyebrow="Tích hợp"
            title="Kết nối và tích hợp"
            titleId="integrations-heading"
          />
          <div className={styles.grid3}>
            <Card>
              <div className={styles.integrationHead}>
                <Heading level={3} size="card">
                  TikTok Shop
                </Heading>
                <StatusPill status="live" />
              </div>
              <p>
                Kết nối chính thức qua TikTok Shop Open API. Juli đọc đơn hàng, sản phẩm, tồn kho, đơn
                hoàn và huỷ, số liệu hiệu suất theo luồng truy cập, hiệu suất video và LIVE, chương trình
                khuyến mãi của shop.
              </p>
              <TextLink href={PRODUCT_PAGES.tiktokShop.href}>Cách kết nối TikTok Shop</TextLink>
            </Card>
            <Card>
              <div className={styles.integrationHead}>
                <Heading level={3} size="card">
                  Shopee
                </Heading>
                <StatusPill status="integrating" />
              </div>
              <p>
                Juli đang tích hợp qua Shopee Open Platform. Hiện chưa kết nối được shop Shopee. Cách Juli
                sẽ dùng dữ liệu Shopee đã được nêu trước trong Chính sách bảo mật.
              </p>
              <TextLink href="/privacy#shopee-data">Dữ liệu Shopee trong Chính sách bảo mật</TextLink>
            </Card>
            <Card>
              <Heading level={3} size="card">
                Đăng nhập và thiết bị
              </Heading>
              <p>
                Đăng nhập bằng Google hoặc mã gửi qua email. Giao diện thiết kế cho điện thoại trước, nên
                chủ shop và đội vận hành duyệt đề xuất được ở bất cứ đâu, trên điện thoại hoặc máy tính.
              </p>
            </Card>
          </div>
        </Section>

        <Section labelledBy="data-heading" tone="alt">
          <div className={styles.split}>
            <SectionIntro eyebrow="An toàn dữ liệu" title="Dữ liệu và quyền kiểm soát" titleId="data-heading" />
            <div className={styles.prose}>
              <CheckList
                items={[
                  "Kết nối qua trang uỷ quyền chính thức của TikTok Shop; Juli không nhận mật khẩu shop.",
                  "Mỗi thay đổi ghi lên shop cần bạn duyệt riêng, và giá trị cũ được lưu để hoàn tác.",
                  <>
                    Muốn ngắt kết nối shop, bạn liên hệ Juli qua email {COMPANY.email} hoặc{" "}
                    <Link className={styles.a} href="/contact">
                      trang Liên hệ
                    </Link>
                    ; đội Juli ngắt kết nối và Juli ngừng đồng bộ dữ liệu mới ngay sau đó.
                  </>,
                  "Khi bạn yêu cầu xoá tài khoản, dữ liệu tài khoản và dữ liệu shop được xoá trong vòng 30 ngày.",
                ]}
              />
              <p className="ui-body">
                Chi tiết xem tại{" "}
                <Link className={styles.a} href="/privacy">
                  Chính sách bảo mật
                </Link>{" "}
                và{" "}
                <Link className={styles.a} href="/terms">
                  Điều khoản dịch vụ
                </Link>
                .
              </p>
            </div>
          </div>
        </Section>

        <Section labelledBy="audience-heading" width="reading">
          <div className={styles.prose}>
            <Heading id="audience-heading" level={2} size="feature">
              Dành cho ai
            </Heading>
            <p className="ui-body">
              Juli dành cho nhà bán TMĐT nhỏ và vừa muốn tăng GMV mà không thêm người phân tích;
              cho đội vận hành sàn muốn bớt thời gian tổng hợp số liệu; cho người làm affiliate cùng shop
              cần biết sản phẩm nào đang chuyển đổi tốt qua Video và LIVE; và cho agency cần một cách đo
              thống nhất khi báo cáo cho nhiều shop.
            </p>
          </div>
        </Section>

        <Section className={styles.pricingSection} id="bang-gia" labelledBy="pricing-heading" tone="alt">
          <div className={styles.split}>
            <SectionIntro
              lead="Dùng thử miễn phí 3 tháng, sau đó 500.000đ/tháng."
              title="Bảng giá"
              titleId="pricing-heading"
            />
            <Card className={styles.price} data-testid="product-pricing" tone="highlight">
              <Heading level={3} size="card">
                Juli AI
              </Heading>
              <p className={styles.priceValue}>500.000đ/tháng</p>
              <CheckList
                items={[
                  "Tài khoản mới được dùng thử miễn phí 3 tháng kể từ ngày đăng ký",
                  "Không cần thẻ thanh toán khi đăng ký",
                  "Đầy đủ phân tích, đề xuất, thực thi và đo lường",
                  "Huỷ bất cứ lúc nào",
                ]}
              />
              <LinkButton blockOnMobile data-testid="product-pricing-trial-cta" href={SIGNUP_URL}>
                {TRIAL_CTA_LABEL}
              </LinkButton>
            </Card>
          </div>
        </Section>

        <Section labelledBy="faq-heading">
          <div className={styles.faq}>
            <div className={styles.faqIntro}>
              <Heading id="faq-heading" level={2} size="feature">
                Câu hỏi thường gặp
              </Heading>
              <p className="ui-body">
                Chưa thấy câu trả lời? <TextLink href="/contact">Liên hệ Juli</TextLink>
              </p>
            </div>
            <FaqList items={FAQ} openFirst />
          </div>
        </Section>

        <Section labelledBy="start-heading" spacing="compact" tone="dark">
          <div className={styles.band}>
            <div className={styles.bandText}>
              <Heading id="start-heading" level={2} onDark size="article">
                Bắt đầu với dữ liệu thật của shop bạn
              </Heading>
              <p className="ui-lead ui-lead--on-dark">
                Dùng thử miễn phí 3 tháng, không cần thẻ thanh toán, hoặc xem bản Demo với dữ liệu mẫu
                trước.
              </p>
            </div>
            <div className={styles.actions}>
              <LinkButton data-testid="product-final-trial-cta" href={SIGNUP_URL} variant="on-dark">
                {TRIAL_CTA_LABEL}
              </LinkButton>
              <LinkButton data-testid="product-final-demo-cta" href={DEMO_URL} variant="on-dark-secondary">
                Xem demo
              </LinkButton>
              <LinkButton data-testid="product-contact-cta" href="/contact" variant="on-dark-secondary">
                Liên hệ tư vấn
              </LinkButton>
            </div>
          </div>
        </Section>
      </main>
      <SiteFooter />
    </>
  );
}
