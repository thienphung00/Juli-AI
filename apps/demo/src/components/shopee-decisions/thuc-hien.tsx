"use client";

import { useEffect, useState } from "react";

import { DASH, fmt } from "../../lib/shopee-analytics/format";
import { useResource, type Resource } from "../../lib/shopee-analytics/use-resource";
import { useReco } from "../../lib/shopee-decisions/context";
import { FILLABLE_CHANGE_KINDS } from "../../lib/shopee-decisions/model";
import type { ExecutionCard, ExecutionState, ExecutionStates, ReaderBlock } from "../../lib/shopee-decisions/types";
import { useSampleShopReviewer } from "../../lib/reviewer/mode";
import { fillJobHref } from "../planned-changes/listing-extras";
import { TextChip } from "../shopee-analytics/ui";
import { errorText, NavLink, RecoState } from "./ui";
import { BoardActions } from "./board-actions";

/**
 * Quyết định › Thực hiện: Juli Connector fills Seller Centre, the seller saves, the Connector reads
 * it back. One row per approved card with the four steps, its state and what it can do next. Data
 * comes through the host's RecoApi; the same view serves the seller, Ops and the reviewer's sample
 * shop (read-only).
 */

const STEPS = ["Đã duyệt", "Connector điền", "Bạn lưu", "Khớp Seller Centre"] as const;
/**
 * P100 S2-D4 (owner, 2026-11-14): the reviewer's sample shop has no Juli Connector. No Connector
 * bar, no "Mở Seller Centre" and no Connector step: the reviewer fills Seller Centre and presses
 * "Đã làm" (an admitted sample write), as a seller without the extension would.
 */
const SAMPLE_STEPS = ["Đã duyệt", "Bạn điền", "Bạn lưu", "Khớp Seller Centre"] as const;
/** The cards whose execution is a voucher that Juli reads back by its code. */
const VOUCHER_KINDS = new Set(["min_spend_voucher", "review_voucher", "voucher_cap", "voucher"]);
const STATE_LABEL: Record<ExecutionState, string> = { cho_dien: "Chờ điền", da_dien: "Đã điền · chờ bạn lưu", khop: "Khớp Seller Centre", lech: "Lệch Seller Centre", hoan_tac: "Đã hoàn tác" };
const STATE_TONE: Record<ExecutionState, "flat" | "warn" | "up" | "down"> = { cho_dien: "flat", da_dien: "warn", khop: "up", lech: "down", hoan_tac: "flat" };
/** The chip of a card: once the seller pressed "Đã làm" (the "Bạn lưu" step is done) it waits for Seller Centre's read-back. */
export function stateLabel(c: ExecutionCard): string {
  if (c.state === "da_dien" && (c.executed_at || c.completed >= 3)) return "Đã lưu · chờ xác minh";
  return STATE_LABEL[c.state];
}
const MONEY = new Set(["min_spend", "discount_amount", "max_value", "current_price", "list_price", "total_budget"]);

function dm(iso: string | null): string {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  return m ? `${m[3]}/${m[2]}` : DASH;
}

function hhmm(iso: string | null): string {
  const m = iso ? /T(\d{2}):(\d{2})/.exec(iso) : null;
  return m ? `${m[1]}:${m[2]}` : DASH;
}

/** A Seller Centre / card value with its unit by field. */
const SECTION_LABEL: Record<string, string> = { phan_tich_ban_hang: "Phân tích bán hàng", seller_centre: "Seller Centre" };

const BLOCK_VERB: Record<string, string> = {
  captcha: "Xác minh lại",
  password_recheck: "Xác nhận mật khẩu",
  no_permission: "Cần quyền Tài chính",
};

