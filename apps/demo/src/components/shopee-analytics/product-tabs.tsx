"use client";

import Link from "next/link";
import { useState } from "react";

import { useShopee } from "../../lib/shopee-analytics/context";
import { DASH, chipFromChange, fmt, pc, pp, sv, vnd } from "../../lib/shopee-analytics/format";
import { srcOfFlowKey, type WindowState } from "../../lib/shopee-analytics/params";
import type { HistoryEvent, KeywordEntry, ProductPage, SkuCost } from "../../lib/shopee-analytics/types";
import { Bar, ChipView, Empty, Notice, Section, TextChip } from "./ui";

/** The five sub-tabs of the product page. */

export function PerformanceTab({ page, periodHref }: { readonly page: ProductPage; readonly periodHref: (period: string) => string }) {
  const sel = page.period.selected;
  const k = page.kpi_by_period[sel];
  const periods: [string, string][] = [
    ["7d", "7 ngày"],
    ["30d", "30 ngày"],
    ["90d", "90 ngày"],
  ];
  if (!k) return <Empty>Chưa có số liệu hiệu suất cho kỳ này.</Empty>;
  const chain: [string, string, React.ReactNode][] = [
    ["Lượt xem", fmt(k.views), null],
    ["CTR", pc(k.ctr), null],
    ["CTOR", pc(k.ctor), null],
    ["AOV", vnd(k.aov), null],
    ["GMV", vnd(k.gmv.value), <ChipView chip={chipFromChange(k.gmv.change_pct)} key="g" />],
    ["Biên lợi nhuận", pp(k.profit?.margin_pct, 1), null],
  ];
  return (
    <Section testId="sa-tab-hs" title="Hiệu suất">
      <div className="sa-perhead">
        <div aria-label="Kỳ" className="sa-seg" role="group">
          {periods.map(([p, label]) => (
            <Link aria-current={sel === p ? "true" : undefined} className={`sa-seg__item ${sel === p ? "sa-seg__item--on" : ""}`} href={periodHref(p)} key={p}>
              {label}
            </Link>
          ))}
        </div>
        <span className="sa-hint">Chuỗi chỉ số: Lượt xem → CTR → CTOR → AOV → GMV → Biên lợi nhuận</span>
      </div>
      <div className="sa-chain6">
        {chain.map(([label, value, chip]) => (
          <div className="sa-node" key={label}>
            <span className="sa-tile__label">{label}</span>
            <span className="sa-node__value">{value}</span>
            {chip}
          </div>
        ))}
      </div>
      {k.views === null ? (
        <p className="sa-hint" data-testid="sa-no-flows-chain">
          Lượt xem, CTR, CTOR của sản phẩm này chưa có trong kỳ (chưa có báo cáo lưu lượng theo sản phẩm).
        </p>
      ) : null}
      <Empty testId="sa-no-daily">
        Chuỗi theo ngày và các thẻ đã thực hiện (◆) chưa có trong dữ liệu của trang này; hiện chỉ có tổng theo kỳ. Số GMV ở
        đây dùng cơ sở &ldquo;{k.basis.gmv === "shopee_product_period" ? "báo cáo sản phẩm của Shopee" : "dòng đơn hàng"}&rdquo;, cùng số với
        Tổng quan và Xếp hạng.
      </Empty>
    </Section>
  );
}

