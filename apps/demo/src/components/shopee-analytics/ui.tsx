"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { DASH, pp, vnd, type Chip, type Tone } from "../../lib/shopee-analytics/format";
import type { ApiRefusal } from "../../lib/shopee-analytics/client";
import { notMaterializedOf } from "../../lib/shopee-analytics/not-materialized";
import type { Resource } from "../../lib/shopee-analytics/use-resource";

/** Small pieces every Shopee shop screen uses (classes in `app/shopee-analytics.css`). */

export function toneClass(tone: Tone): string {
  return `sa-tone--${tone}`;
}

export function ChipView({ chip, invert = false, testId }: { readonly chip: Chip; readonly invert?: boolean; readonly testId?: string }) {
  const tone: Tone = chip.up === null ? "flat" : chip.up !== invert ? "up" : "down";
  return (
    <span className={`sa-chip sa-chip--${tone}`} data-testid={testId}>
      {chip.text}
    </span>
  );
}

export function TextChip({ tone, children }: { readonly tone: Tone | "warn" | "pink" | "info"; readonly children: ReactNode }) {
  return <span className={`sa-chip sa-chip--${tone}`}>{children}</span>;
}

export function Section({
  title,
  hint,
  aside,
  children,
  testId,
}: {
  readonly title: string;
  readonly hint?: ReactNode;
  readonly aside?: ReactNode;
  readonly children: ReactNode;
  readonly testId?: string;
}) {
  return (
    <section className="sa-card" data-testid={testId}>
      <div className="sa-card__head">
        <h2 className="sa-h2">{title}</h2>
        {hint ? <span className="sa-hint">{hint}</span> : null}
        {aside ? <span className="sa-card__aside">{aside}</span> : null}
      </div>
      {children}
    </section>
  );
}

export function Eyebrow({ children }: { readonly children: string }) {
  return <div className="sa-eyebrow">{children}</div>;
}

export function PageHead({
  eyebrow,
  title,
  chips,
  info,
  right,
}: {
  readonly eyebrow: string;
  readonly title: string;
  readonly chips?: ReactNode;
  readonly info?: ReactNode;
  readonly right?: ReactNode;
}) {
  return (
    <header className="sa-head">
      <Eyebrow>{eyebrow}</Eyebrow>
      <div className="sa-head__line">
        <h1 className="sa-h1">{title}</h1>
        {chips}
        {info}
        {right ? <span className="sa-head__right">{right}</span> : null}
      </div>
    </header>
  );
}

export function InfoToggle({ children }: { readonly children: ReactNode }) {
  return (
    <details className="sa-info">
      <summary aria-label="Cách tính">i</summary>
      <div className="sa-info__body">{children}</div>
    </details>
  );
}

export function Notice({ tone = "warn", children, testId }: { readonly tone?: "warn" | "info"; readonly children: ReactNode; readonly testId?: string }) {
  return (
    <div className={`sa-notice sa-notice--${tone}`} data-testid={testId} role="status">
      {children}
    </div>
  );
}

export function Empty({ children, testId }: { readonly children: ReactNode; readonly testId?: string }) {
  return (
    <div className="sa-empty" data-testid={testId}>
      {children}
    </div>
  );
}

export function Bar({ pct, tone = "neutral" }: { readonly pct: number | null; readonly tone?: "neutral" | "green" | "red" | "pink" }) {
  const w = pct === null || !Number.isFinite(pct) ? 0 : Math.max(0, Math.min(100, pct));
  return (
    <span className="sa-bar" aria-hidden="true">
      <span className={`sa-bar__fill sa-bar__fill--${tone}`} style={{ width: `${w}%` }} />
    </span>
  );
}

export function Ini({ text }: { readonly text: string }) {
  return <span className="sa-ini">{text}</span>;
}

export function initialsOf(name: string | null | undefined): string {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return DASH;
  return words
    .slice(0, 2)
    .map((w) => Array.from(w)[0] ?? "")
    .join("")
    .toLocaleUpperCase("vi-VN");
}

export function PillLink({ href, active, children, label }: { readonly href: string; readonly active: boolean; readonly children: ReactNode; readonly label?: string }) {
  return (
    <Link aria-current={active ? "true" : undefined} aria-label={label} className={`sa-pill${active ? " sa-pill--on" : ""}`} href={href}>
      {children}
    </Link>
  );
}

