"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";

import { opsApi, type OpsApi } from "../../lib/ops/api";
import { writeCurrentShop } from "../../lib/ops/current-shop";
import { ACTION_NAMES, DIAG_KEYS, QUOTA_KEYS, SHRINKAGE_NAMES, STREAM_NAMES, TRIGGER_NAMES, changeRows, draftRows, draftSummary, fmtSetting, SETTING_KEYS, STAGE_NAMES } from "../../lib/ops/setting-changes";
import type { DiagKey, OpsMe, OverrideKey, ShopSettingsPage, StageId } from "../../lib/ops/types";
import { auditWhat, auditWhen, auditWho } from "./audit-text";
import { ConfirmDialog, DraftBar, Toast } from "./ops-confirm";
import { OpsCardGroups } from "./ops-card-groups";
import { OpsRules } from "./ops-rules";
import { C, OpsHeader, OpsPage, STAGE_STYLE, card } from "./ops-shell";
import { OpsSkeleton } from "./ops-skeleton";

/**
 * "Cài đặt shop" — artboards OpsShopSettings.dc.html (D25.4, D25.7) and
 * OpsConfirm.dc.html (D27.5): the stage asks before → after; every other setting
 * is a draft saved in ONE PUT (one audit row) after one confirm dialog.
 */

const STAGES: [StageId, string, string][] = [
  ["trial", "Thử nghiệm", "Đội ngũ nhập liệu, theo dõi sát"],
  ["self", "Tự vận hành", "Seller tự dùng"],
  ["pilot", "Pilot đặc biệt", "Cấu hình riêng, ưu tiên hỗ trợ"],
];
const STREAM_LABEL: Record<string, string> = { product_card: "Thẻ SP", shop_tab: "Tab", seller_video: "Video", seller_live: "LIVE" };
const OWN: CSSProperties = { background: "#fff7fa", borderColor: "#f8b9d3", fontWeight: 600 };

type Api = Pick<OpsApi, "settings" | "putSettings" | "resetSettings" | "invite"> & Partial<Pick<OpsApi, "groups">>;

function SettingRow({
  title,
  help,
  overridden,
  summary,
  children,
  onDefault,
  disabled,
}: {
  readonly title: string;
  readonly help: string;
  readonly overridden: boolean;
  readonly summary: string;
  readonly children?: ReactNode;
  readonly onDefault?: () => void;
  readonly disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div data-testid="ops-setting" style={{ borderTop: `1px solid ${C.lineSoft}`, paddingTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 200px 120px", gap: 12, alignItems: "center", fontSize: 14 }}>
        <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <b>{title}</b>
          <span style={{ fontSize: 12, color: C.muted2 }}>{help}</span>
        </span>
        <button
          aria-expanded={open}
          aria-label={`Sửa ${title}`}
          disabled={disabled || !children}
          onClick={() => setOpen(!open)}
          style={{
            font: "inherit",
            fontSize: 14,
            textAlign: "left",
            border: `1px solid ${C.line}`,
            borderRadius: 8,
            minHeight: 36,
            padding: "0 10px",
            background: "#fff",
            color: overridden ? C.ink : C.body,
            cursor: disabled ? "default" : "pointer",
            ...(overridden ? OWN : {}),
          }}
          type="button"
        >
          {summary}
        </button>
        <span style={{ fontSize: 12, display: "flex", flexDirection: "column", gap: 2, ...(overridden ? { color: C.pink, fontWeight: 700 } : { color: C.muted2 }) }}>
          {overridden ? "Ghi đè" : "Mặc định"}
          {overridden && onDefault && !disabled ? (
            <button onClick={onDefault} style={{ font: "inherit", fontSize: 11, color: C.pink, background: "transparent", border: 0, padding: 0, textAlign: "left", cursor: "pointer" }} type="button">
              về mặc định
            </button>
          ) : null}
        </span>
      </div>
      {open && children ? <div style={{ background: "#fafafb", borderRadius: 10, padding: 10, fontSize: 13 }}>{children}</div> : null}
    </div>
  );
}

/** Artboard OpsConfirm: each stream / action is a chip with a check box. */
function Chips({
  options,
  value,
  labels,
  onChange,
}: {
  readonly options: readonly string[];
  readonly value: readonly string[];
  readonly labels: Readonly<Record<string, string>>;
  readonly onChange: (next: string[]) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      {options.map((id) => {
        const on = value.includes(id);
        return (
          <button
            aria-pressed={on}
            key={id}
            onClick={() => onChange(options.filter((o) => (o === id ? !on : value.includes(o))))}
            style={{
              font: "inherit",
              fontSize: 14,
              borderRadius: 10,
              minHeight: 40,
              padding: "0 12px",
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              ...(on ? { color: C.ink, background: "#fff7fa", border: "1px solid #f8b9d3", fontWeight: 600 } : { color: C.muted2, background: "#ffffff", border: `1px solid ${C.line}` }),
            }}
            type="button"
          >
            <span aria-hidden="true" style={{ width: 16, height: 16, borderRadius: 4, boxSizing: "border-box", ...(on ? { background: C.pinkStrong, border: 0 } : { border: "1.5px solid #b8b8c2" }) }} />
            {labels[id] ?? id}
          </button>
        );
      })}
    </div>
  );
}

type Draft = Partial<Record<OverrideKey, unknown>>;
type Dialog = { kind: "stage"; stage: StageId } | { kind: "save" } | { kind: "reset" } | null;

const sameValue = (a: unknown, b: unknown) => {
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x) => b.includes(x));
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
};

