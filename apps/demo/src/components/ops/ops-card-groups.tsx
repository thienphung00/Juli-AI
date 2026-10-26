"use client";

import { useEffect, useState } from "react";

import { OpsApiError, type OpsApi } from "../../lib/ops/api";
import { fmtDate, fmtGmvShort } from "../../lib/ops/format";
import type { CardGroup, CardGroupComparison, CardGroupCreate, CardGroupEb, CardGroupPlan, CardGroupsPage } from "../../lib/ops/types";
import { C, card } from "./ops-shell";

/**
 * P30 (D34 / D39.3): "Nhóm thử nghiệm" — the shop's card groups (metric × lever × channel),
 * each with its random delayed control: members and arms, launch and release days, the
 * seed, and the day-14 verdict with its interval (by assignment; approved-only below).
 *
 * P36 (D45, Ops only): Ops can make a group itself ("Tạo nhóm thử nghiệm", e.g. "Quy cách
 * mới" read on AOV with the product-card CTR as a guard); every group shows its weekly-drift
 * floor next to the traffic needed, all-channel AOV / items per order, the CTR guard warning,
 * and an editable one-line "lý do chọn thử nghiệm". The seller never sees an Ops group.
 *
 * P45 (D52, Ops only): beside each raw result, "Lift đã co (EB)" — the lift shrunk toward
 * groups of the same lever type (a winner's-curse guard), with the prior it used. The
 * seller's sentence and the verdict label do not change.
 *
 * D76 / D11 (ADR-116 §3): only shops that opted into pooling ("pooled_training") feed the
 * prior; a shop that did not reads "chỉ dữ liệu của shop này" and borrows no other shop's groups.
 *
 * P46 (D55.1, Ops only): TikTok's GMV includes cancelled and refunded orders. When the shop's
 * orders cover the days read, AOV / items per order are read net ("đã trừ huỷ/hoàn") with the
 * TikTok-GMV reading beside them ("gồm huỷ/hoàn"); otherwise the label says the numbers include
 * them. The plan line shows "Doanh thu (đã trừ huỷ/hoàn)" next to "GMV TikTok (gồm huỷ/hoàn)".
 */

const ARM_LABEL: Record<string, string> = { treated: "Áp dụng", control: "Đối chứng" };
const STRATUM_LABEL: Record<string, string> = { high: "nhiều đơn", low: "ít đơn" };
const STATUS_LABEL: Record<string, string> = { open: "Đang chạy", measured: "Đã đo" };
const METHOD_LABEL: Record<string, string> = {
  change: "thay đổi thường (nhóm nhỏ)",
  one_window: "điều chỉnh theo một cửa sổ tiền kỳ",
  two_windows: "điều chỉnh theo hai cửa sổ tiền kỳ",
};

/** P36 (D45.1): what Ops can create. "Quy cách mới" first: the lever Juli never proposes as a card. */
const LEVER_OPTIONS: Readonly<Record<string, string>> = {
  pack_option: "Quy cách mới",
  cover_image: "Ảnh bìa",
  title: "Tiêu đề",
  product_discount: "Giảm giá sản phẩm",
  flash_sale: "Flash sale",
  shipping_discount: "Giảm phí vận chuyển",
  buy_more_save_more: "Mua nhiều giảm nhiều",
};
const METRIC_OPTIONS: Readonly<Record<string, string>> = { aov: "AOV", items_per_order: "Số món mỗi đơn", ctr: "CTR", ctor: "CTOR" };
const CHANNEL_OPTIONS: Readonly<Record<string, string>> = { total: "Tất cả kênh", product_card: "Thẻ sản phẩm" };

