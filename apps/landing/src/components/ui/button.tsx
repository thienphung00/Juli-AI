import Link from "next/link";
import type { ComponentPropsWithoutRef, ReactNode } from "react";

import { Icon, type IconName } from "./icon";

export type ButtonVariant =
  /** Dark ink fill — the one primary action ("Dùng thử miễn phí 3 tháng"). */
  | "primary"
  /** White with a hairline outline ("Xem video 1 phút", "Xem demo"). */
  | "secondary"
  /** White fill on the dark band ("Đăng ký dùng thử"). */
  | "on-dark"
  /** Outline on the dark band ("Xem demo với dữ liệu mẫu"). */
  | "on-dark-secondary";

export type ButtonSize =
  /** 15 px, 44 px tall, radius 10 — header. */
  | "md"
  /** 16 px, 52 px tall, radius 12 — hero, CTA bands. Default. */
  | "lg";

interface ButtonLookProps {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Leading line icon, e.g. `"play"`. */
  icon?: IconName;
  /** Full width below 640 px (HomeMobile stacks the hero CTAs). */
  blockOnMobile?: boolean;
  className?: string;
  children: ReactNode;
}

export function buttonClassName({
  variant = "primary",
  size = "lg",
  blockOnMobile = false,
  className,
}: Pick<ButtonLookProps, "variant" | "size" | "blockOnMobile" | "className">): string {
  return [
    "ui-button",
    `ui-button--${variant}`,
    `ui-button--${size}`,
    blockOnMobile ? "ui-button--block-mobile" : null,
    className,
  ]
    .filter(Boolean)
    .join(" ");
}

function Content({ icon, size, children }: Pick<ButtonLookProps, "icon" | "size" | "children">) {
  return (
    <>
      {icon ? <Icon name={icon} size={size === "md" ? 16 : 18} /> : null}
      {children}
    </>
  );
}

export type LinkButtonProps = ButtonLookProps &
  Omit<ComponentPropsWithoutRef<"a">, "className" | "children"> & { href: string };

/**
 * A link styled as a button. Internal paths (`/…`) use `next/link`; anything
 * else (the Demo, `mailto:`) a plain `<a>`. Keep `data-testid` on CTAs: the
 * TikTok listener reports it as `content_name`.
 */
export function LinkButton({
  variant,
  size,
  icon,
  blockOnMobile,
  className,
  children,
  href,
  ...rest
}: LinkButtonProps) {
  const classes = buttonClassName({ variant, size, blockOnMobile, className });
  const content = (
    <Content icon={icon} size={size}>
      {children}
    </Content>
  );
  if (href.startsWith("/") && !href.startsWith("//")) {
    return (
      <Link className={classes} href={href} {...rest}>
        {content}
      </Link>
    );
  }
  return (
    <a className={classes} href={href} {...rest}>
      {content}
    </a>
  );
}

export type ButtonProps = ButtonLookProps &
  Omit<ComponentPropsWithoutRef<"button">, "className" | "children">;

/** A real `<button>` with the same looks (forms, the video play control). */
export function Button({
  variant,
  size,
  icon,
  blockOnMobile,
  className,
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      className={buttonClassName({ variant, size, blockOnMobile, className })}
      type={type}
      {...rest}
    >
      <Content icon={icon} size={size}>
        {children}
      </Content>
    </button>
  );
}

export interface TextLinkProps extends Omit<ComponentPropsWithoutRef<"a">, "href"> {
  href: string;
  /** Appends " →" (decorative). Default true. */
  arrow?: boolean;
  /** `on-dark` for links on the dark band. */
  tone?: "default" | "on-dark";
}

/** The pink "Xem Phân tích shop →" link under feature blocks and cards. */
export function TextLink({
  href,
  arrow = true,
  tone = "default",
  className,
  children,
  ...rest
}: TextLinkProps) {
  const classes = ["ui-text-link", tone === "on-dark" ? "ui-text-link--on-dark" : null, className]
    .filter(Boolean)
    .join(" ");
  const content = (
    <>
      {children}
      {arrow ? <span aria-hidden="true"> →</span> : null}
    </>
  );
  if (href.startsWith("/") && !href.startsWith("//")) {
    return (
      <Link className={classes} href={href} {...rest}>
        {content}
      </Link>
    );
  }
  return (
    <a className={classes} href={href} {...rest}>
      {content}
    </a>
  );
}
