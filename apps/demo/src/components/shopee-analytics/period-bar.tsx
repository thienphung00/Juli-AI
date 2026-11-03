"use client";

import Link from "next/link";
import { useState } from "react";

import { rangeText } from "../../lib/shopee-analytics/format";
import { periodLabel, type WindowState } from "../../lib/shopee-analytics/params";
import type { WindowJson } from "../../lib/shopee-analytics/types";
import type { PeriodKind } from "../../lib/shopee-analytics/client";

/**
 * Kỳ xem: 7 / 30 / 90 ngày, a calendar month, a custom window, and "So sánh kỳ trước". Every
 * control is a link to the same screen with the window in the URL, so a window can be shared,
 * survives a reload and is carried by every link on the screen.
 */
export function PeriodBar({
  state,
  window: win,
  previous,
  hrefFor,
}: {
  readonly state: WindowState;
  readonly window: WindowJson | null;
  readonly previous: WindowJson | null;
  readonly hrefFor: (next: WindowState) => string;
}) {
  const q = state.query;
  const monthDefault = (win?.to ?? new Date().toISOString().slice(0, 10)).slice(0, 7);
  const [month, setMonth] = useState(q.month ?? monthDefault);
  const [from, setFrom] = useState(q.from ?? win?.from ?? "");
  const [to, setTo] = useState(q.to ?? win?.to ?? "");
  const kinds: [PeriodKind, string][] = [
    ["7d", "7 ngày"],
    ["30d", "30 ngày"],
    ["90d", "90 ngày"],
  ];
  const customOk = /^\d{4}-\d{2}-\d{2}$/.test(from) && /^\d{4}-\d{2}-\d{2}$/.test(to) && from <= to;
  const monthOk = /^\d{4}-\d{2}$/.test(month);
  return (
    <div className="sa-period" data-testid="sa-period">
      <div aria-label="Kỳ xem" className="sa-seg sa-seg--round" role="group">
        {kinds.map(([kind, label]) => (
          <Link
            aria-current={q.period === kind ? "true" : undefined}
            className={`sa-seg__item${q.period === kind ? " sa-seg__item--on" : ""}`}
            href={hrefFor({ ...state, query: { period: kind } })}
            key={kind}
          >
            {label}
          </Link>
        ))}
        <span className={`sa-seg__item${q.period === "month" || q.period === "custom" ? " sa-seg__item--on" : ""}`}>
          {q.period === "month" || q.period === "custom" ? periodLabel(q) : "Tháng / tuỳ chọn"}
        </span>
      </div>
      <details className="sa-period__more">
        <summary>Chọn tháng hoặc khoảng ngày ▾</summary>
        <div className="sa-period__form">
          <label>
            Tháng
            <input onChange={(e) => setMonth(e.target.value)} type="month" value={month} />
          </label>
          {monthOk ? (
            <Link className="sa-btn" href={hrefFor({ ...state, query: { period: "month", month } })}>
              Xem tháng
            </Link>
          ) : null}
          <label>
            Từ ngày
            <input onChange={(e) => setFrom(e.target.value)} type="date" value={from} />
          </label>
          <label>
            Đến ngày
            <input onChange={(e) => setTo(e.target.value)} type="date" value={to} />
          </label>
          {customOk ? (
            <Link className="sa-btn" href={hrefFor({ ...state, query: { period: "custom", from, to } })}>
              Xem khoảng này
            </Link>
          ) : (
            <span className="sa-hint">Ngày kết thúc phải sau ngày bắt đầu.</span>
          )}
        </div>
      </details>
      <Link
        aria-pressed={state.compare}
        className={`sa-toggle${state.compare ? " sa-toggle--on" : ""}`}
        href={hrefFor({ ...state, compare: !state.compare })}
      >
        {state.compare ? "So sánh kỳ trước: bật" : "So sánh kỳ trước: tắt"}
      </Link>
      <span className="sa-hint" data-testid="sa-range">
        {win ? rangeText(win) : null}
        {win && previous && state.compare ? ` so với ${rangeText(previous)}` : ""}
      </span>
    </div>
  );
}

