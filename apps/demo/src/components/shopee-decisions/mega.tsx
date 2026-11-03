"use client";

import { DASH, fmt, vnd } from "../../lib/shopee-analytics/format";
import { FAMILY_TITLE, vnWhen } from "../../lib/shopee-decisions/model";
import type { Card, Family, MegaChild } from "../../lib/shopee-decisions/types";
import { TextChip } from "../shopee-analytics/ui";
import { PageLink } from "./execution";
import type { Patch } from "./whatif";

/**
 * The mega-sale card (contract 12): one campaign window made of several changes, ONE schedule, ONE
 * budget cap, ONE approval. The window's orders are re-priced once with every change stacked, so the
 * totals never count an order twice. The person may take a change out before approving; every change
 * recomputes the whole card.
 */

const LEVER_LABEL: Readonly<Record<string, string>> = { combo: "Combo", khuyen_mai: "Khuyến mãi", voucher: "Voucher", khong_uu_dai: "Không ưu đãi" };

function dayMonth(iso: string): string {
  const [, m, d] = iso.slice(0, 10).split("-");
  return m && d ? `${d}/${m}` : DASH;
}

/** One line for a child's "after" (its sheet summary): primitives as `key: value`, SKU lists as a count. */
export function summaryText(summary: MegaChild["summary"]): string {
  if (!summary) return DASH;
  const parts: string[] = [];
  for (const [k, v] of Object.entries(summary)) {
    if (v === null || v === undefined) continue;
    if (Array.isArray(v)) parts.push(`${v.length} SKU`);
    else if (typeof v === "number") parts.push(`${k}: ${fmt(v, v % 1 === 0 ? 0 : 1)}`);
    else if (typeof v === "string" || typeof v === "boolean") parts.push(`${k}: ${String(v)}`);
  }
  return parts.length > 0 ? parts.join(" · ") : DASH;
}

