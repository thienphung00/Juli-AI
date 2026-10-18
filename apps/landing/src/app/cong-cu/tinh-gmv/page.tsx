import Link from "next/link";
import type { ReactNode } from "react";

import { GmvCalculator } from "../../../components/gmv-calculator/gmv-calculator";
import { gmvPostHref } from "../../../components/gmv-calculator/post-href";
import {
  GMV_POST_ANCHORS,
  PRIVACY_LINE,
  TOOL_FAQ,
  TOOL_H1,
  TOOL_LEAD,
  TOOL_PATH,
  type GmvPostAnchor,
} from "../../../components/gmv-calculator/content";
import {
  Breadcrumb,
  Container,
  Eyebrow,
  FaqList,
  Heading,
  Icon,
  LinkButton,
  Section,
  TextLink,
} from "../../../components/ui";
import { SiteFooter } from "../../../components/ui/site-footer";
import { SiteHeader } from "../../../components/ui/site-header";
import {
  breadcrumbSchema,
  breadcrumbTrail,
  buildMetadata,
  faqPageSchema,
  JsonLd,
  webPageSchema,
} from "../../../lib/seo";
import { PRODUCT_PAGES, SIGNUP_URL, TRIAL_CTA_LABEL } from "../../../lib/site";
import styles from "./page.module.css";

export const metadata = buildMetadata(TOOL_PATH);

function PostLink({ href, anchor, children }: { href: string | null; anchor?: GmvPostAnchor; children: ReactNode }) {
  if (!href) return <>{children}</>;
  return <Link href={anchor ? `${href}#${GMV_POST_ANCHORS[anchor]}` : href}>{children}</Link>;
}

