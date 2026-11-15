"use client";

import { useEffect, useState } from "react";

import { DASH, fmt } from "../../lib/shopee-analytics/format";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { useReco } from "../../lib/shopee-decisions/context";
import type { ExecutionCard, ExecutionState, ReaderBlock } from "../../lib/shopee-decisions/types";
import { useSampleShopReviewer } from "../../lib/reviewer/mode";
import { fillJobHref } from "../planned-changes/listing-extras";
import { TextChip } from "../shopee-analytics/ui";
import { errorText, NavLink, RecoState } from "./ui";

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
const STATE_LABEL: Record<ExecutionState, string> = { cho_dien: "Chờ điền", da_dien: "Đã điền · chờ bạn lưu", khop: "Khớp Seller Centre", lech: "Lệch Seller Centre" };
const STATE_TONE: Record<ExecutionState, "flat" | "warn" | "up" | "down"> = { cho_dien: "flat", da_dien: "warn", khop: "up", lech: "down" };
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

/** Connector 0.3.22: one short line per blocked section ("Đăng nhập lại Phân tích bán hàng"). */
export function readerBlockText(blocks: readonly ReaderBlock[] | undefined): string | null {
  const lines = [
    ...new Set(
      (blocks ?? []).map((b) => `${b.reason === "captcha" ? "Xác minh lại" : "Đăng nhập lại"} ${SECTION_LABEL[b.section] ?? "Seller Centre"}`),
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

function Row({
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
  const href = c.open_job ? fillJobHref(c.open_job) : null;
  const markDone = async () => {
    setBusy(true);
    setError(null);
    try {
      await host.reco.executed(c.card_id, {});
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
      <Steps c={c} sample={sample} />
      <div className="sd-th-row__side">
        <span data-testid={`sd-th-state-${c.card_id}`}>
          <TextChip tone={STATE_TONE[c.state]}>{STATE_LABEL[c.state]}</TextChip>
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
            ) : (
              <button className="sa-btn sa-btn--primary" disabled type="button">
                Mở Seller Centre
              </button>
            )
          ) : null}
          {(c.state === "da_dien" || (sample && c.state === "cho_dien")) && !c.executed_at ? (
            <button className="sa-btn" disabled={readOnly || busy} onClick={() => void markDone()} type="button">
              Đã làm
            </button>
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
  const count = res.status === "ready" ? res.data.cards.length : null;
  useEffect(() => {
    if (count !== null) onCount?.(count);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [count]);
  return (
    <RecoState resource={res}>
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
