"use client";

import { useEffect, useState } from "react";

import { useReco } from "../../lib/shopee-decisions/context";
import type { CardDetail, ExecutionSheet } from "../../lib/shopee-decisions/types";
import { readAuthSession } from "../../lib/supabase-auth";
import { TextChip } from "../shopee-analytics/ui";

/**
 * What the execution sheet of a LISTING card (P91 D-13) adds to the common one: the product's own edit
 * page, the changes that must run first, the cover image as a download, where the card came from (an
 * imported plan row), and - only when the server flag is on - "Điền bằng Connector". Juli never saves
 * for anyone: the Connector types the approved text into the page, a person reviews it and presses
 * Shopee's own Save.
 */

/** Change kinds the Connector opens a page for (it types only the title and the first description line). */
export const CONNECTOR_KINDS: ReadonlySet<string> = new Set([
  "title",
  "description_first_line",
  "cover_image",
  "variation_restructure",
  "listing_hide",
  "listing_relist",
]);

export const FILL_HASH_KEY = "juli-fill";

/** The page address that hands the card to the Connector: only the card's code travels in it. */
export function connectorFillHref(itemLink: string, code: string): string {
  return `${itemLink}#${FILL_HASH_KEY}=${code}`;
}

interface Planned {
  readonly ref?: string;
  readonly cost?: number | null;
  readonly window_days?: number | null;
  readonly decision_label?: string;
  readonly status_label?: string;
}

type DetailWithCode = CardDetail & { readonly code?: string | null };

/** Whether the server lets the Connector fill listing pages (`CONNECTOR_FILL_LISTING`); false until it answers. */
export function useConnectorFillFlag(active: boolean, fetchImpl?: typeof fetch): boolean {
  const { shopKey } = useReco();
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    if (!active) return;
    const token = readAuthSession()?.accessToken;
    const doFetch = fetchImpl ?? (typeof fetch === "function" ? fetch : null);
    if (!token || !doFetch) return;
    const ops = shopKey.startsWith("ops");
    let live = true;
    doFetch(ops ? "/v1/ops/connector-fill" : "/v1/demo/connector-fill", {
      headers: { Accept: "application/json", Authorization: `Bearer ${token}`, ...(ops ? {} : { "X-Shop-Id": shopKey }) },
      cache: "no-store",
    })
      .then((r) => (r.ok ? (r.json() as Promise<{ data?: { enabled?: boolean } }>) : null))
      .then((body) => live && setEnabled(body?.data?.enabled === true))
      .catch(() => live && setEnabled(false));
    return () => {
      live = false;
    };
  }, [active, shopKey, fetchImpl]);
  return enabled;
}

export function ListingSheetExtras({ detail, sheet, fetchImpl }: { readonly detail: DetailWithCode; readonly sheet: ExecutionSheet; readonly fetchImpl?: typeof fetch }) {
  const kind = detail.change_kind;
  const itemLink = sheet.page.item_deep_link ?? null;
  const code = detail.code ?? null;
  const planned = (detail.card as { readonly planned?: Planned }).planned;
  const eligible = CONNECTOR_KINDS.has(kind) && !!itemLink && !!code && detail.status === "approved";
  const fill = useConnectorFillFlag(eligible, fetchImpl);
  const dependencies = sheet.dependencies ?? [];
  const downloads = (sheet.downloads ?? []).filter((d) => d.url);
  if (!itemLink && dependencies.length === 0 && downloads.length === 0 && !planned) return null;
  return (
    <div className="sd-listing" data-testid="sd-listing-extras">
      {planned ? (
        <p className="sa-hint" data-testid="sd-planned">
          Từ tệp kế hoạch{planned.ref ? ` · mã ${planned.ref}` : ""}
          {planned.cost ? ` · chi phí ${planned.cost.toLocaleString("vi-VN")}đ` : ""}
          {planned.window_days ? ` · đo ${planned.window_days} ngày` : ""}
          {planned.decision_label ? ` · ${planned.decision_label}` : ""}
          {planned.status_label ? ` · ${planned.status_label}` : ""}
        </p>
      ) : null}
      {dependencies.map((d) => (
        <p className="sa-hint" data-testid="sd-dependency" key={d.ref}>
          {d.text}
          {d.code ? ` (${d.code})` : ""}
        </p>
      ))}
      {itemLink ? (
        <span className="sd-page" data-testid="sd-item-page">
          <a className="sa-btn sa-btn--s" href={itemLink} rel="noopener noreferrer" target="_blank">
            Mở trang sửa sản phẩm
          </a>
          {sheet.page.item_link_verified === false ? <TextChip tone="warn">đường dẫn chưa kiểm</TextChip> : null}
          {fill && code ? (
            <a className="sa-btn sa-btn--primary sa-btn--s" data-testid="sd-connector-fill" href={connectorFillHref(itemLink, code)} rel="noopener noreferrer" target="_blank">
              Điền bằng Connector
            </a>
          ) : null}
        </span>
      ) : null}
      {fill ? (
        <p className="sa-hint">Connector điền sẵn nội dung đã duyệt; bạn kiểm tra rồi bấm Lưu của chính Shopee. Juli không bấm Lưu thay bạn.</p>
      ) : null}
      {downloads.map((d) => (
        <a className="sa-btn sa-btn--s" data-testid="sd-download" download href={d.url as string} key={d.ref} rel="noopener noreferrer" target="_blank">
          {d.label}
        </a>
      ))}
    </div>
  );
}

