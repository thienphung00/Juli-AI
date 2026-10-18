import type { ReactNode } from "react";

import { faqPageSchema, JsonLd, type FaqItem } from "../../lib/seo";
import { TextLink } from "./button";
import { Icon, type IconName } from "./icon";
import { CheckList, Eyebrow, Heading, type HeadingSize } from "./section";

function cx(...names: Array<string | false | null | undefined>): string {
  return names.filter(Boolean).join(" ");
}

/* ————— FeatureRow ————— */

export interface FeatureRowProps {
  eyebrow?: ReactNode;
  title: ReactNode;
  /** Heading id → pass as `aria-labelledby` if the row is its own section. */
  titleId?: string;
  /** Default 2. */
  level?: 2 | 3;
  /** Default `feature` (36 → 26 px). */
  size?: HeadingSize;
  /** Body paragraph(s). A string becomes one `<p class="ui-body">`. */
  children?: ReactNode;
  /** Pink-check bullets under the body. */
  bullets?: readonly ReactNode[];
  /** "Xem Phân tích shop →" */
  link?: { href: string; label: string };
  /** Usually a `<Shot>`. */
  media: ReactNode;
  /** Media on the left at ≥ 960 px. On mobile text always comes first. */
  reverse?: boolean;
  /** Render as `<section aria-labelledby={titleId}>` (home) or `<div>` (inside a Section). Default `section`. */
  as?: "section" | "div";
  className?: string;
}

/** Zig-zag text + screenshot (home capabilities, Main.dc.html cap1–cap3). */
export function FeatureRow({
  eyebrow,
  title,
  titleId,
  level = 2,
  size = "feature",
  children,
  bullets,
  link,
  media,
  reverse = false,
  as: Tag = "section",
  className,
}: FeatureRowProps) {
  return (
    <Tag
      aria-labelledby={Tag === "section" ? titleId : undefined}
      className={cx("ui-feature", reverse && "ui-feature--reverse", className)}
    >
      <div className="ui-feature__text">
        {eyebrow ? <Eyebrow>{eyebrow}</Eyebrow> : null}
        <Heading id={titleId} level={level} size={size}>
          {title}
        </Heading>
        {typeof children === "string" ? <p className="ui-body">{children}</p> : children}
        {bullets && bullets.length > 0 ? <CheckList items={bullets} /> : null}
        {link ? <TextLink href={link.href}>{link.label}</TextLink> : null}
      </div>
      <div className="ui-feature__media">{media}</div>
    </Tag>
  );
}

/* ————— StatusPill ————— */

export type MarketStatus = "live" | "integrating";

const STATUS_LABEL: Record<MarketStatus, string> = {
  live: "Đang hoạt động",
  integrating: "Đang tích hợp",
};

export interface StatusPillProps {
  status: MarketStatus;
  /** Defaults: live "Đang hoạt động", integrating "Đang tích hợp" (D42). */
  children?: ReactNode;
}

/** Green / amber pill for the marketplace strip (TikTok Shop live, Shopee integrating). */
export function StatusPill({ status, children }: StatusPillProps) {
  return (
    <span className={`ui-pill ui-pill--${status}`} data-status={status}>
      {children ?? STATUS_LABEL[status]}
    </span>
  );
}

/* ————— StepList ————— */

export interface Step {
  title: string;
  body: string;
  /** The seller's step ("Duyệt"): pink tint, label "03 · bạn". */
  you?: boolean;
  /** Line icon in a chip before the title (decorative). */
  icon?: IconName;
  /** One short muted line under the body (a caveat that must stay with the step). */
  note?: string;
}

/** Juli's 5-step loop as in Main.dc.html "Cách Juli làm việc". */
export const LOOP_STEPS: readonly Step[] = [
  { title: "Phân tích", body: "Đọc 5 luồng truy cập và phễu của từng luồng mỗi ngày." },
  { title: "Đề xuất", body: "Mỗi thẻ nêu chỉ số mục tiêu, lý do và thay đổi cụ thể." },
  { title: "Duyệt", body: "Bạn duyệt, sửa hoặc từ chối. Không gì chạy khi chưa duyệt.", you: true },
  { title: "Thực thi", body: "Juli cập nhật tiêu đề, mô tả qua Open API; phần còn lại có hướng dẫn." },
  { title: "Đo lường", body: "Kiểm tra ngày 7, chốt ngày 14, hoàn tác được." },
];

