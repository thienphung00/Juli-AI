"use client";

import { useMemo, type ReactNode } from "react";

import { DEMO_PLANNED_BASE, createPlannedChangesApi } from "../../lib/planned-changes/api";
import type { PlannedChangesApi } from "../../lib/planned-changes/types";
import { AppPageHeader } from "../app-shell/page-header";
import { PlannedChangesPanel } from "./planned-changes-panel";

export const PLANNED_CHANGES_TAB_LABEL = "Đề xuất kế hoạch";

/** /settings › Đề xuất kế hoạch (P91 D-13): the shop's own list of listing changes, imported from a file. */
export function PlannedChangesSettings({
  auth,
  shopName,
  tabs,
  api,
}: {
  readonly auth: { readonly token: string; readonly shopId: string; readonly fetchImpl?: typeof fetch };
  readonly shopName: string;
  readonly tabs?: ReactNode;
  /** Tests inject a fake; the page builds the real client. */
  readonly api?: PlannedChangesApi;
}) {
  const client = useMemo(
    () => api ?? createPlannedChangesApi({ base: DEMO_PLANNED_BASE, token: auth.token, shopId: auth.shopId, fetchImpl: auth.fetchImpl }),
    [api, auth.token, auth.shopId, auth.fetchImpl],
  );
  return (
    <section aria-labelledby="planned-changes-title" className="qd-page">
      <AppPageHeader
        eyebrow="Cài đặt"
        lede={
          <>
            Các thay đổi tên, mô tả, ảnh bìa, phân loại của <strong>{shopName}</strong> bạn đã lên kế hoạch hoặc đã làm. Nhập từ tệp để Juli theo dõi và đo kết quả.
          </>
        }
        title="Đề xuất kế hoạch"
        titleId="planned-changes-title"
      />
      {tabs}
      <PlannedChangesPanel api={client} />
    </section>
  );
}
