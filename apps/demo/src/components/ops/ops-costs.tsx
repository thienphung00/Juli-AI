"use client";

import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { opsApi, type OpsApi } from "../../lib/ops/api";
import { fmtPctWhole, fmtUsd2 } from "../../lib/ops/format";
import type { CostsPage, OpsMe, ShopCost, ShopCostState } from "../../lib/ops/types";
import { publishCostSystem } from "./ops-cost-banner";
import { ConfirmDialog, Toast } from "./ops-confirm";
import { C, OpsHeader, OpsPage, card } from "./ops-shell";

/**
 * Tab "Chi phí" (D28.3, artboard OpsOpenAICap.dc.html): the month's OpenAI spend
 * of the whole system against the system cap (bar with the 80 % marker), and
 * each shop's spend against its own cap ("· riêng" when set for that shop).
 * Admins change either cap through a confirm dialog (one audit row each).
 */

type Api = Pick<OpsApi, "costs" | "putSystemCap" | "putShopCap">;

export const SYSTEM_CHOICES = [30, 50, 80, 120] as const;
export const SHOP_CHOICES = [5, 10, 20, 50] as const;

const STATE_TEXT: Record<ShopCostState, string> = {
  ok: "Bình thường",
  shop_cap: "Dừng (riêng)",
  system_cap: "Dừng (hệ thống)",
};

const GRID = "minmax(0, 1fr) 110px 150px 130px 70px";

function tone(level: number | null, reached: boolean): { text: string; bar: string } {
  if (reached || level === 100) return { text: C.red, bar: "#a3222f" };
  if (level === 80) return { text: "#c96a00", bar: "#e0a100" };
  return { text: C.green, bar: "#2f9e5b" };
}

type Edit = { kind: "system" } | { kind: "shop"; shop: ShopCost };

function CapDialog({
  edit,
  current,
  onCancel,
  onSave,
}: {
  readonly edit: Edit;
  readonly current: number;
  readonly onCancel: () => void;
  readonly onSave: (usd: number) => Promise<void>;
}) {
  const choices: readonly number[] = edit.kind === "system" ? SYSTEM_CHOICES : SHOP_CHOICES;
  const [next, setNext] = useState<number>(current);
  const title = edit.kind === "system" ? "Sửa giới hạn OpenAI cả hệ thống?" : `Sửa giới hạn riêng của ${edit.shop.shop_name}?`;
  return (
    <ConfirmDialog
      confirmDisabled={next === current}
      confirmLabel="Xác nhận lưu"
      note="Áp dụng ngay cho lượt soạn mới. Nhật ký ghi 1 dòng."
      onCancel={onCancel}
      onConfirm={() => onSave(next)}
      rows={[{ k: edit.kind === "system" ? "Giới hạn hệ thống / tháng" : "Giới hạn shop / tháng", before: fmtUsd2(current), after: fmtUsd2(next) }]}
      title={title}
    >
      <div role="group" aria-label="Mức giới hạn" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {choices.map((v) => (
          <button
            aria-pressed={next === v}
            key={v}
            onClick={() => setNext(v)}
            style={{
              font: "inherit",
              fontSize: 14,
              fontWeight: 600,
              borderRadius: 10,
              minHeight: 40,
              padding: "0 14px",
              cursor: "pointer",
              ...(next === v ? { color: "#ffffff", background: C.ink, border: `1px solid ${C.ink}` } : { color: C.ink, background: "#ffffff", border: `1px solid ${C.line}` }),
            }}
            type="button"
          >
            ${v}
          </button>
        ))}
      </div>
    </ConfirmDialog>
  );
}

const EDIT_BUTTON: CSSProperties = {
  font: "inherit",
  fontSize: 13,
  fontWeight: 600,
  color: C.pink,
  background: "transparent",
  border: "1px solid #f3cfdf",
  borderRadius: 8,
  minHeight: 34,
  cursor: "pointer",
};

