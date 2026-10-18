import Link from "next/link";

import { COMPANY, DEMO_URL, FREE_TOOLS, PRODUCT_PAGES, SECTION_IDS, SIGNUP_URL, TRIAL_CTA_LABEL } from "../../lib/site";
import {
  CAP_DL_TANG_THEM,
  CAP_DL_TANG_THEM_MOBILE,
  CAP_DX_THE,
  CAP_DX_THE_MOBILE,
  CAP_PT_LUONG,
  CAP_PT_LUONG_MOBILE,
  CAP_PT_PHEU,
  CAP_PT_XEP_HANG,
  CAP_PT_XEP_HANG_MOBILE,
} from "../product/screens";
import {
  BirdGlyph,
  Card,
  CheckList,
  Container,
  Eyebrow,
  FaqList,
  FeatureRow,
  Heading,
  Icon,
  LinkButton,
  Section,
  SectionIntro,
  Shot,
  ShotFrame,
  StatusPill,
  StepList,
  TextLink,
} from "../ui";
import { AUDIENCES, CAPABILITY_ROWS, HOME_FAQ, PRICING_POINTS, SAFETY } from "./home-content";
import { HeroVideo } from "./hero-video";
import styles from "./home.module.css";

/**
 * Homepage sections, built to the approved mockups (D44, P34-B):
 * fasttrack/design/p34/Main.dc.html (desktop) and HomeMobile.dc.html (390 px).
 * Heading outline: one H1 in the hero, one H2 per section, H3 inside — never
 * deeper. Every CTA carries a `data-testid` (TikTok listener `content_name`).
 */

export function HomeHero() {
  return (
    <section aria-labelledby="hero-heading" className={styles.hero}>
      <Container className={styles.heroInner}>
        <div className={styles.heroCopy}>
          <Eyebrow variant="badge">Kết nối chính thức qua TikTok Shop Open API</Eyebrow>
          <Heading id="hero-heading" level={1}>
            Trợ lý AI vận hành TMĐT: tìm chỗ cải thiện GMV, đề xuất chiến lược, đo kết quả.
          </Heading>
          <p className="ui-lead">
            Juli đọc dữ liệu shop của bạn, chỉ ra luồng truy cập và sản phẩm đang kéo GMV xuống,
            rồi chỉ thực hiện thay đổi khi bạn đã duyệt.
          </p>
          <div className={styles.heroActions}>
            <LinkButton blockOnMobile data-testid="hero-trial-cta" href={SIGNUP_URL}>
              {TRIAL_CTA_LABEL}
            </LinkButton>
            <HeroVideo />
          </div>
          <p className={styles.heroNote}>
            Không cần thẻ thanh toán · sau đó từ 500.000đ/tháng ·{" "}
            <a className={styles.heroNoteLink} data-testid="hero-demo-cta" href={DEMO_URL}>
              Xem demo
            </a>{" "}
            với dữ liệu mẫu
          </p>
          <p className={styles.heroConsent} data-testid="hero-consent-note">
            Khi đăng ký, bạn đồng ý với <Link href="/terms">Điều khoản dịch vụ</Link> và{" "}
            <Link href="/privacy">Chính sách bảo mật</Link> của Juli.
          </p>
        </div>
        <div className={styles.heroMedia}>
          <svg aria-hidden="true" className={styles.heroPath} fill="none" viewBox="0 0 560 120">
            <path
              d="M8 104 C 140 20, 300 120, 470 34"
              stroke="var(--lp-pink)"
              strokeDasharray="2 9"
              strokeLinecap="round"
              strokeWidth="2"
            />
          </svg>
          <BirdGlyph className={styles.heroBird} height={39} />
          <figure className={styles.heroMain}>
            <ShotFrame
              chrome="Quyết định · Juli"
              elevation="hero"
              images={{
                variants: CAP_DX_THE,
                // Phones: the card header only (D46, AC-35.5). A smaller shot keeps the H1 the LCP
                // element; the full card made the lazy shot the LCP (3.2 s vs 2.6 s).
                mobileVariants: CAP_DX_THE_MOBILE,
                alt: "Thẻ đề xuất của Juli cho Son môi số 12: CTOR 5,4 % lên 5,9 % và GMV dự kiến (dữ liệu mẫu)",
                crop: 7 / 5,
              }}
              sizes="(min-width: 1200px) 600px, (min-width: 960px) 50vw, 100vw"
            />
            <figcaption className={styles.heroMainCaption}>Dữ liệu mẫu</figcaption>
          </figure>
          <ShotFrame
            as="figure"
            caption="Dữ liệu mẫu"
            className={styles.heroFloat}
            elevation="float"
            images={{
              variants: CAP_PT_PHEU,
              alt: "Phễu của luồng Thẻ sản phẩm: Lượt hiển thị, CTR, CTOR, AOV (dữ liệu mẫu)",
            }}
            sizes="(min-width: 1200px) 380px, 32vw"
          />
        </div>
      </Container>
    </section>
  );
}

