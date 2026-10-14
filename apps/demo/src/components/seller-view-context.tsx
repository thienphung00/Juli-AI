"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";

/**
 * How the seller screens are being shown (D25.3, amended 2026-10-10).
 *
 * The seller's own client renders them as-is (the default). Juli Ops "Xem như
 * shop" renders the very same components read-only: every READ interaction
 * (expand / collapse, tabs, filters, sorting, links) keeps working, every
 * control that WRITES is rendered `disabled`, greyed, with
 * {@link READ_ONLY_TITLE} — artboard `OpsViewAs.dc.html`. Links between seller
 * pages go through {@link useSellerHref} so view-as keeps them under its own
 * route instead of leaving to `/analytics`, `/decisions`, `/`.
 *
 * This is presentation only: the view-as fetch and the server still refuse
 * every non-GET.
 */

export const READ_ONLY_TITLE = "Chế độ xem: không thể thao tác thay seller";

export interface SellerViewMode {
  readonly readOnly: boolean;
  /** Tooltip of a disabled write control (P32-A: the partner trial account has its own). */
  readonly readOnlyTitle: string;
  /**
   * P32-A: the partner trial account — "Duyệt" stays enabled and runs a
   * simulation instead of the real approve; every other write is read-only.
   */
  readonly simulateApprove: boolean;
  /** Maps a seller href (`/analytics?…`, `/decisions?…`, `/`) to where it lives in this mode. */
  readonly href: (sellerHref: string) => string;
}

const SELLER_MODE: SellerViewMode = {
  readOnly: false,
  readOnlyTitle: READ_ONLY_TITLE,
  simulateApprove: false,
  href: (h) => h,
};

const SellerViewContext = createContext<SellerViewMode>(SELLER_MODE);

export function SellerViewProvider({
  readOnly,
  href,
  readOnlyTitle = READ_ONLY_TITLE,
  simulateApprove = false,
  children,
}: {
  readonly readOnly: boolean;
  readonly href?: (sellerHref: string) => string;
  readonly readOnlyTitle?: string;
  readonly simulateApprove?: boolean;
  readonly children: ReactNode;
}) {
  const value = useMemo<SellerViewMode>(
    () => ({ readOnly, readOnlyTitle, simulateApprove, href: href ?? SELLER_MODE.href }),
    [readOnly, readOnlyTitle, simulateApprove, href],
  );
  return <SellerViewContext.Provider value={value}>{children}</SellerViewContext.Provider>;
}

export function useReadOnly(): boolean {
  return useContext(SellerViewContext).readOnly;
}

export function useSellerHref(): (sellerHref: string) => string {
  return useContext(SellerViewContext).href;
}

export interface WriteControlProps {
  readonly disabled: boolean | undefined;
  readonly title?: string;
  readonly "data-read-only"?: "";
}

/**
 * Props for a control that writes (approve, save, an input of a rule…):
 * spread AFTER the control's own `disabled` / `title`. In read-only mode it is
 * disabled with the view-as title and `data-read-only` (greyed by
 * `globals.css`); otherwise it keeps its own `disabled`.
 */
export function writeControl(
  readOnly: boolean,
  disabled?: boolean,
  title?: string,
  readOnlyTitle: string = READ_ONLY_TITLE,
): WriteControlProps {
  if (readOnly) return { disabled: true, title: readOnlyTitle, "data-read-only": "" };
  return title === undefined ? { disabled } : { disabled, title };
}

/** Hook form of {@link writeControl}: `const write = useWriteControl(); <button {...write(busy)}>`. */
export function useWriteControl(): (disabled?: boolean, title?: string) => WriteControlProps {
  const { readOnly, readOnlyTitle } = useContext(SellerViewContext);
  return (disabled, title) => writeControl(readOnly, disabled, title, readOnlyTitle);
}

/**
 * The single-card "Duyệt" control: like {@link useWriteControl}, except in the
 * partner trial account (P32-A), where it stays enabled — the click runs the
 * simulated Duyệt → Thực thi instead of the real approve.
 */
export function useApproveControl(): (disabled?: boolean, title?: string) => WriteControlProps {
  const { readOnly, readOnlyTitle, simulateApprove } = useContext(SellerViewContext);
  return (disabled, title) => writeControl(readOnly && !simulateApprove, disabled, title, readOnlyTitle);
}
