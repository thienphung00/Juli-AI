"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";

import { opsApi, type OpsApi } from "../../lib/ops/api";
import type { OpsMe, OverrideKey, ShopSettings, ShopSettingsPage, StageId } from "../../lib/ops/types";
import { auditWhat, auditWhen, auditWho } from "./audit-text";
import { C, OpsHeader, OpsPage, STAGE_STYLE, card } from "./ops-shell";

/** "Cài đặt shop" — artboard OpsShopSettings.dc.html (D25.4, D25.7). */

const STAGES: [StageId, string, string][] = [
  ["trial", "Thử nghiệm", "Đội ngũ nhập liệu, theo dõi sát"],
  ["self", "Tự vận hành", "Seller tự dùng"],
  ["pilot", "Pilot đặc biệt", "Cấu hình riêng, ưu tiên hỗ trợ"],
];
const STREAM_LABEL: Record<string, string> = { product_card: "Thẻ SP", shop_tab: "Tab", seller_video: "Video", seller_live: "LIVE" };
const ACTION_LABEL: Record<string, string> = {
  cover_image: "Ảnh bìa",
  title: "Tiêu đề",
  description: "Mô tả",
  product_discount: "Giảm giá SP",
  buy_more_save_more: "Mua nhiều giảm nhiều",
  flash_sale: "Flash sale",
  shipping_discount: "Giảm phí ship",
  video_script: "Kịch bản video",
  live_script: "Kịch bản LIVE",
};
const OWN: CSSProperties = { background: "#fff7fa", borderColor: "#f8b9d3", fontWeight: 600 };

type Api = Pick<OpsApi, "settings" | "putSettings" | "resetSettings" | "invite">;

function eff(settings: ShopSettings, key: OverrideKey): unknown {
  const o = settings.overrides[key];
  return o === null || o === undefined ? settings.defaults[key] : o;
}

function isSet(settings: ShopSettings, key: OverrideKey): boolean {
  const o = settings.overrides[key];
  return o !== null && o !== undefined;
}

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

function Checks({
  options,
  value,
  labels,
  onChange,
}: {
  readonly options: readonly string[];
  readonly value: readonly string[];
  readonly labels: Record<string, string>;
  readonly onChange: (next: string[]) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
      {options.map((id) => (
        <label key={id} style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input
            checked={value.includes(id)}
            onChange={(e) => onChange(e.target.checked ? [...value, id] : value.filter((v) => v !== id))}
            type="checkbox"
          />
          {labels[id] ?? id}
        </label>
      ))}
    </div>
  );
}

