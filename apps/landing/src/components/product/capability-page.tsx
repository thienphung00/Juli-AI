import Link from "next/link";
import { Children, isValidElement, type ReactNode } from "react";

import type { MediaSource } from "../../lib/media";
import {
  breadcrumbSchema,
  breadcrumbTrail,
  faqPageSchema,
  type FaqItem,
  JsonLd,
  softwareApplicationSchema,
} from "../../lib/seo";
import { DEMO_URL, SIGNUP_URL, TRIAL_CTA_LABEL } from "../../lib/site";
import {
  Breadcrumb,
  Container,
  Eyebrow,
  FaqList,
  Heading,
  LinkButton,
  Section,
  Shot,
  type ShotImage,
  TocNav,
} from "../ui";
import { SiteFooter } from "../ui/site-footer";
import { SiteHeader } from "../ui/site-header";
import styles from "./capability.module.css";

/**
 * Shared template of the capability pages and `/ket-noi/tiktok-shop`
 * (Product.dc.html, D44.4; content P33-C, D43.1 / D43.4): breadcrumb, split
 * hero, a large framed shot on a backdrop, a side TOC (a disclosure on
 * mobile), an article whose every content H2 carries one labelled sample
 * screenshot (with its mobile crop), an FAQ that is exactly the FAQPage
 * JSON-LD, next / see-also cards and one dark CTA band.
 */

/** `/blog` is P33-D's; linked from here so the capability pages feed it. */
export const BLOG_PATH = "/blog";

/** Caption shared by every product screenshot (D44.3). */
const SAMPLE_SHOP = "Dữ liệu mẫu · Cửa hàng Mẫu Hoa Mai";

/** Desktop `sizes` of a shot in the article column (≤ 876 px wide). */
const ARTICLE_SIZES = "(min-width: 1200px) 876px, (min-width: 960px) 70vw, 100vw";
const HERO_SIZES = "(min-width: 1200px) 1088px, 100vw";

export interface TocEntry {
  id: string;
  label: string;
}

export interface RelatedLink {
  href: string;
  title: string;
  body: string;
}

export interface CapabilityPageProps {
  /** Registry path (`src/lib/seo/routes/capabilities.ts`). */
  path: string;
  eyebrow: string;
  heading: string;
  /** One paragraph of text (rendered as `p.ui-lead`). */
  lead: ReactNode;
  /** The large framed hero shot (one image, or several joined in one frame). */
  heroShot: ShotImage | readonly ShotImage[];
  /** Browser-chrome title of the hero shot, e.g. "Phân tích · Juli". */
  heroChrome: string;
  /** Hero caption. Default "Dữ liệu mẫu · Cửa hàng Mẫu Hoa Mai". */
  heroCaption?: string;
  toc: readonly TocEntry[];
  faq: readonly FaqItem[];
  /** The first is shown as "Tiếp theo", the others as "Cũng xem". */
  related: readonly RelatedLink[];
  /** Heading of the dark CTA band. */
  ctaTitle: string;
  /** SoftwareApplication + Offer — the three `/san-pham/*` pages. */
  software?: boolean;
  /** Screenshot URL for the SoftwareApplication schema. */
  screenshot?: string;
  children: ReactNode;
}