export function SourcesTab({ id, page, state }: { readonly id: string; readonly page: ProductPage; readonly state: WindowState }) {
  const { links } = useShopee();
  const n = page.nguon;
  const flows = n.flows;
  const totalOrders = n.orders ?? 0;
  const has5 = page.item_traffic_sources != null || flows?.trang_shop_available === true;
  const rows = flows ? flows.rows.filter((r) => !r.is_residual) : [];
  const residual = flows?.rows.find((r) => r.is_residual);
  const [adOn, setAdOn] = useState(true);
  const rk = (kpi: string, src: string) => links.ranking({ kpi, src, focus: id, from: "san-pham" }, state);
  const ads = page.ads;
  const levers = n.levers;
  return (
    <Section
      aside={
        <button aria-pressed={adOn} className={`sa-toggle ${adOn ? "sa-toggle--on" : ""}`} onClick={() => setAdOn(!adOn)} type="button">
          {adOn ? "Ẩn lớp Quảng cáo" : "Hiện lớp Quảng cáo (trong đó)"}
        </button>
      }
      hint={`${page.period.window.days} ngày · ${fmt(totalOrders)} đơn`}
      testId="sa-tab-ng"
      title="Nguồn của sản phẩm này"
    >
      <h3 className="sa-h3">Luồng khách vào</h3>
      {flows ? (
        <>
          <div className="sa-prow sa-prow--head">
            <span>Nguồn</span>
            <span>Đơn</span>
            <span>Tỉ lệ đơn</span>
            <span>GMV</span>
            <span>Biên</span>
            <span>→ đề xuất</span>
          </div>
          {rows.map((r) => (
            <div className="sa-prow" data-testid={`sa-ng-flow-${r.key}`} key={r.key}>
              <Link className="sa-prow__name" href={rk("gmv", srcOfFlowKey(r.key))}>
                <b>{r.label}</b>
              </Link>
              <b>{fmt(r.orders)}</b>
              <span className="sa-prow__share">
                <Bar pct={totalOrders ? (r.orders / totalOrders) * 100 : null} />
                <b>{pp(totalOrders ? (r.orders / totalOrders) * 100 : null, 1)}</b>
              </span>
              <span>{vnd(r.gmv)}</span>
              <span className="sa-hint" title="Biên chưa tách được theo luồng">{DASH}</span>
              <span className="sa-hint">Chưa có đề xuất</span>
            </div>
          ))}
          {residual ? (
            <div className="sa-prow sa-prow--diff" data-testid="sa-ng-residual">
              <span>
                <b>Chênh lệch nguồn</b>
                <span className="sa-hint sa-block">loại trùng người mua</span>
              </span>
              <b>{residual.orders >= 0 ? "+" : "−"}{fmt(Math.abs(residual.orders))}</b>
              <span />
              <span>{sv(residual.gmv)}</span>
              <span />
              <span />
            </div>
          ) : null}
          <div className="sa-prow sa-prow--total">
            <span className="sa-hint">Tổng · bằng số đơn của sản phẩm</span>
            <b>
              {fmt(totalOrders)} đơn · 100,0% · {vnd(n.gmv)} · {pp(n.profit?.margin_pct, 1)} biên
            </b>
          </div>
          {!has5 ? (
            <Notice tone="info" testId="sa-four-flows">
              Sản phẩm này có 4 luồng (trang_shop_available: false): Thẻ sản phẩm gồm cả Trang shop. Năm luồng chỉ có khi
              Connector đã đọc lưu lượng theo sản phẩm (item_traffic_sources).
            </Notice>
          ) : null}
        </>
      ) : (
        <Empty testId="sa-ng-noflows">Chưa có lưu lượng theo nguồn cho sản phẩm này trong kỳ.</Empty>
      )}

      <h3 className="sa-h3">Mức ưu đãi trên mỗi dòng đơn</h3>
      <div className="sa-prow sa-prow--head">
        <span>Loại ưu đãi</span>
        <span>Đơn</span>
        <span>Tỉ lệ đơn</span>
        <span>GMV</span>
        <span>Biên</span>
        <span>→ đề xuất</span>
      </div>
      {levers.map((l) => {
        const srcKey = { khong_uu_dai: "none", voucher: "voucher", khuyen_mai: "promo", combo: "combo" }[l.key] ?? "all";
        return (
          <div className="sa-prow" data-testid={`sa-ng-lever-${l.key}`} key={l.key}>
            <Link className="sa-prow__name" href={rk("gmv", srcKey)}>
              <b>{l.label}</b>
            </Link>
            <b>{fmt(l.orders)}</b>
            <span className="sa-prow__share">
              <Bar pct={totalOrders ? (l.orders / totalOrders) * 100 : null} />
              <b>{pp(totalOrders ? (l.orders / totalOrders) * 100 : null, 1)}</b>
            </span>
            <span>{vnd(l.gmv)}</span>
            <span>{pp(l.margin_pct, 1)}</span>
            <span className="sa-hint">Chưa có đề xuất</span>
          </div>
        );
      })}

      {adOn ? (
        <div className="sa-adbox" data-testid="sa-ng-ads">
          <div className="sa-subhead">
            <h3 className="sa-h3">Quảng cáo · lớp phủ</h3>
            <TextChip tone="pink">{ads.basis.label}</TextChip>
            <span className="sa-hint">{ads.note}</span>
          </div>
          <div className="sa-pairs sa-pairs--4">
            <div className="sa-pair">
              <span className="sa-hint">Chi</span>
              <b>{vnd(ads.spend)}</b>
            </div>
            <div className="sa-pair">
              <span className="sa-hint">GMV ({ads.basis.label})</span>
              <b>{vnd(ads.gmv_placed)}</b>
            </div>
            <div className="sa-pair">
              <span className="sa-hint">ROAS (rộng · trực tiếp)</span>
              <b>
                {fmt(ads.roas_broad, 2)} · {fmt(ads.roas_direct, 2)}
              </b>
            </div>
            <div className="sa-pair">
              <span className="sa-hint">ROAS hoà vốn</span>
              <b className={ads.below_break_even ? "sa-tone--down" : ""}>
                {fmt(ads.break_even_roas, 2)}
                {ads.below_break_even ? " · đang dưới hoà vốn" : ""}
              </b>
            </div>
          </div>
          <p className="sa-hint">Quảng cáo nằm trong các luồng (chủ yếu Thẻ sản phẩm), không cộng thêm vào tổng.</p>
        </div>
      ) : null}
    </Section>
  );
}