export function OpsShopSettings({ me, shopId, api = opsApi }: { readonly me: OpsMe; readonly shopId: string; readonly api?: Api }) {
  const [page, setPage] = useState<ShopSettingsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [keep, setKeep] = useState(true);
  const [inviteNote, setInviteNote] = useState<string | null>(null);
  const canEdit = me.role !== "viewer";

  const load = useCallback(() => {
    api
      .settings(shopId)
      .then(setPage)
      .catch(() => setError("Không tải được cài đặt."));
  }, [api, shopId]);

  useEffect(() => {
    load();
  }, [load]);

  const save = async (changes: Record<string, unknown>) => {
    setError(null);
    try {
      await api.putSettings(shopId, changes);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không lưu được.");
    }
  };

  if (!page) {
    return (
      <OpsPage>
        <OpsHeader back me={me} />
        <main style={{ padding: "24px 28px" }}>{error ? <p role="alert">{error}</p> : <p role="status">Đang tải…</p>}</main>
      </OpsPage>
    );
  }
  const s = page.settings;
  const limits = [eff(s, "card_daily_limit"), eff(s, "card_weekly_limit"), eff(s, "card_open_limit")];
  const streams = (eff(s, "enabled_streams") as string[]) ?? [];
  const actions = (eff(s, "enabled_actions") as string[]) ?? [];
  const content = eff(s, "content_cards_enabled") as boolean;
  const cap = s.overrides.openai_monthly_cap_usd as number | null;
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

  return (
    <OpsPage>
      <OpsHeader back me={me} />
      <main className="ops-settings" style={{ padding: "24px 28px", display: "grid", gridTemplateColumns: "minmax(0, 1.6fr) minmax(0, 1fr)", gap: 20, alignItems: "start" }}>
        <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>{page.shop.shop_name}</h1>
            <span style={{ fontSize: 12, fontWeight: 600, borderRadius: 999, padding: "3px 10px", ...STAGE_STYLE[s.stage] }}>{s.stage_label}</span>
            <Link href={`/ops/shops/${shopId}/mo-phong`} style={{ marginLeft: "auto", fontSize: 14, fontWeight: 600, textDecoration: "none", color: C.pink }}>
              Mô phỏng ›
            </Link>
            <Link href={`/ops/shops/${shopId}/xem`} style={{ fontSize: 14, fontWeight: 600, textDecoration: "none", color: C.pink }}>
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
                    onClick={() => void save({ stage: id })}
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
                disabled={!canEdit}
                onClick={async () => {
                  await api.resetSettings(shopId);
                  load();
                }}
                style={{ marginLeft: "auto", font: "inherit", fontSize: 13, fontWeight: 600, color: C.pink, background: "transparent", border: 0, minHeight: 36, cursor: "pointer" }}
                type="button"
              >
                Về mặc định
              </button>
            </div>
            <SettingRow
              disabled={!canEdit}
              help="D24.17"
              onDefault={() => void save({ card_daily_limit: null, card_weekly_limit: null, card_open_limit: null })}
              overridden={isSet(s, "card_daily_limit") || isSet(s, "card_weekly_limit") || isSet(s, "card_open_limit")}
              summary={`${limits[0]}/ngày · ${limits[1]}/tuần · ${limits[2]} mở`}
              title="Giới hạn thẻ"
            >
              <LimitEditor
                labels={["/ngày", "/tuần", "mở"]}
                onSave={(v) => void save({ card_daily_limit: v[0], card_weekly_limit: v[1], card_open_limit: v[2] })}
                values={limits as number[]}
              />
            </SettingRow>
            <SettingRow
              disabled={!canEdit}
              help="Tắt luồng không phù hợp với shop"
              onDefault={() => void save({ enabled_streams: null })}
              overridden={isSet(s, "enabled_streams")}
              summary={streams.map((id) => STREAM_LABEL[id] ?? id).join(" · ") || "Không luồng nào"}
              title="Luồng được đề xuất"
            >
              <Checks labels={STREAM_LABEL} onChange={(next) => void save({ enabled_streams: next })} options={s.options.streams.map((x) => x.id)} value={streams} />
            </SettingRow>
            <SettingRow
              disabled={!canEdit}
              help="Ví dụ tắt Flash sale nếu shop không đủ điều kiện"
              onDefault={() => void save({ enabled_actions: null })}
              overridden={isSet(s, "enabled_actions")}
              summary={`${actions.filter((a) => !a.endsWith("_script")).length}/7${actions.some((a) => a.endsWith("_script")) ? " + nội dung" : ""}`}
              title="Hành động bật"
            >
              <Checks labels={ACTION_LABEL} onChange={(next) => void save({ enabled_actions: next })} options={s.options.actions} value={actions} />
            </SettingRow>
            <SettingRow
              disabled={!canEdit}
              help="Juli soạn · bạn làm"
              onDefault={() => void save({ content_cards_enabled: null })}
              overridden={isSet(s, "content_cards_enabled")}
              summary={content ? "Bật" : "Tắt"}
              title="Thẻ nội dung (Video/LIVE)"
            >
              <Toggle on={content} onChange={(v) => void save({ content_cards_enabled: v })} />
            </SettingRow>
            <SettingRow
              disabled={!canEdit}
              help="Juli tự tạo khuyến mãi sau khi seller đồng ý"
              onDefault={() => void save({ promotion_api_enabled: null })}
              overridden={isSet(s, "promotion_api_enabled")}
              summary={eff(s, "promotion_api_enabled") ? "Bật" : "Tắt"}
              title="API khuyến mãi"
            >
              <Toggle on={Boolean(eff(s, "promotion_api_enabled"))} onChange={(v) => void save({ promotion_api_enabled: v })} />
            </SettingRow>
            <SettingRow
              disabled={!canEdit}
              help="Vòng gọi tool và soạn nội dung"
              onDefault={() => void save({ openai_model: null })}
              overridden={isSet(s, "openai_model")}
              summary={String(eff(s, "openai_model"))}
              title="Model OpenAI"
            >
              <select aria-label="Model OpenAI" onChange={(e) => void save({ openai_model: e.target.value })} value={String(eff(s, "openai_model"))}>
                {s.options.models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </SettingRow>
            <SettingRow
              disabled={!canEdit}
              help="Vượt trần: dừng soạn mới, báo đội ngũ"
              onDefault={() => void save({ openai_monthly_cap_usd: null })}
              overridden={cap !== null}
              summary={cap !== null ? `$${String(cap).replace(".", ",")} / tháng` : "Không giới hạn"}
              title="Trần chi phí OpenAI"
            >
              <CapEditor onSave={(v) => void save({ openai_monthly_cap_usd: v })} value={cap} />
            </SettingRow>
          </div>
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
    </OpsPage>
  );
}

function Toggle({ on, onChange }: { readonly on: boolean; readonly onChange: (v: boolean) => void }) {
  return (
    <label style={{ display: "flex", gap: 6 }}>
      <input checked={on} onChange={(e) => onChange(e.target.checked)} type="checkbox" />
      Bật
    </label>
  );
}

function LimitEditor({ values, labels, onSave }: { readonly values: number[]; readonly labels: string[]; readonly onSave: (v: number[]) => void }) {
  const [draft, setDraft] = useState(values.map(String));
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      {draft.map((v, i) => (
        <label key={labels[i]} style={{ display: "flex", gap: 4, alignItems: "center" }}>
          <input
            aria-label={`Giới hạn ${labels[i]}`}
            max={100}
            min={1}
            onChange={(e) => setDraft(draft.map((d, j) => (j === i ? e.target.value : d)))}
            style={{ width: 56 }}
            type="number"
            value={v}
          />
          {labels[i]}
        </label>
      ))}
      <button onClick={() => onSave(draft.map((d) => Number.parseInt(d, 10)))} type="button">
        Lưu
      </button>
    </div>
  );
}

function CapEditor({ value, onSave }: { readonly value: number | null; readonly onSave: (v: number) => void }) {
  const [draft, setDraft] = useState(value === null ? "" : String(value));
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      $
      <input aria-label="Trần USD mỗi tháng" min={0} onChange={(e) => setDraft(e.target.value)} step="0.5" style={{ width: 80 }} type="number" value={draft} />
      / tháng
      <button disabled={draft === ""} onClick={() => onSave(Number(draft))} type="button">
        Lưu
      </button>
    </div>
  );
}
