"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";

import { opsApi, type OpsApi } from "../../../lib/ops/api";
import { fmtDate, fmtInt, fmtPct, fmtWhen } from "../../../lib/ops/format";
import type {
  ApprovalChannel,
  ApprovalDecision,
  ExecutorRole,
  OpsMe,
  ProposalKind,
  ProposalResult,
  ProposalSubject,
  ShopProposalRow,
} from "../../../lib/ops/types";
import { C, OpsHeader, OpsPage, card } from "../ops-shell";

/**
 * "Chu kỳ" (ADR-118): the manual Analyze → Recommend → Execute → Measure loop of a
 * contract-client shop. Staff write each proposal, record the client's decision (email or
 * document, with a pointer to the evidence) and the representative's execution on Shopee.
 * Viewers read only. An executed proposal shows how its item did in the 7 days after the
 * change against its own last 28 days (D81): verdict, before / after per metric and the last
 * day of data used; operators can recompute it ("Tính lại"). Ops only, no seller view.
 */

const BUTTON: CSSProperties = {
  font: "inherit",
  fontSize: 14,
  fontWeight: 600,
  color: "#ffffff",
  background: C.pinkStrong,
  border: 0,
  borderRadius: 10,
  minHeight: 40,
  padding: "0 16px",
  cursor: "pointer",
};
const SECONDARY: CSSProperties = { ...BUTTON, color: C.ink, background: "#ffffff", border: `1px solid ${C.line}` };
const INPUT: CSSProperties = { font: "inherit", fontSize: 14, border: `1px solid ${C.line}`, borderRadius: 8, padding: "8px 10px", minWidth: 200 };
const LABEL: CSSProperties = { display: "flex", flexDirection: "column", gap: 4, fontSize: 13, fontWeight: 600 };

export const STATUS_LABELS: Readonly<Record<string, string>> = {
  draft: "Nháp",
  sent: "Đã gửi, chờ duyệt",
  approved: "Đã duyệt",
  rejected: "Bị từ chối",
  changes_requested: "Cần sửa",
  executed: "Đã thực hiện",
  measured: "Đã đo kết quả",
  withdrawn: "Đã rút",
  superseded: "Đã thay bằng bản mới",
};
const STATUS_COLOR: Readonly<Record<string, string>> = {
  approved: C.green,
  executed: C.green,
  measured: C.green,
  rejected: C.red,
  changes_requested: C.amber,
  sent: C.amber,
};
export const KIND_LABELS: Readonly<Record<ProposalKind, string>> = {
  title: "Tiêu đề",
  images: "Hình ảnh",
  price: "Giá",
  voucher: "Voucher",
  flash_sale: "Flash sale",
  ads: "Quảng cáo",
  bundle: "Combo",
  program: "Chương trình",
  stock: "Tồn kho",
  other: "Khác",
};
const SUBJECT_LABELS: Readonly<Record<ProposalSubject, string>> = { item: "Sản phẩm", shop: "Shop", campaign: "Chiến dịch" };
const DECISION_LABELS: Readonly<Record<ApprovalDecision, string>> = { approved: "Duyệt", rejected: "Từ chối", changes_requested: "Cần sửa" };
const CHANNEL_LABELS: Readonly<Record<string, string>> = { email: "Email", document: "Tài liệu", in_app: "Trong app" };
const VERDICT_LABELS: Readonly<Record<string, string>> = { dat: "Đạt", khong_dat: "Không đạt", chua_ket_luan: "Chưa kết luận" };
const VERDICT_COLOR: Readonly<Record<string, string>> = { dat: C.green, khong_dat: C.red };
const METRIC_LABELS: Readonly<Record<string, string>> = { impressions: "Lượt xem", clicks: "Lượt nhấp", ctr: "CTR" };
const ROLE_LABELS: Readonly<Record<string, string>> = {
  client_representative: "Đại diện khách hàng",
  juli_operator: "Nhân viên Juli",
  platform_api: "API sàn",
};

type CycleApi = Partial<
  Pick<OpsApi, "proposals" | "createProposal" | "sendProposal" | "withdrawProposal" | "recordApproval" | "recordExecution" | "measureProposal">
>;

