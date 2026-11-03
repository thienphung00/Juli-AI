"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { useShopee } from "../../lib/shopee-analytics/context";
import { DASH, chipOf, chipPt, fmt, pc, pp, sv, vnd, type Chip } from "../../lib/shopee-analytics/format";
import { CELL_THRESHOLD, isBad, isGood } from "../../lib/shopee-analytics/model";
import { srcOfFlowKey, type WindowState } from "../../lib/shopee-analytics/params";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import type { FlowRow, LeverRow, MatrixProduct, N, Overview } from "../../lib/shopee-analytics/types";
import { ChipView, Empty, Ini, ResourceState, Section, initialsOf } from "./ui";

/**
 * "Sản phẩm × nguồn": every product with the nine numbers (Lượt xem, CTR, CTOR, ⑤ AOV, GMV,
 * ④ Đơn, ③ Biên cuối, ① % giảm, ② Thu / chi thêm), the traffic ↔ price-lever switch, a sort on any
 * column and filters. A product opens into its five flows (four when the product has no Trang shop
 * split), "Chênh lệch nguồn" and the ads overlay (placed-order basis, "trong đó"). Cells compare
 * with the previous window read from the same matrix API. ① and ② are per-product figures the
 * matrix payload does not carry; they read "—" here and are on the product page.
 */

type ColKey = "views" | "ctr" | "ctor" | "aov" | "gmv" | "orders" | "bien" | "disc" | "eff";

interface Col {
  readonly key: ColKey;
  readonly label: string;
  /** The ranking KPI the cell opens. */
  readonly kpi: string;
  readonly kind: "rel" | "pt";
}

const COLS: readonly Col[] = [
  { key: "views", label: "Lượt xem", kpi: "views", kind: "rel" },
  { key: "ctr", label: "CTR", kpi: "ctr", kind: "rel" },
  { key: "ctor", label: "CTOR", kpi: "ctor", kind: "rel" },
  { key: "aov", label: "⑤ AOV", kpi: "aov", kind: "rel" },
  { key: "gmv", label: "GMV", kpi: "gmv", kind: "rel" },
  { key: "orders", label: "④ Đơn", kpi: "orders", kind: "rel" },
  { key: "bien", label: "③ Biên cuối", kpi: "bien", kind: "pt" },
  { key: "disc", label: "① % giảm", kpi: "disc", kind: "pt" },
  { key: "eff", label: "② Thu / chi thêm", kpi: "gmv", kind: "rel" },
];

interface Figures {
  views: N;
  ctr: N;
  ctor: N;
  aov: N;
  gmv: N;
  orders: N;
  bien: N;
}

const ratio = (a: N, b: N): N => (typeof a === "number" && typeof b === "number" && b > 0 ? a / b : null);

function sumFlows(rows: readonly FlowRow[]): { views: N; clicks: N } {
  const flows = rows.filter((r) => !r.is_residual);
  const views = flows.reduce((t, r) => t + (r.views ?? 0), 0);
  const clicks = flows.reduce((t, r) => t + (r.clicks ?? 0), 0);
  return { views: views || null, clicks: clicks || null };
}

export function figuresOf(p: MatrixProduct): Figures {
  const { views, clicks } = p.flows ? sumFlows(p.flows.rows) : { views: null, clicks: null };
  return {
    views,
    ctr: ratio(clicks, views),
    ctor: ratio(p.orders, clicks),
    aov: ratio(p.gmv, p.orders),
    gmv: p.gmv,
    orders: p.orders,
    bien: p.profit?.margin_pct ?? null,
  };
}

interface Shown {
  readonly value: string;
  readonly chip: Chip | null;
  readonly tone: "bad" | "good" | "";
  readonly raw: number | null;
}

function show(col: Col, now: Figures, before: Figures | null, target: N): Shown {
  const v = (now as unknown as Record<string, N>)[col.key] ?? null;
  const b = before ? ((before as unknown as Record<string, N>)[col.key] ?? null) : null;
  if (col.key === "disc" || col.key === "eff") return { value: DASH, chip: null, tone: "", raw: null };
  const text =
    col.key === "views" || col.key === "orders"
      ? fmt(v)
      : col.key === "ctr" || col.key === "ctor"
        ? pc(v)
        : col.key === "bien"
          ? pp(v, 1)
          : vnd(v);
  const chip = before ? (col.kind === "pt" ? chipPt(b, v) : chipOf(b, v)) : null;
  let tone: Shown["tone"] = "";
  if (col.key === "bien") {
    if (v !== null && target !== null && v < target) tone = "bad";
  } else if (chip) {
    tone = isBad(chip, CELL_THRESHOLD) ? "bad" : isGood(chip, CELL_THRESHOLD) ? "good" : "";
  }
  return { value: text, chip, tone, raw: v };
}