export function CapabilityPage({
  path,
  eyebrow,
  heading,
  lead,
  heroShot,
  heroChrome,
  heroCaption = SAMPLE_SHOP,
  toc,
  faq,
  related,
  ctaTitle,
  software = false,
  screenshot,
  children,
}: CapabilityPageProps) {
  const trail = breadcrumbTrail(path);
  const current = trail[trail.length - 1];
  return (
    <>
      <JsonLd
        data={[
          breadcrumbSchema(path),
          ...(software ? [softwareApplicationSchema({ path, screenshot })] : []),
          faqPageSchema(faq),
        ]}
      />
      <SiteHeader />
      <main className={styles.main}>
        <section aria-labelledby="cap-heading" className={styles.hero}>
          <Container>
            <Breadcrumb
              current={current?.name ?? heading}
              items={trail.slice(0, -1).map((item) => ({ href: item.path, label: item.name }))}
            />
            <div className={styles.heroSplit}>
              <div className={styles.heroTitle}>
                <Eyebrow>{eyebrow}</Eyebrow>
                <Heading id="cap-heading" level={1} size="page">
                  {heading}
                </Heading>
              </div>
              <div className={styles.heroAside}>
                <p className="ui-lead">{lead}</p>
                <div className={styles.actions}>
                  <LinkButton data-testid="cap-trial-cta" href={SIGNUP_URL} size="md">
                    {TRIAL_CTA_LABEL}
                  </LinkButton>
                  <LinkButton data-testid="cap-demo-cta" href={DEMO_URL} size="md" variant="secondary">
                    Xem demo
                  </LinkButton>
                </div>
              </div>
            </div>
            <Shot
              caption={heroCaption}
              chrome={heroChrome}
              className={styles.heroShot}
              images={heroShot}
              layout="joined"
              padding="lg"
              sizes={HERO_SIZES}
            />
          </Container>
        </section>

        <Container className={styles.body}>
          <div className="ui-toc-layout">
            <TocNav activeId={toc[0]?.id} items={toc} />
            <article className={styles.article}>
              {children}

              <section aria-labelledby="cap-faq" className={styles.section} id="cau-hoi">
                <Heading id="cap-faq" level={2} size="article">
                  Câu hỏi thường gặp
                </Heading>
                <FaqList items={faq} openFirst />
              </section>

              <nav aria-label="Trang liên quan" className={styles.next}>
                {related.map((link, index) => (
                  <Link className={`ui-card ${styles.nextCard}`} href={link.href} key={link.href}>
                    <span className={styles.nextKicker}>{index === 0 ? "Tiếp theo" : "Cũng xem"}</span>
                    <span className={styles.nextTitle}>{link.title} →</span>
                    <span className={styles.nextBody}>{link.body}</span>
                  </Link>
                ))}
              </nav>
            </article>
          </div>
        </Container>

        <Section labelledBy="cap-cta" spacing="compact" tone="dark">
          <div className={styles.band}>
            <div className={styles.bandText}>
              <Heading id="cap-cta" level={2} onDark size="article">
                {ctaTitle}
              </Heading>
              <p className="ui-lead ui-lead--on-dark">
                Miễn phí 3 tháng đầu, sau đó 500.000đ/tháng. Muốn xem trước? Bản demo chạy trên một
                shop mẫu, không cần tài khoản.
              </p>
            </div>
            <div className={styles.actions}>
              <LinkButton data-testid="cap-final-trial-cta" href={SIGNUP_URL} variant="on-dark">
                {TRIAL_CTA_LABEL}
              </LinkButton>
              <LinkButton data-testid="cap-final-demo-cta" href={DEMO_URL} variant="on-dark-secondary">
                Xem demo
              </LinkButton>
            </div>
          </div>
        </Section>
      </main>
      <SiteFooter />
    </>
  );
}

export interface CapSectionProps {
  id: string;
  heading: string;
  /** One real screenshot per H2 (D43.4). */
  image: readonly MediaSource[];
  /** Mobile crop (`screens.ts` `*_MOBILE`), served at ≤ 640 px (D44.3). */
  mobileImage?: readonly MediaSource[];
  /** Describes what the screenshot shows; "(dữ liệu mẫu)" is appended. */
  alt: string;
  /** What the shot shows; prefixed with "Dữ liệu mẫu · ". */
  caption: string;
  /** Narrow crops (dialogs, single cards) render at card width on the backdrop. */
  narrow?: boolean;
  /**
   * Body. The screenshot goes after the opening paragraphs, i.e. before the
   * first `<H3>` (or straight under the H2 when the body starts with one).
   */
  children: ReactNode;
}

export function CapSection({
  id,
  heading,
  image,
  mobileImage,
  alt,
  caption,
  narrow = false,
  children,
}: CapSectionProps) {
  const nodes = Children.toArray(children);
  const firstH3 = nodes.findIndex((node) => isValidElement(node) && node.type === H3);
  const split = firstH3 === -1 ? nodes.length : firstH3;
  return (
    <section aria-labelledby={`${id}-h`} className={styles.section} id={id}>
      <Heading id={`${id}-h`} level={2} size="article">
        {heading}
      </Heading>
      {nodes.slice(0, split)}
      <Shot
        caption={`Dữ liệu mẫu · ${caption}`}
        className={narrow ? `${styles.shot} ${styles.shotNarrow}` : styles.shot}
        images={{ alt: `${alt} (dữ liệu mẫu)`, mobileVariants: mobileImage, variants: image }}
        sizes={narrow ? "(min-width: 640px) 560px, 100vw" : ARTICLE_SIZES}
      />
      {nodes.slice(split)}
    </section>
  );
}

export function H3({ children }: { children: ReactNode }) {
  return <h3 className={styles.h3}>{children}</h3>;
}

export function P({ children }: { children: ReactNode }) {
  return <p className={`ui-body ${styles.p}`}>{children}</p>;
}

export function Ul({ children }: { children: ReactNode }) {
  return <ul className={styles.list}>{children}</ul>;
}

export function Ol({ children }: { children: ReactNode }) {
  return <ol className={styles.list}>{children}</ol>;
}

export function Formula({ children }: { children: ReactNode }) {
  return <p className={styles.formula}>{children}</p>;
}

export function Note({ children }: { children: ReactNode }) {
  return <p className={styles.note}>{children}</p>;
}

/** Inline link in the article (pink text, underlined). */
export function A({ href, children }: { href: string; children: ReactNode }) {
  if (href.startsWith("mailto:")) {
    return (
      <a className={styles.a} href={href}>
        {children}
      </a>
    );
  }
  return (
    <Link className={styles.a} href={href}>
      {children}
    </Link>
  );
}
