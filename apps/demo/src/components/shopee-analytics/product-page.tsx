"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { useShopee } from "../../lib/shopee-analytics/context";
import { DASH, fmt, pp, vnd } from "../../lib/shopee-analytics/format";
import { fiveCards } from "../../lib/shopee-analytics/model";
import {
  CHILD_NAME,
  KPI_NAME,
  PRODUCT_TABS,
  SOURCE_NAME,
  productPeriod,
} from "../../lib/shopee-analytics/params";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { ProposalsTab, openCardsOf } from "../shopee-decisions/product-proposals";
import { ProductKolTab } from "../shopee-kol/product-kol-tab";
import type { CardList } from "../../lib/shopee-decisions/types";
import type { ProductHeader, ProductPage, SkuCost } from "../../lib/shopee-analytics/types";
import { CostTab, HistoryTab, KeywordsTab, PerformanceTab, SourcesTab } from "./product-tabs";
import { Empty, Notice, PillLink, ResourceState, Section, TextChip, toneClass } from "./ui";
import type { WindowState } from "../../lib/shopee-analytics/params";
import { readWindow } from "../../lib/shopee-analytics/params";

/**
 * Sản phẩm (artboards SanPham / SanPhamMobile): the listing as on Shopee (image with a version
 * stepper when snapshots exist, Mã SP with copy, SKU, category, status, group, price block with
 * floors and max discount, stock with days to sell-out, reputation, variations, per-block
 * freshness), the five numbers, and the sub-tabs Hiệu suất · Nguồn · Từ khoá · Chi phí & giá sàn ·
 * Lịch sử. A field the platform has not given is shown as "chưa có", never as 0.
 */

const SELLER_CENTRE_ITEM = "https://banhang.shopee.vn/portal/product";

export function ProductPageView({ id, params }: { readonly id: string; readonly params: URLSearchParams }) {
  const host = useShopee();
  const period = productPeriod(params);
  const key = `${host.shopKey}|sp|${id}|${period}`;
  const data = useResource(() => host.api.product(id, period), key);
  return (
    <div className="sa-page" data-testid="sa-san-pham">
      <ResourceState resource={data}>{(page) => <Loaded id={id} page={page} params={params} />}</ResourceState>
    </div>
  );
}

function when(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = iso.slice(0, 10).split("-");
  const t = iso.slice(11, 16);
  return d.length === 3 ? `${d[2]}/${d[1]}/${d[0]}${t ? ` ${t}` : ""}` : DASH;
}

