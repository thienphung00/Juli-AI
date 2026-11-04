"use client";

import Link from "next/link";

import { useShopee } from "../../lib/shopee-analytics/context";
import { pc } from "../../lib/shopee-analytics/format";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { FEW_ORDERS, KOL_KIND_LABEL, rowText } from "../../lib/shopee-kol/model";
import type { KolReport } from "../../lib/shopee-kol/types";
import { Empty, ResourceState, Section, TextChip } from "../shopee-analytics/ui";

/** Sản phẩm › Tiếp thị liên kết (`SanPhamLienKet.dc.html`): the KOLs of one product, the columns of Phân tích › KOL in short. */
export function ProductKolTab({ productId, productName }: { readonly productId: string; readonly productName: string }) {
  const host = useShopee();
  const res = useResource<KolReport | null>(() => (host.kol ? host.kol.report() : Promise.resolve(null)), `${host.shopKey}|kol`);
  return <ResourceState resource={res}>{(report) => (report ? <Body productId={productId} productName={productName} report={report} /> : null)}</ResourceState>;
}

function Body({ productId, productName, report }: { readonly productId: string; readonly productName: string; readonly report: KolReport }) {
  const { links } = useShopee();
  const rows = report.rows.filter((r) => r.product_id === productId);
  const rate = report.product_rates[productId];
  return (
    <Section hint={`30 ngày · ${rows.length} KOL · lợi nhuận ròng sau phí sàn, giá vốn, đóng gói, hoa hồng`} testId="sa-tab-kl" title={`KOL bán ${productName}`}>
      <p className="sa-hint" data-testid="kl-rate">
        Hoa hồng hiện tại {rate === undefined ? "—" : pc(rate, 0)} mỗi sản phẩm bán ra (mức áp dụng cho sản phẩm này)
      </p>
      <Link className="sa-link" href={links.screen("phan-tich", new URLSearchParams({ tab: "kol" }))}>
        Xem tất cả KOL trong Phân tích ›
      </Link>
      <div className="kol-table kol-table--compact" role="table">
        <div className="kol-row kol-row--head" role="row">
          {["KOL · kênh", "Đơn", "GMV", "Hoa hồng", "Lợi nhuận ròng", "Chi phí mẫu", "Lợi nhuận sau mẫu", "ROI gồm mẫu", "ROI Shopee (chỉ hoa hồng)", "Hoàn vốn", "Thẻ"].map((h) => (
            <span key={h} role="columnheader">
              {h}
            </span>
          ))}
        </div>
        {rows.map((r) => {
          const t = rowText(r);
          return (
            <div className={`kol-row ${t.few ? "kol-row--few" : ""}`} data-testid={`kl-row-${r.kol_key}`} key={`${r.kol_key}|${r.channel}`} role="row">
              <span role="cell">
                <b>{t.handle}</b>
                <span className="kol-sub">
                  <span className="sa-chip sa-chip--outline">{t.channel}</span>
                  {t.few ? <TextChip tone="warn">Ít dữ liệu</TextChip> : null}
                </span>
              </span>
              <span role="cell">{t.orders}</span>
              <span role="cell">{t.gmv}</span>
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
                {r.card ? (
                  <>
                    <span className="sd-code">{r.card.code}</span>{" "}
                    <Link className="sa-link" href={links.card(r.card.id, "san-pham")}>
                      {KOL_KIND_LABEL[r.card.kind]} ›
                    </Link>
                  </>
                ) : (
                  <span className="sa-hint">Chưa có thẻ</span>
                )}
              </span>
            </div>
          );
        })}
        {rows.length === 0 ? <Empty testId="kl-empty">Chưa có KOL nào bán sản phẩm này trong 30 ngày.</Empty> : null}
      </div>
      <p className="sa-hint">
        ROI Shopee (chỉ hoa hồng) là giá trị trong file xuất KOL của Shopee, giữ nguyên. ROI gồm mẫu = (lợi nhuận ròng − chi phí mẫu) ÷ (hoa hồng + chi phí mẫu). Cặp KOL × sản phẩm có dưới {FEW_ORDERS} đơn mang nhãn “Ít dữ liệu”.
      </p>
    </Section>
  );
}
