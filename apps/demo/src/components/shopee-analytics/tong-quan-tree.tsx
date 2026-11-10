"use client";

import Link from "next/link";
import { useState } from "react";

import { useShopee } from "../../lib/shopee-analytics/context";
import { DASH, chipFromChange, dayMonth, fmt, pc, pp, sv, vnd } from "../../lib/shopee-analytics/format";
import { impactsOf, weakestLink } from "../../lib/shopee-analytics/model";
import { childUrlKey, srcOfFlowKey, type WindowState } from "../../lib/shopee-analytics/params";
import type { CardChild, FlowRow, N, Overview } from "../../lib/shopee-analytics/types";
import { ChipView, Empty, Section } from "./ui";

/**
 * "GMV đến từ đâu" (ADR-120 d.3): GMV = lượt xem × CTR × CTOR × AOV, the five traffic flows that
 * add up to the shop GMV with the "Chênh lệch nguồn" row, Thẻ sản phẩm's six children as a
 * drill-down (never summed), the ads overlay as a dashed "trong đó" row (placed-order basis; per
 * D-3 it is shown for the shop and per product, not per flow) and the four price levers.
 */

const FLOW_SUB: Readonly<Record<string, string>> = {
  the_san_pham_khac: "Gồm 6 nguồn con · không gồm Trang shop",
  trang_shop: "Cửa hàng",
  live: "Lượt xem phiên Live",
  video: "Lượt xem video",
  lien_ket: "Gồm Affiliate Live và Video",
};

const ratio = (a: N | undefined, b: N | undefined): number | null =>
  typeof a === "number" && typeof b === "number" && b > 0 ? a / b : null;

export function FlowTree({ ov, state }: { readonly ov: Overview; readonly state: WindowState }) {
  const { links } = useShopee();
  const [open, setOpen] = useState(false);
  const [adOn, setAdOn] = useState(true);
  const flows = ov.flows;
  const kpi = ov.kpi_strip;
  const win = ov.period.window;
  const impacts = impactsOf(kpi, win.days);
  const weak = weakestLink(impacts);
  const rk = (kpiKey: string, src = "all", sub?: string | null) =>
    links.ranking({ kpi: kpiKey, src, sub: sub ?? null, from: "tong-quan" }, state);
  const per = (v: number | null) => (v === null ? DASH : `${sv(v)}/ngày`);

  const node = (key: string, label: string, value: string, chipPctChange: number | null, impact: string, extra = "") => (
    <Link className={`sa-node ${extra}`} data-testid={`sa-node-${key}`} href={rk(key)} key={key}>
      <span className="sa-tile__label">{label}</span>
      <span className="sa-node__value">{value}</span>
      <span>
        <ChipView chip={chipFromChange(chipPctChange)} />
      </span>
      <span className={`sa-tile__impact ${impact.startsWith("−") ? "sa-tone--down" : "sa-tone--up"}`}>{impact}</span>
    </Link>
  );

  return (
    <Section
      aside={`Dữ liệu đến ${dayMonth(win.to)}`}
      hint="GMV = lượt xem × CTR × CTOR × AOV · năm luồng cộng lại bằng GMV shop"
      testId="sa-tree"
      title="GMV đến từ đâu"
    >
      <div className="sa-chain">
        {node("views", "Lượt xem", fmt(kpi.views.value), kpi.views.change_pct, per(impacts.views), weak === "views" ? "sa-node--hint" : "")}
        <span aria-hidden="true" className="sa-chain__op">×</span>
        {node("ctr", "CTR", pc(kpi.ctr.value), kpi.ctr.change_pct, per(impacts.ctr), weak === "ctr" ? "sa-node--hint" : "")}
        <span aria-hidden="true" className="sa-chain__op">×</span>
        {node("ctor", "CTOR", pc(kpi.ctor.value), kpi.ctor.change_pct, per(impacts.ctor), weak === "ctor" ? "sa-node--hint" : "")}
        <span aria-hidden="true" className="sa-chain__op">×</span>
        {node("aov", "AOV", vnd(kpi.aov.value), kpi.aov.change_pct, per(impacts.aov), weak === "aov" ? "sa-node--hint" : "")}
        <span aria-hidden="true" className="sa-chain__op">=</span>
        {node("gmv", "GMV", vnd(kpi.gmv.value), kpi.gmv.change_pct, `Tổng: ${per(impacts.gmv)}`, "sa-node--gmv")}
      </div>
      {flows.chain && !flows.chain.identity_ok ? (
        <p className="sa-hint" data-testid="sa-chain-identity">
          Chuỗi theo luồng cho {vnd(flows.chain.identity_gmv)} so với GMV {vnd(flows.chain.gmv)}: {flows.chain.note}
        </p>
      ) : null}

      <div className="sa-subhead">
        <b>Năm luồng lưu lượng</b>
        <span className="sa-hint">Bấm số để xem xếp hạng · bấm ▸ ở Thẻ sản phẩm để mở sáu nguồn con</span>
        <button
          aria-pressed={adOn}
          className={`sa-toggle ${adOn ? "sa-toggle--on" : ""} sa-toggle--right`}
          onClick={() => setAdOn((v) => !v)}
          type="button"
        >
          {adOn ? "Ẩn Quảng cáo (trong đó)" : "Hiện Quảng cáo (trong đó)"}
        </button>
      </div>

      {flows.available && flows.rows ? (
        <FlowTable
          adOn={adOn}
          ov={ov}
          open={open}
          rk={rk}
          setOpen={setOpen}
        />
      ) : (
        <Empty testId="sa-flows-empty">Chưa có lưu lượng theo nguồn cho kỳ này. Khi báo cáo lưu lượng được tải lên, năm luồng sẽ hiện ở đây.</Empty>
      )}
      <LeversBlock ov={ov} state={state} />
    </Section>
  );
}