function Loaded({ id, page, params }: { readonly id: string; readonly page: ProductPage; readonly params: URLSearchParams }) {
  const host = useShopee();
  const { links } = host;
  const w: WindowState = readWindow(params);
  const h = page.header;
  const proposals = useResource<CardList | null>(() => (host.reco ? host.reco.list({ productId: id, queue: "all" }) : Promise.resolve(null)), `${host.shopKey}|sp-dx|${id}`);
  const proposalCards = proposals.status === "ready" ? (proposals.data?.cards ?? []) : null;
  const tabs: readonly (readonly [string, string])[] = host.reco
    ? PRODUCT_TABS.flatMap(([k, label]) =>
        k === "ng"
          ? [[k, label] as const, ["dx", proposalCards ? `Đề xuất (${openCardsOf(proposalCards).length})` : "Đề xuất"] as const, ...(host.kol ? [["kl", "Tiếp thị liên kết"] as const] : [])]
          : [[k, label] as const],
      )
    : PRODUCT_TABS;
  const tab = tabs.some(([k]) => k === params.get("tab")) ? (params.get("tab") as string) : "hs";
  const kpi = params.get("kpi");
  const src = params.get("src");
  const sub = params.get("sub");
  const row = params.get("row");
  const from = params.get("from");
  const card = params.get("card");
  const period = page.period.selected as "7d" | "30d" | "90d";
  const skus = page.cost_and_floor.skus;
  const [selSku, setSelSku] = useState<string | null>(skus[0]?.sku ?? null);
  const sel = skus.find((s) => s.sku === selSku) ?? skus[0] ?? null;

  const carry = { kpi, src, sub, row, from, card };
  const tabHref = (t: string) => links.product(id, { ...carry, tab: t }, w);
  const periodHref = (p: string) => {
    const next = new URLSearchParams(params);
    next.set("ky", p);
    return links.screen("san-pham", next, id);
  };

  const backHref =
    from === "ranking"
      ? links.ranking({ kpi: kpi ?? "gmv", src: src ?? "all", sub: sub ?? null, focus: row ?? id }, w)
      : from === "card"
        ? links.card(card ?? "", "san-pham")
        : from === "phan-tich"
          ? links.critical(w)
          : from === "san-pham"
            ? links.products(w)
            : links.overview(w);
  const backLabel = from === "ranking" ? "Xếp hạng" : from === "card" ? "Thẻ đề xuất" : from === "phan-tich" ? "Phân tích" : from === "san-pham" ? "Sản phẩm" : "Tổng quan";
  const banner =
    from === "ranking" && kpi
      ? `Mở từ Xếp hạng · ${KPI_NAME[kpi] ?? kpi} × ${(sub && CHILD_NAME[sub]) || SOURCE_NAME[src ?? "all"] || src}${row ? ` · dòng ${row}` : ""}`
      : null;

  const five = fiveCards(page.kpi_by_period[period]?.five_numbers ?? Object.values(page.kpi_by_period)[0]!.five_numbers, null);
  const cards = [page.nguon.card].filter(Boolean);

  return (
    <>
      <header className="sa-prodhead">
        <Link className="sa-link" href={backHref}>
          ‹ {backLabel}
        </Link>
        <div className="sa-eyebrow">SẢN PHẨM</div>
        <span className="sa-chip sa-chip--outline sa-row__end">Shopee{host.shopName ? ` · ${host.shopName}` : ""}</span>
      </header>

      <Hero h={h} id={id} links={links} cards={cards.length} firstCard={page.nguon.card?.id ?? null} w={w} />

      {h.missing_fields.length > 0 ? (
        <Notice tone="info" testId="sa-missing-fields">
          Shopee chưa cung cấp: {h.missing_fields.join(", ")}. Các khối bên dưới ghi &ldquo;chưa có&rdquo; thay vì đoán.
        </Notice>
      ) : null}

      <div className="sa-blocks">
        <PriceBlock h={h} sel={sel} readOnly={!!host.readOnly} costImportHref={links.costImport(sel?.sku ?? null, "san-pham")} />
        <StockBlock h={h} page={page} />
        <ReputationBlock h={h} />
      </div>

      <Variations h={h} skus={skus} selSku={sel?.sku ?? null} onPick={setSelSku} period={page.period.window.days} />

      <Section hint={`${page.period.window.days} ngày · so với ${page.period.previous.days} ngày trước · cùng định nghĩa với Tổng quan và thẻ`} testId="sa-sp-five" title="5 con số chính">
        <div className="sa-five sa-five--5">
          {five.map((f) => (
            <div className="sa-five__card" data-testid={`sa-sp-five-${f.key}`} key={f.key}>
              <span className="sa-tile__label">{f.label}</span>
              <span className="sa-five__value">{f.value}</span>
              <span>
                <span className={`sa-chip sa-chip--${f.tone}`}>{f.chip}</span>
              </span>
              <span className="sa-five__sub">{f.sub1}</span>
              <span className={`sa-five__sub sa-five__sub--b ${toneClass(f.tone)}`}>{f.sub2}</span>
            </div>
          ))}
        </div>
        {!page.kpi_by_period[period]?.five_numbers.comparison.available ? (
          <Notice tone="info">Kỳ trước chưa có dòng đơn của sản phẩm này, nên chỉ hiện số của kỳ này.</Notice>
        ) : null}
      </Section>

      {banner ? (
        <Notice tone="info" testId="sa-from-banner">
          <b>{banner}</b>{" "}
          <Link className="sa-link" href={backHref}>
            ‹ Về Xếp hạng
          </Link>
        </Notice>
      ) : null}

      <div aria-label="Sản phẩm" className="sa-seg sa-seg--round sa-tabs" role="tablist">
        {tabs.map(([k, label]) => (
          <PillLink active={tab === k} href={tabHref(k)} key={k}>
            {label}
          </PillLink>
        ))}
      </div>

      {tab === "hs" ? <PerformanceTab page={page} periodHref={periodHref} /> : null}
      {tab === "ng" ? <SourcesTab id={id} page={page} state={w} /> : null}
      {tab === "dx" && host.reco ? <ProposalsTab builderHref={links.builder("product", id)} cards={proposalCards ?? []} historyHref={tabHref("ls")} links={links} reco={host.reco} /> : null}
      {tab === "kl" && host.kol ? <ProductKolTab productId={id} productName={h.title ?? id} /> : null}
      {tab === "kw" ? <KeywordsTab id={id} page={page} /> : null}
      {tab === "cp" ? <CostTab onPick={setSelSku} page={page} sel={sel} /> : null}
      {tab === "ls" ? <HistoryTab page={page} /> : null}
    </>
  );
}