/** Shopee's traffic check: "Juli dừng đến HH:mm" (GMT+7) when the Connector said until when. */
function trafficCheckText(until: string | null | undefined): string {
  const ms = until ? Date.parse(until) : Number.NaN;
  if (Number.isNaN(ms)) return "Shopee tạm chặn";
  const d = new Date(ms + 7 * 3600_000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `Shopee tạm chặn — Juli dừng đến ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

/** Connector 0.3.22: one short line per blocked section ("Đăng nhập lại Phân tích bán hàng"). */
export function readerBlockText(blocks: readonly ReaderBlock[] | undefined): string | null {
  const lines = [
    ...new Set(
      (blocks ?? []).map((b) =>
        b.reason === "traffic_check"
          ? trafficCheckText(b.until)
          : `${BLOCK_VERB[b.reason] ?? "Đăng nhập lại"} ${SECTION_LABEL[b.section] ?? "Seller Centre"}`,
      ),
    ),
  ];
  return lines.length > 0 ? lines.join(" · ") : null;
}

export function valueText(field: string | null, v: unknown): string {
  if (typeof v === "number") {
    if (field === "daily_budget") return `${fmt(v, 0)} đ/ngày`;
    if (field && MONEY.has(field)) return `${fmt(v, 0)} đ`;
    if (field && (field.endsWith("_percent") || field.endsWith("_pct"))) return `${fmt(v, 0)} %`;
    return fmt(v, field === "roas_target" ? 1 : 0);
  }
  if (v === null || v === undefined) return DASH;
  return typeof v === "string" ? v : JSON.stringify(v);
}

export function detailOf(c: ExecutionCard): string {
  if (c.state === "hoan_tac") return "Đã dừng đo lường";
  if (c.state === "khop") return `Đo từ ${dm(c.measure_start)}${c.measure_days ? ` · ${fmt(c.measure_days, 0)} ngày` : ""}`;
  if (c.state === "lech" && c.mismatch) return `Seller Centre ${valueText(c.mismatch.field, c.mismatch.observed)} · thẻ ${valueText(c.mismatch.field, c.mismatch.expected)}`;
  if (c.state === "da_dien" && c.not_seen) return "Chưa thấy thay đổi";
  return c.fields.total > 0 ? `${fmt(c.fields.filled, 0)}/${fmt(c.fields.total, 0)} đã điền` : DASH;
}

function Steps({ c, sample }: { readonly c: ExecutionCard; readonly sample: boolean }) {
  return (
    <ol aria-label="Tiến độ" className="sd-th-steps" data-testid={`sd-th-steps-${c.card_id}`}>
      {(sample ? SAMPLE_STEPS : STEPS).map((label, i) => {
        const done = i < c.completed;
        const bad = c.bad === i;
        return (
          <li className={`sd-th-step${done ? " sd-th-step--done" : ""}${bad ? " sd-th-step--bad" : ""}`} data-testid={`sd-th-step-${c.card_id}-${i + 1}`} key={label}>
            <span aria-hidden="true" className="sd-th-step__dot" />
            <span className="sd-th-step__label">{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** A kind the Connector does not fill: the status line and the sheet's own Seller Centre page. */
function ManualPage({ cardId }: { readonly cardId: string }) {
  const host = useReco();
  const res = useResource(() => host.reco.detail(cardId), `${host.shopKey}|th-page|${cardId}`);
  const link = res.status === "ready" ? (res.data.card.execution_sheet?.page?.deep_link ?? null) : null;
  return (
    <span className="sd-th-row__manual" data-testid={`sd-th-manual-${cardId}`}>
      <span>Connector chưa điền loại thẻ này — làm theo bảng thao tác</span>
      {link ? (
        <a className="sa-btn sa-btn--primary" href={link} rel="noopener noreferrer" target="_blank">
          Mở trang
        </a>
      ) : (
        <NavLink className="sa-btn" href={host.href({ the: cardId })}>
          Mở trang
        </NavLink>
      )}
    </span>
  );
}

export function Row({
  c,
  name,
  readOnly,
  sample,
  onDone,
}: {
  readonly c: ExecutionCard;
  readonly name: string | null;
  readonly readOnly: boolean;
  readonly sample: boolean;
  readonly onDone: () => void;
}) {
  const host = useReco();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // UI grill G14: a voucher needs its Seller Centre code to be read back; the row asks for it (the
  // sample shop has none to give: the server gives it a sample code).
  const needsCode = !sample && VOUCHER_KINDS.has(c.change_kind);
  // the captured code can arrive on a later refresh (after Lưu, or the Connector's next voucher read):
  // it fills the field until the seller types their own
  const [typed, setTyped] = useState<string | null>(null);
  const code = typed ?? c.captured_voucher_id ?? "";
  const setCode = (v: string) => setTyped(v);
  const href = c.open_job ? fillJobHref(c.open_job) : null;
  const markDone = async () => {
    setBusy(true);
    setError(null);
    try {
      await host.reco.executed(c.card_id, needsCode ? { voucherId: code.trim() || null } : {});
      onDone();
    } catch (e) {
      // P100 S2-F2: a refusal (e.g. a voucher needs its Seller Centre code) is said, never silent
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className={`sd-th-row${c.state === "lech" ? " sd-th-row--bad" : ""}`} data-testid={`sd-th-${c.card_id}`}>
      <div className="sd-th-row__main">
        <span className="sd-th-row__group">{c.family_label}</span>
        <NavLink className="sd-th-row__title" href={host.href({ the: c.card_id })}>
          {c.title}
        </NavLink>
        {name ? <span className="sd-th-row__product">{name}</span> : null}
      </div>
      {c.state === "hoan_tac" ? <span /> : <Steps c={c} sample={sample} />}
      <div className="sd-th-row__side">
        <span data-testid={`sd-th-state-${c.card_id}`}>
          <TextChip tone={STATE_TONE[c.state]}>{stateLabel(c)}</TextChip>
        </span>
        <span className="sd-th-row__detail" data-testid={`sd-th-detail-${c.card_id}`}>
          {detailOf(c)}
        </span>
        <span className="sd-th-row__actions">
          {c.state === "lech" ? (
            <>
              <button className="sa-btn" disabled type="button">
                Dùng số Seller Centre
              </button>
              <button className="sa-btn sa-btn--primary" disabled type="button">
                Điền lại
              </button>
            </>
          ) : null}
          {c.state === "khop" ? (
            <NavLink className="sa-btn" href={host.href({ tab: "do-luong" })}>
              Xem đo lường
            </NavLink>
          ) : null}
          {(c.state === "cho_dien" || c.state === "da_dien") && !sample ? (
            readOnly ? null : href ? (
              <a className="sa-btn sa-btn--primary" href={href} rel="noopener noreferrer" target="_blank">
                Mở Seller Centre
              </a>
            ) : !FILLABLE_CHANGE_KINDS.includes(c.change_kind) ? (
              <ManualPage cardId={c.card_id} />
            ) : (
              <button className="sa-btn sd-btn--off" disabled type="button">
                Mở Seller Centre
              </button>
            )
          ) : null}
          {(c.state === "da_dien" || (sample && c.state === "cho_dien")) && !c.executed_at ? (
            <>
              {needsCode ? (
                <input aria-label="Mã voucher" className="sd-th-row__code" data-testid={`sd-th-code-${c.card_id}`} disabled={readOnly} inputMode="numeric" onChange={(e) => setCode(e.target.value)} placeholder="Mã voucher" type="text" value={code} />
              ) : null}
              <button className="sa-btn" disabled={readOnly || busy || (needsCode && code.trim() === "")} onClick={() => void markDone()} type="button">
                Đã làm
              </button>
            </>
          ) : null}
        </span>
        {error ? (
          <p className="sd-error" data-testid={`sd-th-error-${c.card_id}`} role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </li>
  );
}

export function ThucHienView({ onCount }: { readonly onCount?: (n: number) => void }) {
  const host = useReco();
  const sample = useSampleShopReviewer();
  const readOnly = !!host.readOnly;
  const [tick, setTick] = useState(0);
  const res = useResource(() => host.reco.executionStates(), `${host.shopKey}|thuc-hien|${tick}`);
  // F6.1: a refetch (tick) must not unmount the page: the "Xoá bảng" confirm and the import panel keep
  // their state. While the next answer is on its way the last one of this shop stays on screen.
  const [kept, setKept] = useState<{ readonly shop: string; readonly data: ExecutionStates } | null>(null);
  if (res.status === "ready" && kept?.data !== res.data) setKept({ shop: host.shopKey, data: res.data });
  const shown: Resource<ExecutionStates> = res.status === "loading" && kept && kept.shop === host.shopKey ? { status: "ready", data: kept.data } : res;
  const names = useResource(async () => new Map((await (host.products?.() ?? Promise.resolve([]))).map((p) => [p.id, p.name])), `${host.shopKey}|products`);
  const [asking, setAsking] = useState(false);
  const reconcile = async () => {
    setAsking(true);
    try {
      await host.reco.reconcile();
      setTick((t) => t + 1);
    } finally {
      setAsking(false);
    }
  };
  // F3.2: a card saved and waiting for its read-back turns Khớp / Lệch as soon as the API says so (15 s poll)
  const waiting = res.status === "ready" && !sample && res.data.cards.some((c) => c.state === "da_dien" && (c.executed_at || c.completed >= 3));
  useEffect(() => {
    if (!waiting) return;
    const timer = setTimeout(() => setTick((t) => t + 1), 15_000);
    return () => clearTimeout(timer);
  }, [waiting, tick]);
  const count = res.status === "ready" ? res.data.cards.length : null;
  useEffect(() => {
    if (count !== null) onCount?.(count);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [count]);
  return (
    <RecoState resource={shown}>
      {(data) => {
        const k = data.connector;
        const blocked = readerBlockText(k.reader_blocks);
        return (
          <div className="sd-th" data-testid="sd-thuc-hien">
            {sample ? null : (
            <section aria-label="Juli Connector" className="sd-th-bar" data-testid="sd-th-bar">
              <span aria-hidden="true" className={`sd-th-bar__dot${k.connected ? " sd-th-bar__dot--on" : ""}`} />
              <b>Juli Connector{k.version ? ` ${k.version}` : ""}</b>
              <span>
                {k.seller_centre_open ? "Seller Centre đang mở · " : ""}
                {k.last_check_at ? `đối chiếu lần cuối ${hhmm(k.last_check_at)}` : "chưa đối chiếu"}
              </span>
              {k.upgrade_required && k.min_version ? (
                <span className="sd-th-bar__block" data-testid="sd-th-bar-upgrade">
                  Cập nhật Juli Connector lên {k.min_version}
                </span>
              ) : null}
              {blocked ? (
                <span className="sd-th-bar__block" data-testid="sd-th-bar-block">
                  {blocked}
                </span>
              ) : null}
              {readOnly ? null : (
                <button className="sa-btn sd-th-bar__sync" disabled={!k.connected || !!k.reconcile_pending || asking} onClick={() => void reconcile()} type="button">
                  Đối chiếu ngay
                </button>
              )}
            </section>
            )}
            {host.reco.board && !sample && !readOnly && !host.staff ? <BoardActions board={host.reco.board} onChanged={() => setTick((t) => t + 1)} /> : null}
            <ul className="sd-th-list">
              {data.cards.map((c) => (
                <Row c={c} key={c.card_id} name={(names.status === "ready" && c.product_id ? names.data.get(c.product_id) : null) ?? null} onDone={() => setTick((t) => t + 1)} readOnly={readOnly} sample={sample} />
              ))}
            </ul>
          </div>
        );
      }}
    </RecoState>
  );
}