export function OpsShopSettings({ me, shopId, api = opsApi }: { readonly me: OpsMe; readonly shopId: string; readonly api?: Api }) {
  const [page, setPage] = useState<ShopSettingsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [keep, setKeep] = useState(true);
  const [inviteNote, setInviteNote] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [dialog, setDialog] = useState<Dialog>(null);
  const [toast, setToast] = useState<string | null>(null);
  // Bumped whenever the draft is dropped so the number inputs restart from the saved value.
  const [epoch, setEpoch] = useState(0);
  const clearToast = useCallback(() => setToast(null), []);
  const canEdit = me.role !== "viewer";

  const load = useCallback(() => {
    api
      .settings(shopId)
      .then((p) => {
        setPage(p);
        // D27.8: opening a shop's settings makes it the current shop (Mô phỏng opens it).
        writeCurrentShop({ id: shopId, name: p.shop.shop_name });
      })
      .catch(() => setError("Không tải được cài đặt."));
  }, [api, shopId]);

  useEffect(() => {
    load();
  }, [load]);

  const rows = useMemo(() => (page ? draftRows(page.settings, draft) : []), [page, draft]);

  if (!page) {
    return (
      <OpsPage>
        <OpsHeader me={me} />
        <main style={{ padding: "24px 28px" }}>{error ? <p role="alert">{error}</p> : <OpsSkeleton rows={3} variant="cards" />}</main>
      </OpsPage>
    );
  }
  const s = page.settings;
  const shopName = page.shop.shop_name;
  /** The value shown: the draft's when there is one, else the saved one. */
  const eff = (key: OverrideKey): unknown => {
    const o = key in draft ? draft[key] : s.overrides[key];
    return o === null || o === undefined ? s.defaults[key] : o;
  };
  const isSet = (key: OverrideKey): boolean => {
    const o = key in draft ? draft[key] : s.overrides[key];
    return o !== null && o !== undefined;
  };
  const change = (patch: Draft) => {
    setToast(null);
    setDraft((cur) => {
      const next: Draft = { ...cur };
      for (const key of Object.keys(patch) as OverrideKey[]) {
        const value = patch[key];
        const saved = s.overrides[key] ?? null;
        const back = sameValue(value, saved) || (saved === null && value !== null && sameValue(value, s.defaults[key]));
        if (back) delete next[key];
        else next[key] = value;
      }
      return next;
    });
  };
  const limits = [eff("card_daily_limit"), eff("card_weekly_limit"), eff("card_open_limit")] as number[];
  const streams = (eff("enabled_streams") as string[]) ?? [];
  const actions = (eff("enabled_actions") as string[]) ?? [];
  const content = eff("content_cards_enabled") as boolean;
  const capShown = eff("openai_monthly_cap_usd") as number | null;
  const anyOverride = SETTING_KEYS.some((k) => s.overrides[k] !== null && s.overrides[k] !== undefined);
  const pendingInvite = page.invites.find((i) => !i.accepted_at && !i.revoked_at);
  const ownerText = page.shop.owned_by_team
    ? pendingInvite
      ? `Đã gửi lời mời tới ${pendingInvite.email} · chờ seller đăng nhập và nhận shop.`
      : `Shop do đội ngũ kết nối (tài khoản ${page.shop.owner_email ?? "—"}). Chưa bàn giao.`
    : `Chủ shop: ${page.shop.owner_email ?? "—"}.`;

  const sendInvite = async () => {
    setInviteNote(null);
    try {
      const r = await api.invite(shopId, inviteEmail, keep);
      setInviteNote(r.email_sent ? "Đã gửi email mời." : `Chưa gửi được email. Gửi liên kết này cho seller: ${r.accept_url ?? ""}`);
      load();
    } catch (e) {
      setInviteNote(e instanceof Error ? e.message : "Không mời được.");
    }
  };

  const resetRows = SETTING_KEYS.filter((k) => s.overrides[k] !== null && s.overrides[k] !== undefined).flatMap((k) =>
    changeRows(k, s.overrides[k], s.defaults[k], true),
  );
  const confirmDialog =
    dialog?.kind === "stage" ? (
      <ConfirmDialog
        confirmLabel="Đổi giai đoạn"
        note="Áp dụng ngay cho thẻ và lượt chạy mới. Nhật ký ghi 1 dòng."
        onCancel={() => setDialog(null)}
        onConfirm={async () => {
          await api.putSettings(shopId, { stage: dialog.stage });
          setDialog(null);
          setToast("Đã đổi giai đoạn · ghi 1 dòng nhật ký");
          load();
        }}
        rows={[{ k: "Giai đoạn", before: STAGE_NAMES[s.stage] ?? s.stage_label, after: STAGE_NAMES[dialog.stage] ?? dialog.stage }]}
        title={`Đổi giai đoạn của ${shopName}?`}
      />
    ) : dialog?.kind === "save" ? (
      <ConfirmDialog
        confirmLabel="Xác nhận lưu"
        note={`Áp dụng từ lượt tạo thẻ kế tiếp. Nhật ký ghi 1 dòng cho cả ${rows.length} thay đổi.`}
        onCancel={() => setDialog(null)}
        onConfirm={async () => {
          const n = rows.length;
          await api.putSettings(shopId, { ...draft });
          setDraft({});
          setEpoch((e) => e + 1);
          setDialog(null);
          setToast(`Đã lưu ${n} thay đổi · ghi 1 dòng nhật ký`);
          load();
        }}
        rows={rows}
        title={`Lưu ${rows.length} thay đổi cho ${shopName}?`}
      />
    ) : dialog?.kind === "reset" ? (
      <ConfirmDialog
        confirmLabel="Về mặc định"
        note="Mọi cài đặt riêng của shop trở về mặc định. Nhật ký ghi 1 dòng."
        onCancel={() => setDialog(null)}
        onConfirm={async () => {
          await api.resetSettings(shopId);
          setDraft({});
          setEpoch((e) => e + 1);
          setDialog(null);
          setToast("Đã đưa về mặc định · ghi 1 dòng nhật ký");
          load();
        }}
        rows={resetRows}
        title={`Đưa cài đặt riêng của ${shopName} về mặc định?`}
      />
    ) : null;

  return (
    <OpsPage>
      <OpsHeader me={me} />
      <main
        className="ops-settings"
        style={{ padding: `22px 28px ${rows.length > 0 ? 110 : 24}px`, display: "grid", gridTemplateColumns: "minmax(0, 1.6fr) minmax(0, 1fr)", gap: 20, alignItems: "start" }}
      >
        <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <Link href="/ops" style={{ fontSize: 14, textDecoration: "none", color: C.pink }}>
              ‹ Tổng quan
            </Link>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>{shopName} · Cài đặt shop</h1>
            <span style={{ fontSize: 12, fontWeight: 600, borderRadius: 999, padding: "3px 10px", ...STAGE_STYLE[s.stage] }}>{s.stage_label}</span>
            <Link href={`/ops/shops/${shopId}/xem`} style={{ marginLeft: "auto", fontSize: 14, fontWeight: 600, textDecoration: "none", color: C.pink }}>
              Xem như shop ›
            </Link>
          </div>
          {error ? (
            <p role="alert" style={{ margin: 0, color: C.red }}>
              {error}
            </p>
          ) : null}
          <div style={{ ...card, gap: 12 }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Giai đoạn</h2>
            <div aria-label="Giai đoạn" role="radiogroup" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {STAGES.map(([id, label, sub]) => {
                const on = s.stage === id;
                return (
                  <button
                    aria-checked={on}
                    disabled={!canEdit}
                    key={id}
                    onClick={() => {
                      if (!on) setDialog({ kind: "stage", stage: id });
                    }}
                    role="radio"
                    style={{
                      font: "inherit",
                      fontSize: 14,
                      fontWeight: 600,
                      borderRadius: 10,
                      minHeight: 44,
                      padding: "0 14px",
                      cursor: canEdit ? "pointer" : "default",
                      textAlign: "left",
                      ...(on ? { color: "#fff", background: C.ink, border: `1px solid ${C.ink}` } : { color: C.ink, background: "#fff", border: `1px solid ${C.line}` }),
                    }}
                    type="button"
                  >
                    {label}
                    <br />
                    <span style={{ fontSize: 12, fontWeight: 400 }}>{sub}</span>
                  </button>
                );
              })}
            </div>
          </div>
          <div style={card}>
            <div style={{ display: "flex", alignItems: "center" }}>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Cài đặt riêng</h2>
              <button
                disabled={!canEdit || !anyOverride}
                onClick={() => setDialog({ kind: "reset" })}
                style={{ marginLeft: "auto", font: "inherit", fontSize: 13, fontWeight: 600, color: C.pink, background: "transparent", border: 0, minHeight: 36, cursor: canEdit && anyOverride ? "pointer" : "default", opacity: canEdit && anyOverride ? 1 : 0.5 }}
                type="button"
              >
                Về mặc định
              </button>
            </div>
            <SettingRow
              disabled={!canEdit}
              help="D24.17"
              onDefault={() => {
                change({ card_daily_limit: null, card_weekly_limit: null, card_open_limit: null });
                setEpoch((e) => e + 1);
              }}
              overridden={isSet("card_daily_limit") || isSet("card_weekly_limit") || isSet("card_open_limit")}
              summary={`${limits[0]}/ngày · ${limits[1]}/tuần · ${limits[2]} mở`}
              title="Giới hạn thẻ"
            >
              <LimitEditor
                key={`limits-${epoch}`}
                keys={["card_daily_limit", "card_weekly_limit", "card_open_limit"]}
                labels={["/ngày", "/tuần", "mở"]}
                onChange={change}
                values={limits}
              />
            </SettingRow>
            <SettingRow
              disabled={!canEdit}
              help="Tắt luồng không phù hợp với shop"
              onDefault={() => change({ enabled_streams: null })}
              overridden={isSet("enabled_streams")}
              summary={streams.map((id) => STREAM_LABEL[id] ?? id).join(" · ") || "Không luồng nào"}
              title="Luồng được đề xuất"
            >
              <Chips labels={STREAM_NAMES} onChange={(next) => change({ enabled_streams: next })} options={s.options.streams.map((x) => x.id)} value={streams} />
            </SettingRow>
            <SettingRow
              disabled={!canEdit}
              help="Ví dụ tắt Flash sale nếu shop không đủ điều kiện"
              onDefault={() => change({ enabled_actions: null })}
              overridden={isSet("enabled_actions")}
              summary={`${actions.filter((a) => !a.endsWith("_script")).length}/7${actions.some((a) => a.endsWith("_script")) ? " + nội dung" : ""}`}
              title="Hành động bật"
            >
              <Chips labels={ACTION_NAMES} onChange={(next) => change({ enabled_actions: next })} options={s.options.actions} value={actions} />
            </SettingRow>
            <SettingRow
              disabled={!canEdit}
              help="Juli soạn · bạn làm"
              onDefault={() => change({ content_cards_enabled: null })}
              overridden={isSet("content_cards_enabled")}
              summary={content ? "Bật" : "Tắt"}
              title="Thẻ nội dung (Video/LIVE)"
            >
              <Toggle label="Thẻ nội dung" on={content} onChange={(v) => change({ content_cards_enabled: v })} />
            </SettingRow>
            <SettingRow
              disabled={!canEdit}
              help="Juli tự tạo khuyến mãi sau khi seller đồng ý"
              onDefault={() => change({ promotion_api_enabled: null })}
              overridden={isSet("promotion_api_enabled")}
              summary={eff("promotion_api_enabled") ? "Bật" : "Tắt"}
              title="API khuyến mãi"
            >
              <Toggle label="API khuyến mãi" on={Boolean(eff("promotion_api_enabled"))} onChange={(v) => change({ promotion_api_enabled: v })} />
            </SettingRow>
            <SettingRow
              disabled={!canEdit}
              help="Vòng gọi tool và soạn nội dung"
              onDefault={() => change({ openai_model: null })}
              overridden={isSet("openai_model")}
              summary={String(eff("openai_model"))}
              title="Model OpenAI"
            >
              <select aria-label="Model OpenAI" onChange={(e) => change({ openai_model: e.target.value })} value={String(eff("openai_model"))}>
                {s.options.models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </SettingRow>
            <SettingRow
              disabled={!canEdit}
              help="Vượt giới hạn: dừng soạn mới, báo đội ngũ"
              onDefault={() => {
                change({ openai_monthly_cap_usd: null });
                setEpoch((e) => e + 1);
              }}
              overridden={isSet("openai_monthly_cap_usd")}
              summary={capShown !== null ? `$${String(capShown).replace(".", ",")} / tháng` : "Không giới hạn"}
              title="Giới hạn chi phí OpenAI"
            >
              <CapEditor key={`cap-${epoch}`} onChange={(v) => change({ openai_monthly_cap_usd: v })} value={capShown} />
            </SettingRow>
          </div>
          {DIAG_KEYS.some((k) => s.defaults[k] !== undefined) ? (
            <DiagSection canEdit={canEdit} change={change} eff={eff} epoch={epoch} isSet={isSet} onEpoch={() => setEpoch((e) => e + 1)} />
          ) : null}
          {QUOTA_KEYS.some((k) => s.defaults[k] !== undefined) ? (
            <QuotaSection canEdit={canEdit} cells={page.card_cells ?? null} change={change} eff={eff} epoch={epoch} isSet={isSet} onEpoch={() => setEpoch((e) => e + 1)} />
          ) : null}
          <OpsCardGroups load={api.groups} shopId={shopId} />
          <OpsRules canEdit={canEdit} shopName={shopName} shopId={shopId} />
        </section>
        <aside style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={card}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Chủ shop và bàn giao</h2>
            <div style={{ fontSize: 14, color: C.body }}>{ownerText}</div>
            {page.shop.owned_by_team && !pendingInvite && canEdit ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: C.muted }}>
                  Email của seller
                  <input
                    onChange={(e) => setInviteEmail(e.target.value)}
                    style={{ font: "inherit", fontSize: 14, border: `1px solid ${C.line}`, borderRadius: 8, minHeight: 40, padding: "0 10px" }}
                    type="email"
                    value={inviteEmail}
                  />
                </label>
                <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
                  <input checked={keep} onChange={(e) => setKeep(e.target.checked)} style={{ width: 18, height: 18, accentColor: C.pinkStrong }} type="checkbox" />
                  Hỏi seller cho đội ngũ giữ quyền Vận hành
                </label>
                <button
                  disabled={!inviteEmail.includes("@")}
                  onClick={() => void sendInvite()}
                  style={{ font: "inherit", fontSize: 14, fontWeight: 600, color: "#fff", background: C.pinkStrong, border: 0, borderRadius: 10, minHeight: 44, cursor: "pointer" }}
                  type="button"
                >
                  Mời seller
                </button>
              </div>
            ) : null}
            {inviteNote ? (
              <span role="status" style={{ fontSize: 13, wordBreak: "break-all" }}>
                {inviteNote}
              </span>
            ) : null}
            <span style={{ fontSize: 12, color: C.muted2 }}>Thẻ, lượt chạy, Quy tắc và lịch sử được giữ nguyên khi bàn giao.</span>
          </div>
          <div style={{ ...card, gap: 8 }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Nhật ký</h2>
            {page.audit.length === 0 ? <span style={{ fontSize: 13, color: C.muted2 }}>Chưa có thao tác nào.</span> : null}
            {page.audit.map((entry) => (
              <div data-testid="ops-audit-row" key={entry.id} style={{ display: "grid", gridTemplateColumns: "92px minmax(0, 1fr)", gap: 8, fontSize: 13, borderTop: `1px solid ${C.lineSoft}`, paddingTop: 6 }}>
                <span style={{ color: C.muted2 }}>{auditWhen(entry.at)}</span>
                <span>
                  <b>{auditWho(entry)}</b> {auditWhat(entry)}
                </span>
              </div>
            ))}
          </div>
        </aside>
      </main>
      {rows.length > 0 && !dialog ? (
        <DraftBar count={rows.length} onDiscard={() => {
            setDraft({});
            setEpoch((e) => e + 1);
          }} onSave={() => setDialog({ kind: "save" })} summary={draftSummary(rows)} />
      ) : null}
      {toast && rows.length === 0 && !dialog ? <Toast onDone={clearToast} text={toast} /> : null}
      {confirmDialog}
    </OpsPage>
  );
}