function Hero({
  h,
  id,
  links,
  cards,
  firstCard,
  w,
}: {
  readonly h: ProductHeader;
  readonly id: string;
  readonly links: ReturnType<typeof useShopee>["links"];
  readonly cards: number;
  readonly firstCard: string | null;
  readonly w: WindowState;
}) {
  const versions = useMemo(() => {
    const v = h.versions ?? [];
    return v.length > 0 ? v : [{ captured_at: h.price.captured_at ?? "", images: h.images }];
  }, [h]);
  const [ver, setVer] = useState(versions.length - 1);
  const [copied, setCopied] = useState(false);
  const cur = versions[Math.min(ver, versions.length - 1)]!;
  const image = cur.images[0] ?? null;
  const title = h.title;
  const chars = h.title_chars ?? title?.length ?? null;
  const copy = () => {
    try {
      void navigator.clipboard?.writeText(h.product_id);
    } catch {
      /* clipboard may be blocked; the id is on screen */
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };
  const statusChip =
    h.status === null ? (
      <TextChip tone="flat">Trạng thái: chưa có</TextChip>
    ) : (
      <TextChip tone={/active|normal|đang/i.test(h.status) ? "up" : "warn"}>● {statusLabel(h.status)}</TextChip>
    );
  return (
    <section className="sa-hero" data-testid="sa-hero">
      <div className="sa-hero__media">
        <div className="sa-hero__img">
          {image ? (
            // Private copies of the listing images; the URL is the shop's own.
            // eslint-disable-next-line @next/next/no-img-element
            <img alt={title ?? h.product_id} src={image} />
          ) : (
            <span className="sa-hint">Chưa có ảnh sản phẩm</span>
          )}
        </div>
        {cur.images.length > 1 ? (
          <div className="sa-thumbs">
            {cur.images.slice(0, 6).map((src) => (
              // eslint-disable-next-line @next/next/no-img-element
              <img alt="" key={src} src={src} />
            ))}
          </div>
        ) : null}
        {versions.length > 1 ? (
          <div className="sa-stepper" data-testid="sa-image-stepper">
            <button aria-label="Phiên bản ảnh cũ hơn" disabled={ver === 0} onClick={() => setVer(Math.max(0, ver - 1))} type="button">
              ‹
            </button>
            <span>
              <b>
                Phiên bản {ver + 1}/{versions.length}
              </b>
              <span className="sa-hint sa-block">{when(cur.captured_at)}</span>
            </span>
            <button aria-label="Phiên bản ảnh mới hơn" disabled={ver === versions.length - 1} onClick={() => setVer(Math.min(versions.length - 1, ver + 1))} type="button">
              ›
            </button>
          </div>
        ) : null}
      </div>
      <div className="sa-hero__body">
        <div className="sa-chips">
          {statusChip}
          {h.group_label ?? h.group ? <TextChip tone="pink">Nhóm · {h.group_label ?? h.group}</TextChip> : null}
          {h.priority ? <TextChip tone="warn">★ Ưu tiên {h.priority}</TextChip> : null}
        </div>
        <div>
          <h1 className="sa-h1 sa-h1--title" data-testid="sa-title">
            {title ?? "Chưa có tiêu đề"}
          </h1>
          <div className="sa-title-meta">
            <b>{chars === null ? DASH : `${chars}/120`} ký tự</b>
            <span aria-hidden="true" className="sa-bar sa-bar--w">
              <span className="sa-bar__fill sa-bar__fill--neutral" style={{ width: `${Math.min(100, ((chars ?? 0) / 120) * 100)}%` }} />
            </span>
            <span className="sa-hint">Tìm kiếm chỉ hiện khoảng 100 ký tự đầu</span>
          </div>
        </div>
        <dl className="sa-facts2">
          <dt>Mã SP</dt>
          <dd>
            <b data-testid="sa-pid">{h.product_id}</b>
            <button className="sa-btn sa-btn--s" onClick={copy} type="button">
              {copied ? "Đã sao chép ✓" : "Sao chép"}
            </button>
          </dd>
          <dt>SKU</dt>
          <dd>
            {h.seller_sku ? <TextChip tone="pink">{h.seller_sku}</TextChip> : <span className="sa-hint">chưa có</span>}
            {h.variations.length > 1 ? <span className="sa-hint">+ {h.variations.length - 1} phiên bản</span> : null}
          </dd>
          <dt>Danh mục</dt>
          <dd className="sa-facts2__wide">
            {h.category_path && h.category_path.length > 0 ? h.category_path.join(" › ") : <span className="sa-hint">chưa có</span>}
          </dd>
        </dl>
        <div className="sa-hero__links">
          <a className="sa-link" href={`${SELLER_CENTRE_ITEM}/${encodeURIComponent(id)}`} rel="noopener noreferrer" target="_blank">
            Mở trong Seller Centre ↗
          </a>
          {firstCard ? (
            <Link className="sa-link" href={links.card(firstCard, "san-pham")}>
              Xem {cards} đề xuất ›
            </Link>
          ) : null}
          <Link className="sa-link" href={links.ranking({ kpi: "gmv", src: "all", focus: id, from: "san-pham" }, w)}>
            Phân tích sản phẩm này ›
          </Link>
        </div>
      </div>
    </section>
  );
}

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    NORMAL: "Đang bán",
    normal: "Đang bán",
    active: "Đang bán",
    UNLIST: "Đã ẩn",
    unlist: "Đã ẩn",
    BANNED: "Bị khoá",
    DELETED: "Đã xoá",
  };
  return map[s] ?? s;
}

