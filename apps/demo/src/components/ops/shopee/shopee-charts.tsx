"use client";

import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { fmtGmvShort, fmtInt } from "../../../lib/ops/format";
import { CHART_COLORS } from "./shopee-ui";

/** Thin recharts wrappers; every chart has its table next to it, so these only add the picture. */

export interface Series {
  readonly key: string;
  readonly label: string;
}

type Row = Record<string, string | number | null>;

const AXIS = { fontSize: 11 } as const;

export function StackedBars({ data, series, label, money = true }: { readonly data: Row[]; readonly series: Series[]; readonly label: string; readonly money?: boolean }) {
  return (
    <div aria-label={label} role="img" style={{ width: "100%", height: 240 }}>
      <ResponsiveContainer height="100%" width="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#eceaee" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" tick={AXIS} />
          <YAxis tick={AXIS} tickFormatter={(v: number) => (money ? fmtGmvShort(v) : fmtInt(v))} width={56} />
          <Tooltip formatter={(v: number) => (money ? `${fmtInt(v)} ₫` : fmtInt(v))} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {series.map((s, i) => (
            <Bar dataKey={s.key} fill={CHART_COLORS[i % CHART_COLORS.length]} key={s.key} name={s.label} stackId="a" />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Lines({ data, series, label, reference }: { readonly data: Row[]; readonly series: Series[]; readonly label: string; readonly reference?: number }) {
  return (
    <div aria-label={label} role="img" style={{ width: "100%", height: 220 }}>
      <ResponsiveContainer height="100%" width="100%">
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#eceaee" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" tick={AXIS} />
          <YAxis tick={AXIS} width={40} />
          <Tooltip />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {series.map((s, i) => (
            <Line connectNulls dataKey={s.key} dot={false} key={s.key} name={s.label} stroke={CHART_COLORS[i % CHART_COLORS.length]} strokeWidth={2} type="monotone" />
          ))}
          {reference !== undefined ? <Line dataKey={() => reference} dot={false} legendType="none" stroke="#a3222f" strokeDasharray="4 4" strokeWidth={1} /> : null}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