function FlowTable({
  ov,
  open,
  setOpen,
  adOn,
  rk,
}: {
  readonly ov: Overview;
  readonly open: boolean;
  readonly setOpen: (v: boolean) => void;
  readonly adOn: boolean;
  readonly rk: (kpi: string, src?: string, sub?: string | null) => string;
}) {
  const flows = ov.flows;
  const rows = flows.rows ?? [];
  const total = flows.total_gmv ?? null;
  const kids = flows.the_san_pham_children;
  const cell = (label: string, value: string, href: string, chip?: React.ReactNode) => (
    <Link className="sa-fcell" href={href} key={label}>
      <span className="sa-fcell__label">{label}</span>
      <span className="sa-fcell__v">{value}</span>
      {chip}
    </Link>
  );
  const flowCells = (r: FlowRow, src: string, sub?: string | null) => [
    cell("Lượt xem", fmt(r.views), rk("views", src, sub)),
    cell("CTR", pc(r.ctr), rk("ctr", src, sub)),
    cell("CTOR", pc(r.ctor), rk("ctor", src, sub)),
    cell("AOV", vnd(r.aov), rk("aov", src, sub)),
    cell("GMV", vnd(r.gmv), rk("gmv", src, sub), r.gmv_change_pct !== undefined ? <ChipView chip={chipFromChange(r.gmv_change_pct)} /> : null),
    cell("% GMV", pp(r.share_pct, 1), rk("gmv", src, sub)),
    <span className="sa-fcell sa-fcell--na" key="bien" title="Biên chưa tách được theo luồng: đơn hàng không ghi nguồn lưu lượng">
      <span className="sa-fcell__label">Biên</span>
      <span className="sa-fcell__v">{DASH}</span>
    </span>,
  ];
  const real = rows.filter((r) => !r.is_residual);
  const residual = rows.find((r) => r.is_residual);
  const tsp = real.find((r) => r.key === "the_san_pham_khac");
  const trang = real.find((r) => r.key === "trang_shop");
  const gap: number | null = residual?.gmv ?? null;
  return (
    <div className="sa-flows" data-testid="sa-flows">
      <div className="sa-frow sa-frow--head" aria-hidden="true">
        <span>Luồng</span>
        <span>Lượt xem</span>
        <span>CTR</span>
        <span>CTOR</span>
        <span>AOV</span>
        <span>GMV</span>
        <span>% GMV</span>
        <span>Biên</span>
      </div>
      {real.map((r) => {
        const src = srcOfFlowKey(r.key);
        const isTsp = r.key === "the_san_pham_khac";
        return (
          <div key={r.key}>
            <div className="sa-frow" data-testid={`sa-flow-${r.key}`}>
              <span className="sa-frow__name">
                {isTsp && kids ? (
                  <button aria-expanded={open} aria-label="Mở các nguồn con" className="sa-caret" onClick={() => setOpen(!open)} type="button">
                    {open ? "▾" : "▸"}
                  </button>
                ) : null}
                <span>
                  <b>{r.label}</b>
                  <span className="sa-hint sa-block">{FLOW_SUB[r.key] ?? ""}</span>
                </span>
              </span>
              {flowCells(r, src)}
            </div>
            {isTsp && open && kids
              ? kids.rows.map((k) => (
                  <div className="sa-frow sa-frow--kid" data-testid={`sa-kid-${k.key}`} key={k.key}>
                    <span className="sa-frow__name">
                      <span>
                        <span>{k.label}</span>
                        <span className="sa-hint sa-block">Nguồn con của Thẻ sản phẩm</span>
                      </span>
                    </span>
                    {kidCells(k, total, rk)}
                  </div>
                ))
              : null}
          </div>
        );
      })}
      {adOn ? (
        <div className="sa-frow sa-frow--ad" data-testid="sa-ads-row">
          <span className="sa-frow__name">
            <span>
              <i>trong đó Quảng cáo</i>
              <span className="sa-hint sa-block">
                {ov.ads.basis.label} · ROAS {fmt(ov.ads.roas, 1)} · chi {vnd(ov.ads.spend)}
              </span>
            </span>
          </span>
          <Link className="sa-fcell sa-fcell--span" href={rk("gmv", "ads")}>
            <span className="sa-fcell__label">GMV ({ov.ads.basis.label})</span>
            <span className="sa-fcell__v">{vnd(ov.ads.gmv_placed)}</span>
          </Link>
          <Link className="sa-fcell" href={rk("orders", "ads")}>
            <span className="sa-fcell__label">Đơn ({ov.ads.basis.label})</span>
            <span className="sa-fcell__v">{fmt(ov.ads.orders_placed)}</span>
          </Link>
          <span className="sa-hint sa-fcell--span2">{ov.ads.note}</span>
        </div>
      ) : null}
      {residual ? (
        <div className="sa-frow sa-frow--diff" data-testid="sa-residual">
          <span className="sa-frow__name">
            <span>
              <b>Chênh lệch nguồn</b>
              <span className="sa-hint sa-block">Shopee loại trùng người mua giữa các nguồn · không chia ngược vào luồng nào</span>
            </span>
          </span>
          <span className="sa-fcell sa-fcell--na" />
          <span className="sa-fcell sa-fcell--na" />
          <span className="sa-fcell sa-fcell--na" />
          <span className="sa-fcell sa-fcell--na" />
          <span className="sa-fcell">
            <span className="sa-fcell__label">GMV</span>
            <span className="sa-fcell__v sa-tone--warn">{sv(residual.gmv)}</span>
          </span>
          <span className="sa-fcell">
            <span className="sa-fcell__label">% GMV</span>
            <span className="sa-fcell__v sa-tone--warn">{pp(residual.share_pct, 1)}</span>
          </span>
          <span className="sa-fcell sa-fcell--na" />
        </div>
      ) : null}
      <div className="sa-frow sa-frow--total" data-testid="sa-flow-total">
        <span className="sa-frow__name">
          <span>
            <b>GMV shop</b>
            <span className="sa-hint sa-block">Năm luồng + chênh lệch nguồn = GMV shop</span>
          </span>
        </span>
        <Link className="sa-fcell" href={rk("views")}>
          <span className="sa-fcell__label">Lượt xem</span>
          <span className="sa-fcell__v">{fmt(ov.kpi_strip.views.value)}</span>
        </Link>
        <Link className="sa-fcell" href={rk("ctr")}>
          <span className="sa-fcell__label">CTR</span>
          <span className="sa-fcell__v">{pc(ov.kpi_strip.ctr.value)}</span>
        </Link>
        <Link className="sa-fcell" href={rk("ctor")}>
          <span className="sa-fcell__label">CTOR</span>
          <span className="sa-fcell__v">{pc(ov.kpi_strip.ctor.value)}</span>
        </Link>
        <Link className="sa-fcell" href={rk("aov")}>
          <span className="sa-fcell__label">AOV</span>
          <span className="sa-fcell__v">{vnd(ov.kpi_strip.aov.value)}</span>
        </Link>
        <Link className="sa-fcell" href={rk("gmv")}>
          <span className="sa-fcell__label">GMV</span>
          <span className="sa-fcell__v">{vnd(total)}</span>
          <ChipView chip={chipFromChange(ov.kpi_strip.gmv.change_pct)} />
        </Link>
        <span className="sa-fcell">
          <span className="sa-fcell__label">% GMV</span>
          <span className="sa-fcell__v">100,0%</span>
        </span>
        <span className="sa-fcell sa-fcell--na" />
      </div>
      <p className="sa-hint" data-testid="sa-sum-check">
        Σ năm luồng {vnd(flows.gmv_sum)} {gap === null ? "+ chênh lệch chưa rõ" : `${gap >= 0 ? "+" : "−"} chênh lệch ${vnd(Math.abs(gap))}`} = GMV shop {vnd(total)}
        {flows.adds_up === false ? " (chưa khớp)" : ""}
      </p>
      {tsp && trang ? (
        <p className="sa-hint" data-testid="sa-tsp-note">
          Shopee tính &ldquo;Thẻ sản phẩm&rdquo; gồm cả Trang shop: tổng Shopee {vnd(tsp.gmv != null && trang.gmv != null ? tsp.gmv + trang.gmv : null)} = Thẻ
          sản phẩm (ngoài Trang shop) {vnd(tsp.gmv)} + Trang shop {vnd(trang.gmv)}. Juli tách Trang shop ra để năm luồng cộng
          đúng bằng GMV.
        </p>
      ) : null}
    </div>
  );
}