/** D42.6: TikTok Shop is live; Shopee is "đang tích hợp", never live. */
export function MarketplaceStrip() {
  return (
    <Section labelledBy="marketplace-heading" spacing="none" tone="alt" className={styles.strip}>
      <div className={styles.stripInner}>
        {/* A label, not a section heading (D46.6): it names the strip region and the list. */}
        <p className={styles.stripHeading} id="marketplace-heading">
          Sàn Juli kết nối
        </p>
        <ul aria-labelledby="marketplace-heading" className={styles.markets}>
          <li className={styles.market} data-testid="market-tiktok">
            <span className={styles.marketName}>TikTok Shop</span>
            <StatusPill status="live" />
            <span className={styles.marketNote}>TikTok Shop Open API</span>
          </li>
          <li className={styles.market} data-testid="market-shopee">
            <span className={styles.marketName}>Shopee</span>
            <StatusPill status="integrating" />
            <span className={styles.marketNote}>qua Shopee Open Platform</span>
          </li>
        </ul>
      </div>
    </Section>
  );
}

export function LoopSection() {
  return (
    <Section id={SECTION_IDS.howItWorks} labelledBy="loop-heading">
      <SectionIntro
        eyebrow="Cách Juli làm việc"
        title="Năm bước, và bạn luôn là người quyết định."
        titleId="loop-heading"
      />
      <StepList className={styles.steps} />
    </Section>
  );
}

export function CapabilityRows() {
  const { analysis, actions, measurement } = CAPABILITY_ROWS;
  return (
    <Container className={styles.capabilities} id={SECTION_IDS.capabilities}>
      <FeatureRow
        eyebrow={analysis.eyebrow}
        media={
          <Shot
            caption="Dữ liệu mẫu · Cửa hàng Mẫu Hoa Mai"
            images={[
              {
                variants: CAP_PT_LUONG,
                mobileVariants: CAP_PT_LUONG_MOBILE,
                alt: "Phân tích: GMV chia theo 5 luồng truy cập (dữ liệu mẫu)",
              },
              {
                variants: CAP_PT_XEP_HANG,
                mobileVariants: CAP_PT_XEP_HANG_MOBILE,
                alt: "Xếp hạng sản phẩm kéo CTOR xuống (dữ liệu mẫu)",
              },
            ]}
          />
        }
        title={analysis.title}
        titleId="cap-analysis"
      >
        <p className="ui-body">{analysis.body}</p>
        <CheckList items={analysis.points} />
        <TextLink data-testid="capability-link-analysis" href={PRODUCT_PAGES.analysis.href}>
          Xem {PRODUCT_PAGES.analysis.label}
        </TextLink>
      </FeatureRow>
      <FeatureRow
        eyebrow={actions.eyebrow}
        media={
          <Shot
            images={{
              variants: CAP_DX_THE,
              alt: "Thẻ đề xuất với thay đổi trước–sau (dữ liệu mẫu)",
              crop: 3 / 2,
            }}
          />
        }
        reverse
        title={actions.title}
        titleId="cap-actions"
      >
        <p className="ui-body">{actions.body}</p>
        <CheckList items={actions.points} />
        <TextLink data-testid="capability-link-actions" href={PRODUCT_PAGES.actions.href}>
          Xem {PRODUCT_PAGES.actions.label}
        </TextLink>
      </FeatureRow>
      <FeatureRow
        eyebrow={measurement.eyebrow}
        media={
          <Shot
            images={{
              variants: CAP_DL_TANG_THEM,
              mobileVariants: CAP_DL_TANG_THEM_MOBILE,
              alt: "Kết quả đo của một thay đổi: chỉ số trước, mục tiêu và thực tế (dữ liệu mẫu)",
            }}
          />
        }
        title={measurement.title}
        titleId="cap-measurement"
      >
        <p className="ui-body">{measurement.body}</p>
        <TextLink data-testid="capability-link-measurement" href={PRODUCT_PAGES.measurement.href}>
          Xem {PRODUCT_PAGES.measurement.label}
        </TextLink>
      </FeatureRow>
    </Container>
  );
}

export function SafetySection() {
  return (
    <Section labelledBy="safety-heading" tone="alt">
      <SectionIntro
        className={styles.introWithLink}
        eyebrow="Dữ liệu và quyền quyết định"
        lead={
          <>
            Dữ liệu shop chỉ dùng để phục vụ chính shop của bạn và không được bán. Juli đọc gì,
            lưu bao lâu và chia sẻ với ai được nêu tại{" "}
            <Link href="/privacy">Chính sách bảo mật</Link>.
          </>
        }
        title="Shop là của bạn. Juli chỉ đọc những gì cần và chỉ làm khi bạn đồng ý."
        titleId="safety-heading"
      />
      <ul className={styles.safetyGrid}>
        {SAFETY.map((item) => (
          <Card as="li" key={item.title}>
            <Icon name={item.icon} size={28} strokeWidth={1.8} />
            <Heading level={3}>{item.title}</Heading>
            <p>{item.body}</p>
          </Card>
        ))}
      </ul>
    </Section>
  );
}

