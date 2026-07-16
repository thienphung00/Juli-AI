import type { ComponentPropsWithoutRef } from "react";

export type LoadingSpinnerSize = "default" | "inline";

export interface LoadingSpinnerProps extends ComponentPropsWithoutRef<"div"> {
  size?: LoadingSpinnerSize;
  label?: string;
}

export function LoadingSpinner({
  size = "default",
  label = "Đang tải",
  className,
  ...rest
}: LoadingSpinnerProps) {
  const classNames = ["juli-loading", className].filter(Boolean).join(" ");

  return (
    <div
      aria-busy="true"
      aria-live="polite"
      className={classNames}
      data-testid="juli-loading-spinner"
      role="status"
      {...rest}
    >
      <span
        aria-hidden="true"
        className={[
          "juli-spinner",
          size === "inline" ? "juli-spinner--inline" : null,
        ]
          .filter(Boolean)
          .join(" ")}
      />
      <span className="juli-sr-only">{label}</span>
    </div>
  );
}

export interface LoadingSkeletonProps extends ComponentPropsWithoutRef<"div"> {
  shimmer?: boolean;
}

export function LoadingSkeleton({
  className,
  shimmer = true,
  ...rest
}: LoadingSkeletonProps) {
  const classNames = [
    "juli-skeleton",
    shimmer ? "juli-skeleton--shimmer" : null,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return <div aria-hidden="true" className={classNames} {...rest} />;
}

export type LoadingIndicatorVariant = "spinner" | "skeleton";

export type LoadingIndicatorProps =
  | ({
      variant?: "spinner";
    } & LoadingSpinnerProps)
  | ({
      variant: "skeleton";
    } & LoadingSkeletonProps);

export function LoadingIndicator(props: LoadingIndicatorProps) {
  if (props.variant === "skeleton") {
    const { variant: _variant, ...skeletonProps } = props;
    return <LoadingSkeleton {...skeletonProps} />;
  }

  const { variant: _variant, ...spinnerProps } = props;
  return <LoadingSpinner {...spinnerProps} />;
}