const REFUSAL_COPY: Record<ApiRefusal, { title: string; body: string }> = {
  "not-shopee": {
    title: "Shop này không phải shop Shopee",
    body: "Màn hình này dành cho shop Shopee. Shop TikTok dùng Trang chủ và Phân tích như trước.",
  },
  "no-data": {
    title: "Shop chưa có dữ liệu Shopee",
    body: "Khi Juli Connector hoặc tệp báo cáo đầu tiên được tải lên, số liệu sẽ hiện ở đây.",
  },
  "not-found": {
    title: "Không tìm thấy sản phẩm này",
    body: "Mã sản phẩm không có trong dữ liệu của shop. Quay lại danh sách Sản phẩm để chọn lại.",
  },
  invalid: {
    title: "Kỳ xem không hợp lệ",
    body: "Chọn lại khoảng thời gian (ngày kết thúc phải sau ngày bắt đầu).",
  },
  "not-materialized": {
    title: "Số liệu kỳ này chưa sẵn sàng",
    body: "Juli chưa dựng xong số liệu theo ngày của kỳ này nên chưa hiện con số nào. Thử lại sau ít phút.",
  },
  failed: {
    title: "Chưa tải được số liệu",
    body: "Đã có lỗi khi đọc số liệu. Thử tải lại trang; nếu vẫn lỗi, báo cho đội Juli.",
  },
};

/**
 * P99b: HTTP 409 `rows_not_materialized`. The message, the window and the missing days; no figures, and
 * nothing cached from an earlier answer (the resource that refused holds no data).
 */
export function NotMaterializedNotice({ error, testId = "sa-not-materialized" }: { readonly error: unknown; readonly testId?: string }) {
  const n = notMaterializedOf(error);
  if (!n) return null;
  return (
    <section className="sa-card" data-testid={testId} role="alert">
      <h2 className="sa-h2">Số liệu kỳ này chưa sẵn sàng</h2>
      <p className="sa-hint" data-testid="sa-nm-message">{n.message}</p>
      <p className="sa-hint" data-testid="sa-nm-detail">
        {n.window ? `Kỳ ${n.window}` : "Chưa rõ kỳ"}
        {n.missingDays !== null ? ` · thiếu số liệu ${n.missingDays} ngày${n.firstMissing ? `, từ ${n.firstMissing.slice(8, 10)}/${n.firstMissing.slice(5, 7)}` : ""}` : ""}
      </p>
    </section>
  );
}

/** The state of a resource that is not ready, or `null` when it is. */
export function ResourceState<T>({ resource, children }: { readonly resource: Resource<T>; readonly children: (data: T) => ReactNode }) {
  if (resource.status === "loading") {
    return (
      <p className="sa-loading" role="status">
        Đang tải số liệu…
      </p>
    );
  }
  if (resource.status === "refused") {
    if (resource.refusal === "not-materialized" && notMaterializedOf(resource.error)) return <NotMaterializedNotice error={resource.error} />;
    const copy = REFUSAL_COPY[resource.refusal];
    return (
      <section className="sa-card" data-testid={`sa-refusal-${resource.refusal}`} role="alert">
        <h2 className="sa-h2">{copy.title}</h2>
        <p className="sa-hint">{copy.body}</p>
      </section>
    );
  }
  return <>{children(resource.data)}</>;
}

/** P92 B-9: "giá" (selling price min-max, list price struck through when different) and "biên" with its basis label. */
export function priceText(p: { readonly price_min?: number | null; readonly price_max?: number | null }): string {
  const lo = p.price_min ?? null;
  const hi = p.price_max ?? null;
  if (lo === null && hi === null) return DASH;
  return lo !== null && hi !== null && Math.round(lo) !== Math.round(hi) ? `${vnd(lo)} – ${vnd(hi)}` : vnd(lo ?? hi);
}

export function PriceMargin({ p, margin }: { readonly p: { readonly price_min?: number | null; readonly price_max?: number | null; readonly list_price?: number | null; readonly margin_basis?: string }; readonly margin?: number | null }) {
  const struck = p.list_price != null && p.price_max != null && Math.round(p.list_price) > Math.round(p.price_max);
  const basis = p.margin_basis ?? "chưa tính";
  return (
    <span className="sa-pm" data-testid="sa-price-margin">
      <span className="sa-pm__price">
        <span className="sa-fcell__label">Giá</span>
        <b>{priceText(p)}</b>
        {struck ? <s className="sa-hint">{vnd(p.list_price)}</s> : null}
      </span>
      <span className="sa-pm__margin">
        <span className="sa-fcell__label">Biên</span>
        <b>{basis === "chưa tính" || margin == null ? "chưa tính" : pp(margin, 1)}</b>
        {basis === "ước tính" ? null : <span className="sa-hint">{basis}</span>}
      </span>
    </span>
  );
}