export function OpsCosts({ me, api = opsApi }: { readonly me: OpsMe; readonly api?: Api }) {
  const [page, setPage] = useState<CostsPage | null>(null);
  const [failed, setFailed] = useState(false);
  const [edit, setEdit] = useState<Edit | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const isAdmin = me.role === "admin";

  const load = useCallback(() => {
    api
      .costs()
      .then((p) => {
        setPage(p);
        publishCostSystem(p.system);
      })
      .catch(() => setFailed(true));
  }, [api]);

  useEffect(() => {
    load();
  }, [load]);

  const system = page?.system;
  const colours = system ? tone(system.level, system.reached) : tone(null, false);
  const month = system ? Number(system.month.split("-")[1]) : null;

  return (
    <OpsPage>
      <OpsHeader active="costs" me={me} />
      <h1 style={{ margin: "22px 28px 0", fontSize: 24, fontWeight: 700 }}>Chi phí</h1>
      {failed ? (
        <p role="alert" style={{ margin: "12px 28px" }}>
          Không tải được chi phí OpenAI.
        </p>
      ) : null}
      {!page && !failed ? (
        <p role="status" style={{ margin: "12px 28px" }}>
          Đang tải…
        </p>
      ) : null}
      {page && system ? (
        <main className="ops-sim" style={{ padding: "16px 28px 22px", display: "grid", gridTemplateColumns: "minmax(0, 1fr) 420px", gap: 20, alignItems: "start" }}>
          <section style={{ ...card, padding: "18px 20px", gap: 14, minWidth: 0, overflowX: "auto" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Chi phí OpenAI · tháng {month}</h2>
              <span style={{ fontSize: 13, color: C.muted }}>còn {page.days_left_in_month} ngày</span>
              {isAdmin ? (
                <button
                  onClick={() => setEdit({ kind: "system" })}
                  style={{ ...EDIT_BUTTON, marginLeft: "auto", fontSize: 14, borderRadius: 10, minHeight: 40, padding: "0 14px" }}
                  type="button"
                >
                  Sửa giới hạn
                </button>
              ) : null}
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
              <b data-testid="cost-used" style={{ fontSize: 32 }}>
                {fmtUsd2(system.used_usd)}
              </b>
              <span style={{ fontSize: 16, color: C.body }}>/ {fmtUsd2(system.cap_usd)} giới hạn cả hệ thống</span>
              <b data-testid="cost-pct" style={{ marginLeft: "auto", fontSize: 18, color: colours.text }}>
                {fmtPctWhole(system.pct)}
              </b>
            </div>
            <div
              aria-label={`Đã dùng ${fmtPctWhole(system.pct)} giới hạn`}
              aria-valuemax={100}
              aria-valuemin={0}
              aria-valuenow={Math.round(system.pct * 100)}
              role="progressbar"
              style={{ position: "relative", height: 14, background: C.lineSoft, borderRadius: 999 }}
            >
              <div data-testid="cost-bar" style={{ position: "absolute", left: 0, top: 0, bottom: 0, borderRadius: 999, width: `${Math.min(100, system.pct * 100)}%`, background: colours.bar }} />
              <div title="Cảnh báo 80 %" style={{ position: "absolute", left: `${page.warn_pct * 100}%`, top: -4, bottom: -4, width: 2, background: "#c96a00" }} />
            </div>
            <div style={{ display: "flex", gap: 18, fontSize: 12, color: C.muted, flexWrap: "wrap" }}>
              <span>80 %: báo trên Ops + email Admin</span>
              <span>100 %: dừng soạn nội dung mới cho mọi shop · thẻ đề xuất vẫn tạo</span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: GRID, gap: 10, fontSize: 12, fontWeight: 600, color: C.muted, borderTop: `1px solid ${C.lineSoft}`, paddingTop: 12, minWidth: 600 }}>
              <span>Shop</span>
              <span>Đã dùng</span>
              <span>Giới hạn riêng</span>
              <span>Trạng thái</span>
              <span />
            </div>
            {page.shops.map((s) => (
              <div
                data-testid="cost-row"
                key={s.shop_id}
                style={{ display: "grid", gridTemplateColumns: GRID, gap: 10, fontSize: 14, borderTop: "1px solid #f7f7f9", paddingTop: 8, alignItems: "center", minWidth: 600 }}
              >
                <b>{s.shop_name}</b>
                <span>{fmtUsd2(s.used_usd)}</span>
                <span data-custom={s.is_custom ? "true" : "false"} style={s.is_custom ? { fontWeight: 700, color: C.pink } : undefined}>
                  {fmtUsd2(s.cap_usd)} / tháng{s.is_custom ? " · riêng" : ""}
                </span>
                <span style={{ fontSize: 12, fontWeight: 600, color: s.state === "ok" ? C.green : C.red }}>{STATE_TEXT[s.state]}</span>
                {isAdmin ? (
                  <button aria-label={`Sửa giới hạn ${s.shop_name}`} onClick={() => setEdit({ kind: "shop", shop: s })} style={EDIT_BUTTON} type="button">
                    Sửa
                  </button>
                ) : (
                  <span />
                )}
              </div>
            ))}
            {page.shops.length === 0 ? <span style={{ fontSize: 14, color: C.muted }}>Chưa có shop nào.</span> : null}
          </section>

          <aside style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ ...card, gap: 8 }}>
              <b style={{ fontSize: 14 }}>Seller thấy</b>
              <div
                data-testid="cost-seller-sees"
                style={{ borderRadius: 10, padding: "10px 12px", fontSize: 13, ...(system.reached ? { color: "#5c3a00", background: "#fff4e0" } : { color: C.body, background: "#f7f7f9" }) }}
              >
                {system.reached ? page.seller_paused_text : "Không thấy gì khác."}
              </div>
            </div>
            <div style={{ ...card, gap: 6, fontSize: 13, color: C.body }}>
              <b style={{ fontSize: 14, color: C.ink }}>Giới hạn</b>
              <span>
                Cả hệ thống: {fmtUsd2(system.cap_usd)} / tháng{system.cap_is_default ? " (mặc định)" : system.cap_updated_by ? ` · ${system.cap_updated_by.split("@")[0]}` : ""}
              </span>
              <span>Mỗi shop mặc định: {fmtUsd2(page.default_shop_cap_usd)} / tháng</span>
              <span style={{ color: C.muted }}>Tháng tính theo giờ Việt Nam (UTC+7).</span>
            </div>
          </aside>
        </main>
      ) : null}
      {edit && page ? (
        <CapDialog
          current={edit.kind === "system" ? page.system.cap_usd : edit.shop.cap_usd}
          edit={edit}
          key={edit.kind === "system" ? "system" : edit.shop.shop_id}
          onCancel={() => setEdit(null)}
          onSave={async (usd) => {
            if (edit.kind === "system") await api.putSystemCap(usd);
            else await api.putShopCap(edit.shop.shop_id, usd);
            setEdit(null);
            setToast("Đã lưu giới hạn · ghi 1 dòng nhật ký");
            load();
          }}
        />
      ) : null}
      {toast ? <Toast onDone={() => setToast(null)} text={toast} /> : null}
    </OpsPage>
  );
}