function Toggle({ on, label, onChange }: { readonly on: boolean; readonly label: string; readonly onChange: (v: boolean) => void }) {
  return (
    <button
      aria-label={label}
      aria-pressed={on}
      onClick={() => onChange(!on)}
      style={{
        font: "inherit",
        fontSize: 13,
        fontWeight: 600,
        borderRadius: 999,
        minHeight: 36,
        padding: "0 14px",
        cursor: "pointer",
        ...(on ? { color: "#ffffff", background: C.pinkStrong, border: 0 } : { color: C.body, background: "#ffffff", border: `1px solid ${C.line}` }),
      }}
      type="button"
    >
      {on ? "Bật" : "Tắt"}
    </button>
  );
}

function LimitEditor({
  keys,
  values,
  labels,
  onChange,
}: {
  readonly keys: readonly OverrideKey[];
  readonly values: readonly number[];
  readonly labels: readonly string[];
  readonly onChange: (patch: Draft) => void;
}) {
  const [text, setText] = useState(values.map(String));
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      {text.map((v, i) => (
        <label key={labels[i]} style={{ display: "flex", gap: 4, alignItems: "center" }}>
          <input
            aria-label={`Giới hạn ${labels[i]}`}
            max={100}
            min={1}
            onChange={(e) => {
              setText(text.map((d, j) => (j === i ? e.target.value : d)));
              const n = Number.parseInt(e.target.value, 10);
              if (Number.isFinite(n) && n > 0) onChange({ [keys[i]]: n });
            }}
            style={{ width: 56 }}
            type="number"
            value={v}
          />
          {labels[i]}
        </label>
      ))}
    </div>
  );
}