function kwRow(k: KeywordEntry, roleLabel: string, tone: "pink" | "flat") {
  const m = k.market;
  return (
    <div className="sa-kwrow" data-testid={`sa-kw-${k.keyword}`} key={`${roleLabel}-${k.keyword}`}>
      <span>
        <b>{k.keyword}</b>
        <TextChip tone={tone}>{roleLabel}</TextChip>
      </span>
      <span>{m ? fmt(m.volume) : "chưa thu thập"}</span>
      <span>{m ? fmt(m.difficulty, 0) : DASH}</span>
      <span>{m ? `${vnd(m.cpc_min)}–${vnd(m.cpc_max)}` : DASH}</span>
      <span className={k.in_title === false ? "sa-tone--warn" : ""}>
        {k.in_title === null ? DASH : k.in_title ? `ký tự ${k.title_position}${k.within_counted_chars === false ? " (ngoài 100 ký tự)" : ""}` : "không có trong tiêu đề"}
      </span>
      <span>
        {k.ads_placed ? `chi ${vnd(k.ads_placed.spend)} · ${fmt(k.ads_placed.orders)} đơn (đơn đã đặt)` : DASH}
      </span>
    </div>
  );
}

export function KeywordsTab({ page }: { readonly id: string; readonly page: ProductPage }) {
  const kw = page.keywords;
  const chinh = kw.roles.chinh?.keywords ?? [];
  const phu = kw.roles.phu?.keywords ?? [];
  const brand = kw.roles.thuong_hieu?.keywords ?? [];
  const excluded = kw.roles.loai_tru?.keywords ?? [];
  const limit = kw.core.full;
  const total = chinh.length + phu.length + brand.length;
  return (
    <Section
      aside={<TextChip tone={limit ? "warn" : "up"}>{kw.core.used}/{kw.core.max} chính</TextChip>}
      hint={`Danh sách từ khoá của sản phẩm · tối đa ${kw.core.max} từ khoá chính`}
      testId="sa-tab-kw"
      title="Từ khoá"
    >
      {limit ? (
        <Notice testId="sa-kw-limit">
          <b>Đã đủ {kw.core.max} từ khoá chính.</b> Muốn thêm từ khoá chính mới, hãy hạ một từ khoá chính xuống Phụ. Từ khoá
          phụ không giới hạn.
        </Notice>
      ) : null}
      {total + excluded.length === 0 ? (
        <Empty testId="sa-kw-empty">
          Sản phẩm này chưa có danh sách từ khoá. Khi chủ shop thu thập từ khoá (lượt tìm, độ khó, CPC), danh sách hiện ở đây.
        </Empty>
      ) : (
        <>
          <div className="sa-pairs sa-pairs--3">
            <div className="sa-pair sa-pair--pink">
              <span className="sa-hint">Từ khoá chính có trong tiêu đề</span>
              <b data-testid="sa-kw-cover">
                {kw.core.in_title}/{kw.core.used} · {pp(kw.core.coverage_pct, 0)}
              </b>
            </div>
            <div className="sa-pair">
              <span className="sa-hint">Tìm kiếm chỉ hiện</span>
              <b>{kw.title_counted_chars} ký tự đầu của tiêu đề</b>
            </div>
          </div>
          <div className="sa-kwrow sa-kwrow--head">
            <span>Từ khoá</span>
            <span>Lượt tìm/tháng</span>
            <span>Độ khó</span>
            <span>CPC</span>
            <span>Vị trí trong tiêu đề</span>
            <span>Quảng cáo theo từ khoá</span>
          </div>
          {chinh.map((k) => kwRow(k, "Chính", "pink"))}
          {phu.map((k) => kwRow(k, "Phụ", "flat"))}
          {brand.map((k) => kwRow(k, "Thương hiệu", "flat"))}
          {excluded.length > 0 ? (
            <div className="sa-excl" data-testid="sa-kw-excluded">
              <span className="sa-hint">Loại trừ · không dùng trong tiêu đề và quảng cáo</span>
              <span className="sa-chips">
                {excluded.map((k) => (
                  <span className="sa-chip sa-chip--down" key={k.keyword}>
                    − {k.keyword}
                  </span>
                ))}
              </span>
            </div>
          ) : null}
        </>
      )}
      <p className="sa-hint">Lượt tìm, độ khó, CPC do chủ shop thu thập · vị trí trong tiêu đề tính từ tiêu đề hiện tại.</p>
    </Section>
  );
}