function changeText(value: Record<string, unknown>): string {
  if (typeof value.text === "string") return value.text;
  const entries = Object.entries(value);
  return entries.length === 0 ? "—" : entries.map(([k, v]) => `${k}: ${String(v)}`).join(" · ");
}

function metricValue(metric: string, value: number | null): string {
  if (value === null) return "—";
  return metric === "ctr" ? fmtPct(value) : `${fmtInt(value)} /ngày`;
}

/** D81: the targeted metric's verdict decides; the others are shown for context. */
function ResultsBlock({ results }: { readonly results: readonly ProposalResult[] }) {
  const decided = results.find((r) => r.verdict !== "chua_ket_luan");
  const verdict = decided?.verdict ?? "chua_ket_luan";
  const through = results.map((r) => r.data_through).filter((d): d is string => d !== null).sort().at(-1);
  return (
    <section aria-label="Kết quả" data-testid="results" style={{ display: "flex", flexDirection: "column", gap: 4, borderTop: `1px solid ${C.lineSoft}`, paddingTop: 8 }}>
      <p style={{ margin: 0, fontSize: 13 }}>
        Kết quả:{" "}
        <strong data-testid="verdict" style={{ color: VERDICT_COLOR[verdict] ?? C.muted }}>
          {VERDICT_LABELS[verdict] ?? verdict}
        </strong>
        {through ? ` · dữ liệu đến ${fmtDate(through)}` : ""}
      </p>
      {results.map((r) => (
        <p data-testid={`result-${r.metric}`} key={r.metric} style={{ margin: 0, fontSize: 13, color: C.body }}>
          {METRIC_LABELS[r.metric] ?? r.metric}: {metricValue(r.metric, r.comparison)} → <strong>{metricValue(r.metric, r.value)}</strong>
        </p>
      ))}
    </section>
  );
}

/** `datetime-local` value ("2026-11-02T09:30") as an ISO instant. */
function localToIso(value: string): string {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toISOString();
}