function CapEditor({ value, onChange }: { readonly value: number | null; readonly onChange: (v: number) => void }) {
  const [text, setText] = useState(value === null ? "" : String(value));
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      $
      <input
        aria-label="Trần USD mỗi tháng"
        min={0}
        onChange={(e) => {
          setText(e.target.value);
          const n = Number(e.target.value);
          if (e.target.value !== "" && Number.isFinite(n) && n >= 0) onChange(n);
        }}
        step="0.5"
        style={{ width: 80 }}
        type="number"
        value={text}
      />
      / tháng
    </div>
  );
}

const WINDOW_OPTIONS = ["14", "30", "60"];
const WINDOW_LABELS: Record<string, string> = { "14": "14 ngày", "30": "30 ngày", "60": "60 ngày" };

/** One numeric tunable: `scale` 100 shows a fraction as % (0,30 → 30). */
const DIAG_NUMBERS: readonly {
  key: Exclude<DiagKey, "diag_windows">;
  title: string;
  help: string;
  unit: string;
  step: number;
  scale?: number;
  integer?: boolean;
}[] = [
  { key: "diag_min_events", title: "Dữ liệu tối thiểu", help: "Lượt nhấp (CTR) / đơn (CTOR, AOV) trong cửa sổ", unit: "lượt nhấp/đơn", step: 1, integer: true },
  { key: "kpi_min_band_mult", title: "KPI tối thiểu", help: "Mục tiêu ≥ hiện tại + N × dao động", unit: "× dao động", step: 0.5 },
  { key: "kpi_max_band_mult", title: "KPI tối đa", help: "Mục tiêu ≤ hiện tại + N × dao động", unit: "× dao động", step: 0.5 },
  { key: "guard_band_mult", title: "Ngưỡng giữ ổn định", help: "Chỉ số không phải mục tiêu", unit: "× dao động", step: 0.5 },
  { key: "volatile_cv", title: "Ngưỡng lưu lượng ổn định", help: "Lượt hiển thị dao động (CV) trên ngưỡng: KPI dạng khoảng, độ tin cậy Thấp", unit: "% CV", step: 5, scale: 100 },
];

