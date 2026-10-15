import Link from "next/link";
import type { ReactNode } from "react";

import type { MediaSource } from "../../lib/media";
import {
  breadcrumbSchema,
  breadcrumbTrail,
  faqPageSchema,
  type FaqItem,
  JsonLd,
  softwareApplicationSchema,
} from "../../lib/seo";
import { DEMO_URL, LOGIN_URL } from "../../lib/site";
import { CtaLink } from "../cta-link";
import { SiteHeader } from "../ui/site-header";
import { Picture } from "../picture";
import { SiteFooter } from "../ui/site-footer";
import styles from "./capability.module.css";

/**
 * Shared frame of the capability pages (P33-C, D43.1 / D43.4): breadcrumb,
 * one H1, H2 sections each with one labelled screenshot of the app's sample
 * shop, an FAQ whose questions are exactly the FAQPage JSON-LD, related links
 * and the "Dùng thử 3 tháng" / "Xem demo" CTAs.
 */

/** `/blog` is P33-D's; linked from here so the capability pages feed it. */
export const BLOG_PATH = "/blog";

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
  lead: ReactNode;
  toc: readonly TocEntry[];
  faq: readonly FaqItem[];
  related: readonly RelatedLink[];
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
  toc,
  faq,
  related,
  software = false,
  screenshot,
  children,
}: CapabilityPageProps) {
  const trail = breadcrumbTrail(path);
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
      <main className="lp-main">
        <section aria-labelledby="cap-heading" className="lp-page-hero">
          <nav aria-label="Đường dẫn">
            <p className={styles.breadcrumb}>
              {trail.map((item, index) => (
                <span key={item.path}>
                  {index > 0 ? " › " : null}
                  {index < trail.length - 1 ? <Link href={item.path}>{item.name}</Link> : item.name}
                </span>
              ))}
            </p>
          </nav>
          <p className="lp-page-hero__eyebrow">{eyebrow}</p>
          <h1 className="lp-page-hero__heading" id="cap-heading">
            {heading}
          </h1>
          <div className="lp-page-hero__lead">{lead}</div>
          <div className="lp-page-hero__actions">
            <CtaLink data-testid="cap-trial-cta" href={LOGIN_URL} size="large">
              Dùng thử 3 tháng
            </CtaLink>
            <CtaLink data-testid="cap-demo-cta" href={DEMO_URL} size="large" variant="secondary">
              Xem demo
            </CtaLink>
          </div>
          <nav aria-label="Nội dung trang">
            <ul className={styles.toc}>
              {toc.map((entry) => (
                <li key={entry.id}>
                  <a href={`#${entry.id}`}>{entry.label}</a>
                </li>
              ))}
            </ul>
          </nav>
        </section>

        {children}

        <section aria-labelledby="cap-faq" className={styles.section} id="cau-hoi">
          <h2 className={styles.h2} id="cap-faq">
            Câu hỏi thường gặp
          </h2>
          <dl className="lp-page-faq">
            {faq.map((item) => (
              <div className="lp-page-faq__item" key={item.question}>
                <dt className="lp-page-faq__question">{item.question}</dt>
                <dd className="lp-page-faq__answer">{item.answer}</dd>
              </div>
            ))}
          </dl>
          <ul aria-label="Trang liên quan" className={styles.related}>
            {related.map((link) => (
              <li className={styles.relatedItem} key={link.href}>
                <Link href={link.href}>{link.title}</Link>
                <p>{link.body}</p>
              </li>
            ))}
          </ul>
          <div className={styles.cta}>
            <p className={styles.ctaTitle}>Thử Juli trên shop của bạn</p>
            <p className={styles.p}>
              Miễn phí 3 tháng đầu, sau đó 500.000đ/tháng. Muốn xem trước? Bản demo chạy trên một
              shop mẫu, không cần tài khoản.
            </p>
            <div className={styles.ctaActions}>
              <CtaLink href={LOGIN_URL}>Dùng thử 3 tháng</CtaLink>
              <CtaLink href={DEMO_URL} variant="secondary">
                Xem demo
              </CtaLink>
            </div>
          </div>
        </section>
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
  /** Describes what the screenshot shows; "(dữ liệu mẫu)" is appended. */
  alt: string;
  caption: string;
  /** Narrow crops (dialogs, single cards) render at card width. */
  narrow?: boolean;
  children: ReactNode;
}

export function CapSection({ id, heading, image, alt, caption, narrow = false, children }: CapSectionProps) {
  return (
    <section aria-labelledby={`${id}-h`} className={styles.section} id={id}>
      <h2 className={styles.h2} id={`${id}-h`}>
        {heading}
      </h2>
      <figure className={narrow ? `${styles.figure} ${styles.figureNarrow}` : styles.figure}>
        <Picture
          alt={`${alt} (dữ liệu mẫu)`}
          sizes={narrow ? "(min-width: 600px) 544px, 100vw" : "(min-width: 1080px) 1024px, 100vw"}
          variants={image}
        />
        <figcaption className={styles.caption}>
          <span className={styles.sampleTag}>Dữ liệu mẫu</span>
          {caption}
        </figcaption>
      </figure>
      {children}
    </section>
  );
}

export function H3({ children }: { children: ReactNode }) {
  return <h3 className={styles.h3}>{children}</h3>;
}

export function P({ children }: { children: ReactNode }) {
  return <p className={styles.p}>{children}</p>;
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

/** Inline internal link styled like the legal pages' links. */
export function A({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link className="lp-legal__contact-link" href={href}>
      {children}
    </Link>
  );
}