export function MegaPanel({ card, patch, editable, disabled, onChange }: { readonly card: Card; readonly patch: Patch; readonly editable: boolean; readonly disabled: boolean; readonly onChange: (next: Patch) => void }) {
  const children = [...(card.children ?? [])].sort((a, b) => a.starts.localeCompare(b.starts));
  const label = new Map(children.map((c) => [c.child_id, c.label] as const));
  const removed = (Array.isArray(patch["remove"]) ? patch["remove"] : []) as readonly string[];
  const cap = "budget_cap_per_day" in patch ? patch["budget_cap_per_day"] : card.inputs["budget_cap_per_day"];
  const c = card.certain;
  const w = card.mega_window;
  const canRemove = editable && !disabled && children.length > 1;
  return (
    <div className="sd-mega" data-testid="sd-mega">
      <div className="sd-mega__head">
        <b>Chiến dịch {w ? `${dayMonth(w.start)}–${dayMonth(w.end)} (${w.days} ngày)` : ""}</b>
        <span className="sa-hint">Một lịch · một ngân sách · một lần duyệt. Bỏ một thay đổi nếu bạn không muốn làm; mọi con số tính lại.</span>
      </div>

      <ol className="sd-mega__children" data-testid="sd-mega-children">
        {children.map((ch) => (
          <li className="sd-mega__child" data-testid={`sd-child-${ch.child_id}`} key={ch.child_id}>
            <span className="sd-mega__label">
              <b>{ch.label}</b>
              <TextChip tone="flat">{FAMILY_TITLE[ch.family as Family] ?? ch.family}</TextChip>
              <span className="sa-hint">{summaryText(ch.summary)}</span>
              {ch.page ? <PageLink page={ch.page} /> : null}
            </span>
            {editable ? (
              <button aria-label={`Bỏ ${ch.label}`} className="sa-btn sa-btn--s" disabled={!canRemove} onClick={() => onChange({ ...patch, remove: [...removed, ch.child_id] })} title={children.length <= 1 ? "Chiến dịch cần ít nhất một thay đổi" : undefined} type="button">
                Bỏ thay đổi này
              </button>
            ) : null}
          </li>
        ))}
      </ol>
      {removed.length > 0 ? (
        <p className="sa-hint" data-testid="sd-mega-removed">
          Đã bỏ {removed.length} thay đổi. <button className="sd-linkbtn" disabled={disabled} onClick={() => onChange({ ...patch, remove: [] })} type="button">Khôi phục tất cả</button>
        </p>
      ) : null}

      <h3 className="sa-h3">Lịch theo ngày</h3>
      <ol className="sd-mega__days" data-testid="sd-mega-schedule">
        {(card.schedule ?? []).map((day) => (
          <li data-testid={`sd-day-${day.date}`} key={day.date}>
            <b>{dayMonth(day.date)}</b>
            {day.events.length === 0 ? (
              <span className="sa-hint">Chạy tiếp, không thao tác</span>
            ) : (
              <ul>
                {day.events.map((e) => (
                  <li key={`${e.child_id}-${e.action}`}>
                    {e.action === "bat" ? "Bật" : "Tắt"} lúc {e.at} · {label.get(e.child_id) ?? e.kind}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>

      <div className="sd-mega__totals" data-testid="sd-mega-totals">
        <h3 className="sa-h3">Tổng cả chiến dịch</h3>
        <dl>
          <dt>Tổng tiền giảm</dt>
          <dd>{vnd(c.total_discount ?? null)}</dd>
          <dt>Số đơn dự kiến trong kỳ</dt>
          <dd>{typeof c.orders_in_window_expected === "number" ? fmt(c.orders_in_window_expected, 0) : DASH}</dd>
          {(c.by_lever ?? []).map((l) => (
            <div className="sd-mega__lever" key={l.lever}>
              <dt>{LEVER_LABEL[l.lever] ?? l.lever}</dt>
              <dd>{`${vnd(l.discount)} · ${fmt(l.lines, 0)} dòng đơn`}</dd>
            </div>
          ))}
        </dl>
        {c.no_double_counting ? <p className="sa-hint">{c.no_double_counting}</p> : null}
      </div>

      <div className="sd-mega__cap" data-testid="sd-mega-cap">
        <label className="sd-field__label" htmlFor="sd-cap">
          Trần chi / ngày cho cả chiến dịch
        </label>
        <input
          disabled={disabled}
          id="sd-cap"
          min={0}
          onChange={(event) => onChange({ ...patch, budget_cap_per_day: event.target.value === "" ? null : Number(event.target.value) })}
          step={10_000}
          type="number"
          value={typeof cap === "number" ? cap : ""}
        />
        {c.spend ? (
          <span className={c.spend.over_budget ? "sd-error" : "sa-hint"}>
            Chi dự kiến {vnd(c.spend.mega_chi_per_day)}/ngày{typeof cap === "number" ? `, ${c.spend.over_budget ? "vượt" : "trong"} trần ${vnd(cap)}` : ", chưa đặt trần"}.
          </span>
        ) : null}
      </div>

      <h3 className="sa-h3">Giá sàn từng SKU (giá thấp nhất khách có thể trả khi mọi thay đổi chồng lên nhau)</h3>
      <table className="sd-table" data-testid="sd-mega-skus">
        <thead>
          <tr>
            <th>SKU</th>
            <th>Giá thấp nhất khách trả</th>
            <th>Giá sàn</th>
            <th>Kết quả</th>
          </tr>
        </thead>
        <tbody>
          {(c.skus ?? []).map((s) => (
            <tr data-testid={`sd-sku-${s.sku}`} key={s.sku}>
              <td>{s.sku}</td>
              <td>{vnd(s.worst_unit_net_revenue)}</td>
              <td>{vnd(s.floor)}</td>
              <td>{s.below_floor ? <TextChip tone="down">Dưới giá sàn</TextChip> : <TextChip tone="up">Trên giá sàn</TextChip>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {w ? <p className="sa-hint">Bắt đầu {vnWhen(w.start)}, kết thúc {vnWhen(w.end)}.</p> : null}
    </div>
  );
}
