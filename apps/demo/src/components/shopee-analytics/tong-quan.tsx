"use client";

import Link from "next/link";
import { useMemo } from "react";

import { useShopee } from "../../lib/shopee-analytics/context";
import {
  DASH,
  chipFromChange,
  chipPt,
  dayMonth,
  fmt,
  pc,
  pp,
  sv,
  vnd,
  type Chip,
} from "../../lib/shopee-analytics/format";
import {
  CAP_LABEL,
  fiveCards,
  freshnessOf,
  impactsOf,
  isStale,
  marginDropText,
  weakestLink,
} from "../../lib/shopee-analytics/model";
import { readWindow, type WindowState, windowParams } from "../../lib/shopee-analytics/params";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import type { Overview } from "../../lib/shopee-analytics/types";
import { FlowTree } from "./tong-quan-tree";
import { ProductMatrix } from "./tong-quan-matrix";
import { PeriodBar } from "./period-bar";
import { ChipView, InfoToggle, Notice, PageHead, ResourceState, Section, toneClass } from "./ui";

/**
 * Tổng quan (artboards TongQuan / TongQuanMobile): the shop in one screen. KPI strip, the five
 * numbers, shop profit with cost coverage, the GMV tree (five flows + Chênh lệch nguồn) and the
 * product × source matrix. Every number is a link to its Xếp hạng. The mobile layout is the same
 * markup under the stylesheet's narrow breakpoint (tiles 2 columns, rows as cards).
 */
export function TongQuanView({ params }: { readonly params: URLSearchParams }) {
  const host = useShopee();
  const state = useMemo(() => readWindow(params), [params]);
  const key = `${host.shopKey}|ov|${JSON.stringify(state.query)}`;
  const overview = useResource(() => host.api.overview(state.query), key);
  return (
    <div className="sa-page" data-testid="sa-tong-quan">
      <ResourceState resource={overview}>{(ov) => <Loaded ov={ov} state={state} />}</ResourceState>
    </div>
  );
}

