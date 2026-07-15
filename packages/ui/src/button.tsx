import type { ComponentPropsWithoutRef } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost";

export interface ButtonProps extends ComponentPropsWithoutRef<"button"> {
  variant?: ButtonVariant;
}

export function Button({
  className,
  type = "button",
  variant = "primary",
  ...rest
}: ButtonProps) {
  const classNames = ["juli-btn", `juli-btn--${variant}`, className]
    .filter(Boolean)
    .join(" ");

  return <button className={classNames} type={type} {...rest} />;
}