const num = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(1).replace(".", ",")}`;
const pct1 = (n: number) => `${n.toFixed(1).replace(".", ",")} %`;
const whole = (n: number) => Math.round(n).toLocaleString("vi-VN");

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

/** P45 (D52): the one-line tooltip of the EB-shrunk lift, in plain Vietnamese. */
export const EB_TOOLTIP = "Điều chỉnh theo các nhóm cùng loại để tránh tin nhầm kết quả may mắn";

/** D76 / D11: the shop did not opt into pooling, so its estimate uses no other shop's groups. */
export const OWN_DATA_PRIOR = "chỉ dữ liệu của shop này (shop chưa đồng ý gộp dữ liệu)";

/** "Lift đã co (EB): +3,1 % [-2,0; +8,4] · lift thô +40,0 % · theo 3 nhóm cùng loại" or null. */
export function ebText(eb: CardGroupEb | null | undefined): string | null {
  if (!eb) return null;
  const prior =
    eb.prior.source === "pooled"
      ? `theo ${eb.prior.n_groups} nhóm cùng loại`
      : eb.prior.source === "own"
        ? OWN_DATA_PRIOR
        : "mức mặc định (chưa đủ nhóm cùng loại)";
  return `Lift đã co (EB): ${num(eb.shrunk_pct)} % [${num(eb.interval_pct[0])}; ${num(eb.interval_pct[1])}] · lift thô ${num(eb.observed_pct)} % · ${prior}`;
}

function EbLine({ comparison }: { readonly comparison: CardGroupComparison | null | undefined }) {
  const text = ebText(comparison?.eb);
  if (!text) return null;
  return (
    <div data-testid="ops-group-eb" style={{ color: C.muted2, fontSize: 12 }} title={EB_TOOLTIP}>
      {text} <span aria-label={EB_TOOLTIP}>ⓘ</span>
    </div>
  );
}

/**
 * D45.4: "Sàn trôi tuần của khoảng 90 %: ±10,1 % (6 sp × 2 tuần; áp dụng − đối chứng ±21,4 %) ·
 * Cần mỗi nhánh cho ±10,0 %: …". Numbers only — no label, no gate.
 */
export function planText(plan: CardGroupPlan | null | undefined): string | null {
  if (!plan || !plan.floor) return null;
  const n = plan.n_treated + plan.n_control;
  const diff = plan.floor.difference_pct !== null ? `; áp dụng − đối chứng ±${pct1(plan.floor.difference_pct)}` : "";
  const parts = [`Sàn trôi tuần của khoảng 90 %: ±${pct1(plan.floor.pooled_pct)} (${n} sp × ${String(plan.weeks).replace(".", ",")} tuần${diff})`];
  const need = plan.needed_per_arm;
  if (need) {
    const unit = need.unit === "orders" ? "đơn" : "lượt hiển thị";
    const drift = need.reachable && need.with_drift !== null ? `${whole(need.with_drift)} khi tính trôi tuần` : "không đạt được khi tính trôi tuần";
    parts.push(`Cần mỗi nhánh cho ±${pct1(need.half_width_pct)}: ${whole(need.no_drift)} ${unit} (không tính trôi) · ${drift}`);
    const key = need.unit === "orders" ? "orders" : "impressions";
    parts.push(`14 ngày trước khi bắt đầu: ${whole(plan.have_before.treated[key])} áp dụng · ${whole(plan.have_before.control[key])} đối chứng`);
  }
  return parts.join(" · ");
}

/** P46 (D55.1): the Ops revenue labels. */
export const REVENUE_NET_LABEL = "Doanh thu (đã trừ huỷ/hoàn)";
export const GMV_GROSS_LABEL = "GMV TikTok (gồm huỷ/hoàn)";
export const GMV_GROSS_ONLY_LABEL = "GMV (gồm đơn huỷ/hoàn, theo TikTok)";

/**
 * P46 (D55.1): "14 ngày trước khi bắt đầu · Doanh thu (đã trừ huỷ/hoàn): 41,2 tr áp dụng · 20,1 tr
 * đối chứng · GMV TikTok (gồm huỷ/hoàn): 44,8 tr · 21,0 tr", or the TikTok GMV alone, labelled.
 */
export function revenueText(plan: CardGroupPlan | null | undefined): string | null {
  if (!plan?.have_before) return null;
  const { treated, control } = plan.have_before;
  const gross = `${fmtGmvShort(treated.gmv)} áp dụng · ${fmtGmvShort(control.gmv)} đối chứng`;
  if (plan.revenue_basis === "net" && treated.gmv_net !== undefined && control.gmv_net !== undefined) {
    return `14 ngày trước khi bắt đầu · ${REVENUE_NET_LABEL}: ${fmtGmvShort(treated.gmv_net)} áp dụng · ${fmtGmvShort(control.gmv_net)} đối chứng · ${GMV_GROSS_LABEL}: ${gross}`;
  }
  return `14 ngày trước khi bắt đầu · ${GMV_GROSS_ONLY_LABEL}: ${gross}`;
}

function ReasonLine({
  group,
  canEdit,
  onSave,
}: {
  readonly group: CardGroup;
  readonly canEdit: boolean;
  readonly onSave?: (reason: string | null) => Promise<void>;
}) {
  const reason = group.design?.reason ?? null;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(reason ?? "");
  const [error, setError] = useState<string | null>(null);
  if (!group.design) return null;
  if (!editing) {
    return (
      <div style={{ color: C.body }}>
        Lý do chọn thử nghiệm: {reason ?? <span style={{ color: C.muted2 }}>chưa ghi</span>}
        {canEdit && onSave ? (
          <button
            onClick={() => {
              setDraft(reason ?? "");
              setEditing(true);
            }}
            style={{ font: "inherit", fontSize: 12, marginLeft: 8, color: C.pink, background: "transparent", border: 0, cursor: "pointer" }}
            type="button"
          >
            Sửa lý do
          </button>
        ) : null}
      </div>
    );
  }
  return (
    <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
      <input aria-label="Lý do chọn thử nghiệm" maxLength={200} onChange={(e) => setDraft(e.target.value)} style={{ font: "inherit", flex: "1 1 240px", minWidth: 0 }} value={draft} />
      <button
        onClick={() => {
          if (!onSave) return;
          setError(null);
          onSave(draft.trim() ? draft.trim() : null)
            .then(() => setEditing(false))
            .catch(() => setError("Không lưu được lý do."));
        }}
        type="button"
      >
        Lưu lý do
      </button>
      <button onClick={() => setEditing(false)} type="button">
        Huỷ
      </button>
      {error ? <span style={{ color: C.red, fontSize: 12 }}>{error}</span> : null}
    </div>
  );
}

function GroupRow({
  group,
  canEdit,
  onReason,
}: {
  readonly group: CardGroup;
  readonly canEdit: boolean;
  readonly onReason?: (groupId: string, reason: string | null) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const ops = group.design?.source === "ops";
  const guard = group.verdict?.guard;
  const metrics = Object.values(group.verdict?.metrics ?? {}).filter((m) => !(guard && m.metric === guard.metric && m.channel === guard.channel));
  const plan = planText(group.plan);
  const revenue = revenueText(group.plan);
  const adjustment = group.verdict?.adjustment;
  const basis = group.verdict?.basis;
  return (
    <div data-testid="ops-group" style={{ borderTop: `1px solid ${C.lineSoft}`, paddingTop: 10, display: "flex", flexDirection: "column", gap: 6, fontSize: 13 }}>
      <button
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        style={{ font: "inherit", display: "flex", gap: 8, alignItems: "baseline", background: "transparent", border: 0, padding: 0, cursor: "pointer", textAlign: "left", color: C.ink, flexWrap: "wrap" }}
        type="button"
      >
        <b>{group.label}</b>
        {ops ? <span style={{ fontSize: 11, fontWeight: 700, color: C.pink }}>Tạo trong Ops</span> : null}
        <span style={{ color: C.muted2 }}>
          {STATUS_LABEL[group.status] ?? group.status} · bắt đầu {fmtDate(group.launched_on)} · {ops ? "đối chứng được đổi từ" : "trả thẻ đối chứng"} {fmtDate(group.release_on)}
        </span>
        <span style={{ marginLeft: "auto", color: C.muted2 }}>
          {group.treated} áp dụng · {group.control} đối chứng
        </span>
      </button>
      <ReasonLine canEdit={canEdit} group={group} onSave={onReason ? (reason) => onReason(group.id, reason) : undefined} />
      {plan ? (
        <div data-testid="ops-group-plan" style={{ color: C.muted2 }}>
          {plan}
        </div>
      ) : null}
      {revenue ? (
        <div data-testid="ops-group-revenue" style={{ color: C.muted2 }}>
          {revenue}
        </div>
      ) : null}
      <div>
        Kết quả ngày 14: <b>{group.verdict ? comparisonText(group.verdict.primary) : "chưa đo"}</b>
      </div>
      <EbLine comparison={group.verdict?.primary} />
      {basis ? (
        <div data-testid="ops-group-basis" style={{ color: C.muted2, fontSize: 12 }}>
          {basis.text}
        </div>
      ) : null}
      {group.verdict?.gross ? (
        <div data-testid="ops-group-gross" style={{ color: C.muted2, fontSize: 12 }}>
          {group.verdict.gross.label}: {comparisonText(group.verdict.gross.primary)}
        </div>
      ) : null}
      {group.verdict?.net ? (
        <div data-testid="ops-group-net" style={{ color: C.body }}>
          {group.verdict.net.label} (chỉ Ops): {comparisonText(group.verdict.net.primary)}
          <EbLine comparison={group.verdict.net.primary} />
        </div>
      ) : null}
      {adjustment ? <div style={{ color: C.muted2, fontSize: 12 }}>Cách tính: {METHOD_LABEL[adjustment.method] ?? adjustment.method}</div> : null}
      {group.verdict?.ops_rule ? (
        <div data-testid="ops-group-ops-rule" style={{ color: C.muted2, fontSize: 12 }}>
          Theo cách tính mới ({METHOD_LABEL[group.verdict.ops_rule.adjustment?.method ?? ""] ?? "—"}, chỉ Ops): {comparisonText(group.verdict.ops_rule.primary)}
        </div>
      ) : null}
      {group.verdict?.ops_rule ? <EbLine comparison={group.verdict.ops_rule.primary} /> : null}
      {group.design?.strata ? <div style={{ color: C.muted2, fontSize: 12 }}>Chia tầng theo số đơn 30 ngày (mỗi tầng ≈ 1/3 đối chứng)</div> : null}
      {metrics.map((m) => (
        <div key={`${m.metric}|${m.channel}`} style={{ color: C.body }}>
          {m.label}: {comparisonText(m.primary)}
          <EbLine comparison={m.primary} />
          {m.gross ? (
            <div data-testid="ops-group-metric-gross" style={{ color: C.muted2, fontSize: 12 }}>
              {m.gross.label}: {comparisonText(m.gross.primary)}
            </div>
          ) : null}
        </div>
      ))}
      {guard ? (
        <div data-testid="ops-group-guard" style={{ color: guard.warning ? C.red : C.muted2, fontWeight: guard.warning ? 700 : 400 }}>
          {guard.text}
        </div>
      ) : null}
      {group.verdict && !ops ? <div style={{ color: C.muted2 }}>Chỉ thẻ đã duyệt: {comparisonText(group.verdict.approved_only)}</div> : null}
      {group.seller_sentence ? <div style={{ color: C.body }}>Người bán thấy: “{group.seller_sentence}”</div> : null}
      {ops ? <div style={{ color: C.muted2, fontSize: 12 }}>Người bán không thấy nhóm này. Chủ shop tự đổi trên TikTok cho nhóm áp dụng; Juli không ghi lên TikTok.</div> : null}
      {open ? (
        <table style={{ borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ textAlign: "left", color: C.muted2 }}>
              <th>Sản phẩm</th>
              <th>Nhóm</th>
              {group.design?.strata ? <th>Tầng</th> : null}
              <th>Thẻ</th>
              <th>Thay đổi</th>
            </tr>
          </thead>
          <tbody>
            {group.members.map((m) => {
              const measured = group.verdict?.products.find((p) => p.product_id === m.product_id);
              const cardText = m.card_id === null ? "—" : m.arm === "control" ? (m.released_at ? "đã trả thẻ" : "đang giữ") : m.surfaced_at ? "đã hiện" : "chờ hiện";
              return (
                <tr key={m.product_id}>
                  <td>{m.product_title ?? m.product_id}</td>
                  <td>{ARM_LABEL[m.arm] ?? m.arm}</td>
                  {group.design?.strata ? <td>{m.stratum ? (STRATUM_LABEL[m.stratum] ?? m.stratum) : "—"}</td> : null}
                  <td>
                    {cardText}
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

/** P36 (D45.1): "Tạo nhóm thử nghiệm" — TikTok product ids, one per line (or comma-separated). */
function CreateGroupForm({ onCreate }: { readonly onCreate: (body: CardGroupCreate) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [lever, setLever] = useState("pack_option");
  const [metric, setMetric] = useState("aov");
  const [channel, setChannel] = useState("total");
  const [ids, setIds] = useState("");
  const [reason, setReason] = useState("");
  const [guard, setGuard] = useState(true);
  const [stratify, setStratify] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const products = ids
    .split(/[\s,;]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (!open) {
    return (
      <button onClick={() => setOpen(true)} style={{ alignSelf: "flex-start" }} type="button">
        Tạo nhóm thử nghiệm
      </button>
    );
  }
  const select = (label: string, value: string, set: (v: string) => void, options: Readonly<Record<string, string>>) => (
    <label>
      {label}{" "}
      <select aria-label={label} onChange={(e) => set(e.target.value)} value={value}>
        {Object.entries(options).map(([id, name]) => (
          <option key={id} value={id}>
            {name}
          </option>
        ))}
      </select>
    </label>
  );
  return (
    <form
      data-testid="ops-group-create"
      onSubmit={(e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        onCreate({ lever, metric, channel, product_ids: products, reason: reason.trim() || null, guard: metric === "ctr" ? false : guard, stratify })
          .then(() => {
            setOpen(false);
            setIds("");
            setReason("");
          })
          .catch((err: unknown) => setError(err instanceof OpsApiError ? err.detail : "Không tạo được nhóm."))
          .finally(() => setBusy(false));
      }}
      style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 13, borderTop: `1px solid ${C.lineSoft}`, paddingTop: 10 }}
    >
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {select("Đòn bẩy", lever, setLever, LEVER_OPTIONS)}
        {select("Chỉ số chính", metric, setMetric, METRIC_OPTIONS)}
        {select("Kênh", channel, setChannel, CHANNEL_OPTIONS)}
        {metric !== "ctr" ? (
          <label>
            <input checked={guard} onChange={(e) => setGuard(e.target.checked)} type="checkbox" /> Kiểm tra CTR thẻ sản phẩm
          </label>
        ) : null}
        <label>
          <input checked={stratify} onChange={(e) => setStratify(e.target.checked)} type="checkbox" /> Chia tầng theo số đơn 30 ngày (nhiều / ít đơn)
        </label>
      </div>
      <textarea aria-label="Mã sản phẩm TikTok" onChange={(e) => setIds(e.target.value)} placeholder="Mã sản phẩm TikTok, mỗi dòng một mã (ít nhất 3)" rows={4} value={ids} />
      <input
        aria-label="Lý do chọn thử nghiệm (không bắt buộc)"
        maxLength={200}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Lý do chọn thử nghiệm (một dòng, không bắt buộc)"
        value={reason}
      />
      <div style={{ color: C.muted2, fontSize: 12 }}>
        Juli chia ngẫu nhiên ≈ 1/3 làm đối chứng (ghi lại seed). Chủ shop tự tạo thay đổi trên TikTok cho nhóm áp dụng; Juli không ghi lên TikTok. Người bán không thấy nhóm này.
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button disabled={busy || products.length < (stratify ? 6 : 3)} type="submit">
          Tạo nhóm ({products.length} sản phẩm)
        </button>
        <button onClick={() => setOpen(false)} type="button">
          Huỷ
        </button>
        {error ? <span style={{ color: C.red, fontSize: 12 }}>{error}</span> : null}
      </div>
    </form>
  );
}

export function OpsCardGroups({
  shopId,
  load,
  create,
  setReason,
  canEdit = false,
}: {
  readonly shopId: string;
  readonly load?: OpsApi["groups"];
  readonly create?: OpsApi["createGroup"];
  readonly setReason?: OpsApi["setGroupReason"];
  readonly canEdit?: boolean;
}) {
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
  const onReason = setReason
    ? async (groupId: string, reason: string | null) => {
        setPage(await setReason(shopId, groupId, reason));
      }
    : undefined;
  return (
    <div data-testid="ops-groups" style={card}>
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Nhóm thử nghiệm (đối chứng chậm)</h2>
      {failed ? <span style={{ color: C.red, fontSize: 13 }}>Không tải được nhóm thử nghiệm.</span> : null}
      {page && !page.enabled ? <span style={{ color: C.muted2, fontSize: 13 }}>Đang tắt cho shop này (nhóm từ thẻ); nhóm tạo trong Ops vẫn được đo.</span> : null}
      {page && page.groups.length === 0 ? <span style={{ color: C.muted2, fontSize: 13 }}>Chưa có nhóm nào.</span> : null}
      {canEdit && create && page ? (
        <CreateGroupForm
          onCreate={async (body) => {
            setPage(await create(shopId, body));
          }}
        />
      ) : null}
      {page?.groups.map((g) => <GroupRow canEdit={canEdit} group={g} key={g.id} onReason={onReason} />)}
    </div>
  );
}