function Loaded({ ov, state }: { readonly ov: Overview; readonly state: WindowState }) {
  const host = useShopee();
  const { links } = host;
  const win = ov.period.window;
  const stale = isStale(ov.data, win);
  const impacts = impactsOf(ov.kpi_strip, win.days);
  const weak = weakestLink(impacts);
  const target = ov.targets.margin_pct ?? null;
  const cap = ov.targets.daily_marketing_cap ?? null;
  const dropText = marginDropText(ov.kpi_strip);
  const asOf = `Dữ liệu đến ${dayMonth(win.to)} · nguồn Seller Centre`;
  const hrefFor = (next: WindowState) => {
    const q = windowParams(next);
    return links.screen("tong-quan", q);
  };
  const compare = state.compare;
  const five = fiveCards(ov.five_numbers, target);
  const days = win.days;
  const kpi = ov.kpi_strip;

  const tile = (
    key: string,
    label: string,
    value: string,
    chip: Chip,
    impact: string,
    flag: string,
    sub?: string,
  ) => (
    <Link
      className={`sa-tile ${flag ? "sa-tile--hint" : ""} ${sub === "below" ? "sa-tile--bad" : ""}`}
      data-testid={`sa-tile-${key}`}
      href={links.ranking({ kpi: key, src: "all", from: "tong-quan" }, state)}
      key={key}
    >
      <span className="sa-tile__top">
        <span className="sa-tile__label">{label}</span>
        {flag ? <span className="sa-tile__flag">{flag}</span> : null}
      </span>
      <span className="sa-tile__value">{value}</span>
      {compare ? (
        <span>
          <ChipView chip={chip} />
        </span>
      ) : null}
      <span className={`sa-tile__impact ${impact.startsWith("−") ? "sa-tone--down" : impact.startsWith("+") ? "sa-tone--up" : ""}`}>{impact}</span>
      {stale ? <span className="sa-tile__stale">Tính đến {dayMonth(win.to)}</span> : null}
    </Link>
  );
  const per = (v: number | null) => (v === null ? DASH : `${sv(v)}/ngày`);
  const marginChip = chipPt(kpi.margin_pct.previous, kpi.margin_pct.value);
  const profitDelta =
    ov.five_numbers.margin.profit_after !== null && ov.five_numbers.margin.profit_before !== null
      ? (ov.five_numbers.margin.profit_after - ov.five_numbers.margin.profit_before) / days
      : null;
  const belowTarget = kpi.margin_pct.value !== null && target !== null && kpi.margin_pct.value < target;
  const partial = ov.profit.profit_is_partial;

  return (
    <>
      <PageHead
        chips={
          <span className={`sa-fresh ${stale ? "sa-fresh--stale" : ""}`} data-testid="sa-fresh">
            {stale ? `Dữ liệu chưa đủ kỳ: số mới nhất đến ${dayMonth(win.to)}` : asOf}
          </span>
        }
        eyebrow="TỔNG QUAN"
        info={
          <InfoToggle>
            GMV = lượt xem × CTR × CTOR × AOV. Năm luồng (Thẻ sản phẩm ngoài Trang shop, Trang shop, Live, Video,
            Tiếp thị liên kết) cộng lại đúng bằng GMV shop; phần lệch hiện ở dòng Chênh lệch nguồn. Đơn tính theo
            đơn đã xác nhận; quảng cáo tính theo đơn đã đặt và là phần &quot;trong đó&quot;, không cộng thêm.
          </InfoToggle>
        }
        title={`${host.shopName || "Shop"}${dropText ? `: ${dropText}` : ": tổng quan"}`}
      />

      <div className="sa-row">
        <PeriodBar hrefFor={hrefFor} previous={ov.period.previous} state={state} window={win} />
        <span className="sa-hint sa-row__end">
          Mục tiêu biên: <b>{target === null ? "chưa đặt" : pp(target, 0)}</b> · Trần chi marketing:{" "}
          <b>{cap === null ? "chưa đặt" : `${vnd(cap)}/ngày`}</b>
        </span>
      </div>

      {stale ? <StaleBlock ov={ov} /> : null}
      {ov.warnings
        .filter((w) => !["ads_estimated"].includes(w.code))
        .map((w) => (
          <Notice key={w.code} testId={`sa-warning-${w.code}`}>
            {w.message}
          </Notice>
        ))}

      <Section hint="Bấm một ô để xem bảng xếp hạng · ₫/ngày là phần GMV chỉ số đó kéo" title="Sáu chỉ số chính">
        <div className="sa-tiles">
          {tile("gmv", "GMV", vnd(kpi.gmv.value), chipFromChange(kpi.gmv.change_pct), `Tổng 4 ô: ${per(impacts.gmv)}`, "")}
          {tile("views", "Lượt xem", fmt(kpi.views.value), chipFromChange(kpi.views.change_pct), per(impacts.views), weak === "views" ? "✦ Juli gợi ý" : "")}
          {tile("ctr", "CTR", pc(kpi.ctr.value), chipFromChange(kpi.ctr.change_pct), per(impacts.ctr), weak === "ctr" ? "✦ Juli gợi ý" : "")}
          {tile("ctor", "CTOR", pc(kpi.ctor.value), chipFromChange(kpi.ctor.change_pct), per(impacts.ctor), weak === "ctor" ? "✦ Juli gợi ý" : "")}
          {tile("aov", "AOV", vnd(kpi.aov.value), chipFromChange(kpi.aov.change_pct), per(impacts.aov), weak === "aov" ? "✦ Juli gợi ý" : "")}
          {tile(
            "bien",
            "Biên cuối",
            pp(kpi.margin_pct.value, 1),
            marginChip,
            partial && kpi.margin_pct.label ? kpi.margin_pct.label : `Lợi nhuận ${per(profitDelta)}`,
            belowTarget ? "Dưới mục tiêu" : "",
            belowTarget ? "below" : undefined,
          )}
        </div>
        {(ov.gmv.excluded_gmv ?? 0) > 0 ? (
          <p className="sa-hint" data-testid="sa-excluded-gmv">
            <b>GMV</b> trong đó{" "}
            <Link data-testid="sa-excluded-gmv-link" href={links.exclusions()}>
              {vnd(ov.gmv.excluded_gmv)} từ sản phẩm đã loại trừ
            </Link>
          </p>
        ) : null}
        <p className="sa-hint" data-testid="sa-aov-note">
          AOV ở đây = GMV ÷ đơn ({vnd(ov.gmv.aov_gmv)}); AOV theo Seller Centre (trừ voucher shop) ={" "}
          {vnd(ov.gmv.aov_seller_centre)}.
        </p>
      </Section>

      <Section hint="Cùng định nghĩa ở Tổng quan, Sản phẩm và thẻ · kèm chi marketing so với trần" title="5 con số chính">
        <div className="sa-five" data-testid="sa-five">
          {five.map((f) => (
            <Link
              className={`sa-five__card ${f.tone === "down" ? "sa-five__card--bad" : ""}`}
              data-testid={`sa-five-${f.key}`}
              href={links.ranking({ kpi: f.kpi, src: f.src ?? "all", from: "tong-quan" }, state)}
              key={f.key}
            >
              <span className="sa-tile__label">{f.label}</span>
              <span className="sa-five__value">{f.value}</span>
              <span>
                <span className={`sa-chip sa-chip--${f.tone}`}>{f.chip}</span>
              </span>
              <span className="sa-five__sub">{f.sub1}</span>
              <span className={`sa-five__sub sa-five__sub--b ${toneClass(f.tone)}`}>{f.sub2}</span>
            </Link>
          ))}
        </div>
        {!ov.five_numbers.comparison.available ? (
          <Notice tone="info" testId="sa-no-comparison">
            Kỳ trước chưa có dòng đơn hàng nên chỉ hiện số của kỳ này; Juli không so với một kỳ trống.
          </Notice>
        ) : null}
        <p className="sa-hint">
          ② = ΔGMV ÷ Δchi · {ov.five_numbers.chi_definition}. {CAP_LABEL}: chi ÷ số ngày của kỳ.
        </p>
      </Section>

      <ProfitBlock ov={ov} />
      <FlowTree ov={ov} state={state} />
      <ProductMatrix ov={ov} state={state} />
    </>
  );
}

