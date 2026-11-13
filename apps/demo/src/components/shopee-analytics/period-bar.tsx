"use client";

import Link from "next/link";
import { useState } from "react";

import { DateField } from "../date-field";
import { rangeText } from "../../lib/shopee-analytics/format";
import type { WindowState } from "../../lib/shopee-analytics/params";
import type { WindowJson } from "../../lib/shopee-analytics/types";
import type { PeriodKind } from "../../lib/shopee-analytics/client";
import { PERIOD_LABEL } from "../../lib/metrics";

/**
 * Kỳ xem (P100): 7 / 30 / 90 ngày and Tùy chọn (a from / to range; a calendar month is a Tùy chọn
 * range), then the date range. Every control is a link to the same screen with the window in the
 * URL, so a window can be shared, survives a reload and is carried by every link on the screen.
 * The change figures are always against the previous period of the same length, so there is no
 * compare switch. `previous` is kept for the callers that still pass it.
 */
export function PeriodBar({
  state,
  window: win,
  hrefFor,
}: {
  readonly state: WindowState;
  readonly window: WindowJson | null;
  readonly previous?: WindowJson | null;
  readonly hrefFor: (next: WindowState) => string;
}) {
  const q = state.query;
  const isCustom = q.period === "custom" || q.period === "month";
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState(q.from ?? win?.from ?? "");
  const [to, setTo] = useState(q.to ?? win?.to ?? "");
  const kinds: readonly (readonly [PeriodKind, string])[] = [
    ["7d", PERIOD_LABEL["7"]],
    ["30d", PERIOD_LABEL["30"]],
    ["90d", PERIOD_LABEL["90"]],
  ];
  const customOk = /^\d{4}-\d{2}-\d{2}$/.test(from) && /^\d{4}-\d{2}-\d{2}$/.test(to) && from <= to;
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
        <button
          aria-pressed={isCustom || open}
          className={`sa-seg__item${isCustom || open ? " sa-seg__item--on" : ""}`}
          data-testid="sa-period-custom"
          onClick={() => setOpen((v) => !v)}
          type="button"
        >
          {PERIOD_LABEL.custom}
        </button>
      </div>
      {open || isCustom ? (
        <span className="sa-period__form" data-testid="sa-period-form">
          <label>
            Từ
            <DateField ariaLabel="Từ ngày" onChange={setFrom} value={from} />
          </label>
          <label>
            Đến
            <DateField ariaLabel="Đến ngày" onChange={setTo} value={to} />
          </label>
          {customOk ? (
            <Link className="sa-btn" href={hrefFor({ ...state, query: { period: "custom", from, to } })}>
              Xem
            </Link>
          ) : null}
        </span>
      ) : null}
      <span className="sa-hint" data-testid="sa-range">
        {win ? rangeText(win) : null}
      </span>
    </div>
  );
}
