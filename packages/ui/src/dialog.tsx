"use client";

import {
  createContext,
  useContext,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentPropsWithoutRef,
  type MouseEvent,
  type ReactNode,
  type RefObject,
} from "react";

import { Button } from "./button";
import { useEscapeDismiss, useFocusTrap } from "./overlay-utils";

interface DialogContextValue {
  closeButtonRef: RefObject<HTMLButtonElement | null>;
  onDismiss: () => void;
  registerTitleId: (id: string) => void;
}

const DialogContext = createContext<DialogContextValue | null>(null);

function useDialogContext() {
  const context = useContext(DialogContext);

  if (!context) {
    throw new Error("Dialog subcomponents must render inside <Dialog>.");
  }

  return context;
}

export interface DialogProps {
  children: ReactNode;
  onOpenChange: (open: boolean) => void;
  open: boolean;
}

export function Dialog({ children, onOpenChange, open }: DialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const [titleId, setTitleId] = useState<string | undefined>(undefined);

  const handleDismiss = () => {
    onOpenChange(false);
  };

  useEscapeDismiss(open, handleDismiss);
  useFocusTrap(panelRef, open, closeButtonRef);

  if (!open) {
    return null;
  }

  const handleBackdropClick = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) {
      handleDismiss();
    }
  };

  return (
    <div
      className="juli-dialog__backdrop"
      data-testid="juli-dialog-backdrop"
      onClick={handleBackdropClick}
    >
      <div
        ref={panelRef}
        aria-labelledby={titleId}
        aria-modal="true"
        className="juli-dialog__panel"
        role="dialog"
      >
        <DialogContext.Provider
          value={{
            closeButtonRef,
            onDismiss: handleDismiss,
            registerTitleId: setTitleId,
          }}
        >
          {children}
        </DialogContext.Provider>
      </div>
    </div>
  );
}

export interface DialogHeaderProps extends ComponentPropsWithoutRef<"header"> {
  children: ReactNode;
}

export function DialogHeader({ className, children, ...rest }: DialogHeaderProps) {
  const classNames = ["juli-dialog__header", className]
    .filter(Boolean)
    .join(" ");

  return (
    <header className={classNames} {...rest}>
      {children}
    </header>
  );
}

export interface DialogTitleProps extends ComponentPropsWithoutRef<"h2"> {
  children: ReactNode;
  id?: string;
}

export function DialogTitle({ className, children, id, ...rest }: DialogTitleProps) {
  const reactId = useId();
  const titleId = id ?? `${reactId}-title`;
  const { registerTitleId } = useDialogContext();

  useLayoutEffect(() => {
    registerTitleId(titleId);
  }, [registerTitleId, titleId]);

  const classNames = ["juli-dialog__title", className].filter(Boolean).join(" ");

  return (
    <h2 className={classNames} id={titleId} {...rest}>
      {children}
    </h2>
  );
}

export interface DialogDescriptionProps extends ComponentPropsWithoutRef<"p"> {
  children: ReactNode;
}

export function DialogDescription({
  className,
  children,
  ...rest
}: DialogDescriptionProps) {
  const classNames = ["juli-dialog__description", className]
    .filter(Boolean)
    .join(" ");

  return (
    <p className={classNames} {...rest}>
      {children}
    </p>
  );
}

export interface DialogBodyProps extends ComponentPropsWithoutRef<"div"> {
  children: ReactNode;
}

export function DialogBody({ className, children, ...rest }: DialogBodyProps) {
  const classNames = ["juli-dialog__body", className].filter(Boolean).join(" ");

  return (
    <div className={classNames} {...rest}>
      {children}
    </div>
  );
}

export interface DialogFooterProps extends ComponentPropsWithoutRef<"footer"> {
  children: ReactNode;
}

export function DialogFooter({ className, children, ...rest }: DialogFooterProps) {
  const classNames = ["juli-dialog__footer", className]
    .filter(Boolean)
    .join(" ");

  return (
    <footer className={classNames} {...rest}>
      {children}
    </footer>
  );
}

export interface DialogCloseProps
  extends Omit<ComponentPropsWithoutRef<"button">, "children"> {
  label?: string;
}

export function DialogClose({
  className,
  label = "Đóng",
  onClick,
  ...rest
}: DialogCloseProps) {
  const { closeButtonRef, onDismiss } = useDialogContext();
  const classNames = [
    "juli-btn",
    "juli-btn--ghost",
    "juli-btn--small",
    "juli-dialog__close",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      ref={closeButtonRef}
      aria-label={label}
      className={classNames}
      data-testid="juli-dialog-close"
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) {
          onDismiss();
        }
      }}
      type="button"
      {...rest}
    >
      <span aria-hidden="true">✕</span>
    </button>
  );
}

export interface DialogActionsProps extends ComponentPropsWithoutRef<"div"> {
  children: ReactNode;
}

export function DialogActions({
  className,
  children,
  ...rest
}: DialogActionsProps) {
  const classNames = ["juli-dialog__actions", className]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classNames} {...rest}>
      {children}
    </div>
  );
}

export interface ConfirmDialogProps {
  cancelLabel?: string;
  confirmLabel: string;
  description: string;
  onCancel?: () => void;
  onConfirm: () => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  title: string;
}

export function ConfirmDialog({
  cancelLabel = "Hủy",
  confirmLabel,
  description,
  onCancel,
  onConfirm,
  onOpenChange,
  open,
  title,
}: ConfirmDialogProps) {
  const handleCancel = () => {
    onCancel?.();
    onOpenChange(false);
  };

  const handleConfirm = () => {
    onConfirm();
    onOpenChange(false);
  };

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogClose />
      </DialogHeader>
      <DialogBody>
        <DialogDescription>{description}</DialogDescription>
      </DialogBody>
      <DialogFooter>
        <DialogActions>
          <Button onClick={handleCancel} variant="secondary">
            {cancelLabel}
          </Button>
          <Button onClick={handleConfirm} variant="primary">
            {confirmLabel}
          </Button>
        </DialogActions>
      </DialogFooter>
    </Dialog>
  );
}
