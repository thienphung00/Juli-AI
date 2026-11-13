"use client";

import { useState } from "react";

import { DASH, fmt, pc, pp, vnd } from "../../lib/shopee-analytics/format";
import { useShopee } from "../../lib/shopee-analytics/context";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import type { KolCompareGroup, KolCompareReport, KolCompareRow, KolStreamRow } from "../../lib/shopee-kol/types";
import { ResourceState, TextChip } from "../shopee-analytics/ui";

/**
 * Phân tích › KOL › So sánh (P100): the KOL rows summed by Kênh / Loại chiến dịch / KOL, with the
 * real cost (hoa hồng Shopee thu, gồm 8 %) and the Mẫu KOL cost, then Affiliate beside Ads and the
 * shop's own flows for the same window. Every block names its basis; the two affiliate counts
 * (báo cáo chuyển đổi KOL vs nguồn lưu lượng) are never mixed in one ratio.
 */

const GROUPS: readonly { readonly key: KolCompareGroup; readonly label: string }[] = [
  { key: "channel", label: "Kênh" },
  { key: "campaign_type", label: "Loại chiến dịch" },
  { key: "kol", label: "KOL" },
];

export const COMPARE_HEADS = ["Nhóm", "Đơn", "GMV", "Chi phí", "% chi phí", "Chi phí mẫu", "Lợi nhuận ròng", "Lãi / đơn", "ROI gồm mẫu", "KOL", "Tỷ trọng GMV"] as const;

const num = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

export function KolCompare() {
  const host = useShopee();
  const kol = host.kol;
  const [group, setGroup] = useState<KolCompareGroup>("channel");
  const res = useResource<KolCompareReport | null>(() => (kol?.compare ? kol.compare(group) : Promise.resolve(null)), `${host.shopKey}|kol-compare|${group}`);
  if (!kol?.compare) return null;
  return (
    <section className="kolcmp" data-testid="kol-compare">
      <div className="kolcmp__head">
        <b>So sánh Tiếp thị liên kết</b>
        <div className="sb-tabs" role="group" aria-label="Nhóm theo">
          {GROUPS.map((g) => (
            <button aria-pressed={group === g.key} className={`sb-pill ${group === g.key ? "sb-pill--on" : ""}`} key={g.key} onClick={() => setGroup(g.key)} type="button">
              {g.label}
            </button>
          ))}
        </div>
      </div>
      <ResourceState resource={res}>{(report) => (report ? <CompareBody report={report} /> : null)}</ResourceState>
    </section>
  );
}

function CompareBody({ report }: { readonly report: KolCompareReport }) {
  return (
    <>
      <span className="sa-chip sa-chip--outline" data-testid="kol-compare-basis">
        {report.basis.label}
      </span>
      <div className="kol-table" data-testid="kol-compare-table" role="table">
        <div className="kolcmp__row kol-row--head" role="row">
          {COMPARE_HEADS.map((h) => (
            <span key={h} role="columnheader">
              {h === "Nhóm" ? report.group_label : h}
            </span>
          ))}
        </div>
        {report.rows.map((r) => (
          <GroupRow key={r.key} row={r} />
        ))}
        {report.rows.length > 0 ? <GroupRow row={{ ...report.total, label: "Tổng" }} total /> : null}
      </div>
      {report.rows.length === 0 ? <p className="sa-hint">Chưa có đơn Tiếp thị liên kết theo KOL trong kỳ này.</p> : null}
      <p className="sa-hint">
        Chi phí = {report.labels.cost}. Lợi nhuận ròng {report.labels.net_profit}. ROI gồm mẫu = {report.labels.roi_formula}. “{report.labels.low_data}”: nhóm dưới {report.labels.low_data_threshold} đơn.
      </p>
      <StreamStrip streams={report.streams} />
    </>
  );
}

function GroupRow({ row, total = false }: { readonly row: KolCompareRow; readonly total?: boolean }) {
  const roiBad = num(row.roi_incl_samples) && row.roi_incl_samples < 0;
  return (
    <div className={`kolcmp__row ${row.low_data && !total ? "kol-row--few" : ""} ${total ? "kolcmp__row--total" : ""}`} data-testid={total ? "kol-compare-total" : `kol-compare-row-${row.key}`} role="row">
      <span role="cell">
        <b>{row.label}</b>
        {row.low_data && !total ? (
          <span className="kol-sub">
            <TextChip tone="warn">{row.low_data_label ?? "Ít dữ liệu"}</TextChip>
          </span>
        ) : null}
      </span>
      <span role="cell">{fmt(row.orders, 0)}</span>
      <span role="cell">{vnd(row.gmv)}</span>
      <span role="cell">{vnd(row.cost)}</span>
      <span role="cell">{pp(row.cost_pct_gmv)}</span>
      <span role="cell">{num(row.sample_cost) ? (row.sample_cost > 0 ? vnd(row.sample_cost) : DASH) : "chưa tính được"}</span>
      <span className={row.net_profit < 0 ? "sa-tone--down" : ""} role="cell">
        {vnd(row.net_profit)}
      </span>
      <span role="cell">{vnd(row.profit_per_order)}</span>
      <b className={roiBad ? "sa-tone--down" : ""} role="cell">
        {num(row.roi_incl_samples) ? pc(row.roi_incl_samples, 0) : DASH}
      </b>
      <span role="cell">{fmt(row.kols, 0)}</span>
      <span role="cell">{pp(row.share_gmv_pct)}</span>
    </div>
  );
}

function StreamStrip({ streams }: { readonly streams: KolCompareReport["streams"] }) {
  return (
    <div className="kolcmp__strip" data-testid="kol-stream-strip">
      <b>Tiếp thị liên kết so với Quảng cáo và luồng của shop, cùng kỳ</b>
      <div className="kol-tiles">
        {streams.rows.map((s) => (
          <StreamTile key={s.key} s={s} />
        ))}
      </div>
      <p className="sa-hint">{streams.note}</p>
    </div>
  );
}

function StreamTile({ s }: { readonly s: KolStreamRow }) {
  return (
    <div className="kol-tile" data-testid={`kol-stream-${s.key}`}>
      <span className="sa-hint">{s.label}</span>
      <b>{vnd(s.gmv)}</b>
      <span className="sa-hint">
        {num(s.orders) ? `${fmt(s.orders, 0)} đơn` : DASH} · {s.basis.label}
      </span>
      <span>
        Chi phí {vnd(s.cost)}
        {num(s.cost_pct_gmv) ? ` · ${pp(s.cost_pct_gmv)} GMV` : ""}
      </span>
      {s.cost_basis && s.cost_basis.key !== s.basis.key ? <span className="sa-hint">Chi phí: {s.cost_basis.label}</span> : null}
      <span>{num(s.profit_after_cost) ? `Lợi nhuận sau chi phí ${vnd(s.profit_after_cost)}` : `Lợi nhuận: ${DASH}`}</span>
      {s.reason ? <span className="sa-hint">{s.reason}</span> : null}
      {!num(s.profit_after_cost) && s.profit_reason ? <span className="sa-hint">{s.profit_reason}</span> : null}
      {s.note ? <span className="sa-hint">{s.note}</span> : null}
    </div>
  );
}