function StaleBlock({ ov }: { readonly ov: Overview }) {
  const sources = freshnessOf(ov.data, ov.period.window);
  return (
    <section className="sa-stale" data-testid="sa-stale" role="status">
      <b>⚠ Dữ liệu chưa đủ cho cả kỳ: số hôm nay có thể thiếu</b>
      <div className="sa-stale__chips">
        {sources.map((s) => (
          <span className={`sa-chip ${s.ok ? "sa-chip--up" : "sa-chip--warn"}`} key={s.key}>
            {s.label}: {s.covered}/{s.days} ngày
          </span>
        ))}
      </div>
      <span className="sa-hint">
        Các con số bên dưới tính trên những ngày đã có dữ liệu. Đề xuất mới chỉ tạo khi dữ liệu đã cập nhật.
      </span>
    </section>
  );
}

function ProfitBlock({ ov }: { readonly ov: Overview }) {
  const host = useShopee();
  const p = ov.profit;
  const cov = p.cost_coverage;
  const partial = p.profit_is_partial;
  const productProfit =
    !partial && p.contribution_before_ads !== null && p.ad_spend.by_product !== null
      ? p.contribution_before_ads - p.ad_spend.by_product
      : null;
  const missing = Object.entries(p.missing).filter(([, n]) => n > 0);
  // Bar widths may use 0 for a missing share; every printed percentage stays "—" when it is missing.
  const realN = cov.real_pct ?? null;
  const assumedN = cov.assumed_pct ?? null;
  const unknownN = cov.unknown_pct ?? null;
  const real = realN ?? 0;
  const assumed = assumedN ?? 0;
  const unknown = unknownN ?? 0;
  const lines: { k: string; v: string; note: string; tone?: string }[] = [
    {
      k: "Lợi nhuận các sản phẩm",
      v: partial || productProfit === null ? DASH : vnd(productProfit),
      note: partial ? `Chưa hiện số đồng: còn ${pp(unknownN, 1)} doanh thu chưa có giá vốn` : "Σ lợi nhuận từng sản phẩm",
    },
    {
      k: "− QC không gắn sản phẩm",
      v: p.ad_spend.unattributed === null ? DASH : `−${vnd(p.ad_spend.unattributed)}`,
      note: `${p.ad_spend.unattributed_label} (đơn đã đặt)`,
      tone: "sa-tone--down",
    },
    {
      k: "− Chi marketing khác",
      v: p.other_marketing_costs === null ? DASH : `−${vnd(p.other_marketing_costs)}`,
      note: "Giải thưởng trò chơi, không nằm trên đơn",
      tone: "sa-tone--down",
    },
    {
      k: "= Lợi nhuận (chi tiết)",
      v: partial ? DASH : vnd(p.profit_waterfall_vnd ?? p.profit_vnd),
      note: partial
        ? "Chỉ hiện bằng đồng khi 100% doanh thu có giá vốn"
        : `${p.profit_detail_label ? `${p.profit_detail_label} · ` : ""}Biên ${pp(p.margin_pct, 1)} = lợi nhuận ÷ doanh thu thực (sau voucher và combo)`,
    },
    {
      k: "Lợi nhuận shop",
      v: partial ? DASH : vnd(p.profit_vnd),
      note: p.profit_estimated
        ? `${p.profit_estimate_label ?? "ước tính theo tỉ lệ"} · cùng số với Sản phẩm và Kế hoạch`
        : "Cùng số với Sản phẩm và Kế hoạch",
    },
  ];
  return (
    <Section hint={`Biên = ${p.margin_basis}`} testId="sa-profit" title="Lợi nhuận shop">
      <div className="sa-profit">
        <div className="sa-profit__lines">
          {lines.map((l) => (
            <div className="sa-profit__line" key={l.k}>
              <span className="sa-profit__k">{l.k}</span>
              <span className="sa-hint">{l.note}</span>
              <span className={`sa-profit__v ${l.tone ?? ""}`}>{l.v}</span>
            </div>
          ))}
          <p className="sa-hint" data-testid="sa-ad-check">
            Kiểm tra: QC các sản phẩm {vnd(p.ad_spend.by_product)} + QC không gắn sản phẩm{" "}
            {vnd(p.ad_spend.unattributed)} = tổng chi QC {vnd(p.ad_spend.total)}{" "}
            {p.ad_spend.consistent ? "✓" : "(chi phí theo sản phẩm lớn hơn tổng chiến dịch)"}
          </p>
        </div>
        <div className="sa-profit__panel">
          <span className="sa-tile__label">Biên lợi nhuận cuối</span>
          <span className={`sa-profit__margin ${ov.targets.margin_pct != null && p.margin_pct !== null && p.margin_pct < ov.targets.margin_pct ? "sa-tone--down" : ""}`} data-testid="sa-margin">
            {pp(p.margin_pct, 1)}
          </span>
          <span className="sa-tone--warn sa-profit__note">
            {partial
              ? `trên ${pp(realN !== null && assumedN !== null ? realN + assumedN : null, 1)} doanh thu có giá vốn`
              : "trên 100% doanh thu khách trả"}
          </span>
          <span aria-hidden="true" className="sa-cov">
            <span className="sa-cov__seg sa-cov__seg--real" style={{ width: `${real}%` }} />
            <span className="sa-cov__seg sa-cov__seg--assumed" style={{ width: `${assumed}%` }} />
            <span className="sa-cov__seg sa-cov__seg--unknown" style={{ width: `${unknown}%` }} />
          </span>
          <span className="sa-profit__cov" data-testid="sa-coverage">
            Giá vốn thật: <b>{pp(realN, 1)}</b> · {p.assumed_cost_label}: <b>{pp(assumedN, 1)}</b> · chưa có:{" "}
            <b>{pp(unknownN, 1)}</b>
          </span>
          {assumed > 0 ? (
            <span className="sa-hint" data-testid="sa-assumed-label">
              {pp(p.assumed_cost_share_pct, 1)} doanh thu dùng {p.assumed_cost_label}; biên chưa ngoại suy sang
              phần chưa có giá vốn.
            </span>
          ) : null}
          {missing.length > 0 ? (
            <span className="sa-hint">
              Thiếu: {missing.map(([k, n]) => `${k} (${fmt(n)} dòng)`).join(" · ")}
            </span>
          ) : null}
          {host.readOnly ? null : (
            <Link className="sa-link" href={host.links.costImport(null, "tong-quan")}>
              Nhập giá vốn ở Cài đặt ›
            </Link>
          )}
        </div>
      </div>
    </Section>
  );
}
