"use client";

import { useEffect, useState } from "react";

import { opsRequest } from "../../../lib/ops/api";
import { fmtDate } from "../../../lib/ops/format";
import type { OpsMe } from "../../../lib/ops/types";
import { C, OpsHeader, OpsPage } from "../ops-shell";
import { OpsSkeleton } from "../ops-skeleton";
import { Empty, PageTitle, Section, TD, TD_LEFT, TH, TH_LEFT, TableWrap, errorText } from "./shopee-ui";

/**
 * Lệch số liệu (P98, ADR-122 d.11.3-d.11.4): the daily funnel check's findings per day, and how
 * often the frozen predictions landed inside their range per family (target about 80 %). Read only:
 * nothing is corrected from here.
 */

export type MismatchKind = "missing_rows" | "sources_sum" | "shop_totals" | "traffic";

export interface FunnelMismatch {
  readonly kind: MismatchKind;
  readonly day: string;
  readonly scope: "shop" | "product";
  readonly item_id: string | null;
  readonly source: string | null;
  readonly metric: string;
  readonly expected: string | null;
  readonly actual: string | null;
  readonly gap_pct: number | null;
}

export interface FunnelCheck {
  readonly days: number;
  readonly from: string;
  readonly to: string;
  readonly tolerance_pct: number;
  readonly mismatches: readonly FunnelMismatch[];
}

export interface CoverageFamily {
  readonly family: string;
  readonly scored: number;
  readonly inside: number;
  readonly coverage: number | null;
  readonly metrics: readonly { readonly metric: string; readonly scored: number; readonly inside: number; readonly coverage: number | null; readonly range_scale: number }[];
}

export interface PredictionCoverage {
  readonly target: number;
  readonly source: string;
  readonly families: readonly CoverageFamily[];
}

export interface FunnelApi {
  readonly funnelCheck: (shopId: string, days: number) => Promise<FunnelCheck>;
  readonly predictionCoverage: (shopId: string) => Promise<PredictionCoverage>;
}

const shopPath = (shopId: string) => `/shops/${encodeURIComponent(shopId)}/shopee`;

export const defaultFunnelApi: FunnelApi = {
  funnelCheck: (shopId, days) => opsRequest<FunnelCheck>(`${shopPath(shopId)}/funnel-check?days=${days}`),
  predictionCoverage: (shopId) => opsRequest<PredictionCoverage>(`${shopPath(shopId)}/prediction-coverage`),
};

export const KIND_LABEL: Record<MismatchKind, string> = {
  missing_rows: "Thiếu dòng nguồn",
  sources_sum: "Tổng các nguồn không khớp",
  shop_totals: "Lệch tổng shop của Shopee",
  traffic: "Lệch lượt xem / lượt nhấp",
};

export const METRIC_LABEL: Record<string, string> = { orders: "Đơn", gmv: "GMV", views: "Lượt xem", clicks: "Lượt nhấp", rows: "Dòng" };

const DAY_CHOICES = [7, 14, 30] as const;

const fmtNum = (v: string | null): string => (v === null ? "—" : Number(v).toLocaleString("vi-VN"));
const fmtGap = (g: number | null): string => (g === null ? "—" : `${g.toLocaleString("vi-VN", { maximumFractionDigits: 2 })} %`);
const fmtShare = (v: number | null): string => (v === null ? "chưa có kết quả" : `${(v * 100).toLocaleString("vi-VN", { maximumFractionDigits: 0 })} %`);

/** Mismatches grouped by day, newest day first. */
export function byDay(rows: readonly FunnelMismatch[]): [string, FunnelMismatch[]][] {
  const map = new Map<string, FunnelMismatch[]>();
  for (const r of rows) map.set(r.day, [...(map.get(r.day) ?? []), r]);
  return [...map.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1));
}

function scopeText(m: FunnelMismatch): string {
  const where = m.scope === "shop" ? "Cả shop" : `Sản phẩm ${m.item_id ?? ""}`;
  return m.source ? `${where} · ${m.source}` : where;
}