type Filter = "all" | "bad" | "bien" | "ctor" | "rec";

export function ProductMatrix({ ov, state }: { readonly ov: Overview; readonly state: WindowState }) {
  const host = useShopee();
  const { links } = host;
  const [dim, setDim] = useState<"traffic" | "price">("traffic");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<{ key: ColKey; dir: "asc" | "desc" }>({ key: "gmv", dir: "desc" });
  const [openIds, setOpenIds] = useState<Readonly<Record<string, boolean>>>({});
  const [showAll, setShowAll] = useState(false);
  const prev = ov.period.previous;
  const key = `${host.shopKey}|mx|${JSON.stringify(state.query)}`;
  const now = useResource(() => host.api.matrix({ ...state.query, sort: "gmv" }), key);
  const before = useResource(
    () =>
      state.compare
        ? host.api.matrix({ period: "custom", from: prev.from, to: prev.to, sort: "gmv" })
        : Promise.resolve(null),
    `${key}|prev|${state.compare}|${prev.from}|${prev.to}`,
  );
  const target = ov.targets.margin_pct ?? null;
  const rk = (kpi: string, src = "all", sub?: string | null) =>
    links.ranking({ kpi, src, sub: sub ?? null, from: "tong-quan" }, state);

  return (
    <Section
      hint="Bấm tên để mở năm luồng · bấm số để xem xếp hạng · bấm tiêu đề cột để sắp xếp"
      testId="sa-matrix"
      title="Sản phẩm × nguồn"
    >
      <ResourceState resource={now}>
        {(m) => {
          const beforeMap = new Map<string, MatrixProduct>();
          if (before.status === "ready" && before.data) before.data.products.forEach((p) => beforeMap.set(p.product_id, p));
          return (
            <MatrixBody
              beforeMap={beforeMap}
              compare={state.compare && before.status === "ready"}
              dim={dim}
              filter={filter}
              matrix={m}
              openIds={openIds}
              ov={ov}
              rk={rk}
              setDim={setDim}
              setFilter={setFilter}
              setOpenIds={setOpenIds}
              setShowAll={setShowAll}
              setSort={setSort}
              showAll={showAll}
              sort={sort}
              state={state}
              target={target}
            />
          );
        }}
      </ResourceState>
    </Section>
  );
}

interface BodyProps {
  readonly matrix: import("../../lib/shopee-analytics/types").Matrix;
  readonly beforeMap: ReadonlyMap<string, MatrixProduct>;
  readonly compare: boolean;
  readonly dim: "traffic" | "price";
  readonly filter: Filter;
  readonly sort: { key: ColKey; dir: "asc" | "desc" };
  readonly openIds: Readonly<Record<string, boolean>>;
  readonly showAll: boolean;
  readonly ov: Overview;
  readonly state: WindowState;
  readonly target: N;
  readonly rk: (kpi: string, src?: string, sub?: string | null) => string;
  readonly setDim: (d: "traffic" | "price") => void;
  readonly setFilter: (f: Filter) => void;
  readonly setSort: (s: { key: ColKey; dir: "asc" | "desc" }) => void;
  readonly setOpenIds: (o: Readonly<Record<string, boolean>>) => void;
  readonly setShowAll: (v: boolean) => void;
}

const PAGE = 25;

