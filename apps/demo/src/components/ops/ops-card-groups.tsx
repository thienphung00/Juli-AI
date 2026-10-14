"use client";

import { useEffect, useState } from "react";

import type { OpsApi } from "../../lib/ops/api";
import { fmtDate } from "../../lib/ops/format";
import type { CardGroup, CardGroupComparison, CardGroupsPage } from "../../lib/ops/types";
import { C, card } from "./ops-shell";

/**
 * P30 (D34 / D39.3): "Nhóm thử nghiệm" — the shop's card groups (metric × lever × channel),
 * each with its random delayed control: members and arms, launch and release days, the
 * seed, and the day-14 verdict with its interval (by assignment; approved-only below).
 */

const ARM_LABEL: Record<string, string> = { treated: "Áp dụng", control: "Đối chứng" };
const STATUS_LABEL: Record<string, string> = { open: "Đang chạy", measured: "Đã đo" };

const num = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(1).replace(".", ",")}`;

/** "+7,0 điểm % (khoảng +2,1 → +11,8) · Thay đổi rõ · Sơ bộ" or the label alone. */
export function comparisonText(c: CardGroupComparison | null | undefined): string {
  if (!c) return "—";
  if (c.difference === null || c.interval === null) return `${c.label ?? "Chưa đủ cơ sở"} (${c.n_treated} áp dụng · ${c.n_control} đối chứng)`;
  const parts = [`${num(c.difference)} điểm % (khoảng ${num(c.interval[0])} → ${num(c.interval[1])})`];
  if (c.strength_label) parts.push(c.strength_label);
  if (c.label) parts.push(c.label);
  if (c.false_alarm) parts.push(`báo động giả ${Math.round(c.false_alarm.rate * 100)} %`);
  parts.push(`${c.n_treated} áp dụng · ${c.n_control} đối chứng`);
  return parts.join(" · ");
}

function GroupRow({ group }: { readonly group: CardGroup }) {
  const [open, setOpen] = useState(false);
  return (
    <div data-testid="ops-group" style={{ borderTop: `1px solid ${C.lineSoft}`, paddingTop: 10, display: "flex", flexDirection: "column", gap: 6, fontSize: 13 }}>
      <button
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        style={{ font: "inherit", display: "flex", gap: 8, alignItems: "baseline", background: "transparent", border: 0, padding: 0, cursor: "pointer", textAlign: "left", color: C.ink }}
        type="button"
      >
        <b>{group.label}</b>
        <span style={{ color: C.muted2 }}>
          {STATUS_LABEL[group.status] ?? group.status} · bắt đầu {fmtDate(group.launched_on)} · trả thẻ đối chứng {fmtDate(group.release_on)}
        </span>
        <span style={{ marginLeft: "auto", color: C.muted2 }}>
          {group.treated} áp dụng · {group.control} đối chứng
        </span>
      </button>
      <div>
        Kết quả ngày 14: <b>{group.verdict ? comparisonText(group.verdict.primary) : "chưa đo"}</b>
      </div>
      {group.verdict ? <div style={{ color: C.muted2 }}>Chỉ thẻ đã duyệt: {comparisonText(group.verdict.approved_only)}</div> : null}
      {group.seller_sentence ? <div style={{ color: C.body }}>Người bán thấy: “{group.seller_sentence}”</div> : null}
      {open ? (
        <table style={{ borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ textAlign: "left", color: C.muted2 }}>
              <th>Sản phẩm</th>
              <th>Nhóm</th>
              <th>Thẻ</th>
              <th>Thay đổi</th>
            </tr>
          </thead>
          <tbody>
            {group.members.map((m) => {
              const measured = group.verdict?.products.find((p) => p.product_id === m.product_id);
              return (
                <tr key={m.product_id}>
                  <td>{m.product_title ?? m.product_id}</td>
                  <td>{ARM_LABEL[m.arm] ?? m.arm}</td>
                  <td>
                    {m.arm === "control" ? (m.released_at ? "đã trả thẻ" : "đang giữ") : m.surfaced_at ? "đã hiện" : "chờ hiện"}
                    {m.approved ? " · đã duyệt" : ""}
                  </td>
                  <td>{measured && measured.change_pct !== null ? `${num(measured.change_pct)} %` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}
      <div style={{ color: C.muted2, fontSize: 11 }}>Seed {group.seed}</div>
    </div>
  );
}

export function OpsCardGroups({ shopId, load }: { readonly shopId: string; readonly load?: OpsApi["groups"] }) {
  const [page, setPage] = useState<CardGroupsPage | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!load) return;
    let alive = true;
    load(shopId)
      .then((p) => alive && setPage(p))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [load, shopId]);
  if (!load || (!page && !failed)) return null;
  return (
    <div data-testid="ops-groups" style={card}>
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Nhóm thử nghiệm (đối chứng chậm)</h2>
      {failed ? <span style={{ color: C.red, fontSize: 13 }}>Không tải được nhóm thử nghiệm.</span> : null}
      {page && !page.enabled ? <span style={{ color: C.muted2, fontSize: 13 }}>Đang tắt cho shop này.</span> : null}
      {page && page.groups.length === 0 ? <span style={{ color: C.muted2, fontSize: 13 }}>Chưa có nhóm nào.</span> : null}
      {page?.groups.map((g) => <GroupRow group={g} key={g.id} />)}
    </div>
  );
}
