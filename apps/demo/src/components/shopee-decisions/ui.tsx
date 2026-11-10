"use client";

import Link from "next/link";
import { useState, type MouseEvent, type ReactNode } from "react";

import { refusalOf } from "../../lib/shopee-analytics/client";
import { notMaterializedLine, notMaterializedOf } from "../../lib/shopee-analytics/not-materialized";
import { useReco } from "../../lib/shopee-decisions/context";
import { statusLabel } from "../../lib/shopee-decisions/model";
import type { CardStatus } from "../../lib/shopee-decisions/types";
import type { Resource } from "../../lib/shopee-analytics/use-resource";
import { NotMaterializedNotice, TextChip } from "../shopee-analytics/ui";

/** Small pieces of the Shopee Quyết định screens (classes in `app/shopee-decisions.css`, `sa-*` from the analytics set). */

/** A link between two views of this host; follows the host's router when it has one. */
export function NavLink({ href, className, children, testId }: { readonly href: string; readonly className?: string; readonly children: ReactNode; readonly testId?: string }) {
  const { navigate } = useReco();
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!navigate || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(href);
  };
  return (
    <Link className={className} data-testid={testId} href={href} onClick={onClick}>
      {children}
    </Link>
  );
}

/** Copies `text` to the clipboard; the label says what, so the button reads alone. */
export function CopyButton({ text, label }: { readonly text: string; readonly label: string }) {
  const [done, setDone] = useState(false);
  const copy = () => {
    try {
      void navigator.clipboard?.writeText(text);
    } catch {
      /* the text is on screen; clipboard may be blocked */
    }
    setDone(true);
    window.setTimeout(() => setDone(false), 1500);
  };
  return (
    <button aria-label={`Sao chép ${label}`} className="sa-btn sa-btn--s sd-copy" onClick={copy} type="button">
      {done ? "Đã sao chép" : "Sao chép"}
    </button>
  );
}

export function StatusChip({ status }: { readonly status: CardStatus }) {
  const tone = status === "sent" || status === "changes_requested" ? "warn" : status === "approved" ? "info" : status === "executed" ? "info" : status === "draft" ? "pink" : "flat";
  return <TextChip tone={tone}>{statusLabel(status)}</TextChip>;
}

const COPY = {
  "not-shopee": { title: "Shop này không phải shop Shopee", body: "Đề xuất Shopee chỉ có cho shop Shopee. Shop TikTok dùng Quyết định như trước." },
  "no-data": { title: "Shop chưa có dữ liệu Shopee", body: "Khi có dữ liệu đầu tiên, đề xuất sẽ hiện ở đây." },
  "not-found": { title: "Không tìm thấy thẻ này", body: "Thẻ có thể đã được rút lại hoặc thay bằng thẻ mới. Quay lại danh sách để xem các thẻ hiện có." },
  invalid: { title: "Thông số không hợp lệ", body: "Kiểm tra lại giá trị vừa nhập." },
  "not-materialized": { title: "Số liệu kỳ này chưa sẵn sàng", body: "Juli chưa dựng xong số liệu theo ngày của kỳ này nên chưa hiện con số nào. Thử lại sau ít phút." },
  failed: { title: "Chưa tải được đề xuất", body: "Đã có lỗi khi đọc đề xuất. Thử tải lại trang; nếu vẫn lỗi, báo cho đội Juli." },
} as const;

/** The state of a resource that is not ready (card wording), or its content. */
export function RecoState<T>({ resource, children }: { readonly resource: Resource<T>; readonly children: (data: T) => ReactNode }) {
  if (resource.status === "loading") {
    return (
      <p className="sa-loading" role="status">
        Đang tải đề xuất…
      </p>
    );
  }
  if (resource.status === "refused") {
    if (resource.refusal === "not-materialized" && notMaterializedOf(resource.error)) return <NotMaterializedNotice error={resource.error} testId="sd-not-materialized" />;
    const copy = COPY[resource.refusal];
    return (
      <section className="sa-card" data-testid={`sd-refusal-${resource.refusal}`} role="alert">
        <h2 className="sa-h2">{copy.title}</h2>
        <p className="sa-hint">{copy.body}</p>
      </section>
    );
  }
  return <>{children(resource.data)}</>;
}

/** The sentence of a failed call. */
export function errorText(error: unknown): string {
  const nm = notMaterializedOf(error);
  if (nm) return notMaterializedLine(nm);
  const refusal = refusalOf(error);
  const message = error instanceof Error ? error.message : "";
  if (refusal === "failed" && !message) return "Chưa lưu được. Thử lại sau ít phút.";
  return message || COPY[refusal].body;
}
