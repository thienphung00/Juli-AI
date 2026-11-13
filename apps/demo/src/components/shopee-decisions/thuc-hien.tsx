"use client";

import { useEffect, useState } from "react";

import { DASH, fmt } from "../../lib/shopee-analytics/format";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { useReco } from "../../lib/shopee-decisions/context";
import type { ExecutionCard, ExecutionState } from "../../lib/shopee-decisions/types";
import { useSampleShopReviewer } from "../../lib/reviewer/mode";
import { fillJobHref } from "../planned-changes/listing-extras";
import { TextChip } from "../shopee-analytics/ui";
import { NavLink, RecoState } from "./ui";

/**
 * Quyết định › Thực hiện: Juli Connector fills Seller Centre, the seller saves, the Connector reads
 * it back. One row per approved card with the four steps, its state and what it can do next. Data
 * comes through the host's RecoApi; the same view serves the seller, Ops and the reviewer's sample
 * shop (read-only).
 */

const STEPS = ["Đã duyệt", "Connector điền", "Bạn lưu", "Khớp Seller Centre"] as const;
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

function Steps({ c }: { readonly c: ExecutionCard }) {
  return (
    <ol aria-label="Tiến độ" className="sd-th-steps" data-testid={`sd-th-steps-${c.card_id}`}>
      {STEPS.map((label, i) => {
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

function Row({ c, name, readOnly, onDone }: { readonly c: ExecutionCard; readonly name: string | null; readonly readOnly: boolean; readonly onDone: () => void }) {
  const host = useReco();
  const [busy, setBusy] = useState(false);
  const href = c.open_job ? fillJobHref(c.open_job) : null;
  const markDone = async () => {
    setBusy(true);
    try {
      await host.reco.executed(c.card_id, {});
      onDone();
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
      <Steps c={c} />
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
          {c.state === "cho_dien" || c.state === "da_dien" ? (
            href && !readOnly ? (
              <a className="sa-btn sa-btn--primary" href={href} rel="noopener noreferrer" target="_blank">
                Mở Seller Centre
              </a>
            ) : (
              <button className="sa-btn sa-btn--primary" disabled type="button">
                Mở Seller Centre
              </button>
            )
          ) : null}
          {c.state === "da_dien" && !c.executed_at ? (
            <button className="sa-btn" disabled={readOnly || busy} onClick={() => void markDone()} type="button">
              Đã làm
            </button>
          ) : null}
        </span>
      </div>
    </li>
  );
}

export function ThucHienView({ onCount }: { readonly onCount?: (n: number) => void }) {
  const host = useReco();
  const sample = useSampleShopReviewer();
  const readOnly = !!host.readOnly || sample;
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
        return (
          <div className="sd-th" data-testid="sd-thuc-hien">
            <section aria-label="Juli Connector" className="sd-th-bar" data-testid="sd-th-bar">
              <span aria-hidden="true" className={`sd-th-bar__dot${k.connected ? " sd-th-bar__dot--on" : ""}`} />
              <b>Juli Connector{k.version ? ` ${k.version}` : ""}</b>
              <span>
                {k.seller_centre_open ? "Seller Centre đang mở · " : ""}
                {k.last_check_at ? `đối chiếu lần cuối ${hhmm(k.last_check_at)}` : "chưa đối chiếu"}
              </span>
              <button className="sa-btn sd-th-bar__sync" disabled={readOnly || !k.connected || !!k.reconcile_pending || asking} onClick={() => void reconcile()} type="button">
                Đối chiếu ngay
              </button>
            </section>
            <ul className="sd-th-list">
              {data.cards.map((c) => (
                <Row c={c} key={c.card_id} name={(names.status === "ready" && c.product_id ? names.data.get(c.product_id) : null) ?? null} onDone={() => setTick((t) => t + 1)} readOnly={readOnly} />
              ))}
            </ul>
          </div>
        );
      }}
    </RecoState>
  );
}
