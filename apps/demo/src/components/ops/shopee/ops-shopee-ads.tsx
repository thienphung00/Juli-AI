"use client";

import { useEffect, useMemo, useState } from "react";

import { opsApi, type OpsApi } from "../../../lib/ops/api";
import { fmtDate } from "../../../lib/ops/format";
import type { OpsMe, ShopeeAds, ShopeeOrderType, ShopeePromotions } from "../../../lib/ops/types";
import { C, OpsHeader, OpsPage } from "../ops-shell";
import { OpsSkeleton } from "../ops-skeleton";
import { Lines, StackedBars } from "./shopee-charts";
import {
  DayRange,
  Empty,
  ORDER_TYPE_LABEL,
  OrderTypeSelect,
  PageTitle,
  Section,
  TD,
  TD_LEFT,
  TH,
  TH_LEFT,
  TableWrap,
  errorText,
  fmtCount,
  fmtMonth,
  fmtRange,
  fmtRoas,
  fmtVnd,
} from "./shopee-ui";

/**
 * Quảng cáo + khuyến mãi (ADR-117 step 4, G5): cost / orders / ROAS / cost per order by ad
 * type, monthly and daily, the promotion programme timeline, and an alert when an ad type's
 * ROAS stays under the floor for several days in a row. Campaign-level numbers need the
 * ads-campaign files, which are not loaded yet: an explicit empty state.
 */

type Api = Pick<OpsApi, "shopeeAds" | "shopeePromotions">;