export interface StepListProps {
  steps?: readonly Step[];
  /** Step titles' level. Default 3 (under the section's h2). */
  level?: 3 | 4;
  /** Suffix on the highlighted step's number. Default "bạn" → "03 · bạn". */
  youLabel?: string;
  /**
   * `cards` (default): 5-up cards ≥ 760 px, ruled rows on phones (home).
   * `stepper`: a vertical timeline with icon chips on phones, one row of five
   * connected cards ≥ 960 px (`/san-pham`, D46.3).
   */
  variant?: "cards" | "stepper";
  className?: string;
}

/**
 * Numbered steps: a 5-up card grid on desktop, a ruled list on mobile
 * (HomeMobile.dc.html). Same DOM at every width.
 */
export function StepList({
  steps = LOOP_STEPS,
  level = 3,
  youLabel = "bạn",
  variant = "cards",
  className,
}: StepListProps) {
  const Title = `h${level}` as "h3" | "h4";
  return (
    <ol className={cx("ui-steps", variant === "stepper" && "ui-steps--stepper", className)}>
      {steps.map((step, index) => {
        const number = String(index + 1).padStart(2, "0");
        return (
          <li className={cx("ui-step", step.you && "ui-step--you")} key={step.title}>
            {step.icon ? (
              <span className="ui-step__icon">
                <Icon name={step.icon} size={20} strokeWidth={1.8} />
              </span>
            ) : null}
            <div className="ui-step__main">
              <span className="ui-step__number">
                {step.you && youLabel ? `${number} · ${youLabel}` : number}
              </span>
              <div className="ui-step__text">
                <Title className="ui-step__title">{step.title}</Title>
                <p className="ui-step__body">{step.body}</p>
                {step.note ? <p className="ui-step__note">{step.note}</p> : null}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/* ————— FunnelDiagram ————— */

export type FunnelStep = "impressions" | "ctr" | "ctor" | "aov";

const FUNNEL: ReadonlyArray<{ key: FunnelStep; label: string }> = [
  { key: "impressions", label: "Lượt hiển thị" },
  { key: "ctr", label: "CTR" },
  { key: "ctor", label: "CTOR" },
  { key: "aov", label: "AOV" },
];

export interface FunnelDiagramProps {
  /** The step marked "Đang nghẽn" (pink border). Omit for a neutral formula. */
  highlight?: FunnelStep;
  /** Label on the highlighted box. Default "Đang nghẽn". */
  highlightLabel?: string;
  /** Under the diagram. Default: the mockup's "Ví dụ minh hoạ: …". `null` hides it. */
  caption?: ReactNode | null;
  className?: string;
}

const FUNNEL_LABEL =
  "Công thức: GMV bằng Lượt hiển thị nhân CTR nhân CTOR nhân AOV";

/**
 * `Lượt hiển thị × CTR × CTOR × AOV = GMV`, built in markup (D44.3, no image).
 * Screen readers get one sentence (`role="img"` + `aria-label`).
 */
export function FunnelDiagram({
  highlight,
  highlightLabel = "Đang nghẽn",
  caption = "Ví dụ minh hoạ: Juli đánh dấu bước có chênh lệch lớn nhất so với kỳ trước.",
  className,
}: FunnelDiagramProps) {
  const label = highlight
    ? `${FUNNEL_LABEL}. ${highlightLabel}: ${FUNNEL.find((s) => s.key === highlight)?.label}.`
    : `${FUNNEL_LABEL}.`;
  return (
    <figure className={cx("ui-funnel", className)}>
      <div aria-label={label} className="ui-funnel__row" role="img">
        {FUNNEL.map((step, index) => {
          const hot = step.key === highlight;
          return (
            <span className="ui-funnel__pair" key={step.key}>
              <span className={cx("ui-funnel__box", hot && "ui-funnel__box--hot")} data-step={step.key}>
                <span className="ui-funnel__meta">{hot ? highlightLabel : `Bước ${index + 1}`}</span>
                <span className="ui-funnel__name">{step.label}</span>
              </span>
              <span aria-hidden="true" className="ui-funnel__op">
                {index < FUNNEL.length - 1 ? "×" : "="}
              </span>
            </span>
          );
        })}
        <span className="ui-funnel__box ui-funnel__box--result">
          <span className="ui-funnel__meta">Kết quả</span>
          <span className="ui-funnel__name">GMV</span>
        </span>
      </div>
      {caption ? <figcaption className="ui-funnel__caption">{caption}</figcaption> : null}
    </figure>
  );
}

/* ————— FaqList ————— */

export interface FaqListProps {
  items: readonly FaqItem[];
  /**
   * Also emit the FAQPage JSON-LD for exactly these items (D43.5: FAQPage only
   * where the FAQ is shown). Leave false if the page already passes
   * `faqPageSchema(items)` to its own `<JsonLd>`.
   */
  schema?: boolean;
  /** Open the first item. */
  openFirst?: boolean;
  className?: string;
}

/** Ruled `<details>` accordion (no JS), questions 17 px semibold. */
export function FaqList({ items, schema = false, openFirst = false, className }: FaqListProps) {
  return (
    <div className={cx("ui-faq", className)}>
      {schema ? <JsonLd data={faqPageSchema(items)} /> : null}
      {items.map((item, index) => (
        <details className="ui-faq__item" key={item.question} open={openFirst && index === 0}>
          <summary className="ui-faq__question">
            <span>{item.question}</span>
            <Icon className="ui-faq__chevron" name="chevron-down" size={20} />
          </summary>
          <p className="ui-faq__answer">{item.answer}</p>
        </details>
      ))}
    </div>
  );
}

/* ————— TocNav ————— */

export interface TocItem {
  /** Target heading id (without #). */
  id: string;
  label: string;
}

export interface TocNavProps {
  items: readonly TocItem[];
  /** Default "Trên trang này". */
  title?: string;
  /** Marked `aria-current` + bold (static; no scroll-spy). */
  activeId?: string;
  /** `rule` = hairline on the left (legal), `plain` (product pages). */
  variant?: "plain" | "rule";
  className?: string;
}

function TocLinks({ items, activeId }: Pick<TocNavProps, "items" | "activeId">) {
  return (
    <ol className="ui-toc__list">
      {items.map((item) => (
        <li key={item.id}>
          <a
            aria-current={item.id === activeId ? "location" : undefined}
            className="ui-toc__link"
            href={`#${item.id}`}
          >
            {item.label}
          </a>
        </li>
      ))}
    </ol>
  );
}

/**
 * Side table of contents. ≥ 960 px: a sticky list. Below: a `<details>`
 * disclosure "Trên trang này" at the top of the content (no JS).
 */
export function TocNav({
  items,
  title = "Trên trang này",
  activeId,
  variant = "plain",
  className,
}: TocNavProps) {
  return (
    <nav aria-label={title} className={cx("ui-toc", `ui-toc--${variant}`, className)}>
      <div className="ui-toc__desktop">
        <p className="ui-toc__title">{title}</p>
        <TocLinks activeId={activeId} items={items} />
      </div>
      <details className="ui-toc__mobile">
        <summary className="ui-toc__summary">
          <span>{title}</span>
          <Icon className="ui-toc__chevron" name="chevron-down" size={18} />
        </summary>
        <TocLinks activeId={activeId} items={items} />
      </details>
    </nav>
  );
}

/* ————— Breadcrumb ————— */

export interface BreadcrumbProps {
  /** Ancestors, root first; the current page is `current`. */
  items: ReadonlyArray<{ href: string; label: string }>;
  current: string;
}

/** "Sản phẩm / Phân tích shop" (Product.dc.html). Pair with `breadcrumbSchema(path)`. */
export function Breadcrumb({ items, current }: BreadcrumbProps) {
  return (
    <nav aria-label="Breadcrumb" className="ui-breadcrumb">
      <ol>
        {items.map((item) => (
          <li key={item.href}>
            <a href={item.href}>{item.label}</a>
            <span aria-hidden="true">/</span>
          </li>
        ))}
        <li aria-current="page">{current}</li>
      </ol>
    </nav>
  );
}