function MatrixBody(props: BodyProps) {
  const { matrix, beforeMap, compare, dim, filter, sort, openIds, showAll, ov, state, target, rk } = props;
  const { links } = useShopee();
  const rows = useMemo(() => {
    const built = matrix.products.map((p) => {
      const nowF = figuresOf(p);
      const bp = beforeMap.get(p.product_id);
      const beforeF = compare && bp ? figuresOf(bp) : null;
      const cells = COLS.map((c) => ({ col: c, ...show(c, nowF, beforeF, target) }));
      return {
        p,
        nowF,
        cells,
        hasBad: cells.some((c) => c.tone === "bad"),
        bienLow: target !== null && nowF.bien !== null && nowF.bien < target,
        ctorDown: beforeF ? chipOf(beforeF.ctor, nowF.ctor).up === false : false,
        card: p.card ?? null,
      };
    });
    return built;
  }, [matrix, beforeMap, compare, target]);
  const counts = {
    all: rows.length,
    bad: rows.filter((r) => r.hasBad).length,
    bien: rows.filter((r) => r.bienLow).length,
    ctor: rows.filter((r) => r.ctorDown).length,
    rec: rows.filter((r) => r.card).length,
  };
  const filtered = rows.filter((r) =>
    filter === "bad" ? r.hasBad : filter === "bien" ? r.bienLow : filter === "ctor" ? r.ctorDown : filter === "rec" ? r.card : true,
  );
  const sorted = [...filtered].sort((a, b) => {
    const av = (a.nowF as unknown as Record<string, N>)[sort.key];
    const bv = (b.nowF as unknown as Record<string, N>)[sort.key];
    const x = av ?? (sort.dir === "asc" ? Infinity : -Infinity);
    const y = bv ?? (sort.dir === "asc" ? Infinity : -Infinity);
    return (sort.dir === "asc" ? 1 : -1) * (x - y);
  });
  const visible = showAll ? sorted : sorted.slice(0, PAGE);
  const FILTERS: [Filter, string][] = [
    ["all", "Tất cả"],
    ["bad", "Có ô đỏ"],
    ["bien", "Biên dưới mục tiêu"],
    ["ctor", "CTOR giảm"],
    ["rec", "Có đề xuất"],
  ];
  const sortLabel = COLS.find((c) => c.key === sort.key)?.label.replace(/^[①②③④⑤] /, "") ?? "";
  const shopGmv = ov.kpi_strip.gmv.value;
  const productSum = matrix.sums.gmv_shopee_products;
  const gap = shopGmv !== null && productSum !== null ? shopGmv - productSum : null;

  return (
    <>
      <div className="sa-matrix__bar">
        <div aria-label="Chiều nguồn" className="sa-seg" role="group">
          {(["traffic", "price"] as const).map((d) => (
            <button
              aria-pressed={dim === d}
              className={`sa-seg__item ${dim === d ? "sa-seg__item--on" : ""}`}
              key={d}
              onClick={() => props.setDim(d)}
              type="button"
            >
              {d === "traffic" ? "Theo lưu lượng" : "Theo ưu đãi"}
            </button>
          ))}
        </div>
        <div className="sa-matrix__filters">
          <span className="sa-hint">Lọc</span>
          {FILTERS.map(([k, label]) => (
            <button
              aria-pressed={filter === k}
              className={`sa-pill ${filter === k ? "sa-pill--on" : ""}`}
              key={k}
              onClick={() => props.setFilter(k)}
              type="button"
            >
              {label} · {counts[k]}
            </button>
          ))}
        </div>
        <span className="sa-hint" data-testid="sa-sort-note">
          Sắp theo {sortLabel} {sort.dir === "asc" ? "thấp → cao" : "cao → thấp"}
        </span>
      </div>

      <div className="sa-mrow sa-mrow--head">
        <span>Sản phẩm</span>
        {COLS.map((c) => (
          <button
            aria-label={`Sắp theo ${c.label}`}
            className={`sa-mhead ${sort.key === c.key ? "sa-mhead--on" : ""}`}
            key={c.key}
            onClick={() =>
              props.setSort({
                key: c.key,
                dir: sort.key === c.key ? (sort.dir === "asc" ? "desc" : "asc") : c.key === "bien" ? "asc" : "desc",
              })
            }
            type="button"
          >
            {c.label}
            <br />
            {sort.key === c.key ? (sort.dir === "asc" ? "▲ thấp → cao" : "▼ cao → thấp") : " "}
          </button>
        ))}
        <span />
      </div>

      {visible.map((r) => {
        const open = !!openIds[r.p.product_id];
        return (
          <div className={`sa-mcard ${open ? "sa-mcard--open" : ""}`} data-testid={`sa-mrow-${r.p.product_id}`} key={r.p.product_id}>
            <div className="sa-mrow">
              <button
                aria-expanded={open}
                className="sa-mname"
                onClick={() => props.setOpenIds({ ...openIds, [r.p.product_id]: !open })}
                type="button"
              >
                <span className="sa-hint sa-caret-s">{open ? "▾" : "▸"}</span>
                <Ini text={initialsOf(r.p.name)} />
                <span>
                  <span className="sa-mname__t">{r.p.name}</span>
                  <span className="sa-hint sa-block">
                    {r.p.product_id}
                    {r.p.profit?.cost_coverage_pct != null && r.p.profit.cost_coverage_pct < 99.95
                      ? ` · biên trên ${pp(r.p.profit.cost_coverage_pct, 0)} DT có giá vốn`
                      : ""}
                    {r.p.profit?.assumed_cost ? " · giá vốn giả định (1/3 giá)" : ""}
                  </span>
                </span>
              </button>
              {r.cells.map((c) => (
                <Link
                  className={`sa-mcell ${c.tone ? `sa-mcell--${c.tone}` : ""}`}
                  href={rk(c.col.kpi, "all")}
                  key={c.col.key}
                >
                  <span className="sa-fcell__label">{c.col.label}</span>
                  <b>{c.value}</b>
                  {c.chip ? <ChipView chip={c.chip} invert={c.col.key === "disc"} /> : null}
                </Link>
              ))}
              <span className="sa-mrec">
                {r.card ? (
                  <Link className="sa-rec" href={links.card(r.card.id, "tong-quan")}>
                    → {r.card.at_stake_per_month != null ? `${sv(r.card.at_stake_per_month)}/th` : "đề xuất"}
                    <br />
                    <span className="sa-hint">{r.card.title ?? ""}</span>
                  </Link>
                ) : (
                  <span className="sa-hint">Chưa có đề xuất</span>
                )}
              </span>
            </div>
            {open ? <ProductSources dim={dim} p={r.p} prev={beforeMap.get(r.p.product_id) ?? null} rk={rk} state={state} /> : null}
          </div>
        );
      })}
      {sorted.length === 0 ? (
        <Empty testId="sa-matrix-empty">Không có sản phẩm nào khớp bộ lọc. Bỏ lọc để xem lại cả danh sách.</Empty>
      ) : null}
      {!showAll && sorted.length > PAGE ? (
        <button className="sa-btn" onClick={() => props.setShowAll(true)} type="button">
          Xem tất cả {sorted.length} sản phẩm
        </button>
      ) : null}

      <div className="sa-mrow sa-mrow--rest" data-testid="sa-matrix-gap">
        <span>Chênh lệch giữa Doanh số shop và Σ sản phẩm</span>
        <span className="sa-mcell">
          <b>{gap === null ? DASH : sv(gap)}</b>
        </span>
      </div>
      <div className="sa-mrow sa-mrow--total" data-testid="sa-matrix-total">
        <b>Tổng shop · bằng sáu ô phía trên</b>
        <span className="sa-mcell">
          <span className="sa-fcell__label">GMV</span>
          <b>{vnd(shopGmv)}</b>
        </span>
        <span className="sa-mcell">
          <span className="sa-fcell__label">④ Đơn</span>
          <b>{fmt(ov.kpi_strip.orders.value)}</b>
        </span>
        <span className="sa-mcell">
          <span className="sa-fcell__label">③ Biên cuối</span>
          <b>{pp(ov.kpi_strip.margin_pct.value, 1)}</b>
        </span>
      </div>
      <p className="sa-hint">{matrix.sums.note}</p>
      <div className="sa-legend">
        <span>
          <i className="sa-swatch sa-swatch--bad" />
          Đỏ: xấu đi từ 8% trở lên, biên dưới mục tiêu, hoặc chi thêm nhiều hơn thu thêm
        </span>
        <span>
          <i className="sa-swatch sa-swatch--good" />
          Xanh: tốt lên từ 8% trở lên
        </span>
        <span>— : chưa tách được theo nguồn</span>
      </div>
    </>
  );
}

