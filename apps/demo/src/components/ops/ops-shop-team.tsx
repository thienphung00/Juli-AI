"use client";

import { useState } from "react";

import type { OpsApi } from "../../lib/ops/api";
import type { Invite, ShopMember } from "../../lib/ops/types";
import { ConfirmDialog } from "./ops-confirm";
import { C, card } from "./ops-shell";

/**
 * "Thành viên shop" (P93): the people who may act on the shop, all with the same role.
 * Only Ops invites ("Mời thêm", one e-mail per link) and removes ("Gỡ", after an in-page
 * confirmation); a seller has neither button.
 */

export type TeamApi = Pick<OpsApi, "invite"> & Partial<Pick<OpsApi, "removeMember">>;

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("vi-VN") : "—");

export function OpsShopTeam({
  api,
  shopId,
  shopName,
  members,
  invites,
  canEdit,
  ownerText,
  onChanged,
}: {
  readonly api: TeamApi;
  readonly shopId: string;
  readonly shopName: string;
  readonly members: readonly ShopMember[];
  readonly invites: readonly Invite[];
  readonly canEdit: boolean;
  readonly ownerText: string;
  readonly onChanged: () => void;
}) {
  const [email, setEmail] = useState("");
  const [keep, setKeep] = useState(true);
  const [note, setNote] = useState<string | null>(null);
  const [removing, setRemoving] = useState<ShopMember | null>(null);
  const pending = invites.filter((i) => !i.accepted_at && !i.revoked_at);
  const send = async () => {
    setNote(null);
    try {
      const r = await api.invite(shopId, email, keep);
      setNote(r.email_sent ? "Đã gửi email mời." : `Chưa gửi được email. Gửi liên kết này cho người được mời: ${r.accept_url ?? ""}`);
      setEmail("");
      onChanged();
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Không mời được.");
    }
  };
  return (
    <div data-testid="ops-shop-team" style={card}>
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Thành viên shop</h2>
      <div style={{ fontSize: 13, color: C.body }}>{ownerText}</div>
      {members.length === 0 ? <span style={{ fontSize: 13, color: C.muted2 }}>Chưa có thành viên nào.</span> : null}
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
        {members.map((m) => (
          <li
            data-testid="ops-member-row"
            key={m.user_id}
            style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 8, alignItems: "center", fontSize: 14, borderTop: `1px solid ${C.lineSoft}`, paddingTop: 6 }}
          >
            <span style={{ overflowWrap: "anywhere" }}>
              <b>{m.email ?? "—"}</b>
              <br />
              <span style={{ fontSize: 12, color: C.muted2 }}>Tham gia {when(m.added_at)}</span>
            </span>
            {canEdit && api.removeMember ? (
              <button
                aria-label={`Gỡ ${m.email ?? "thành viên"}`}
                onClick={() => setRemoving(m)}
                style={{ font: "inherit", fontSize: 13, fontWeight: 600, color: C.red, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 10, minHeight: 40, padding: "0 12px", cursor: "pointer" }}
                type="button"
              >
                Gỡ
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {pending.map((i) => (
        <span data-testid="ops-pending-invite" key={i.id} style={{ fontSize: 12, color: C.muted }}>
          Đã gửi lời mời tới {i.email} · chờ đăng nhập và nhận shop.
        </span>
      ))}
      {canEdit ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: C.muted }}>
            Email của seller
            <input
              onChange={(e) => setEmail(e.target.value)}
              style={{ font: "inherit", fontSize: 14, border: `1px solid ${C.line}`, borderRadius: 8, minHeight: 40, padding: "0 10px" }}
              type="email"
              value={email}
            />
          </label>
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
            <input checked={keep} onChange={(e) => setKeep(e.target.checked)} style={{ width: 18, height: 18, accentColor: C.pinkStrong }} type="checkbox" />
            Hỏi seller cho đội ngũ giữ quyền Vận hành
          </label>
          <button
            disabled={!email.includes("@")}
            onClick={() => void send()}
            style={{ font: "inherit", fontSize: 14, fontWeight: 600, color: "#fff", background: C.pinkStrong, border: 0, borderRadius: 10, minHeight: 44, cursor: "pointer" }}
            type="button"
          >
            {members.length === 0 ? "Mời seller" : "Mời thêm"}
          </button>
        </div>
      ) : null}
      {note ? (
        <span role="status" style={{ fontSize: 13, wordBreak: "break-all" }}>
          {note}
        </span>
      ) : null}
      <span style={{ fontSize: 12, color: C.muted2 }}>
        Mọi thành viên có quyền như nhau; mỗi người đăng nhập bằng email của mình và thao tác được ghi theo người đó. Thẻ, lượt chạy, Quy tắc và lịch sử được giữ nguyên.
      </span>
      {removing && api.removeMember ? (
        <ConfirmDialog
          confirmLabel="Gỡ khỏi shop"
          note="Người này mất quyền vào shop ngay. Dữ liệu của shop và thao tác cũ của họ vẫn được giữ."
          onCancel={() => setRemoving(null)}
          onConfirm={async () => {
            await api.removeMember?.(shopId, removing.user_id);
            setRemoving(null);
            setNote(`Đã gỡ ${removing.email ?? "thành viên"}.`);
            onChanged();
          }}
          rows={[{ k: "Thành viên", before: removing.email ?? "—", after: "Đã gỡ" }]}
          title={`Gỡ ${removing.email ?? "thành viên"} khỏi ${shopName}?`}
        />
      ) : null}
    </div>
  );
}