export function OpsShopeeAds({ me, shopId, api = opsApi }: { readonly me: OpsMe; readonly shopId: string; readonly api?: Api }) {
  const [orderType, setOrderType] = useState<ShopeeOrderType | null>(null);
  const [range, setRange] = useState<{ from: string; to: string } | null>(null);
  const [ads, setAds] = useState<ShopeeAds | null>(null);
  const [promos, setPromos] = useState<ShopeePromotions | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    const q = { ...(range ? { from: range.from, to: range.to } : {}) };
    // The ads section counts placed orders; the promotions follow the confirmed ones, unless the user picks one.
    Promise.all([
      api.shopeeAds(shopId, { ...q, ...(orderType ? { orderType } : {}) }),
      api.shopeePromotions(shopId, { ...q, ...(orderType ? { orderType } : {}) }),
    ])
      .then(([a, p]) => {
        if (!live) return;
        setError(null);
        setAds(a);
        setPromos(p);
      })
      .catch((e) => live && setError(errorText(e)));
    return () => {
      live = false;
    };
  }, [api, shopId, orderType, range]);

  return (
    <OpsPage>
      <OpsHeader me={me} shopId={shopId} />
      <main style={{ padding: "22px 28px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
        <PageTitle active="quang-cao" shopId={shopId} title="Shopee · Quảng cáo + khuyến mãi" />
        {error ? (
          <p role="alert" style={{ margin: 0, color: C.red }}>
            {error}
          </p>
        ) : null}
        <div style={{ display: "flex", gap: 16, alignItems: "flex-end", flexWrap: "wrap" }}>
          <OrderTypeSelect onChange={setOrderType} value={orderType ?? ads?.order_type ?? "placed"} />
          <DayRange onApply={(from, to) => setRange({ from, to })} value={ads?.range ?? null} />
        </div>
        {!error && (!ads || !promos) ? <OpsSkeleton /> : null}
        {ads ? <AdsSection ads={ads} /> : null}
        {promos ? <PromotionsSection promos={promos} /> : null}
      </main>
    </OpsPage>
  );
}

function AdsSection({ ads }: { readonly ads: ShopeeAds }) {
  const types = ads.by_type;
  const monthChart = ads.monthly.map((m) => ({
    label: fmtMonth(m.month),
    ...Object.fromEntries(m.by_type.map((t) => [t.ad_type, t.cost])),
  }));
  const roasDaily = ads.daily.map((d) => ({
    label: fmtDate(d.day).slice(0, 5),
    ...Object.fromEntries(d.by_type.map((t) => [t.ad_type, t.roas])),
  }));
  const series = types.map((t) => ({ key: t.ad_type, label: t.label ?? t.ad_type }));
  return (
    <>
      {ads.alerts.map((a) => (
        <div key={a.ad_type} role="alert" style={{ background: "#fdecec", color: C.red, borderRadius: 12, padding: "10px 14px", fontSize: 14 }}>
          <b>{a.label}</b>: ROAS {fmtRoas(a.roas)} thấp hơn {fmtRoas(a.floor)} trong {a.days} ngày liên tục ({fmtDate(a.from)} – {fmtDate(a.to)}).
        </div>
      ))}
      <Section hint={`${fmtRange(ads.range)} · ${ORDER_TYPE_LABEL[ads.order_type]}`} title="Quảng cáo theo loại">
        {!ads.has_data ? (
          <Empty>Chưa có dữ liệu quảng cáo cho khoảng ngày này.</Empty>
        ) : (
          <>
            <TableWrap label="Quảng cáo theo loại">
              <thead>
                <tr>
                  <th style={TH_LEFT}>Loại quảng cáo</th>
                  <th style={TH}>Chi phí</th>
                  <th style={TH}>Đơn</th>
                  <th style={TH}>GMV</th>
                  <th style={TH}>ROAS</th>
                  <th style={TH}>Chi phí mỗi đơn</th>
                </tr>
              </thead>
              <tbody>
                {types.map((t) => (
                  <tr key={t.ad_type}>
                    <td style={TD_LEFT}>{t.label ?? t.ad_type}</td>
                    <td style={TD}>{fmtVnd(t.cost)}</td>
                    <td style={TD}>{fmtCount(t.orders)}</td>
                    <td style={TD}>{fmtVnd(t.gmv)}</td>
                    <td style={TD}>{fmtRoas(t.roas)}</td>
                    <td style={TD}>{fmtVnd(t.cost_per_order)}</td>
                  </tr>
                ))}
                <tr data-testid="ads-total">
                  <td style={{ ...TD_LEFT, fontWeight: 700 }}>Tổng</td>
                  <td style={{ ...TD, fontWeight: 700 }}>{fmtVnd(ads.total.cost)}</td>
                  <td style={{ ...TD, fontWeight: 700 }}>{fmtCount(ads.total.orders)}</td>
                  <td style={{ ...TD, fontWeight: 700 }}>{fmtVnd(ads.total.gmv)}</td>
                  <td style={{ ...TD, fontWeight: 700 }}>{fmtRoas(ads.total.roas)}</td>
                  <td style={{ ...TD, fontWeight: 700 }}>{fmtVnd(ads.total.cost_per_order)}</td>
                </tr>
              </tbody>
            </TableWrap>
            <p style={{ margin: 0, fontSize: 12, color: C.muted2 }}>
              Cảnh báo khi ROAS một loại dưới {fmtRoas(ads.alert_rule.floor)} trong ít nhất {ads.alert_rule.min_days} ngày liên tục.
            </p>
            <h3 style={{ margin: "6px 0 0", fontSize: 14 }}>Chi phí theo tháng</h3>
            {monthChart.length > 0 ? <StackedBars data={monthChart} label="Chi phí quảng cáo theo tháng" series={series} /> : <Empty>Chưa có lịch sử theo tháng.</Empty>}
            {ads.monthly.length > 0 ? (
              <TableWrap label="Quảng cáo theo tháng">
                <thead>
                  <tr>
                    <th style={TH_LEFT}>Tháng</th>
                    <th style={TH}>Chi phí</th>
                    <th style={TH}>Đơn</th>
                    <th style={TH}>GMV</th>
                    <th style={TH}>ROAS</th>
                    <th style={TH}>Chi phí mỗi đơn</th>
                  </tr>
                </thead>
                <tbody>
                  {ads.monthly.map((m) => (
                    <tr key={m.month}>
                      <td style={TD_LEFT}>{fmtMonth(m.month)}</td>
                      <td style={TD}>{fmtVnd(m.cost)}</td>
                      <td style={TD}>{fmtCount(m.orders)}</td>
                      <td style={TD}>{fmtVnd(m.gmv)}</td>
                      <td style={TD}>{fmtRoas(m.roas)}</td>
                      <td style={TD}>{fmtVnd(m.cost_per_order)}</td>
                    </tr>
                  ))}
                </tbody>
              </TableWrap>
            ) : null}
            <h3 style={{ margin: "6px 0 0", fontSize: 14 }}>ROAS theo ngày</h3>
            <Lines data={roasDaily} label="ROAS theo ngày và loại quảng cáo" reference={ads.alert_rule.floor} series={series} />
          </>
        )}
      </Section>
      <Section title="Theo chiến dịch">
        {ads.campaigns_available && ads.campaigns.length > 0 ? null : (
          <Empty>Chưa có dữ liệu theo chiến dịch: file báo cáo chiến dịch quảng cáo chưa được nạp. Bảng trên là số theo loại quảng cáo.</Empty>
        )}
      </Section>
    </>
  );
}

const DAY_MS = 86_400_000;

function PromotionsSection({ promos }: { readonly promos: ShopeePromotions }) {
  const bars = useMemo(() => {
    const from = Date.parse(promos.range.from);
    const span = Date.parse(promos.range.to) - from + DAY_MS;
    return promos.programs.map((p) => {
      const start = Math.max(Date.parse(p.starts_at.slice(0, 10)), from);
      const end = Math.min(p.ends_at ? Date.parse(p.ends_at.slice(0, 10)) + DAY_MS : from + span, from + span);
      return { left: ((start - from) / span) * 100, width: Math.max(((end - start) / span) * 100, 1.5) };
    });
  }, [promos]);
  return (
    <Section hint={`${fmtRange(promos.range)} · ${ORDER_TYPE_LABEL[promos.order_type]}`} title="Chương trình khuyến mãi">
      {promos.programs.length === 0 ? (
        <Empty>Không có chương trình khuyến mãi nào trong khoảng ngày này.</Empty>
      ) : (
        <div aria-label="Dòng thời gian khuyến mãi" role="list" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {promos.programs.map((p, i) => (
            <div key={`${p.promo_type}-${p.name}-${p.starts_at}-${i}`} role="listitem" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.2fr) minmax(0, 2fr) 150px", gap: 10, alignItems: "center", fontSize: 13 }}>
              <span>
                <b>{p.name}</b>
                <br />
                <span style={{ color: C.muted2, fontSize: 12 }}>
                  {p.type_label} · {fmtDate(p.starts_at)} – {p.ends_at ? fmtDate(p.ends_at) : "chưa kết thúc"}
                  {p.status ? ` · ${p.status}` : ""}
                </span>
              </span>
              <span aria-hidden="true" style={{ position: "relative", height: 12, background: "#f0eef0", borderRadius: 6 }}>
                <span style={{ position: "absolute", left: `${bars[i]?.left ?? 0}%`, width: `${bars[i]?.width ?? 0}%`, top: 0, bottom: 0, background: C.pinkStrong, borderRadius: 6 }} />
              </span>
              <span style={{ textAlign: "right" }}>
                {fmtVnd(p.gmv)}
                <br />
                <span style={{ color: C.muted2, fontSize: 12 }}>{fmtCount(p.orders)} đơn</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}
