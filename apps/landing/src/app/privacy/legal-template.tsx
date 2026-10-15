import type { ReactNode } from "react";

import { Eyebrow, Heading, TocNav, type TocItem } from "../../components/ui";
import { SiteFooter } from "../../components/ui/site-footer";
import { SiteHeader } from "../../components/ui/site-header";
import { COMPANY } from "../../lib/site";

import styles from "./legal.module.css";

/**
 * The legal page template (Legal.dc.html, D44.4, P34-E) shared by /privacy and
 * /terms: header block (eyebrow "Pháp lý", H1, dates, optional VN/EN switch),
 * a 720 px reading column with the "Tóm tắt dễ hiểu" card on top, numbered
 * linkable H2s, a side TOC (disclosure on mobile) and the company contact
 * block. Presentation only — the legal wording lives in each page.
 */

export const SUMMARY_ID = "tom-tat";
export const CONTENT_ID = "noi-dung";

export interface LegalPageProps {
  title: string;
  /** dd/mm/yyyy */
  updated: string;
  effective: string;
  /** Plain-language summary bullets — only what the full text already says. */
  summary: readonly ReactNode[];
  /** TOC entries after "Tóm tắt dễ hiểu" (the summary entry is added here). */
  toc: readonly TocItem[];
  /** The page has a full English version at this anchor → VN/EN switch. */
  englishHref?: string;
  /** Heading of the closing contact block ("Liên hệ về quyền riêng tư"). */
  contactTitle: string;
  contactId: string;
  children: ReactNode;
}

export function LegalPage({
  title,
  updated,
  effective,
  summary,
  toc,
  englishHref,
  contactTitle,
  contactId,
  children,
}: LegalPageProps) {
  const items: TocItem[] = [{ id: SUMMARY_ID, label: "Tóm tắt dễ hiểu" }, ...toc];
  return (
    <>
      <SiteHeader />
      <main className={styles.main}>
        <div className={styles.container}>
          <div className={styles.head}>
            <div className={styles.headText}>
              <Eyebrow variant="muted">Pháp lý</Eyebrow>
              <Heading className={styles.h1} level={1} size="page">
                {title}
              </Heading>
              <p className={styles.dates}>
                Cập nhật lần cuối: {updated} · Có hiệu lực từ {effective}
              </p>
            </div>
            {englishHref ? (
              <nav aria-label="Ngôn ngữ" className={styles.langSwitch}>
                <a aria-current="true" className={styles.langOption} href={`#${CONTENT_ID}`}>
                  Tiếng Việt
                </a>
                <a className={styles.langOption} href={englishHref} hrefLang="en" lang="en">
                  English
                </a>
              </nav>
            ) : null}
          </div>

          <div className={`ui-toc-layout ui-toc-layout--end ${styles.layout}`}>
            <TocNav activeId={SUMMARY_ID} items={items} variant="rule" />
            <article className={styles.article} id={CONTENT_ID}>
              <section aria-labelledby={SUMMARY_ID} className={styles.summary}>
                <h2 className={styles.summaryTitle} id={SUMMARY_ID}>
                  Tóm tắt dễ hiểu
                </h2>
                <ul className={styles.summaryList}>
                  {summary.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
                <p className={styles.summaryNote}>
                  Tóm tắt này không thay thế nội dung đầy đủ bên dưới.
                </p>
              </section>

              {children}

              <section aria-labelledby={contactId} className={styles.contact}>
                <h2 className={styles.contactTitle} id={contactId}>
                  {contactTitle}
                </h2>
                <p data-testid="legal-company">
                  {COMPANY.name} · MST {COMPANY.taxId} · {COMPANY.address} ·{" "}
                  <a href={`mailto:${COMPANY.email}`}>{COMPANY.email}</a>
                </p>
              </section>
            </article>
          </div>
        </div>
      </main>
      <SiteFooter />
    </>
  );
}

export interface LegalSectionProps {
  /** "1." / "4A." — shown muted before the title, part of the heading's name. */
  num: string;
  title: ReactNode;
  /** id of the H2 (TOC target) unless `sectionId` is the target. */
  headingId: string;
  /** id on the <section> (kept for existing deep links, e.g. Google's §3). */
  sectionId?: string;
  children: ReactNode;
}

/** A numbered section: `<section>` named by its linkable H2. */
export function LegalSection({ num, title, headingId, sectionId, children }: LegalSectionProps) {
  return (
    <section aria-labelledby={headingId} className={styles.section} id={sectionId}>
      <h2 className={styles.sectionHeading} id={headingId}>
        <span className={styles.num}>{num}</span> {title}
      </h2>
      {children}
    </section>
  );
}

/** Class names for content inside a section (sub-headings, links, the EN part). */
export const legal = styles;