function MismatchTable({ day, rows }: { readonly day: string; readonly rows: readonly FunnelMismatch[] }) {
  return (
    <TableWrap label={`Lệch số liệu ngày ${fmtDate(day)}`}>
      <thead>
        <tr>
          <th style={TH_LEFT}>Loại</th>
          <th style={TH_LEFT}>Phạm vi</th>
          <th style={TH_LEFT}>Chỉ số</th>
          <th style={TH}>Mong đợi</th>
          <th style={TH}>Thực tế</th>
          <th style={TH}>Chênh lệch</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((m, i) => (
          <tr key={`${m.kind}-${m.metric}-${m.item_id ?? ""}-${m.source ?? ""}-${i}`}>
            <td style={TD_LEFT}>{KIND_LABEL[m.kind]}</td>
            <td style={TD_LEFT}>{scopeText(m)}</td>
            <td style={TD_LEFT}>{METRIC_LABEL[m.metric] ?? m.metric}</td>
            <td style={TD}>{fmtNum(m.expected)}</td>
            <td style={TD}>{fmtNum(m.actual)}</td>
            <td style={TD}>{fmtGap(m.gap_pct)}</td>
          </tr>
        ))}
      </tbody>
    </TableWrap>
  );
}

export function FunnelCheckSection({ check }: { readonly check: FunnelCheck }) {
  const groups = byDay(check.mismatches);
  return (
    <Section hint={`${fmtDate(check.from)} – ${fmtDate(check.to)} · ngưỡng ${check.tolerance_pct} %`} title="Lệch số liệu theo ngày">
      {groups.length === 0 ? (
        <Empty>Không có lệch số liệu</Empty>
      ) : (
        groups.map(([day, rows]) => (
          <div key={day} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <h3 style={{ margin: 0, fontSize: 14 }}>{fmtDate(day)}</h3>
            <MismatchTable day={day} rows={rows} />
          </div>
        ))
      )}
    </Section>
  );
}

export function CoverageSection({ coverage }: { readonly coverage: PredictionCoverage }) {
  const target = Math.round(coverage.target * 100);
  return (
    <Section hint={`mục tiêu khoảng ${target} % kết quả đo nằm trong khoảng thấp – cao`} title="Độ phủ của dự báo đã khóa">
      {coverage.families.length === 0 ? (
        <Empty>Chưa có dự báo nào được chấm điểm</Empty>
      ) : (
        <TableWrap label="Độ phủ theo nhóm">
          <thead>
            <tr>
              <th style={TH_LEFT}>Nhóm</th>
              <th style={TH}>Đã chấm</th>
              <th style={TH}>Nằm trong khoảng</th>
              <th style={TH}>Độ phủ</th>
            </tr>
          </thead>
          <tbody>
            {coverage.families.map((f) => (
              <tr key={f.family}>
                <td style={TD_LEFT}>{f.family}</td>
                <td style={TD}>{f.scored}</td>
                <td style={TD}>{f.inside}</td>
                <td style={{ ...TD, color: f.coverage !== null && f.coverage < coverage.target - 0.1 ? C.red : undefined }}>{fmtShare(f.coverage)}</td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      )}
    </Section>
  );
}

export function OpsShopeeFunnel({ me, shopId, api = defaultFunnelApi }: { readonly me: OpsMe; readonly shopId: string; readonly api?: FunnelApi }) {
  const [days, setDays] = useState<number>(14);
  const [check, setCheck] = useState<FunnelCheck | null>(null);
  const [coverage, setCoverage] = useState<PredictionCoverage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.funnelCheck(shopId, days).then(
      (c) => {
        if (!live) return;
        setCheck(c);
        setError(null);
      },
      (e: unknown) => live && setError(errorText(e)),
    );
    return () => {
      live = false;
    };
  }, [api, shopId, days]);

  useEffect(() => {
    let live = true;
    api.predictionCoverage(shopId).then(
      (c) => live && setCoverage(c),
      (e: unknown) => live && setError(errorText(e)),
    );
    return () => {
      live = false;
    };
  }, [api, shopId]);

  return (
    <OpsPage>
      <OpsHeader me={me} shopId={shopId} />
      <main style={{ padding: "22px 28px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
        <PageTitle active="lech-so-lieu" shopId={shopId} title="Shopee · Lệch số liệu" />
        {error ? (
          <p role="alert" style={{ margin: 0, color: C.red }}>
            {error}
          </p>
        ) : null}
        <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12, fontWeight: 600, width: 160 }}>
          Số ngày gần nhất
          <select onChange={(e) => setDays(Number(e.target.value))} style={{ font: "inherit", fontSize: 13, padding: "6px 8px", borderRadius: 8, border: `1px solid ${C.line}` }} value={days}>
            {DAY_CHOICES.map((d) => (
              <option key={d} value={d}>
                {d} ngày
              </option>
            ))}
          </select>
        </label>
        {check && check.days === days ? <FunnelCheckSection check={check} /> : error ? null : <OpsSkeleton />}
        {coverage ? <CoverageSection coverage={coverage} /> : null}
      </main>
    </OpsPage>
  );
}