export function OpsCycle({ me, shopId, api = opsApi }: { readonly me: OpsMe; readonly shopId: string; readonly api?: CycleApi }) {
  const canEdit = me.role !== "viewer";
  const [rows, setRows] = useState<readonly ShopProposalRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!api.proposals) return Promise.resolve();
    return api
      .proposals(shopId)
      .then((r) => setRows(r.proposals))
      .catch(() => setError("Không tải được danh sách đề xuất."));
  }, [api, shopId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <OpsPage>
      <OpsHeader me={me} />
      <main style={{ padding: "22px 28px", display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <Link href={`/ops/shops/${shopId}`} style={{ fontSize: 14, textDecoration: "none", color: C.pink }}>
            ‹ Cài đặt shop
          </Link>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>Chu kỳ</h1>
        </div>
        {error ? (
          <p role="alert" style={{ margin: 0, color: C.red }}>
            {error}
          </p>
        ) : null}
        {canEdit && api.createProposal ? <NewProposal create={api.createProposal} onDone={load} shopId={shopId} /> : null}
        {rows === null ? (
          error ? null : <p style={{ margin: 0, color: C.muted }}>Đang tải…</p>
        ) : rows.length === 0 ? (
          <p style={{ margin: 0, color: C.muted }}>Chưa có đề xuất nào cho shop này.</p>
        ) : (
          rows.map((p) => <ProposalCard api={api} canEdit={canEdit} key={p.id} onChanged={load} proposal={p} shopId={shopId} />)
        )}
      </main>
    </OpsPage>
  );
}

function NewProposal({
  shopId,
  create,
  onDone,
}: {
  readonly shopId: string;
  readonly create: NonNullable<CycleApi["createProposal"]>;
  readonly onDone: () => Promise<void> | void;
}) {
  const [open, setOpen] = useState(false);
  const [cycle, setCycle] = useState("");
  const [kind, setKind] = useState<ProposalKind>("price");
  const [subject, setSubject] = useState<ProposalSubject>("item");
  const [itemId, setItemId] = useState("");
  const [label, setLabel] = useState("");
  const [before, setBefore] = useState("");
  const [after, setAfter] = useState("");
  const [reason, setReason] = useState("");
  const [start, setStart] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setOpen(false);
    setError(null);
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await create(shopId, {
        cycle: cycle.trim(),
        kind,
        subject_type: subject,
        item_id: subject === "item" ? itemId.trim() : null,
        subject_label: label.trim(),
        change_before: before.trim() ? { text: before.trim() } : {},
        change_after: { text: after.trim() },
        reason: reason.trim(),
        planned_start: start || null,
      });
      setCycle("");
      setItemId("");
      setLabel("");
      setBefore("");
      setAfter("");
      setReason("");
      setStart("");
      setOpen(false);
      await onDone();
    } catch (e) {
      const status = (e as { status?: number }).status;
      setError(status === 422 ? "Không lưu được. Kiểm tra mã sản phẩm có trong dữ liệu shop và các ô bắt buộc." : "Không tạo được đề xuất.");
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <div>
        <button onClick={() => setOpen(true)} style={SECONDARY} type="button">
          + Tạo đề xuất
        </button>
      </div>
    );
  }
  const ready = cycle.trim() && label.trim() && after.trim() && reason.trim() && (subject !== "item" || itemId.trim());
  return (
    <form
      aria-label="Tạo đề xuất"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      style={{ ...card, gap: 10 }}
    >
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Tạo đề xuất</h2>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <label style={LABEL}>
          Đợt
          <input onChange={(e) => setCycle(e.target.value)} placeholder="2026-11 Đợt 1" style={INPUT} value={cycle} />
        </label>
        <label style={LABEL}>
          Loại thay đổi
          <select onChange={(e) => setKind(e.target.value as ProposalKind)} style={INPUT} value={kind}>
            {(Object.keys(KIND_LABELS) as ProposalKind[]).map((k) => (
              <option key={k} value={k}>
                {KIND_LABELS[k]}
              </option>
            ))}
          </select>
        </label>
        <label style={LABEL}>
          Đối tượng
          <select onChange={(e) => setSubject(e.target.value as ProposalSubject)} style={INPUT} value={subject}>
            {(Object.keys(SUBJECT_LABELS) as ProposalSubject[]).map((k) => (
              <option key={k} value={k}>
                {SUBJECT_LABELS[k]}
              </option>
            ))}
          </select>
        </label>
        {subject === "item" ? (
          <label style={LABEL}>
            Mã sản phẩm Shopee
            <input onChange={(e) => setItemId(e.target.value)} style={INPUT} value={itemId} />
          </label>
        ) : null}
        <label style={LABEL}>
          Tên hiển thị
          <input onChange={(e) => setLabel(e.target.value)} style={INPUT} value={label} />
        </label>
        <label style={LABEL}>
          Dự kiến bắt đầu
          <input onChange={(e) => setStart(e.target.value)} style={INPUT} type="date" value={start} />
        </label>
      </div>
      <label style={LABEL}>
        Hiện tại (không bắt buộc)
        <input onChange={(e) => setBefore(e.target.value)} style={{ ...INPUT, width: "100%" }} value={before} />
      </label>
      <label style={LABEL}>
        Đề xuất đổi thành
        <input onChange={(e) => setAfter(e.target.value)} style={{ ...INPUT, width: "100%" }} value={after} />
      </label>
      <label style={LABEL}>
        Lý do (khách hàng đọc được)
        <textarea onChange={(e) => setReason(e.target.value)} rows={3} style={{ ...INPUT, width: "100%" }} value={reason} />
      </label>
      {error ? (
        <p role="alert" style={{ margin: 0, color: C.red, fontSize: 13 }}>
          {error}
        </p>
      ) : null}
      <div style={{ display: "flex", gap: 8 }}>
        <button disabled={busy || !ready} style={BUTTON} type="submit">
          {busy ? "Đang lưu…" : "Lưu nháp"}
        </button>
        <button onClick={close} style={SECONDARY} type="button">
          Hủy
        </button>
      </div>
    </form>
  );
}

