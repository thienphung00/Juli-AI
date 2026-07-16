"use client";

import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  type ComponentPropsWithoutRef,
  type ReactNode,
  type RefObject,
} from "react";

import { useEscapeDismiss, useFocusTrap } from "./overlay-utils";

interface PopoverContextValue {
  contentId: string;
  headingId: string;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  registerTrigger: (element: HTMLElement | null) => void;
}

const PopoverContext = createContext<PopoverContextValue | null>(null);

function usePopoverContext() {
  const context = useContext(PopoverContext);

  if (!context) {
    throw new Error("Popover subcomponents must render inside <Popover>.");
  }

  return context;
}

export interface PopoverProps {
  children: ReactNode;
  onOpenChange: (open: boolean) => void;
  open: boolean;
}

export function Popover({ children, onOpenChange, open }: PopoverProps) {
  const reactId = useId();
  const contentId = `${reactId}-content`;
  const headingId = `${reactId}-heading`;
  const triggerRef = useRef<HTMLElement | null>(null);

  const registerTrigger = (element: HTMLElement | null) => {
    triggerRef.current = element;
  };

  return (
    <PopoverContext.Provider
      value={{
        contentId,
        headingId,
        onOpenChange,
        open,
        registerTrigger,
      }}
    >
      <PopoverDismissLayer
        contentId={contentId}
        onOpenChange={onOpenChange}
        open={open}
        triggerRef={triggerRef}
      >
        <div className="juli-popover">{children}</div>
      </PopoverDismissLayer>
    </PopoverContext.Provider>
  );
}

interface PopoverDismissLayerProps {
  children: ReactNode;
  contentId: string;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  triggerRef: RefObject<HTMLElement | null>;
}

function PopoverDismissLayer({
  children,
  contentId,
  onOpenChange,
  open,
  triggerRef,
}: PopoverDismissLayerProps) {
  const handleDismiss = () => {
    onOpenChange(false);
  };

  useEscapeDismiss(open, handleDismiss);

  useEffect(() => {
    if (!open) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      const content = document.getElementById(contentId);
      const trigger = triggerRef.current;

      if (content?.contains(target) || trigger?.contains(target)) {
        return;
      }

      handleDismiss();
    };

    document.addEventListener("mousedown", handlePointerDown);

    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [contentId, open, triggerRef]);

  useEffect(() => {
    if (!open) {
      return;
    }

    return () => {
      triggerRef.current?.focus();
    };
  }, [open, triggerRef]);

  return children;
}

export interface PopoverTriggerProps
  extends Omit<ComponentPropsWithoutRef<"button">, "children"> {
  children: ReactNode;
  label: string;
}

export function PopoverTrigger({
  children,
  className,
  label,
  onClick,
  ...rest
}: PopoverTriggerProps) {
  const { contentId, onOpenChange, open, registerTrigger } =
    usePopoverContext();
  const classNames = ["juli-popover__trigger", className]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      ref={(element) => {
        registerTrigger(element);
      }}
      aria-controls={contentId}
      aria-expanded={open}
      aria-haspopup="dialog"
      aria-label={label}
      className={classNames}
      data-testid="juli-popover-trigger"
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) {
          onOpenChange(!open);
        }
      }}
      type="button"
      {...rest}
    >
      {children}
    </button>
  );
}

export interface PopoverContentProps extends ComponentPropsWithoutRef<"div"> {
  children: ReactNode;
  closeLabel?: string;
  heading: string;
  showCloseButton?: boolean;
}

export function PopoverContent({
  children,
  className,
  closeLabel = "Đóng giải thích",
  heading,
  showCloseButton = true,
  ...rest
}: PopoverContentProps) {
  const { contentId, headingId, onOpenChange, open } = usePopoverContext();
  const panelRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useFocusTrap(panelRef, open, closeButtonRef);

  useEffect(() => {
    if (!open || !panelRef.current) {
      return;
    }

    const headingElement = panelRef.current.querySelector<HTMLElement>(
      `#${headingId}`,
    );

    if (showCloseButton && closeButtonRef.current) {
      closeButtonRef.current.focus();
    } else {
      headingElement?.focus();
    }
  }, [headingId, open, showCloseButton]);

  if (!open) {
    return null;
  }

  const classNames = ["juli-popover__content", className]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      ref={panelRef}
      aria-labelledby={headingId}
      className={classNames}
      data-testid="juli-popover-content"
      id={contentId}
      role="dialog"
      tabIndex={-1}
      {...rest}
    >
      <header className="juli-popover__header">
        <h3
          className="juli-popover__heading"
          id={headingId}
          tabIndex={showCloseButton ? undefined : -1}
        >
          {heading}
        </h3>
        {showCloseButton ? (
          <button
            ref={closeButtonRef}
            aria-label={closeLabel}
            className="juli-btn juli-btn--ghost juli-btn--small juli-popover__close"
            data-testid="juli-popover-close"
            onClick={() => {
              onOpenChange(false);
            }}
            type="button"
          >
            <span aria-hidden="true">✕</span>
          </button>
        ) : null}
      </header>
      <div className="juli-popover__body">{children}</div>
    </div>
  );
}

export interface UnavailableKpiPopoverProps {
  activationRequirement: string;
  dataSource: string;
  kpiName: string;
  onOpenChange: (open: boolean) => void;
  open: boolean;
}

export function UnavailableKpiPopover({
  activationRequirement,
  dataSource,
  kpiName,
  onOpenChange,
  open,
}: UnavailableKpiPopoverProps) {
  const triggerLabel = `Vì sao ${kpiName} chưa khả dụng?`;
  const heading = `${kpiName} chưa khả dụng`;

  return (
    <Popover onOpenChange={onOpenChange} open={open}>
      <PopoverTrigger label={triggerLabel}>
        <span aria-hidden="true">ℹ️</span>
      </PopoverTrigger>
      <PopoverContent heading={heading}>
        <p className="juli-popover__copy">
          <strong>Nguồn dữ liệu:</strong> {dataSource}
        </p>
        <p className="juli-popover__copy">{activationRequirement}</p>
      </PopoverContent>
    </Popover>
  );
}
