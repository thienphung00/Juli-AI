import type { ComponentPropsWithoutRef, ReactNode } from "react";

export type BadgeVariant =
  | "priority"
  | "confidence-high"
  | "confidence-medium"
  | "confidence-low"
  | "capability"
  | "success"
  | "destructive"
  | "warning"
  | "info"
  | "live";

export type ConfidenceLevel = "high" | "medium" | "low";

export interface BadgeProps extends ComponentPropsWithoutRef<"span"> {
  variant: BadgeVariant;
  children?: ReactNode;
}

const CONFIDENCE_LABELS: Record<ConfidenceLevel, string> = {
  high: "Cao",
  medium: "Trung bình",
  low: "Thấp",
};

export interface ConfidenceBadgeProps {
  level: ConfidenceLevel;
}

export function Badge({ className, variant, ...rest }: BadgeProps) {
  const classNames = ["juli-badge", `juli-badge--${variant}`, className]
    .filter(Boolean)
    .join(" ");

  return <span className={classNames} {...rest} />;
}

export function ConfidenceBadge({ level }: ConfidenceBadgeProps) {
  const variant: BadgeVariant =
    level === "high"
      ? "success"
      : level === "medium"
        ? "warning"
        : "destructive";

  return (
    <Badge variant={variant}>{`Độ tin cậy: ${CONFIDENCE_LABELS[level]}`}</Badge>
  );
}