function PriceBlock({ h, sel, readOnly, costImportHref }: { readonly h: ProductHeader; readonly sel: SkuCost | null; readonly readOnly: boolean; readonly costImportHref: string }) {
  const floor = sel?.floor ?? null;
  const missingCost = !floor || (floor.absolute === null && floor.operating === null);
  const pay = floor?.net_revenue_per_unit ?? null;
  return (
    <Section hint={sel ? `SKU ${sel.sku}` : undefined} testId="sa-price" title="Giá">
      <div className="sa-price__list">
        <span className="sa-price__big">{vnd(h.price.list)}</span>
        <span className="sa-hint">niêm yết</span>
      </div>
      <div className="sa-price__lines">
        <span>
          Đang bán <b>{vnd(h.price.current)}</b>
          {pay !== null ? (
            <>
              {" "}
              · khách trả <b>{vnd(pay)}</b> sau voucher
            </>
          ) : null}
        </span>
        {h.price.promo_label ? <span className="sa-hint">Chương trình đang chạy: {h.price.promo_label}</span> : null}
      </div>
      <div className="sa-pairs">
        <div className="sa-pair">
          <span className="sa-hint">Giá sàn tuyệt đối</span>
          <b data-testid="sa-floor-abs">{missingCost ? "chưa có giá vốn" : vnd(floor?.absolute)}</b>
        </div>
        <div className="sa-pair sa-pair--pink">
          <span className="sa-hint">Giá sàn vận hành</span>
          <b data-testid="sa-floor-op">{missingCost ? "chưa có giá vốn" : vnd(floor?.operating)}</b>
        </div>
        <div className="sa-pair">
          <span className="sa-hint">Giảm tối đa</span>
          <b data-testid="sa-maxdisc">
            {missingCost || floor?.max_discount_pct == null ? "chưa có" : `${pp(floor.max_discount_pct, 1)} · ${vnd(floor.max_discount_amount)}`}
          </b>
        </div>
      </div>
      {missingCost && !readOnly ? (
        <Link className="sa-link" href={costImportHref}>
          Nhập giá vốn ở Cài đặt ›
        </Link>
      ) : null}
      <div className="sa-fresh-line" data-testid="sa-price-fresh">
        Cập nhật {when(h.price.captured_at)} · nguồn: {h.price.source === "snapshot" ? "Seller Centre qua Juli Connector" : h.price.source === "last_order_line" ? "dòng đơn gần nhất (chưa có ảnh chụp sản phẩm)" : "chưa có"}
      </div>
    </Section>
  );
}

function StockBlock({ h, page }: { readonly h: ProductHeader; readonly page: ProductPage }) {
  const stock = h.stock.value;
  const days = page.period.window.days;
  const units = page.cost_and_floor.skus.reduce((t, s) => t + s.units, 0);
  const perDay = days > 0 ? units / days : 0;
  const sellOut = h.days_to_sell_out ?? (stock !== null && perDay > 0 ? stock / perDay : null);
  return (
    <Section aside={h.stock.stale ? <TextChip tone="warn">Cũ {h.stock.age_days} ngày</TextChip> : undefined} testId="sa-stock" title="Tồn kho">
      <div className="sa-price__list">
        <span className="sa-price__big">{stock === null ? "chưa có" : fmt(stock)}</span>
        <span className="sa-hint">{stock === null ? "Shopee chưa cho số tồn" : "sản phẩm"}</span>
      </div>
      <div className="sa-price__lines">
        {sellOut !== null ? (
          <span data-testid="sa-sellout">
            Bán đều như {days} ngày qua: còn đủ khoảng <b>{fmt(sellOut, sellOut < 10 ? 1 : 0)} ngày</b>
            {sellOut < 14 ? <TextChip tone="warn">sắp hết</TextChip> : null}
          </span>
        ) : (
          <span className="sa-hint">Chưa tính được số ngày bán hết (thiếu tồn kho hoặc chưa có đơn).</span>
        )}
      </div>
      <div className="sa-fresh-line">
        {h.stock.age_days === null ? "Chưa có ngày cập nhật tồn kho" : `Cập nhật cách đây ${h.stock.age_days} ngày`}
        {h.stock.stale ? " · số tồn có thể đã đổi" : ""}
      </div>
    </Section>
  );
}

