"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { opsApi, type OpsApi } from "../../lib/ops/api";
import type { OpsMe, Overview } from "../../lib/ops/types";
import { C, OpsHeader, OpsPage } from "./ops-shell";

/**
 * Top-level "Mô phỏng" tab (owner, 2026-10-11): pick a shop, then open its
 * 4 KPI × 4 stream simulation (`/ops/shops/{id}/mo-phong`).
 */
export function OpsSimulatePicker({ me, api = opsApi }: { readonly me: OpsMe; readonly api?: Pick<OpsApi, "overview"> }) {
  const [data, setData] = useState<Overview | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    api
      .overview()
      .then((d) => live && setData(d))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [api]);

  const shops = (data?.shops ?? []).filter((s) => s.connection !== "none");
  return (
    <OpsPage>
      <OpsHeader me={me} active="simulate" />
      <main style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 16 }}>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 700 }}>Mô phỏng · chọn gian hàng</h1>
        {failed ? <p role="alert">Không tải được danh sách gian hàng. Thử lại sau.</p> : null}
        {!data && !failed ? <p role="status">Đang tải…</p> : null}
        {data && shops.length === 0 ? <p>Chưa có gian hàng nào kết nối.</p> : null}
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 10, maxWidth: 720 }}>
          {shops.map((s) => (
            <li key={s.shop_id}>
              <Link
                data-testid="simulate-shop-link"
                href={`/ops/shops/${s.shop_id}/mo-phong`}
                style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, background: "#ffffff", border: `1px solid ${C.line}`, borderRadius: 12, padding: "12px 16px", minHeight: 44, color: C.ink, textDecoration: "none" }}
              >
                <b>{s.shop_name}</b>
                <span style={{ color: C.pink, fontWeight: 600 }}>Mô phỏng ›</span>
              </Link>
            </li>
          ))}
        </ul>
      </main>
    </OpsPage>
  );
}
