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