function wfRows(sku: SkuCost) {
  const w = sku.waterfall_per_unit;
  const rows: [string, number | null, "pos" | "neg" | "total"][] = [
    ["Giá niêm yết", w.list, "pos"],
    ["− Khuyến mãi", w.promo_discount, "neg"],
    ["− Voucher shop", w.shop_voucher, "neg"],
    ["− Combo", w.combo, "neg"],
    ["= Khách trả (doanh thu thực)", w.net_revenue, "total"],
    ["− Phí sàn", w.platform_fees, "neg"],
    ["− Giá vốn", w.cogs, "neg"],
    ["− Đóng gói", w.packaging, "neg"],
    ["− Hoa hồng liên kết", w.commission, "neg"],
    ["= Đóng góp trước quảng cáo", w.contribution_before_ads, "total"],
    ["− Quảng cáo", w.ads, "neg"],
    ["= Lợi nhuận", w.profit, "total"],
  ];
  return rows;
}

export function CostTab({ page, sel, onPick }: { readonly page: ProductPage; readonly sel: SkuCost | null; readonly onPick: (sku: string) => void }) {
  const host = useShopee();
  const c = page.cost_and_floor;
  if (!sel) {
    return (
      <Section testId="sa-tab-cp" title="Chi phí và giá sàn">
        <Empty testId="sa-cp-empty">Chưa có dòng đơn của sản phẩm này trong kỳ nên chưa tính được chi phí theo phiên bản.</Empty>
      </Section>
    );
  }
  const floor = sel.floor;
  const noCost = sel.cost.cogs_per_unit === null || !floor || (floor.absolute === null && floor.operating === null);
  const pay = floor?.net_revenue_per_unit ?? null;
  const gauge = (() => {
    if (!floor || floor.absolute === null || floor.operating === null || sel.list_price === null) return null;
    const pts = [floor.absolute, floor.operating, sel.list_price, ...(pay !== null ? [pay] : [])];
    const lo = Math.min(...pts) * 0.9;
    const hi = Math.max(...pts) * 1.02;
    const pos = (x: number) => ((x - lo) / (hi - lo)) * 100;
    return { abs: pos(floor.absolute), op: pos(floor.operating), pay: pay === null ? null : pos(pay), list: pos(sel.list_price) };
  })();
  return (
    <Section hint="Mỗi đơn · chọn phiên bản" testId="sa-tab-cp" title="Chi phí và giá sàn">
      <div className="sa-chips">
        {c.skus.map((s) => (
          <button aria-pressed={s.sku === sel.sku} className={`sa-pill ${s.sku === sel.sku ? "sa-pill--on" : ""}`} key={s.sku} onClick={() => onPick(s.sku)} type="button">
            {s.sku}
            {s.cost.cogs_per_unit === null ? " · thiếu giá vốn" : ""}
          </button>
        ))}
      </div>
      {noCost ? (
        <div className="sa-nocost" data-testid="sa-nocost">
          <b>Chưa có giá vốn cho {sel.sku}</b>
          <span>Không có giá vốn, Juli chưa tính được biên lợi nhuận và giá sàn của phiên bản này.</span>
          {host.readOnly ? null : (
            <Link className="sa-btn sa-btn--primary" href={host.links.costImport(sel.sku, "san-pham")}>
              Nhập giá vốn ở Cài đặt ›
            </Link>
          )}
        </div>
      ) : null}
      {sel.cost.label ? (
        <Notice testId="sa-assumed-cost">
          Giá vốn của {sel.sku} là <b>{sel.cost.label}</b>
          {sel.cost.cogs_per_unit !== null ? ` (${vnd(sel.cost.cogs_per_unit)}/sản phẩm)` : ""}, chưa phải giá vốn thật. Biên và giá sàn bên dưới chỉ mang tính ước tính cho đến khi nhập giá vốn.
        </Notice>
      ) : null}
      <div className="sa-cost">
        <div>
          <h3 className="sa-h3">Một đơn {sel.sku}</h3>
          <div className="sa-wf" data-testid="sa-waterfall">
            {wfRows(sel).map(([label, v, kind]) => (
              <div className={`sa-wf__row sa-wf__row--${kind}`} key={label}>
                <span>{label}</span>
                <b>{v === null ? DASH : vnd(Math.abs(v) < 0.5 ? 0 : v)}</b>
              </div>
            ))}
            <div className="sa-wf__row sa-wf__row--total">
              <span>Biên lợi nhuận</span>
              <b>{pp(sel.waterfall_per_unit.margin_pct, 1)}</b>
            </div>
          </div>
          <p className="sa-hint">
            Trung bình mỗi đơn trong kỳ ({fmt(sel.units)} sản phẩm). Phí sàn {pp(sel.fee.platform_fee_rate_pct, 1)} trên số tiền khách trả
            · phí cố định/đơn {vnd(sel.fee.fixed_per_order)}. Đơn xuất không ghi đơn nào đến từ quảng cáo, nên chưa tách tự nhiên / từ QC.
          </p>
        </div>
        <div className="sa-floors">
          <h3 className="sa-h3">Giá sàn</h3>
          <div className="sa-pair">
            <span className="sa-hint">Giá sàn tuyệt đối · không lỗ</span>
            <b className="sa-pair__big">{floor?.absolute == null ? "chưa có giá vốn" : vnd(floor.absolute)}</b>
            <span className="sa-hint">(giá vốn + đóng gói + phí cố định) ÷ (1 − phí sàn)</span>
          </div>
          <div className="sa-pair sa-pair--pink">
            <span className="sa-hint">Giá sàn vận hành · còn đạt biên mục tiêu</span>
            <b className="sa-pair__big">{floor?.operating == null ? "chưa có" : vnd(floor.operating)}</b>
            <span className="sa-hint">cùng tử số ÷ (1 − phí sàn − QC − hoa hồng − biên mục tiêu {pp(floor?.margin_target_pct, 0)})</span>
          </div>
          <div className="sa-pair">
            <span className="sa-hint">Giảm tối đa</span>
            <b className="sa-pair__big">
              {floor?.max_discount_pct == null ? "chưa có" : `${pp(floor.max_discount_pct, 1)} · ${vnd(floor.max_discount_amount)}`}
            </b>
            <span className="sa-hint">1 − giá sàn vận hành ÷ giá niêm yết, lấy nhỏ hơn trần bạn đặt</span>
          </div>
          {gauge ? (
            <div className="sa-gauge" data-testid="sa-gauge">
              <div className="sa-gauge__rail">
                <span className="sa-gauge__bad" style={{ left: `${gauge.abs}%`, width: `${gauge.op - gauge.abs}%` }} />
                <span className="sa-gauge__ok" style={{ left: `${gauge.op}%`, width: `${100 - gauge.op}%` }} />
                <span className="sa-gauge__tick sa-gauge__tick--abs" style={{ left: `${gauge.abs}%` }} />
                <span className="sa-gauge__tick sa-gauge__tick--op" style={{ left: `${gauge.op}%` }} />
                {gauge.pay !== null ? <span className="sa-gauge__tick sa-gauge__tick--pay" style={{ left: `${gauge.pay}%` }} /> : null}
                <span className="sa-gauge__tick sa-gauge__tick--list" style={{ left: `${gauge.list}%` }} />
              </div>
              <div className="sa-gauge__legend">
                <span>▎ tuyệt đối</span>
                <span>▎ vận hành</span>
                <span>▎ khách trả {vnd(pay)}</span>
                <span>▎ niêm yết {vnd(sel.list_price)}</span>
              </div>
            </div>
          ) : null}
          {floor && pay !== null && floor.operating !== null ? (
            <div className={`sa-verdict ${floor.breach ? "sa-verdict--bad" : "sa-verdict--ok"}`} data-testid="sa-verdict">
              {floor.breach
                ? `Khách trả ${vnd(pay)} thấp hơn giá sàn ${floor.breach === "absolute" ? "tuyệt đối" : "vận hành"} ${vnd(((floor.breach === "absolute" ? floor.absolute : floor.operating) ?? 0) - pay)}`
                : `Khách trả ${vnd(pay)} cao hơn giá sàn vận hành ${vnd(pay - floor.operating)} · còn đạt biên mục tiêu`}
            </div>
          ) : null}
        </div>
      </div>
      <p className="sa-hint">{c.floor_note}</p>
      <p className="sa-hint">{c.coverage_label}: dùng khi chưa nhập giá vốn thật.</p>
    </Section>
  );
}

