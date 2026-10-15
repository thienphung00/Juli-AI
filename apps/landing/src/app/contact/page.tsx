import {
  Card,
  Container,
  Eyebrow,
  Heading,
  Icon,
  LinkButton,
  Section,
  SectionIntro,
} from "../../components/ui";
import { SiteFooter } from "../../components/ui/site-footer";
import { SiteHeader } from "../../components/ui/site-header";
import { breadcrumbSchema, buildMetadata, JsonLd } from "../../lib/seo";
import { COMPANY, DEMO_URL } from "../../lib/site";
import styles from "../about/info.module.css";

export const metadata = buildMetadata("/contact");

const TOPICS = [
  {
    title: "Tư vấn sử dụng",
    body: "Bạn muốn biết Juli phù hợp với shop của mình thế nào, hoặc cần hướng dẫn kết nối TikTok Shop.",
  },
  {
    title: "Hỗ trợ tài khoản",
    // D43 additions 3: there is no seller disconnect button — the Juli team disconnects on request.
    body: "Câu hỏi về tài khoản, thanh toán, ngắt kết nối shop hoặc yêu cầu xoá dữ liệu. Để ngắt kết nối shop, bạn gửi email và đội ngũ Juli sẽ ngắt kết nối giúp bạn.",
  },
  {
    title: "Hợp tác",
    body: "Agency, đối tác vận hành sàn hoặc nhà cung cấp muốn hợp tác cùng Juli AI.",
  },
] as const;

/** `/contact` (D43, redesigned to D44 by P34-E). */
export default function ContactPage() {
  return (
    <>
      <JsonLd data={breadcrumbSchema("/contact")} />
      <SiteHeader />
      <main>
        <section aria-labelledby="contact-heading" className={styles.hero}>
          <Container>
            <div className={styles.heroInner}>
              <Eyebrow>Liên hệ</Eyebrow>
              <Heading id="contact-heading" level={1} size="page">
                Liên hệ Juli AI
              </Heading>
              <p className={styles.lead}>
                Gửi email cho chúng tôi về mọi câu hỏi liên quan đến sản phẩm, tài khoản hoặc
                hợp tác. Vui lòng ghi rõ tên shop (nếu có) để chúng tôi hỗ trợ nhanh hơn.
              </p>
            </div>
          </Container>
        </section>

        <Section labelledBy="channels-heading" spacing="compact">
          <Heading id="channels-heading" level={2} size="feature">
            Thông tin liên hệ
          </Heading>
          <ul className={`${styles.grid} ${styles.gridTwo}`}>
            <Card as="li" data-testid="contact-email">
              <span className={styles.iconWrap}>
                <Icon name="mail" size={22} strokeWidth={1.8} />
              </span>
              <Heading level={3} size="card">
                Email
              </Heading>
              <a className={styles.cardLink} href={`mailto:${COMPANY.email}`}>
                {COMPANY.email}
              </a>
            </Card>
            <Card as="li" data-testid="contact-address">
              <span className={styles.iconWrap}>
                <Icon name="shield-check" size={22} strokeWidth={1.8} />
              </span>
              <Heading level={3} size="card">
                Địa chỉ
              </Heading>
              <p className={styles.cardText}>
                {COMPANY.name}
                <br />
                {COMPANY.address}
                <br />
                Mã số thuế: {COMPANY.taxId}
              </p>
            </Card>
          </ul>
        </Section>

        <Section labelledBy="topics-heading" tone="alt">
          <SectionIntro title="Chúng tôi có thể giúp gì" titleId="topics-heading" />
          <ul className={styles.grid}>
            {TOPICS.map((item) => (
              <Card as="li" key={item.title}>
                <Heading level={3} size="card">
                  {item.title}
                </Heading>
                <p>{item.body}</p>
              </Card>
            ))}
          </ul>
        </Section>

        <Section labelledBy="contact-cta-heading" spacing="compact" tone="dark">
          <div className={styles.ctaIntro}>
            <SectionIntro
              lead="Bản Demo chạy trên dữ liệu mẫu, không cần đăng ký."
              onDark
              size="feature"
              title="Muốn xem trước khi liên hệ?"
              titleId="contact-cta-heading"
            />
            <div className={styles.actions}>
              <LinkButton blockOnMobile data-testid="contact-demo-cta" href={DEMO_URL} variant="on-dark">
                Trải nghiệm Demo
              </LinkButton>
            </div>
          </div>
        </Section>
      </main>
      <SiteFooter />
    </>
  );
}
