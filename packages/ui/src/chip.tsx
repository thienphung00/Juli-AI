import type { ButtonHTMLAttributes, ReactNode } from "react";

export type StatusChipVariant =
  | "success"
  | "destructive"
  | "warning"
  | "info"
  | "neutral";

export interface StatusChipProps {
  children: ReactNode;
  variant?: StatusChipVariant;
}

export interface FilterChipProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  children: ReactNode;
  selected?: boolean;
}

export interface InputChipProps {
  children: ReactNode;
  onRemove?: () => void;
  removeLabel: string;
}

export function StatusChip({
  children,
  variant = "neutral",
}: StatusChipProps) {
  return (
    <span className={`juli-chip juli-chip--status juli-chip--${variant}`}>
      {children}
    </span>
  );
}

export function FilterChip({
  children,
  className,
  selected = false,
  type = "button",
  ...rest
}: FilterChipProps) {
  const chipClassName = [
    "juli-chip",
    "juli-chip--filter",
    selected ? "juli-chip--selected" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      aria-selected={selected}
      className={chipClassName}
      role="tab"
      type={type}
      {...rest}
    >
      {children}
    </button>
  );
}

export function InputChip({ children, onRemove, removeLabel }: InputChipProps) {
  return (
    <span className="juli-chip juli-chip--input">
      <span className="juli-chip__label">{children}</span>
      {onRemove ? (
        <button
          aria-label={removeLabel}
          className="juli-chip__remove"
          onClick={onRemove}
          type="button"
        >
          <span aria-hidden="true">✕</span>
        </button>
      ) : null}
    </span>
  );
}