/** `/cong-cu/tinh-gmv`: free GMV calculator (D49.1, P43). Runs in the browser; sends nothing. */
export default function GmvCalculatorPage() {
  const postHref = gmvPostHref();
  const trail = breadcrumbTrail(TOOL_PATH);
  return (
    <>
      <JsonLd data={[breadcrumbSchema(TOOL_PATH), webPageSchema(TOOL_PATH), faqPageSchema(TOOL_FAQ)]} />
      <SiteHeader />
      <main className={styles.main}>
        <section aria-labelledby="tool-heading" className={styles.hero}>
          <Container>
            <Breadcrumb
              current={trail[trail.length - 1]?.name ?? TOOL_H1}
              items={trail.slice(0, -1).map((item) => ({ href: item.path, label: item.name }))}
            />
            <div className={styles.heroText}>
              <Eyebrow>Công cụ miễn phí</Eyebrow>
              <Heading id="tool-heading" level={1} size="page">
                {TOOL_H1}
              </Heading>
              <p className="ui-lead">{TOOL_LEAD}</p>
              <p className={styles.privacy} data-testid="tool-privacy">
                <Icon name="shield-check" size={20} strokeWidth={1.8} />
                <span>{PRIVACY_LINE}</span>
              </p>
            </div>
          </Container>
        </section>

        <Section labelledBy="tinh-gmv" spacing="compact">
          <Heading className={styles.calcHeading} id="tinh-gmv" level={2} size="article">
            Tính GMV của bạn
          </Heading>
          <p className={`ui-body ${styles.formula}`}>
            GMV = Lượt hiển thị sản phẩm × CTR × CTOR × AOV (SKU). Nhập bốn chỉ số, hoặc nhập số lượt nhấp và đơn
            hàng để công cụ tự tính tỷ lệ.
          </p>
          <GmvCalculator postHref={postHref} />
        </Section>

        <Section labelledBy="cach-doc" tone="alt" width="reading">
          <Heading id="cach-doc" level={2} size="article">
            Cách đọc kết quả
          </Heading>
          <h3 className={styles.h3}>Mỗi hàng của phễu là một câu hỏi</h3>
          <p className="ui-body">
            Lượt hiển thị nhân CTR ra Lượt nhấp, Lượt nhấp nhân CTOR ra Đơn hàng SKU, Đơn hàng SKU nhân AOV ra GMV.
            Mỗi hàng hỏi một việc khác nhau: có đủ người nhìn thấy sản phẩm không, người thấy có nhấp không, người
            nhấp có mua không, và mỗi lần mua được bao nhiêu tiền. Bài{" "}
            <PostLink anchor="formula" href={postHref}>
              GMV là gì? Cách tính và cách tăng GMV TikTok Shop
            </PostLink>{" "}
            giải thích công thức này từ định nghĩa của TikTok.
          </p>
          <h3 className={styles.h3}>Vì sao công cụ không nói chỉ số nào thấp</h3>
          <p className="ui-body">
            TikTok không công bố một mức CTR hay CTOR chuẩn chung, và các chỉ số này khác nhau nhiều giữa ngành hàng
            và giữa các luồng truy cập. Vì GMV là tích của bốn chỉ số, tăng 10 % ở bước nào cũng làm GMV tăng đúng
            10 %. Bước yếu nhất là bước bạn có thể cải thiện nhiều nhất, và bạn chỉ thấy được điều đó khi so một
            chỉ số với chính sản phẩm ở kỳ trước và với các sản phẩm khác trong shop, trên cùng luồng.
          </p>
          <h3 className={styles.h3}>Lấy số trên cùng một luồng và cùng một kỳ</h3>
          <p className="ui-body">
            Công thức chỉ đúng khi bốn chỉ số lấy trên cùng sản phẩm, cùng luồng truy cập và cùng khoảng thời gian.
            Tính tỷ lệ từ tổng của cả kỳ, không lấy trung bình tỷ lệ của từng ngày, và không gộp tỷ lệ của các luồng
            khác nhau: một luồng tăng mạnh có thể che một luồng đang giảm.
          </p>
          <h3 className={styles.h3}>Đủ dữ liệu chưa</h3>
          <p className="ui-body">
            Một sản phẩm có vài đơn mỗi tuần có thể dao động CTOR rất mạnh chỉ vì ngẫu nhiên. Trước khi kết luận,
            hãy chờ đến khi lượt hiển thị, lượt nhấp và đơn hàng đủ nhiều, hoặc gộp một khoảng thời gian dài hơn.
            Juli cũng chỉ đọc một chỉ số khi số liệu đủ để đọc.
          </p>
          <h3 className={styles.h3}>GMV chưa phải tiền về tài khoản</h3>
          <p className="ui-body">
            Theo định nghĩa của TikTok, GMV gồm cả đơn đã huỷ và hoàn tiền, và chưa trừ phí. Số tiền về Số dư Nhà
            bán hàng là số tiền quyết toán, sau khi trừ các khoản phí. Muốn xem GMV tách theo năm luồng truy cập và
            bước đang kéo GMV xuống, xem trang{" "}
            <Link href={PRODUCT_PAGES.analysis.href}>Phân tích shop</Link>.
          </p>
        </Section>

        <Section labelledBy="cau-hoi-gmv" width="reading">
          <Heading id="cau-hoi-gmv" level={2} size="article">
            Câu hỏi thường gặp
          </Heading>
          <FaqList className={styles.faq} items={TOOL_FAQ} />
        </Section>

        <Section labelledBy="tool-next" spacing="compact" tone="alt">
          <div className={styles.next}>
            <div>
              <Heading id="tool-next" level={2} size="article">
                Muốn biết GMV hụt ở luồng nào, sản phẩm nào?
              </Heading>
              <p className="ui-body">
                Juli đọc dữ liệu shop qua kết nối chính thức, dựng phễu này cho từng luồng truy cập và từng sản phẩm
                mỗi ngày, và chỉ ra bước có thay đổi lớn nhất so với kỳ trước.
              </p>
              <TextLink href={PRODUCT_PAGES.analysis.href}>Xem Phân tích shop</TextLink>
            </div>
            <LinkButton data-testid="tool-trial-cta" href={SIGNUP_URL} variant="secondary">
              {TRIAL_CTA_LABEL}
            </LinkButton>
          </div>
        </Section>
      </main>
      <SiteFooter />
    </>
  );
}
