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
  /** Maps a seller href (`/analytics?…`, `/decisions?…`, `/`) to where it lives in this mode. */
  readonly href: (sellerHref: string) => string;
}

const SELLER_MODE: SellerViewMode = { readOnly: false, href: (h) => h };

const SellerViewContext = createContext<SellerViewMode>(SELLER_MODE);

export function SellerViewProvider({
  readOnly,
  href,
  children,
}: {
  readonly readOnly: boolean;
  readonly href?: (sellerHref: string) => string;
  readonly children: ReactNode;
}) {
  const value = useMemo<SellerViewMode>(() => ({ readOnly, href: href ?? SELLER_MODE.href }), [readOnly, href]);
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
 * Props for a control that writes (Phê duyệt, Lưu, an input of a rule…):
 * spread AFTER the control's own `disabled` / `title`. In read-only mode it is
 * disabled with the view-as title and `data-read-only` (greyed by
 * `globals.css`); otherwise it keeps its own `disabled`.
 */
export function writeControl(readOnly: boolean, disabled?: boolean, title?: string): WriteControlProps {
  if (readOnly) return { disabled: true, title: READ_ONLY_TITLE, "data-read-only": "" };
  return title === undefined ? { disabled } : { disabled, title };
}

/** Hook form of {@link writeControl}: `const write = useWriteControl(); <button {...write(busy)}>`. */
export function useWriteControl(): (disabled?: boolean, title?: string) => WriteControlProps {
  const readOnly = useReadOnly();
  return (disabled, title) => writeControl(readOnly, disabled, title);
}
