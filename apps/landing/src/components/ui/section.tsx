import type { ComponentPropsWithoutRef, ElementType, ReactNode } from "react";

import { Icon } from "./icon";

function cx(...names: Array<string | false | null | undefined>): string {
  return names.filter(Boolean).join(" ");
}

export interface ContainerProps extends ComponentPropsWithoutRef<"div"> {
  /** `wide` = 1200 px (default), `reading` = 720 px (legal, articles). */
  width?: "wide" | "reading";
}

/** Centred column with the page gutters (20 px mobile → 24 px desktop). */
export function Container({ width = "wide", className, ...rest }: ContainerProps) {
  return (
    <div
      className={cx("ui-container", width === "reading" && "ui-container--reading", className)}
      {...rest}
    />
  );
}

export interface SectionProps extends Omit<ComponentPropsWithoutRef<"section">, "title"> {
  /**
   * `default` white · `alt` #fbfbfc with top/bottom hairlines (marketplace
   * strip, data safety) · `dark` the ONE dark band per page (pricing / final CTA).
   */
  tone?: "default" | "alt" | "dark";
  /** Vertical padding: `default` 56→104 px, `compact` 40→72 px, `none`. */
  spacing?: "default" | "compact" | "none";
  /** Inner container width; `none` renders children without a container. */
  width?: "wide" | "reading" | "none";
  /** id of the section's heading → `aria-labelledby` (landmark name). */
  labelledBy?: string;
  /** Classes on the inner container. */
  innerClassName?: string;
}

/** A page band: background tone + vertical rhythm + centred container. */
export function Section({
  tone = "default",
  spacing = "default",
  width = "wide",
  labelledBy,
  className,
  innerClassName,
  children,
  ...rest
}: SectionProps) {
  return (
    <section
      aria-labelledby={labelledBy}
      className={cx(
        "ui-section",
        `ui-section--${tone}`,
        spacing !== "default" && `ui-section--${spacing}`,
        className,
      )}
      {...rest}
    >
      {width === "none" ? (
        children
      ) : (
        <Container className={innerClassName} width={width}>
          {children}
        </Container>
      )}
    </section>
  );
}

export interface EyebrowProps extends ComponentPropsWithoutRef<"p"> {
  /**
   * `default` pink text (section eyebrows) · `muted` grey ("Pháp lý") ·
   * `badge` the hero pill with a pink dot ("Kết nối chính thức qua TikTok Shop Open API").
   */
  variant?: "default" | "muted" | "badge";
}

/** The small label above a heading. A `<p>`, never a heading (heading order). */
export function Eyebrow({ variant = "default", className, children, ...rest }: EyebrowProps) {
  return (
    <p className={cx("ui-eyebrow", `ui-eyebrow--${variant}`, className)} {...rest}>
      {variant === "badge" ? <span aria-hidden="true" className="ui-eyebrow__dot" /> : null}
      {children}
    </p>
  );
}

export type HeadingSize = "display" | "page" | "section" | "feature" | "article" | "card";

export interface HeadingProps extends ComponentPropsWithoutRef<"h2"> {
  /** The element. Pick by document outline, never by looks. */
  level: 1 | 2 | 3;
  /**
   * The look (D44.1): `display` home h1 56/34 · `page` inner h1 50/34 ·
   * `section` 42/26 · `feature` 36/26 · `article` 34/24 · `card` 19.
   * Defaults: h1 → display, h2 → section, h3 → card.
   */
  size?: HeadingSize;
  /** On the dark band. */
  onDark?: boolean;
}

export function Heading({ level, size, onDark, className, ...rest }: HeadingProps) {
  const Tag = `h${level}` as ElementType;
  const look = size ?? (level === 1 ? "display" : level === 2 ? "section" : "card");
  return (
    <Tag
      className={cx("ui-heading", `ui-heading--${look}`, onDark && "ui-heading--on-dark", className)}
      {...rest}
    />
  );
}

export interface SectionIntroProps {
  eyebrow?: ReactNode;
  title: ReactNode;
  /** id for the heading (pass the same to `<Section labelledBy>`). */
  titleId?: string;
  /** Default 2. */
  level?: 1 | 2;
  /** Default `section` for h2, `display` for h1. */
  size?: HeadingSize;
  lead?: ReactNode;
  onDark?: boolean;
  /** Centre the intro (final CTA bands). */
  align?: "start" | "center";
  className?: string;
}

/** Eyebrow + heading + lead, the top of most sections. Heading max 720 px. */
export function SectionIntro({
  eyebrow,
  title,
  titleId,
  level = 2,
  size,
  lead,
  onDark,
  align = "start",
  className,
}: SectionIntroProps) {
  return (
    <div className={cx("ui-intro", align === "center" && "ui-intro--center", className)}>
      {eyebrow ? <Eyebrow>{eyebrow}</Eyebrow> : null}
      <Heading id={titleId} level={level} onDark={onDark} size={size}>
        {title}
      </Heading>
      {lead ? <p className={cx("ui-lead", onDark && "ui-lead--on-dark")}>{lead}</p> : null}
    </div>
  );
}

export interface CardProps extends ComponentPropsWithoutRef<"div"> {
  /** `default` hairline on white · `alt` on #fbfbfc · `highlight` pink tint · `dark` on the dark band. */
  tone?: "default" | "alt" | "highlight" | "dark";
  as?: "div" | "li" | "article";
}

/** Hairline card, radius 16, padding 22–24 (safety cards, streams, next links). */
export function Card({ tone = "default", as = "div", className, ...rest }: CardProps) {
  const Tag = as as ElementType;
  return <Tag className={cx("ui-card", `ui-card--${tone}`, className)} {...rest} />;
}

export interface CheckListProps {
  items: readonly ReactNode[];
  className?: string;
}

/** Bullets with a pink check (feature blocks). */
export function CheckList({ items, className }: CheckListProps) {
  return (
    <ul className={cx("ui-checklist", className)}>
      {items.map((item, index) => (
        <li key={index}>
          <Icon className="ui-checklist__icon" name="check" strokeWidth={2.2} />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}
