"use client";

import Link from "next/link";
import { useState } from "react";

import { useShopee } from "../../lib/shopee-analytics/context";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { rowText, tilesOf } from "../../lib/shopee-kol/model";
import type { KolReport, KolRow } from "../../lib/shopee-kol/types";
import { Empty, Notice, ResourceState, TextChip } from "../shopee-analytics/ui";
import { KolCompare } from "./kol-compare";

/**
 * Phân tích › KOL (`PhanTichKOL.dc.html`): who sells what, at what profit, and whom to send a sample.
 * One row per KOL × sản phẩm × kênh. "ROI Shopee (chỉ hoa hồng)" is the value from Shopee's KOL export,
 * printed as it came; "ROI gồm mẫu" is ours. Fewer than 10 orders for the pair is "Ít dữ liệu".
 */

const ALL = "Tất cả";

export function KolView() {
  const host = useShopee();
  const kol = host.kol;
  const [ch, setCh] = useState(ALL);
  const [pid, setPid] = useState(ALL);
  // The filters go to the server (`channel`, `item_id`), which also sums the totals of what is left.
  const res = useResource<KolReport | null>(() => (kol ? kol.report({ channel: ch === ALL ? null : ch, itemId: pid === ALL ? null : pid }) : Promise.resolve(null)), `${host.shopKey}|kol|${ch}|${pid}`);
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
      <ResourceState resource={res}>{(report) => (report ? <Body channel={ch} item={pid} onChannel={setCh} onItem={setPid} report={report} /> : <Notice tone="info">KOL chưa bật cho shop này.</Notice>)}</ResourceState>
    </div>
  );
}

function Body({ report, channel, item, onChannel, onItem }: { readonly report: KolReport; readonly channel: string; readonly item: string; readonly onChannel: (c: string) => void; readonly onItem: (id: string) => void }) {
  const { links } = useShopee();
  const rows = report.rows;
  const threshold = report.labels.low_data_threshold;
  const dq = report.data_quality;
  return (
    <>
      <div className="kol-tiles" data-testid="kol-tiles">
        {tilesOf(report).map((t) => (
          <div className="kol-tile" key={t.k}>
            <span className="sa-hint">{t.k}</span>
            <b className={t.bad ? "sa-tone--down" : ""}>{t.v}</b>
            <span className="sa-hint">{t.sub}</span>
          </div>
        ))}
      </div>
      {dq.untagged_affiliate_lines > 0 || dq.lines_without_commission > 0 ? (
        <Notice tone="info" testId="kol-quality">
          {dq.untagged_affiliate_lines > 0 ? `${dq.untagged_affiliate_lines} dòng đơn Tiếp thị liên kết chưa gắn được với KOL nào. ` : ""}
          {dq.lines_without_commission > 0 ? `${dq.lines_without_commission} dòng chưa có hoa hồng.` : ""}
        </Notice>
      ) : null}
      <KolCompare />
      <div className="kol-filters">
        <div className="sb-tabs">
          <span className="sa-hint">Kênh:</span>
          {[{ value: ALL, label: ALL }, ...channelOptions(report)].map((c) => (
            <button aria-pressed={channel === c.value} className={`sb-pill ${channel === c.value ? "sb-pill--on" : ""}`} key={c.value} onClick={() => onChannel(c.value)} type="button">
              {c.label}
            </button>
          ))}
        </div>
        <div className="sb-tabs">
          <span className="sa-hint">Sản phẩm:</span>
          {[{ item_id: ALL, name: ALL }, ...report.filters.products].map((p) => (
            <button aria-pressed={item === p.item_id} className={`sb-pill ${item === p.item_id ? "sb-pill--on" : ""}`} key={p.item_id} onClick={() => onItem(p.item_id)} type="button">
              {p.name}
            </button>
          ))}
        </div>
      </div>
      <div className="kol-table" data-testid="kol-table" role="table">
        <div className="kol-row kol-row--head" role="row">
          {["KOL · kênh", "Sản phẩm", "Đơn", "SL", "GMV", "Lượt nhấp của KOL", "Chuyển đổi của KOL", "Người mua của KOL", "Hoa hồng", "Lợi nhuận ròng", "Chi phí mẫu", "Lợi nhuận sau mẫu", "ROI gồm mẫu", "ROI Shopee (chỉ hoa hồng)", "Hoàn vốn mẫu", "Thẻ"].map((h) => (
            <span key={h} role="columnheader">
              {h}
            </span>
          ))}
        </div>
        {rows.map((r) => (
          <KolRowView key={`${r.kol_key}|${r.item_id}|${r.channel}`} row={r} />
        ))}
        {rows.length === 0 ? (
          <Empty testId="kol-empty">
            {channel === ALL && item === ALL
              ? "Chưa có đơn Tiếp thị liên kết theo KOL trong kỳ này. Tải lên báo cáo chuyển đổi Affiliate của Shopee, hoặc bấm Đồng bộ hôm qua trong Juli Connector khi trang Tăng Đơn Cùng KOL đã mở."
              : "Không có dòng nào khớp bộ lọc."}
          </Empty>
        ) : null}
      </div>
      <div className="kol-legend">
        <div>
          <b>ROI gồm mẫu (Juli)</b> <span className="sa-hint">{report.labels.roi_formula}. Dưới 0% là KOL chưa hoàn vốn mẫu.</span>
        </div>
        <div>
          <b>ROI Shopee (chỉ hoa hồng)</b>{" "}
          <span className="sa-hint">
            {report.labels.roi_shopee_note} Chỉ tính hoa hồng, không có giá vốn, phí sàn và mẫu nên thường trông tốt hơn. “{report.labels.low_data}” là cặp KOL × sản phẩm có dưới {threshold} đơn: số chỉ để tham khảo. Lượt nhấp, chuyển đổi và người mua là của cả KOL trên Shopee, không riêng sản phẩm này.
          </span>
        </div>
      </div>
      <span hidden>{links.critical()}</span>
    </>
  );
}

/** The channel pills: the raw value goes to the server, the seller reads its label (P100). */
function channelOptions(report: KolReport): { value: string; label: string }[] {
  const labelled = new Map((report.filters.channel_options ?? []).map((o) => [o.value, o.label]));
  return report.filters.channels.map((c) => ({ value: c, label: labelled.get(c) ?? c }));
}

function KolRowView({ row }: { readonly row: KolRow }) {
  const { links } = useShopee();
  const t = rowText(row);
  return (
    <div className={`kol-row ${t.few ? "kol-row--few" : ""}`} data-testid={`kol-row-${row.kol_key}-${row.item_id}`} role="row">
      <span role="cell">
        <b>{t.handle}</b>
        <span className="kol-sub">
          <span className="sa-chip sa-chip--outline">{t.channel}</span>
          {t.few ? <TextChip tone="warn">{t.fewLabel}</TextChip> : null}
        </span>
      </span>
      <span role="cell">{t.product}</span>
      <span role="cell">{t.orders}</span>
      <span role="cell">{t.units}</span>
      <span role="cell">{t.gmv}</span>
      <span role="cell">{t.clicks}</span>
      <span role="cell">{t.conversion}</span>
      <span role="cell">{t.buyers}</span>
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
              {row.card.kind_label} ›
            </Link>
          </>
        ) : (
          <span className="sa-hint">Chưa có thẻ</span>
        )}
      </span>
    </div>
  );
}
