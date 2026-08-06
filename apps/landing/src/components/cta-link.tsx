import type { ComponentPropsWithoutRef, ReactNode } from "react";

export interface CtaLinkProps extends ComponentPropsWithoutRef<"a"> {
  variant?: "primary" | "secondary" | "ghost";
  size?: "large" | "default" | "small";
  children?: ReactNode;
}

/**
 * Anchor CTA reusing `@juli/ui` button classes so marketing CTAs and product
 * buttons cannot drift apart visually (PRD 2.7 component-reuse requirement).
 */
export function CtaLink({
  className,
  variant = "primary",
  size = "default",
  children,
  ...rest
}: CtaLinkProps) {
  const classNames = [
    "juli-btn",
    `juli-btn--${variant}`,
    `juli-btn--${size}`,
    "lp-cta",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <a className={classNames} {...rest}>
      {children}
    </a>
  );
}