// ── fill jobs (P97 D85.6): what the Connector opens, fills and captures after an approval ──

const SELLER_CENTRE = "https://banhang.shopee.vn";

export type FillJobStatus = "queued" | "opened" | "filled" | "saved" | "captured" | "failed" | "cancelled";

export interface FillJobRow {
  readonly id: string;
  readonly kind: string;
  readonly version: number;
  readonly group_code: string | null;
  readonly status: FillJobStatus;
  readonly target: Record<string, unknown>;
  readonly captured_ref: string | null;
  readonly error: string | null;
  readonly open_path: string | null;
}

/** Kinds the queue fills (migration 124); other cards have no checklist. */
export const FILL_JOB_KINDS: ReadonlySet<string> = new Set([
  "title",
  "description_first_line",
  "min_spend_voucher",
  "review_voucher",
  "ads_budget",
  "ads_roas_target",
  "affiliate_commission",
]);

const KIND_LABEL: Record<string, string> = {
  title: "Tên sản phẩm",
  description_first_line: "Dòng đầu của mô tả",
  voucher: "Tạo voucher",
  ads_edit: "Sửa quảng cáo",
  affiliate_commission: "Hoa hồng chiến dịch mở",
};

export const FILL_STATUS_LABEL: Record<FillJobStatus, string> = {
  queued: "Chờ mở trang",
  opened: "Đã mở trang",
  filled: "Đã điền, chờ bạn lưu",
  saved: "Đã lưu",
  captured: "Xong",
  failed: "Lỗi",
  cancelled: "Đã hủy",
};

const ERROR_TEXT: Record<string, string> = {
  budget_below_minimum: "Ngân sách thấp hơn mức tối thiểu ₫100.000 của Shopee nên Juli không điền.",
  budget_missing: "Thẻ chưa có ngân sách để điền.",
  roas_missing: "Thẻ chưa có mục tiêu ROAS hợp lệ để điền.",
  campaign_unknown: "Chưa biết mã chiến dịch quảng cáo; mở chiến dịch trên Seller Centre và làm theo bảng thao tác.",
  voucher_incomplete: "Voucher thiếu giá trị hoặc số lượng nên Juli không điền.",
  commission_incomplete: "Thiếu sản phẩm hoặc tỉ lệ hoa hồng nên Juli không điền.",
  text_not_fillable: "Nội dung quá dài hoặc có xuống dòng nên Juli không điền; dán bằng tay.",
  password_prompt: "Shopee đang hỏi lại mật khẩu: Connector đã dừng. Hãy tự xác nhận trong Shopee rồi thử lại.",
};

export function fillJobTitle(job: FillJobRow): string {
  const base = KIND_LABEL[job.kind] ?? job.kind;
  const ids = (job.target.product_ids as readonly string[] | undefined) ?? (job.target.item_id ? [String(job.target.item_id)] : []);
  const campaign = job.target.campaign_id ? ` · chiến dịch ${String(job.target.campaign_id)}` : "";
  const items = ids.length > 0 ? ` · ${ids.length === 1 ? `sản phẩm ${ids[0]}` : `${ids.length} sản phẩm`}` : "";
  const group = job.group_code ? ` · Nhóm ${job.group_code}` : "";
  return `${base}${items}${campaign}${group}${job.version > 1 ? ` · V${job.version}` : ""}`;
}