function ReputationBlock({ h }: { readonly h: ProductHeader }) {
  const r = h.reputation;
  return (
    <Section hint="Toàn sản phẩm" testId="sa-reputation" title="Uy tín">
      <div className="sa-price__list">
        <span className="sa-price__big">{r.rating === null ? "chưa có" : fmt(r.rating, 1)}</span>
        <span className="sa-hint">/ 5 · {r.rating_count === null ? "chưa có số đánh giá" : `${fmt(r.rating_count)} đánh giá`}</span>
      </div>
      <div className="sa-pairs sa-pairs--3">
        <div className="sa-pair">
          <span className="sa-hint">Đã bán</span>
          <b>{fmt(r.sold_total)}</b>
        </div>
        <div className="sa-pair">
          <span className="sa-hint">Lượt thích</span>
          <b>{fmt(r.likes)}</b>
        </div>
      </div>
      <div className="sa-fresh-line">Cập nhật {when(h.price.captured_at)} · nguồn: Seller Centre qua Juli Connector</div>
    </Section>
  );
}

function Variations({
  h,
  skus,
  selSku,
  onPick,
  period,
}: {
  readonly h: ProductHeader;
  readonly skus: readonly SkuCost[];
  readonly selSku: string | null;
  readonly onPick: (sku: string) => void;
  readonly period: number;
}) {
  const bySku = new Map(skus.map((s) => [s.sku, s]));
  const rows = h.variations.length > 0 ? h.variations : skus.map((s) => ({ variation_id: s.sku, name: s.sku, seller_sku: s.sku, status: null }));
  return (
    <Section hint={`${rows.length} phiên bản · bấm một dòng để xem chi phí ở tab Chi phí & giá sàn`} testId="sa-variations" title="Phiên bản sản phẩm">
      {rows.length === 0 ? (
        <Empty>Chưa có danh sách phiên bản của sản phẩm này.</Empty>
      ) : (
        <>
          <div className="sa-vrow sa-vrow--head">
            <span>Tên · SKU</span>
            <span>Giá niêm yết</span>
            <span>Đơn {period} ngày</span>
            <span>Biên/đơn</span>
            <span>Giá sàn vận hành · tuyệt đối</span>
          </div>
          {rows.map((v) => {
            const s = v.seller_sku ? bySku.get(v.seller_sku) : undefined;
            const f = s?.floor ?? null;
            return (
              <button
                aria-pressed={!!s && s.sku === selSku}
                className={`sa-vrow ${s && s.sku === selSku ? "sa-vrow--on" : ""}`}
                data-testid={`sa-var-${v.seller_sku ?? v.variation_id}`}
                disabled={!s}
                key={v.variation_id ?? v.seller_sku ?? v.name}
                onClick={() => s && onPick(s.sku)}
                type="button"
              >
                <span>
                  <b>{v.name ?? v.seller_sku ?? "Phiên bản"}</b>
                  {v.seller_sku ? <TextChip tone="pink">{v.seller_sku}</TextChip> : null}
                </span>
                <span>{s ? vnd(s.list_price) : DASH}</span>
                <span>{s ? fmt(s.units) : DASH}</span>
                <span>
                  {s ? pp(s.waterfall_per_unit.margin_pct, 1) : DASH}
                  {s?.cost.label ? <span className="sa-hint sa-block">{s.cost.label}</span> : null}
                </span>
                <span>
                  {f && f.operating !== null ? vnd(f.operating) : "chưa có giá vốn"}
                  <span className="sa-hint sa-block">{f && f.absolute !== null ? vnd(f.absolute) : DASH}</span>
                </span>
              </button>
            );
          })}
        </>
      )}
      <p className="sa-hint">Giá, tồn lấy từ lần đọc Seller Centre gần nhất · giá vốn từ Cài đặt (hoặc giả định 1/3 giá, có ghi rõ) · đơn từ báo cáo đơn.</p>
    </Section>
  );
}

