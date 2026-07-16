import {
  useCallback,
  useEffect,
  useRef,
  type ComponentPropsWithoutRef,
  type ReactNode,
} from "react";

import { Button } from "./button";

export type ToastVariant = "success" | "error" | "actionable";

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastItem {
  id: string;
  message: string;
  variant?: ToastVariant;
  action?: ToastAction;
  duration?: number;
}

export interface ToastProps extends ToastItem {
  onDismiss: (id: string) => void;
}

const DEFAULT_DURATIONS: Record<ToastVariant, number> = {
  success: 4000,
  error: 6000,
  actionable: 6000,
};

export function Toast({
  id,
  message,
  variant = "success",
  action,
  duration,
  onDismiss,
}: ToastProps) {
  const dismissTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const remainingRef = useRef(duration ?? DEFAULT_DURATIONS[variant]);
  const pausedAtRef = useRef<number | null>(null);

  const clearDismissTimer = useCallback(() => {
    if (dismissTimeoutRef.current) {
      clearTimeout(dismissTimeoutRef.current);
      dismissTimeoutRef.current = null;
    }
  }, []);

  const scheduleDismiss = useCallback(
    (delay: number) => {
      clearDismissTimer();
      dismissTimeoutRef.current = setTimeout(() => {
        onDismiss(id);
      }, delay);
    },
    [clearDismissTimer, id, onDismiss],
  );

  const pauseDismiss = useCallback(() => {
    if (pausedAtRef.current !== null || !dismissTimeoutRef.current) {
      return;
    }

    pausedAtRef.current = Date.now();
    clearDismissTimer();
  }, [clearDismissTimer]);

  const resumeDismiss = useCallback(() => {
    if (pausedAtRef.current === null) {
      return;
    }

    const elapsed = Date.now() - pausedAtRef.current;
    remainingRef.current = Math.max(remainingRef.current - elapsed, 0);
    pausedAtRef.current = null;
    scheduleDismiss(remainingRef.current);
  }, [scheduleDismiss]);

  useEffect(() => {
    remainingRef.current = duration ?? DEFAULT_DURATIONS[variant];
    pausedAtRef.current = null;
    scheduleDismiss(remainingRef.current);

    return clearDismissTimer;
  }, [clearDismissTimer, duration, id, scheduleDismiss, variant]);

  const ariaLive = variant === "error" ? "assertive" : "polite";

  return (
    <div
      aria-atomic="true"
      aria-live={ariaLive}
      className={[
        "juli-toast",
        `juli-toast--${variant}`,
        action ? "juli-toast--with-action" : null,
      ]
        .filter(Boolean)
        .join(" ")}
      data-testid="juli-toast"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          resumeDismiss();
        }
      }}
      onFocus={pauseDismiss}
      onMouseEnter={pauseDismiss}
      onMouseLeave={resumeDismiss}
      role="status"
      tabIndex={-1}
    >
      <p className="juli-toast__message">{message}</p>
      {action ? (
        <Button
          className="juli-toast__action"
          onClick={action.onClick}
          size="small"
          variant="ghost"
        >
          {action.label}
        </Button>
      ) : null}
    </div>
  );
}

export interface ToastViewportProps {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
}

const MAX_VISIBLE_TOASTS = 2;

export function ToastViewport({ toasts, onDismiss }: ToastViewportProps) {
  const visibleToasts = toasts.slice(0, MAX_VISIBLE_TOASTS);

  return (
    <div
      aria-label="Thông báo"
      className="juli-toast-viewport"
      data-testid="juli-toast-viewport"
    >
      {visibleToasts.map((toast) => (
        <Toast key={toast.id} {...toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

export type ToastViewportItem = ToastItem;
