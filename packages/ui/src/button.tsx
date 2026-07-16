import type { ComponentPropsWithoutRef, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost";
export type ButtonSize = "large" | "default" | "small";

export interface ButtonProps extends ComponentPropsWithoutRef<"button"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  children?: ReactNode;
}

export function Button({
  className,
  type = "button",
  variant = "primary",
  size = "default",
  loading = false,
  disabled,
  children,
  ...rest
}: ButtonProps) {
  const isDisabled = disabled || loading;
  const classNames = [
    "juli-btn",
    `juli-btn--${variant}`,
    `juli-btn--${size}`,
    loading ? "juli-btn--loading" : null,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      aria-busy={loading || undefined}
      className={classNames}
      disabled={isDisabled}
      type={type}
      {...rest}
    >
      {loading ? (
        <>
          <span aria-hidden="true" className="juli-btn__spinner" />
          <span className="juli-btn__label">{children}</span>
        </>
      ) : (
        children
      )}
    </button>
  );
}