function ProductSources({
  p,
  prev,
  dim,
  rk,
  state,
}: {
  readonly p: MatrixProduct;
  readonly prev: MatrixProduct | null;
  readonly dim: "traffic" | "price";
  readonly rk: (kpi: string, src?: string, sub?: string | null) => string;
  readonly state: WindowState;
}) {
  const { links } = useShopee();
  const price = dim === "price";
  const totalOrders = p.orders ?? 0;
  const prevFlows = new Map((prev?.flows?.rows ?? []).map((r) => [r.key, r]));
  const prevLevers = new Map((prev?.levers ?? []).map((r) => [r.key, r]));
  const sub = (name: string, share: string, cells: [string, string, string, Chip | null][], testId: string, extra = "") => (
    <div className={`sa-srow ${extra}`} data-testid={testId} key={testId}>
      <span className="sa-srow__name">
        <b>{name}</b>
        <span className="sa-hint sa-block">{share}</span>
      </span>
      {cells.map(([label, value, href, chip]) => (
        <Link className="sa-mcell" href={href} key={label}>
          <span className="sa-fcell__label">{label}</span>
          <b>{value}</b>
          {chip ? <ChipView chip={chip} /> : null}
        </Link>
      ))}
    </div>
  );
  return (
    <div className="sa-sources" data-testid={`sa-sources-${p.product_id}`}>
      {price
        ? p.levers.map((l: LeverRow) => {
            const srcKey = { khong_uu_dai: "none", voucher: "voucher", khuyen_mai: "promo", combo: "combo" }[l.key] ?? "all";
            const b = prevLevers.get(l.key);
            return sub(
              l.label,
              `${pp(totalOrders ? (l.orders / totalOrders) * 100 : null, 1)} đơn`,
              [
                ["Lượt xem", DASH, rk("views", srcKey), null],
                ["⑤ AOV", vnd(l.aov), rk("aov", srcKey), b ? chipOf(b.aov, l.aov) : null],
                ["GMV", vnd(l.gmv), rk("gmv", srcKey), b ? chipOf(b.gmv, l.gmv) : null],
                ["④ Đơn", fmt(l.orders), rk("orders", srcKey), b ? chipOf(b.orders, l.orders) : null],
                ["③ Biên cuối", pp(l.margin_pct, 1), rk("bien", srcKey), b ? chipPt(b.margin_pct, l.margin_pct) : null],
              ],
              `sa-lever-${p.product_id}-${l.key}`,
            );
          })
        : p.flows
          ? p.flows.rows.map((r) => {
              if (r.is_residual) {
                return sub(
                  "Chênh lệch nguồn",
                  "loại trùng người mua",
                  [
                    ["GMV", sv(r.gmv), "#", null],
                    ["④ Đơn", `${r.orders >= 0 ? "+" : "−"}${fmt(Math.abs(r.orders))}`, "#", null],
                  ],
                  `sa-pdiff-${p.product_id}`,
                  "sa-srow--diff",
                );
              }
              const src = srcOfFlowKey(r.key);
              const b = prevFlows.get(r.key);
              return sub(
                r.label,
                `${pp(totalOrders ? (r.orders / totalOrders) * 100 : null, 1)} đơn`,
                [
                  ["Lượt xem", fmt(r.views), rk("views", src), b ? chipOf(b.views, r.views) : null],
                  ["CTR", pc(r.ctr), rk("ctr", src), b ? chipOf(b.ctr, r.ctr) : null],
                  ["CTOR", pc(r.ctor), rk("ctor", src), b ? chipOf(b.ctor, r.ctor) : null],
                  ["⑤ AOV", vnd(r.aov), rk("aov", src), b ? chipOf(b.aov, r.aov) : null],
                  ["GMV", vnd(r.gmv), rk("gmv", src), b ? chipOf(b.gmv, r.gmv) : null],
                  ["④ Đơn", fmt(r.orders), rk("orders", src), b ? chipOf(b.orders, r.orders) : null],
                ],
                `sa-pflow-${p.product_id}-${r.key}`,
              );
            })
          : [
              <Empty key="none" testId={`sa-noflows-${p.product_id}`}>
                Chưa có lưu lượng theo nguồn cho sản phẩm này trong kỳ.
              </Empty>,
            ]}
      {!price && p.flows && !p.flows.trang_shop_available ? (
        <p className="sa-hint" data-testid={`sa-nofive-${p.product_id}`}>
          Sản phẩm này có 4 luồng (trang_shop_available: false): Thẻ sản phẩm gồm cả Trang shop vì file xuất theo tháng
          không tách Trang shop. Năm luồng chỉ có khi có dữ liệu lưu lượng theo sản phẩm từ Connector.
        </p>
      ) : null}
      {sub(
        "Quảng cáo (trong đó)",
        `${p.ads.basis.label} · chi ${vnd(p.ads.spend)} · ROAS ${fmt(p.ads.roas_broad, 1)}`,
        [
          ["GMV", vnd(p.ads.gmv_placed), rk("gmv", "ads"), null],
          ["Hoà vốn ROAS", fmt(p.ads.break_even_roas, 2), rk("gmv", "ads"), null],
        ],
        `sa-pads-${p.product_id}`,
        "sa-srow--ad",
      )}
      <p className="sa-hint">
        {price
          ? "Bốn mức ưu đãi cộng lại 100% đơn. Quảng cáo nằm trong đó, không cộng thêm. Lượt xem, CTR, CTOR không tách theo ưu đãi."
          : "Năm luồng cộng lại 100% đơn cùng một dòng “Chênh lệch nguồn”. Quảng cáo nằm trong các luồng, không cộng thêm."}
      </p>
      <Link className="sa-link" href={links.product(p.product_id, { tab: "ng", from: "tong-quan" }, state)}>
        Mở sản phẩm ›
      </Link>
    </div>
  );
}