const HIST_FILTERS: [string, string][] = [
  ["all", "Tất cả"],
  ["card", "Thẻ"],
  ["change", "Thay đổi phát hiện"],
  ["input", "Thông số"],
];

export function HistoryTab({ page }: { readonly page: ProductPage }) {
  const [f, setF] = useState("all");
  const events: readonly HistoryEvent[] = page.history ?? [];
  const shown = events.filter((e) => f === "all" || e.type === f);
  return (
    <Section hint="Chỉ thêm, không sửa · mới nhất ở trên" testId="sa-tab-ls" title="Lịch sử">
      <div aria-label="Lọc lịch sử" className="sa-seg" role="group">
        {HIST_FILTERS.map(([k, label]) => (
          <button aria-pressed={f === k} className={`sa-seg__item ${f === k ? "sa-seg__item--on" : ""}`} key={k} onClick={() => setF(k)} type="button">
            {label}
          </button>
        ))}
      </div>
      {events.length === 0 ? (
        <Empty testId="sa-history-empty">
          Chưa có lịch sử cho sản phẩm này. Thẻ đã thực hiện và các thay đổi phát hiện (tiêu đề, ảnh, giá) sẽ hiện ở đây khi
          Juli đọc Seller Centre hai lần và thấy khác nhau.
        </Empty>
      ) : (
        <div className="sa-timeline">
          {shown.map((e, i) => (
            <div className="sa-event" key={`${e.at}-${i}`}>
              <span className="sa-event__d">{e.at.slice(0, 10).split("-").reverse().slice(0, 2).join("/")}</span>
              <div>
                <b>{e.title}</b>
                {e.detail ? <span className="sa-hint sa-block">{e.detail}</span> : null}
                {e.before || e.after ? (
                  <div className="sa-diff">
                    {e.before ? <s>{e.before}</s> : null}
                    {e.after ? <b>{e.after}</b> : null}
                  </div>
                ) : null}
              </div>
              <TextChip tone={e.type === "card" ? "pink" : "flat"}>{HIST_FILTERS.find(([k]) => k === e.type)?.[1] ?? e.type}</TextChip>
            </div>
          ))}
          {shown.length === 0 ? <Empty>Không có sự kiện nào trong nhóm này.</Empty> : null}
        </div>
      )}
    </Section>
  );
}