function kidCells(k: CardChild, total: N, rk: (kpi: string, src?: string, sub?: string | null) => string) {
  const sub = childUrlKey(k.key);
  const link = (kpi: string) => rk(kpi, "the_san_pham", sub);
  const cells: [string, string, string][] = [
    ["Lượt xem", fmt(k.views), "views"],
    ["CTR", pc(ratio(k.clicks, k.views)), "ctr"],
    ["CTOR", pc(ratio(k.orders, k.clicks)), "ctor"],
    ["AOV", vnd(ratio(k.gmv, k.orders)), "aov"],
    ["GMV", vnd(k.gmv), "gmv"],
    ["% GMV", pp(total && k.gmv != null ? (k.gmv / total) * 100 : null, 1), "gmv"],
  ];
  return [
    ...cells.map(([label, value, kpi]) => (
      <Link className="sa-fcell" href={link(kpi)} key={label}>
        <span className="sa-fcell__label">{label}</span>
        <span className="sa-fcell__v">{value}</span>
      </Link>
    )),
    <span className="sa-fcell sa-fcell--na" key="bien" />,
  ];
}

function LeversBlock({ ov, state }: { readonly ov: Overview; readonly state: WindowState }) {
  const { links } = useShopee();
  const lv = ov.levers;
  const src: Record<string, string> = { khong_uu_dai: "none", voucher: "voucher", khuyen_mai: "promo", combo: "combo" };
  return (
    <div className="sa-levers" data-testid="sa-levers">
      <div className="sa-subhead">
        <b>Mức ưu đãi trên mỗi dòng đơn</b>
        <span className="sa-hint">{lv.note}</span>
      </div>
      {lv.rows.map((r) => (
        <Link
          className="sa-lever"
          href={links.ranking({ kpi: "gmv", src: src[r.key] ?? "all", from: "tong-quan" }, state)}
          key={r.key}
        >
          <b>{r.label}</b>
          <span>{fmt(r.orders)} đơn</span>
          <span>{vnd(r.gmv)}</span>
          <span>{pp(r.share_pct, 1)} GMV</span>
          <span>Biên {pp(r.margin_pct, 1)}</span>
        </Link>
      ))}
      <p className="sa-hint">
        Σ bốn mức = {vnd(lv.gmv_sum)} {lv.adds_up ? "= GMV theo dòng đơn" : `(GMV theo dòng đơn ${vnd(lv.gmv_total)})`}
      </p>
    </div>
  );
}