function ProposalCard({
  proposal: p,
  shopId,
  canEdit,
  api,
  onChanged,
}: {
  readonly proposal: ShopProposalRow;
  readonly shopId: string;
  readonly canEdit: boolean;
  readonly api: CycleApi;
  readonly onChanged: () => Promise<void> | void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<"approval" | "execution" | null>(null);

  const act = async (run: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await run();
      setForm(null);
      await onChanged();
    } catch {
      setError("Thao tác không thực hiện được ở trạng thái hiện tại.");
    } finally {
      setBusy(false);
    }
  };

  const withdrawable = ["draft", "sent", "changes_requested", "approved"].includes(p.status);
  const buttons: ReactNode[] = [];
  if (canEdit) {
    if (p.status === "draft" && api.sendProposal) {
      const send = api.sendProposal;
      buttons.push(
        <button disabled={busy} key="send" onClick={() => void act(() => send(shopId, p.id))} style={BUTTON} type="button">
          Gửi khách hàng
        </button>,
      );
    }
    if (p.status === "sent" && api.recordApproval) {
      buttons.push(
        <button key="approval" onClick={() => setForm(form === "approval" ? null : "approval")} style={BUTTON} type="button">
          Ghi quyết định của khách
        </button>,
      );
    }
    if (p.status === "approved" && api.recordExecution) {
      buttons.push(
        <button key="execution" onClick={() => setForm(form === "execution" ? null : "execution")} style={BUTTON} type="button">
          Ghi việc đã thực hiện
        </button>,
      );
    }
    if (p.status === "executed" && api.measureProposal) {
      const measure = api.measureProposal;
      buttons.push(
        <button disabled={busy} key="measure" onClick={() => void act(() => measure(shopId, p.id))} style={SECONDARY} type="button">
          Tính lại
        </button>,
      );
    }
    if (withdrawable && api.withdrawProposal) {
      const withdraw = api.withdrawProposal;
      buttons.push(
        <button disabled={busy} key="withdraw" onClick={() => void act(() => withdraw(shopId, p.id))} style={SECONDARY} type="button">
          Rút đề xuất
        </button>,
      );
    }
  }

  return (
    <article aria-label={p.subject_label} data-testid={`proposal-${p.id}`} style={card}>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>{p.subject_label}</h2>
        <span style={{ fontSize: 12, color: C.muted }}>
          {KIND_LABELS[p.kind as ProposalKind] ?? p.kind} · {p.cycle}
          {p.revision > 1 ? ` · bản ${p.revision}` : ""}
        </span>
        <span data-testid="status" style={{ marginLeft: "auto", fontSize: 12, fontWeight: 700, color: STATUS_COLOR[p.status] ?? C.muted }}>
          {STATUS_LABELS[p.status] ?? p.status}
        </span>
      </div>
      <p style={{ margin: 0, fontSize: 14 }}>
        {changeText(p.change_before)} → <strong>{changeText(p.change_after)}</strong>
      </p>
      <p style={{ margin: 0, fontSize: 13, color: C.body }}>{p.reason}</p>
      {p.planned_start ? <p style={{ margin: 0, fontSize: 12, color: C.muted }}>Dự kiến bắt đầu {fmtDate(p.planned_start)}</p> : null}
      {p.approvals.map((a) => (
        <p key={a.id} style={{ margin: 0, fontSize: 13, color: C.body }}>
          Quyết định: {DECISION_LABELS[a.decision as ApprovalDecision] ?? a.decision} · {CHANNEL_LABELS[a.channel] ?? a.channel}
          {a.evidence_ref ? ` · bằng chứng: ${a.evidence_ref}` : ""} · {fmtWhen(a.decided_at)}
          {a.note ? ` · ${a.note}` : ""}
        </p>
      ))}
      {p.executions.map((x) => (
        <p key={x.id} style={{ margin: 0, fontSize: 13, color: C.body }}>
          Đã thực hiện: {ROLE_LABELS[x.executor_role] ?? x.executor_role} · {fmtWhen(x.executed_at)}
          {x.evidence_ref ? ` · bằng chứng: ${x.evidence_ref}` : ""}
          {x.verified_at ? ` · đã đối chiếu ${fmtWhen(x.verified_at)}` : ""}
        </p>
      ))}
      {p.results && p.results.length > 0 ? (
        <ResultsBlock results={p.results} />
      ) : p.status === "executed" ? (
        <p style={{ margin: 0, fontSize: 13, color: C.muted }}>Chưa có số liệu sau thay đổi.</p>
      ) : null}
      {error ? (
        <p role="alert" style={{ margin: 0, color: C.red, fontSize: 13 }}>
          {error}
        </p>
      ) : null}
      {buttons.length ? <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{buttons}</div> : null}
      {form === "approval" && api.recordApproval ? (
        <ApprovalForm busy={busy} onSubmit={(body) => void act(() => api.recordApproval!(shopId, p.id, body))} />
      ) : null}
      {form === "execution" && api.recordExecution ? (
        <ExecutionForm busy={busy} onSubmit={(body) => void act(() => api.recordExecution!(shopId, p.id, body))} />
      ) : null}
    </article>
  );
}