export function AudienceSection() {
  return (
    <Section className={styles.audience} labelledBy="audience-heading">
      <div className={styles.split}>
        <div>
          <Eyebrow>Dành cho ai</Eyebrow>
          <Heading className={styles.splitTitle} id="audience-heading" level={2} size="feature">
            Cho người bán và những đội vận hành shop.
          </Heading>
        </div>
        <ul className={styles.audienceGrid}>
          {AUDIENCES.map((item) => (
            <li key={item.title}>
              <Heading level={3}>{item.title}</Heading>
              <p>{item.body}</p>
            </li>
          ))}
        </ul>
      </div>
    </Section>
  );
}

/** D43.3: transparency instead of proof — method, labelled sample data, company. */
export function TransparencySection() {
  return (
    <Section className={styles.transparency} labelledBy="transparency-heading">
      <div className={styles.transparencyCard}>
        <div className={styles.transparencyText}>
          <Heading id="transparency-heading" level={2} size="article">
            Minh bạch thay cho lời quảng cáo
          </Heading>
          <p>
            Juli là sản phẩm mới. Thay vì con số hứa hẹn, chúng tôi công khai cách đo: mỗi thay đổi
            có chỉ số mục tiêu, được so với sản phẩm tương tự không đổi, đọc sơ bộ ở ngày 7 và chốt
            ở ngày 14. Mọi hình trên trang này dùng dữ liệu mẫu và được ghi rõ; chưa có con số nào
            là kết quả của một khách hàng.
          </p>
          <TextLink href={PRODUCT_PAGES.measurement.href}>Cách Juli đo GMV tăng thêm</TextLink>
        </div>
        <dl className={styles.company} data-testid="home-company">
          <div>
            <dt>Doanh nghiệp</dt>
            <dd>{COMPANY.name}</dd>
          </div>
          <div>
            <dt>Mã số thuế</dt>
            <dd>{COMPANY.taxId}</dd>
          </div>
          <div>
            <dt>Địa chỉ</dt>
            <dd>{COMPANY.address}</dd>
          </div>
          <div>
            <dt>Liên hệ</dt>
            <dd>
              <a href={`mailto:${COMPANY.email}`}>{COMPANY.email}</a>
            </dd>
          </div>
        </dl>
      </div>
    </Section>
  );
}

/** The page's one dark band: free trial + price (/terms §5) + both CTAs. */
export function PricingBand() {
  return (
    <Section labelledBy="pricing-heading" tone="dark">
      <div className={styles.pricing}>
        <div className={styles.pricingCopy}>
          <SectionIntro
            lead="Đầy đủ phân tích, đề xuất, thực thi và đo lường. Không cần thẻ thanh toán. Sau đó từ 500.000đ/tháng, huỷ bất cứ lúc nào."
            onDark
            title="Dùng thử miễn phí 3 tháng."
            titleId="pricing-heading"
          />
          <div className={styles.pricingActions}>
            <LinkButton blockOnMobile data-testid="pricing-trial-cta" href={SIGNUP_URL} variant="on-dark">
              Đăng ký dùng thử
            </LinkButton>
            <LinkButton
              blockOnMobile
              data-testid="trial-demo-cta"
              href={DEMO_URL}
              variant="on-dark-secondary"
            >
              Xem demo với dữ liệu mẫu
            </LinkButton>
          </div>
        </div>
        <Card className={styles.priceCard} data-testid="home-pricing" tone="dark">
          <p className={styles.priceLabel}>Juli AI</p>
          <p className={styles.price}>
            500.000đ<span className={styles.priceUnit}> /tháng</span>
          </p>
          <p className={styles.priceNote}>Sau 3 tháng dùng thử miễn phí</p>
          <ul className={styles.priceList}>
            {PRICING_POINTS.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        </Card>
      </div>
    </Section>
  );
}

/** FAQ; its FAQPage JSON-LD is emitted once, by the page (`faqPageSchema(HOME_FAQ)`). */
export function FaqSection() {
  return (
    <Section id={SECTION_IDS.faq} labelledBy="faq-heading">
      <div className={styles.split}>
        <div>
          <Heading id="faq-heading" level={2} size="feature">
            Câu hỏi thường gặp
          </Heading>
          <p className={styles.faqContact}>
            Chưa thấy câu trả lời? <Link href="/contact">Liên hệ Juli</Link>
          </p>
          <p className={styles.faqContact}>
            Muốn tự tính GMV theo bốn chỉ số?{" "}
            <Link href={FREE_TOOLS.gmvCalculator.href}>Dùng công cụ tính GMV miễn phí</Link>
          </p>
        </div>
        <FaqList items={HOME_FAQ} />
      </div>
    </Section>
  );
}
