"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { useShopee } from "../../lib/shopee-analytics/context";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { FEW_ORDERS, KOL_KIND_LABEL, rowText, tilesOf } from "../../lib/shopee-kol/model";
import type { KolReport, KolRow } from "../../lib/shopee-kol/types";
import { Empty, Notice, ResourceState, TextChip } from "../shopee-analytics/ui";

/**
 * Phân tích › KOL (`PhanTichKOL.dc.html`): who sells what, at what profit, and whom to send a sample.
 * One row per KOL × sản phẩm × kênh. "ROI Shopee (chỉ hoa hồng)" is the value from Shopee's KOL export,
 * printed as it came; "ROI gồm mẫu" is ours. Fewer than 10 orders for the pair is "Ít dữ liệu".
 */

const ALL = "Tất cả";

export function KolView() {
  const host = useShopee();
  const kol = host.kol;
  const res = useResource<KolReport | null>(() => (kol ? kol.report() : Promise.resolve(null)), `${host.shopKey}|kol`);
  return (
    <div className="sa-page" data-testid="kol-page">
      <header className="sa-prodhead">
        <Link className="sa-link" href={host.links.critical()}>
          ‹ Phân tích
        </Link>
        <div className="sa-eyebrow">PHÂN TÍCH · KOL</div>
        <span className="sa-chip sa-chip--outline sa-row__end" data-testid="kol-chip">
          Shopee{host.shopName ? ` · ${host.shopName}` : ""} · 30 ngày
        </span>
      </header>
      <div>
        <h1 className="sa-h1">Ai bán gì, lãi bao nhiêu, và nên gửi mẫu cho ai</h1>
        <p className="sa-hint">Mỗi dòng là một KOL × sản phẩm × kênh. Hoa hồng tính theo mức áp dụng cho từng sản phẩm. Lợi nhuận ròng đã trừ phí sàn, giá vốn, đóng gói và hoa hồng. Chi phí mẫu = số lượng × (giá vốn + đóng gói) + phí ship; không tính phí book KOL.</p>
      </div>
      <ResourceState resource={res}>{(report) => (report ? <Body report={report} /> : <Notice tone="info">KOL chưa bật cho shop này.</Notice>)}</ResourceState>
    </div>
  );
}

function Body({ report }: { readonly report: KolReport }) {
  const { links } = useShopee();
  const [ch, setCh] = useState(ALL);
  const [pid, setPid] = useState(ALL);
  const products = useMemo(() => [...new Map(report.rows.map((r) => [r.product_id, r.product_name])).entries()], [report.rows]);
  const rows = report.rows.filter((r) => (ch === ALL || r.channel === ch) && (pid === ALL || r.product_id === pid));
  return (
    <>
      <div className="kol-tiles" data-testid="kol-tiles">
        {tilesOf(rows).map((t) => (
          <div className="kol-tile" key={t.k}>
            <span className="sa-hint">{t.k}</span>
            <b className={t.bad ? "sa-tone--down" : ""}>{t.v}</b>
            <span className="sa-hint">{t.sub}</span>
          </div>
        ))}
      </div>
      <div className="kol-filters">
        <div className="sb-tabs">
          <span className="sa-hint">Kênh:</span>
          {[ALL, ...report.channels].map((c) => (
            <button aria-pressed={ch === c} className={`sb-pill ${ch === c ? "sb-pill--on" : ""}`} key={c} onClick={() => setCh(c)} type="button">
              {c}
            </button>
          ))}
        </div>
        <div className="sb-tabs">
          <span className="sa-hint">Sản phẩm:</span>
          {[[ALL, ALL] as const, ...products].map(([id, name]) => (
            <button aria-pressed={pid === id} className={`sb-pill ${pid === id ? "sb-pill--on" : ""}`} key={id} onClick={() => setPid(id)} type="button">
              {name}
            </button>
          ))}
        </div>
      </div>
      <div className="kol-table" data-testid="kol-table" role="table">
        <div className="kol-row kol-row--head" role="row">
          {["KOL · kênh", "Sản phẩm", "Đơn", "SL", "GMV", "Lượt nhấp", "Chuyển đổi", "Hoa hồng", "Lợi nhuận ròng", "Chi phí mẫu", "Lợi nhuận sau mẫu", "ROI gồm mẫu", "ROI Shopee (chỉ hoa hồng)", "Hoàn vốn mẫu", "Thẻ"].map((h) => (
            <span key={h} role="columnheader">
              {h}
            </span>
          ))}
        </div>
        {rows.map((r) => (
          <KolRowView key={`${r.kol_key}|${r.product_id}|${r.channel}`} row={r} />
        ))}
        {rows.length === 0 ? <Empty testId="kol-empty">Không có dòng nào khớp bộ lọc.</Empty> : null}
      </div>
      <div className="kol-legend">
        <div>
          <b>ROI gồm mẫu (Juli)</b> <span className="sa-hint">(lợi nhuận ròng của đơn KOL − chi phí mẫu) ÷ (hoa hồng + chi phí mẫu). Dưới 0% là KOL chưa hoàn vốn mẫu.</span>
        </div>
        <div>
          <b>ROI Shopee (chỉ hoa hồng)</b>{" "}
          <span className="sa-hint">
            Giá trị trong file xuất KOL của Shopee, giữ nguyên, không tính lại. Chỉ tính hoa hồng, không có giá vốn, phí sàn và mẫu nên thường trông tốt hơn. “Ít dữ liệu” là cặp KOL × sản phẩm có dưới {FEW_ORDERS} đơn: số chỉ để tham khảo.
          </span>
        </div>
      </div>
      <span hidden>{links.critical()}</span>
    </>
  );
}

function KolRowView({ row }: { readonly row: KolRow }) {
  const { links } = useShopee();
  const t = rowText(row);
  return (
    <div className={`kol-row ${t.few ? "kol-row--few" : ""}`} data-testid={`kol-row-${row.kol_key}-${row.product_id}`} role="row">
      <span role="cell">
        <b>{t.handle}</b>
        <span className="kol-sub">
          <span className="sa-chip sa-chip--outline">{t.channel}</span>
          {t.few ? <TextChip tone="warn">Ít dữ liệu</TextChip> : null}
        </span>
      </span>
      <span role="cell">{t.product}</span>
      <span role="cell">{t.orders}</span>
      <span role="cell">{t.units}</span>
      <span role="cell">{t.gmv}</span>
      <span role="cell">{t.clicks}</span>
      <span role="cell">{t.conversion}</span>
      <span role="cell">{t.commission}</span>
      <span role="cell">{t.net}</span>
      <span role="cell">{t.sample}</span>
      <b className={t.afterBad ? "sa-tone--down" : ""} role="cell">
        {t.after}
      </b>
      <b className={t.roiBad ? "sa-tone--down" : t.few ? "sd-hint--warn" : ""} role="cell">
        {t.roi}
      </b>
      <span role="cell">{t.roiShopee}</span>
      <span role="cell">{t.payback}</span>
      <span role="cell">
        {row.card ? (
          <>
            <span className="sd-code">{row.card.code}</span>{" "}
            <Link className="sa-link" href={links.card(row.card.id, "kol")}>
              {KOL_KIND_LABEL[row.card.kind]} ›
            </Link>
          </>
        ) : (
          <span className="sa-hint">Chưa có thẻ</span>
        )}
      </span>
    </div>
  );
}
