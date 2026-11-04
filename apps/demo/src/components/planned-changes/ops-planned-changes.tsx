"use client";

import { useMemo } from "react";

import { createPlannedChangesApi, opsPlannedBase } from "../../lib/planned-changes/api";
import type { PlannedChangesApi } from "../../lib/planned-changes/types";
import { readAuthSession } from "../../lib/supabase-auth";
import { C, card } from "../ops/ops-shell";
import { PlannedChangesPanel } from "./planned-changes-panel";

/**
 * "Đề xuất kế hoạch" in Ops' Cài đặt shop (P91 D-13): the Juli team imports a Shopee shop's list of
 * planned or finished listing changes on its behalf. Vận hành+ uploads and applies (audited, the
 * shop's decision recorded as a document); Xem downloads the template and reads the versions.
 */
export function OpsPlannedChanges({
  shopId,
  canEdit,
  baseFetch,
  api,
}: {
  readonly shopId: string;
  readonly canEdit: boolean;
  readonly baseFetch?: typeof fetch;
  readonly api?: PlannedChangesApi;
}) {
  const client = useMemo(
    () => api ?? createPlannedChangesApi({ base: opsPlannedBase(shopId), token: readAuthSession()?.accessToken ?? "", fetchImpl: baseFetch }),
    [api, shopId, baseFetch],
  );
  return (
    <div data-testid="ops-planned-changes" style={card}>
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Đề xuất kế hoạch</h2>
      <span style={{ fontSize: 12, color: C.muted2 }}>
        Danh sách thay đổi tên, mô tả, ảnh bìa, phân loại, ẩn, nhập hàng lại từ tệp. Mỗi dòng hợp lệ thành một thẻ có mã JC; dòng đã hoàn thành được ghi vào đúng ngày; mỗi lần áp dụng là một phiên bản và được ghi nhật ký.
      </span>
      <PlannedChangesPanel api={client} canEdit={canEdit} />
    </div>
  );
}
