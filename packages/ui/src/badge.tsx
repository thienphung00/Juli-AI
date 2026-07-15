import type { ComponentPropsWithoutRef } from "react";

export type BadgeVariant =
  | "priority"
  | "confidence-high"
  | "confidence-medium"
  | "confidence-low"
  | "capability";

export interface BadgeProps extends ComponentPropsWithoutRef<"span"> {
  variant: BadgeVariant;
}

export function Badge({ className, variant, ...rest }: BadgeProps) {
  const classNames = ["juli-badge", `juli-badge--${variant}`, className]
    .filter(Boolean)
    .join(" ");

  return <span className={classNames} {...rest} />;
}