/** The page address that hands one job to the Connector: only the job's id travels in it. */
export function fillJobHref(job: Pick<FillJobRow, "id" | "open_path">): string | null {
  return job.open_path && job.open_path.startsWith("/") ? `${SELLER_CENTRE}${job.open_path}#${FILL_HASH_KEY}=${job.id}` : null;
}

/** The fill jobs of an approved card, refreshed while one is still open. Seller view only. */
export function useFillJobs(cardId: string, active: boolean, fetchImpl?: typeof fetch): { jobs: readonly FillJobRow[]; enabled: boolean } {
  const { shopKey } = useReco();
  const [state, setState] = useState<{ jobs: readonly FillJobRow[]; enabled: boolean }>({ jobs: [], enabled: false });
  useEffect(() => {
    if (!active || shopKey.startsWith("ops")) return;
    const token = readAuthSession()?.accessToken;
    const doFetch = fetchImpl ?? (typeof fetch === "function" ? fetch : null);
    if (!token || !doFetch) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = () =>
      doFetch(`/v1/demo/shopee/fill-jobs?card_id=${encodeURIComponent(cardId)}`, {
        headers: { Accept: "application/json", Authorization: `Bearer ${token}`, "X-Shop-Id": shopKey },
        cache: "no-store",
      })
        .then((r) => (r.ok ? (r.json() as Promise<{ data?: { enabled?: boolean; jobs?: FillJobRow[] } }>) : null))
        .then((body) => {
          if (!live) return;
          const jobs = Array.isArray(body?.data?.jobs) ? body.data.jobs : [];
          setState({ jobs, enabled: body?.data?.enabled === true });
          if (jobs.some((j) => j.status === "queued" || j.status === "opened" || j.status === "filled" || j.status === "saved")) {
            timer = setTimeout(load, 15_000);
          }
        })
        .catch(() => live && setState({ jobs: [], enabled: false }));
    void load();
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [active, cardId, shopKey, fetchImpl]);
  return state;
}

/** The voucher id the Connector captured after the person saved, so nothing has to be typed. */
export function capturedVoucherId(jobs: readonly FillJobRow[]): string | null {
  return jobs.find((j) => j.kind === "voucher" && j.captured_ref)?.captured_ref ?? null;
}

/**
 * The checklist of an approved card's fill jobs: one row per page, its status, a button that opens
 * the page for the Connector, and the id it captured. Juli never saves: the person presses Shopee's
 * own Lưu / Xác nhận on each page.
 */
export function FillJobsChecklist({ jobs, enabled }: { readonly jobs: readonly FillJobRow[]; readonly enabled: boolean }) {
  if (!enabled || jobs.length === 0) return null;
  const done = jobs.filter((j) => j.status === "captured" || j.status === "saved").length;
  return (
    <div className="sd-fill" data-testid="sd-fill-jobs">
      <h3 className="sa-h3">Connector điền sẵn</h3>
      <p className="sa-hint" data-testid="sd-fill-count">
        {done}/{jobs.length} trang đã xong. Connector mở và điền từng trang một; bạn kiểm tra rồi bấm Lưu / Xác nhận của chính Shopee. Juli không bấm thay bạn.
      </p>
      <ul className="sd-fill__list">
        {jobs.map((job) => {
          const href = job.status === "queued" || job.status === "opened" || job.status === "filled" ? fillJobHref(job) : null;
          return (
            <li data-testid={`sd-fill-job-${job.id}`} data-status={job.status} key={job.id}>
              <span>{fillJobTitle(job)}</span> <TextChip tone={job.status === "failed" ? "warn" : job.status === "captured" ? "pink" : "info"}>{FILL_STATUS_LABEL[job.status]}</TextChip>
              {href ? (
                <a className="sa-btn sa-btn--s" data-testid="sd-fill-open" href={href} rel="noopener noreferrer" target="_blank">
                  Mở trang để điền
                </a>
              ) : null}
              {job.captured_ref ? (
                <span className="sa-hint" data-testid="sd-fill-captured">
                  {job.kind === "voucher" ? "Mã voucher" : "Mã"}: {job.captured_ref}
                </span>
              ) : null}
              {job.error ? (
                <span className="sd-error" data-testid="sd-fill-error">
                  {ERROR_TEXT[job.error] ?? "Connector không điền được trang này; làm theo bảng thao tác."}
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