/** P23 (D29.11): "Chẩn đoán & KPI" — collapsed; every row is part of the D27 draft. */
function DiagSection({
  canEdit,
  eff,
  isSet,
  change,
  epoch,
  onEpoch,
}: {
  readonly canEdit: boolean;
  readonly eff: (key: OverrideKey) => unknown;
  readonly isSet: (key: OverrideKey) => boolean;
  readonly change: (patch: Draft) => void;
  readonly epoch: number;
  readonly onEpoch: () => void;
}) {
  const [open, setOpen] = useState(false);
  const overridden = DIAG_KEYS.filter((k) => isSet(k)).length;
  const windows = ((eff("diag_windows") as number[] | null) ?? []).map(String);
  return (
    <div data-testid="ops-diag" style={card}>
      <button
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        style={{ font: "inherit", display: "flex", alignItems: "center", gap: 8, background: "transparent", border: 0, padding: 0, cursor: "pointer", textAlign: "left", color: C.ink }}
        type="button"
      >
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Chẩn đoán &amp; KPI</h2>
        {overridden > 0 ? <span style={{ fontSize: 12, fontWeight: 700, color: C.pink }}>{overridden} ghi đè</span> : null}
        <span aria-hidden="true" style={{ marginLeft: "auto", color: C.muted2 }}>
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open ? (
        <>
          <SettingRow
            disabled={!canEdit}
            help="Ngắn nhất đủ dữ liệu được dùng"
            onDefault={() => change({ diag_windows: null })}
            overridden={isSet("diag_windows")}
            summary={fmtSetting("diag_windows", eff("diag_windows"))}
            title="Cửa sổ chẩn đoán"
          >
            <Chips
              labels={WINDOW_LABELS}
              onChange={(next) => {
                if (next.length > 0) change({ diag_windows: next.map(Number) });
              }}
              options={WINDOW_OPTIONS}
              value={windows}
            />
          </SettingRow>
          {DIAG_NUMBERS.map((row) => (
            <SettingRow
              disabled={!canEdit}
              help={row.help}
              key={row.key}
              onDefault={() => {
                change({ [row.key]: null });
                onEpoch();
              }}
              overridden={isSet(row.key)}
              summary={fmtSetting(row.key, eff(row.key))}
              title={row.title}
            >
              <NumEditor
                integer={row.integer}
                key={`${row.key}-${epoch}`}
                label={row.title}
                onChange={(v) => change({ [row.key]: v })}
                scale={row.scale ?? 1}
                step={row.step}
                unit={row.unit}
                value={eff(row.key) as number | null}
              />
            </SettingRow>
          ))}
          <SettingRow
            disabled={!canEdit}
            help="Một chỉ số giảm: mở thẻ khi Lượt hiển thị, CTR, CTOR hoặc AOV giảm quá dao động, kể cả khi GMV giữ được. GMV giảm (cũ): chỉ khi GMV giảm"
            onDefault={() => change({ diag_trigger: null })}
            overridden={isSet("diag_trigger")}
            summary={fmtSetting("diag_trigger", eff("diag_trigger"))}
            title="Điều kiện mở thẻ"
          >
            <select aria-label="Điều kiện mở thẻ" onChange={(e) => change({ diag_trigger: e.target.value })} value={String(eff("diag_trigger") ?? "metric_first")}>
              {Object.entries(TRIGGER_NAMES).map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </SettingRow>
          {eff("kpi_shrinkage") !== undefined ? (
            <SettingRow
              disabled={!canEdit}
              help="Bật: CTR và CTOR của sản phẩm ít lượt hiển thị / lượt nhấp được kéo về mức chung của ngành hàng trong shop trước khi so với dao động, nên một lần giảm do may rủi không mở thẻ. Sản phẩm nhiều dữ liệu gần như không đổi. Chỉ ảnh hưởng việc mở thẻ, không đổi KPI"
              onDefault={() => change({ kpi_shrinkage: null })}
              overridden={isSet("kpi_shrinkage")}
              summary={fmtSetting("kpi_shrinkage", eff("kpi_shrinkage"))}
              title="Lọc nhiễu CTR / CTOR"
            >
              <select aria-label="Lọc nhiễu CTR / CTOR" onChange={(e) => change({ kpi_shrinkage: e.target.value })} value={String(eff("kpi_shrinkage") ?? "on")}>
                {Object.entries(SHRINKAGE_NAMES).map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </select>
            </SettingRow>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

/** Cell id ("ctr@product_card") in the team's words. */
const CELL_METRIC: Record<string, string> = { impressions: "Lượt hiển thị", ctr: "CTR", ctor: "CTOR", aov: "AOV" };
const CELL_CHANNEL: Record<string, string> = { product_card: "Thẻ sản phẩm", total: "tất cả kênh" };
const CELL_NAMES: Record<string, string> = { content_video: "Video (nội dung)", content_live: "LIVE (nội dung)", other: "Khác" };

function cellName(cell: string): string {
  if (CELL_NAMES[cell]) return CELL_NAMES[cell];
  const [metric, channel] = cell.split("@");
  return `${CELL_METRIC[metric] ?? metric} · ${CELL_CHANNEL[channel] ?? channel}`;
}

/** P28 (D33): "Nhiều thẻ mỗi ô" — opt-in per shop (Admin); the open cards per cell while on. */
function QuotaSection({
  canEdit,
  cells,
  eff,
  isSet,
  change,
  epoch,
  onEpoch,
}: {
  readonly canEdit: boolean;
  readonly cells: Readonly<Record<string, number>> | null;
  readonly eff: (key: OverrideKey) => unknown;
  readonly isSet: (key: OverrideKey) => boolean;
  readonly change: (patch: Draft) => void;
  readonly epoch: number;
  readonly onEpoch: () => void;
}) {
  const on = Boolean(eff("card_quota_mode"));
  const perCell = Number(eff("card_quota_per_cell") ?? 5);
  return (
    <div data-testid="ops-quota" style={card}>
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Nhiều thẻ mỗi ô (thử nghiệm)</h2>
      <SettingRow
        disabled={!canEdit}
        help="Thay 3/1/1 thẻ mỗi ngày bằng tối đa N thẻ mở cho mỗi chỉ số × kênh"
        onDefault={() => change({ card_quota_mode: null })}
        overridden={isSet("card_quota_mode")}
        summary={on ? "Bật" : "Tắt"}
        title="Nhiều thẻ mỗi ô"
      >
        <Toggle label="Nhiều thẻ mỗi ô" on={on} onChange={(v) => change({ card_quota_mode: v })} />
      </SettingRow>
      {(
        [
          ["card_quota_per_cell", "Thẻ mở mỗi ô", "Mỗi chỉ số × kênh (và Video, LIVE)", "thẻ/ô"],
          ["card_quota_max_open", "Thẻ mở tối đa (nhiều thẻ)", "Quy tắc Số thẻ mở cùng lúc của người bán vẫn thắng", "thẻ"],
        ] as const
      ).map(([key, title, help, unit]) => (
        <SettingRow
          disabled={!canEdit}
          help={help}
          key={key}
          onDefault={() => {
            change({ [key]: null });
            onEpoch();
          }}
          overridden={isSet(key)}
          summary={fmtSetting(key, eff(key))}
          title={title}
        >
          <NumEditor integer key={`${key}-${epoch}`} label={title} onChange={(v) => change({ [key]: v })} scale={1} step={1} unit={unit} value={eff(key) as number | null} />
        </SettingRow>
      ))}
      <SettingRow
        disabled={!canEdit}
        help="Mỗi nhóm (chỉ số × thay đổi × kênh) từ 3 thẻ: khoảng 1/3 sản phẩm chọn ngẫu nhiên nhận thẻ sau 14 ngày để so sánh. Mặc định theo Nhiều thẻ mỗi ô"
        onDefault={() => change({ card_groups: null })}
        overridden={isSet("card_groups")}
        summary={isSet("card_groups") ? fmtSetting("card_groups", eff("card_groups")) : `Theo Nhiều thẻ mỗi ô (${on ? "Bật" : "Tắt"})`}
        title="Nhóm thử nghiệm (đối chứng chậm)"
      >
        <Toggle
          label="Nhóm thử nghiệm"
          on={isSet("card_groups") ? Boolean(eff("card_groups")) : on}
          onChange={(v) => change({ card_groups: v })}
        />
      </SettingRow>
      {on && cells ? (
        <div data-testid="ops-quota-cells" style={{ borderTop: `1px solid ${C.lineSoft}`, paddingTop: 10, fontSize: 13, display: "flex", flexDirection: "column", gap: 4 }}>
          <b>Thẻ đang mở theo ô</b>
          {Object.keys(cells).length === 0 ? <span style={{ color: C.muted2 }}>Chưa có thẻ mở.</span> : null}
          {Object.entries(cells).map(([cell, count]) => (
            <span key={cell}>
              {cellName(cell)}: {count}/{perCell}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function NumEditor({
  value,
  label,
  unit,
  step,
  scale,
  integer,
  onChange,
}: {
  readonly value: number | null;
  readonly label: string;
  readonly unit: string;
  readonly step: number;
  readonly scale: number;
  readonly integer?: boolean;
  readonly onChange: (v: number) => void;
}) {
  const [text, setText] = useState(value === null || value === undefined ? "" : String(Math.round(value * scale * 100) / 100));
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <input
        aria-label={label}
        min={0}
        onChange={(e) => {
          setText(e.target.value);
          const n = Number(e.target.value.replace(",", "."));
          if (e.target.value === "" || !Number.isFinite(n) || n <= 0 || (integer && !Number.isInteger(n))) return;
          onChange(scale === 1 ? n : Math.round((n / scale) * 10_000) / 10_000);
        }}
        step={step}
        style={{ width: 80 }}
        type="number"
        value={text}
      />
      {unit}
    </div>
  );
}