function ApprovalForm({
  busy,
  onSubmit,
}: {
  readonly busy: boolean;
  readonly onSubmit: (body: { decision: ApprovalDecision; channel: ApprovalChannel; evidence_ref: string; decided_at: string; note: string | null }) => void;
}) {
  const [decision, setDecision] = useState<ApprovalDecision>("approved");
  const [channel, setChannel] = useState<ApprovalChannel>("email");
  const [evidence, setEvidence] = useState("");
  const [when, setWhen] = useState("");
  const [note, setNote] = useState("");
  return (
    <form
      aria-label="Ghi quyết định"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ decision, channel, evidence_ref: evidence.trim(), decided_at: localToIso(when), note: note.trim() || null });
      }}
      style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end", borderTop: `1px solid ${C.lineSoft}`, paddingTop: 10 }}
    >
      <label style={LABEL}>
        Quyết định
        <select onChange={(e) => setDecision(e.target.value as ApprovalDecision)} style={INPUT} value={decision}>
          {(Object.keys(DECISION_LABELS) as ApprovalDecision[]).map((d) => (
            <option key={d} value={d}>
              {DECISION_LABELS[d]}
            </option>
          ))}
        </select>
      </label>
      <label style={LABEL}>
        Kênh
        <select onChange={(e) => setChannel(e.target.value as ApprovalChannel)} style={INPUT} value={channel}>
          <option value="email">Email</option>
          <option value="document">Tài liệu</option>
        </select>
      </label>
      <label style={LABEL}>
        Nơi lưu bằng chứng
        <input onChange={(e) => setEvidence(e.target.value)} placeholder="Tên thư / tệp đã lưu" style={INPUT} value={evidence} />
      </label>
      <label style={LABEL}>
        Khách quyết định lúc
        <input onChange={(e) => setWhen(e.target.value)} style={INPUT} type="datetime-local" value={when} />
      </label>
      <label style={LABEL}>
        Ghi chú
        <input onChange={(e) => setNote(e.target.value)} style={INPUT} value={note} />
      </label>
      <button disabled={busy || !evidence.trim() || !when} style={BUTTON} type="submit">
        Lưu quyết định
      </button>
    </form>
  );
}

function ExecutionForm({
  busy,
  onSubmit,
}: {
  readonly busy: boolean;
  readonly onSubmit: (body: { executed_at: string; executor_role: ExecutorRole; evidence_ref: string | null }) => void;
}) {
  const [role, setRole] = useState<ExecutorRole>("client_representative");
  const [when, setWhen] = useState("");
  const [evidence, setEvidence] = useState("");
  return (
    <form
      aria-label="Ghi việc đã thực hiện"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ executed_at: localToIso(when), executor_role: role, evidence_ref: evidence.trim() || null });
      }}
      style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end", borderTop: `1px solid ${C.lineSoft}`, paddingTop: 10 }}
    >
      <label style={LABEL}>
        Người thực hiện
        <select onChange={(e) => setRole(e.target.value as ExecutorRole)} style={INPUT} value={role}>
          <option value="client_representative">{ROLE_LABELS.client_representative}</option>
          <option value="juli_operator">{ROLE_LABELS.juli_operator}</option>
        </select>
      </label>
      <label style={LABEL}>
        Thực hiện lúc
        <input onChange={(e) => setWhen(e.target.value)} style={INPUT} type="datetime-local" value={when} />
      </label>
      <label style={LABEL}>
        Bằng chứng (không bắt buộc)
        <input onChange={(e) => setEvidence(e.target.value)} style={INPUT} value={evidence} />
      </label>
      <button disabled={busy || !when} style={BUTTON} type="submit">
        Lưu việc đã làm
      </button>
    </form>
  );
}
