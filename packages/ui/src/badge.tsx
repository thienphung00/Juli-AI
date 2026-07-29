import type { ComponentPropsWithoutRef, ReactNode } from "react";

export type BadgeVariant =
  | "priority"
  | "capability"
  | "success"
  | "destructive"
  | "warning"
  | "info"
  | "live";

export interface BadgeProps extends ComponentPropsWithoutRef<"span"> {
  variant: BadgeVariant;
  children?: ReactNode;
}

export function Badge({ className, variant, ...rest }: BadgeProps) {
  const classNames = ["juli-badge", `juli-badge--${variant}`, className]
    .filter(Boolean)
    .join(" ");

  return <span className={classNames} {...rest} />;
}
