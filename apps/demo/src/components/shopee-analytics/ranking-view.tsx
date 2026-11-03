"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { useShopee } from "../../lib/shopee-analytics/context";
import { DASH, chipOf, fmt, pp, sv, vnd, type Chip } from "../../lib/shopee-analytics/format";
import {
  CHILDREN,
  CHILD_NAME,
  KPIS,
  KPI_NAME,
  SOURCES,
  SOURCE_NAME,
  XEP,
  apiRankingArgs,
  readRanking,
  readWindow,
  type RankingKind,
  type RankingState,
} from "../../lib/shopee-analytics/params";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import type { N, Ranking, RankingRow, RankingView as RankingSide } from "../../lib/shopee-analytics/types";
import { PeriodBar } from "./period-bar";
import { ChipView, Empty, Ini, InfoToggle, Notice, PageHead, PillLink, ResourceState, Section, initialsOf } from "./ui";

/**
 * Xếp hạng (artboards Ranking / RankingMobile): what a KPI click opens. The context cell, KPI
 * tabs, source chips (Thẻ sản phẩm with its six children), the "Xếp theo" switch, Kéo xuống / Kéo
 * lên, rows with trước → nay, Rõ / Tham khảo, "→ đề xuất", and closing rows so the table adds up to
 * the cell. Row kinds follow the source: products, campaigns (ads), KOLs, vouchers, keywords.
 * Returning from a card or a product highlights `focus` for three seconds.
 */

const ROW_KIND: Record<RankingKind, { noun: string; head: string }> = {
  products: { noun: "sản phẩm", head: "Sản phẩm" },
  campaigns: { noun: "chiến dịch", head: "Chiến dịch" },
  kols: { noun: "KOL", head: "KOL" },
  vouchers: { noun: "voucher", head: "Voucher" },
  keywords: { noun: "từ khoá", head: "Từ khoá" },
};
const ROW_INI: Record<RankingKind, string> = { products: "", campaigns: "QC", kols: "KOL", vouchers: "VC", keywords: "Tk" };

const BACK: Record<string, string> = {
  "tong-quan": "Tổng quan",
  "phan-tich": "Phân tích",
  card: "Thẻ đề xuất",
  "san-pham": "Sản phẩm",
};

function valueText(xep: string, v: N): string {
  if (v === null) return DASH;
  switch (xep) {
    case "gmv":
    case "profit":
    case "aov":
      return vnd(v);
    case "orders":
      return `${fmt(v, 1)} đơn`;
    case "bien":
    case "disc":
      return pp(v, 1);
    default:
      return fmt(v, 2);
  }
}

const isMoney = (xep: string) => xep === "gmv" || xep === "profit";

export function RankingPageView({ params }: { readonly params: URLSearchParams }) {
  const host = useShopee();
  const rs = useMemo(() => readRanking(params), [params]);
  const w = useMemo(() => readWindow(params), [params]);
  const args = apiRankingArgs(rs);
  const key = `${host.shopKey}|rk|${JSON.stringify(w.query)}|${JSON.stringify(args)}`;
  const data = useResource(() => host.api.ranking({ ...w.query, ...args }), key);
  return (
    <div className="sa-page" data-testid="sa-ranking">
      <ResourceState resource={data}>{(r) => <Loaded key={`${key}|${rs.focus ?? ""}`} rankingData={r} rs={rs} w={w} />}</ResourceState>
    </div>
  );
}

function Loaded({ rankingData: r, rs, w }: { readonly rankingData: Ranking; readonly rs: RankingState; readonly w: ReturnType<typeof readWindow> }) {
  const { links } = useShopee();
  const [hl, setHl] = useState(true);
  const [openRows, setOpenRows] = useState<Readonly<Record<string, boolean>>>({});
  const [restOpen, setRestOpen] = useState(true);
  const focusRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!rs.focus) return;
    focusRef.current?.scrollIntoView?.({ block: "center" });
    const t = window.setTimeout(() => setHl(false), 3000);
    return () => window.clearTimeout(t);
  }, [rs.focus, r]);

  const kpiN = KPI_NAME[rs.kpi] ?? rs.kpi;
  const srcN = rs.src === "the_san_pham" && rs.sub ? (CHILD_NAME[rs.sub] ?? rs.sub) : (SOURCE_NAME[rs.src] ?? rs.src);
  const withState = (patch: Partial<Record<keyof ReturnType<typeof readRanking> | "huong" | "loai", string | null>>) => {
    const next = { ...patch };
    return links.ranking(
      {
        kpi: next.kpi ?? rs.kpi,
        src: next.src ?? rs.src,
        sub: "sub" in next ? next.sub : rs.sub,
        xep: "xep" in next ? next.xep : rs.xep === "gmv" ? null : rs.xep,
        huong: "huong" in next ? next.huong : null,
        loai: "loai" in next ? next.loai : rs.byProduct ? "products" : null,
      },
      w,
    );
  };
  const kind = r.kind as RankingKind;
  const nounInfo = ROW_KIND[kind] ?? ROW_KIND.products;
  const back = backOf(rs, links, w);
  const cardBanner = rs.from === "card" && rs.card;

  const additive = r.xep_theo.additive;
  const cellDelta = r.cell?.delta ?? null;
  const autoDir: "xuong" | "len" = (() => {
    if (rs.dir) return rs.dir;
    if (rs.focus) {
      if ((r.up ?? []).some((x) => x.id === rs.focus || x.product_id === rs.focus)) return "len";
      if ((r.down ?? []).some((x) => x.id === rs.focus || x.product_id === rs.focus)) return "xuong";
    }
    return cellDelta !== null && cellDelta > 0 ? "len" : "xuong";
  })();
  const sideKey = autoDir === "xuong" ? "down" : "up";
  const side: RankingSide | undefined = r.views?.[sideKey];
  const listRows: readonly RankingRow[] = additive
    ? (r[sideKey] ?? [])
    : [...(r.down ?? []), ...(r.up ?? [])].sort((a, b) => (autoDir === "xuong" ? 1 : -1) * ((a.now ?? Infinity) - (b.now ?? Infinity)));
  const maxAbs = Math.max(1, ...listRows.map((x) => Math.abs(x.delta ?? 0)));

  return (
    <>
      <header className="sa-head">
        <div className="sa-crumb">
          <Link className="sa-link" href={back.href}>
            ‹ {back.label}
          </Link>
          <span className="sa-hint">/</span>
          <span>Xếp hạng</span>
        </div>
        <PageHead
          chips={
            <span className="sa-chip sa-chip--outline" data-testid="sa-rk-window">
              {r.window.days} ngày · so với {r.previous.days} ngày trước
            </span>
          }
          eyebrow="XẾP HẠNG"
          info={
            <InfoToggle>
              Số trung bình mỗi ngày. Mỗi dòng ghi số ₫/ngày mà thay đổi của dòng đó kéo số của ô lên hoặc xuống. Các dòng và
              các dòng &ldquo;Còn lại&rdquo; cộng lại đúng bằng số của ô vừa bấm. Độ tin cậy &ldquo;Rõ&rdquo; khi có từ 30 đơn
              ở cả hai kỳ.
            </InfoToggle>
          }
          title={`Xếp hạng ${kpiN} · ${srcN}`}
        />
      </header>

      <div className="sa-rk-top">
        <div className="sa-ctx" data-testid="sa-ctx">
          <span className="sa-tile__label">
            {kpiN} · {srcN}
          </span>
          {r.supported && r.cell ? (
            <>
              <span className="sa-ctx__value">
                {valueText(rs.xep, r.cell.now)}
                {isMoney(rs.xep) || rs.xep === "orders" ? "/ngày" : ""}
              </span>
              <span>
                <ChipView chip={cellChip(rs.xep, r.cell.before, r.cell.now)} />
              </span>
              <span className={`sa-ctx__impact ${(cellDelta ?? 0) < 0 ? "sa-tone--down" : "sa-tone--up"}`}>
                {cellDelta === null ? DASH : isMoney(rs.xep) ? `${sv(cellDelta)}/ngày` : deltaText(rs.xep, cellDelta)}
              </span>
              <span className="sa-hint">Các dòng bên dưới cộng lại đúng bằng số này.</span>
            </>
          ) : (
            <span className="sa-ctx__value">{DASH}</span>
          )}
        </div>
        <div className="sa-rk-filters">
          <div aria-label="Chỉ số" className="sa-seg sa-seg--round" role="tablist">
            {KPIS.map(([k, label]) => (
              <PillLink active={rs.kpi === k} href={withState({ kpi: k, sub: null })} key={k}>
                {label}
              </PillLink>
            ))}
          </div>
          <div className="sa-chips" aria-label="Nguồn">
            {SOURCES.map(([k, label, grp], i) => {
              const gap = i > 0 && SOURCES[i - 1]?.[2] !== grp;
              return (
                <span className="sa-chips__item" key={k}>
                  {gap ? <span className="sa-sep">{grp === "p" ? "Ưu đãi" : grp === "ad" ? "Phủ lên" : ""}</span> : null}
                  <PillLink active={rs.src === k} href={withState({ src: k, sub: null })}>
                    {label}
                  </PillLink>
                </span>
              );
            })}
          </div>
          {rs.src === "the_san_pham" ? (
            <div className="sa-chips" data-testid="sa-subchips">
              <span className="sa-hint">Thẻ sản phẩm gồm</span>
              <PillLink active={!rs.sub} href={withState({ sub: null })}>
                Cả Thẻ sản phẩm
              </PillLink>
              {CHILDREN.map(([url, , label]) => (
                <PillLink active={rs.sub === url} href={withState({ sub: url })} key={url}>
                  {label}
                </PillLink>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <PeriodBar
        hrefFor={(next) => links.ranking({ kpi: rs.kpi, src: rs.src, sub: rs.sub, focus: rs.focus, from: rs.from, card: rs.card, xep: rs.xep === "gmv" ? null : rs.xep }, next)}
        previous={r.previous}
        state={w}
        window={r.window}
      />

      {cardBanner ? (
        <Notice tone="info" testId="sa-card-banner">
          <b>Vừa quay về từ thẻ</b> · {rs.card} · dòng được đánh dấu bên dưới, tự tắt sau 3 giây{" "}
          <Link className="sa-link" href={links.card(rs.card as string, "xep-hang")}>
            Về thẻ ›
          </Link>
        </Notice>
      ) : null}
      {r.ads_note ? (
        <Notice tone="info" testId="sa-ads-note">
          <b>{r.ads_basis?.label ?? "đơn đã đặt"}</b>: {r.ads_note}
        </Notice>
      ) : null}
      {r.before_note ? <Notice tone="info">{r.before_note}</Notice> : null}

      {!r.supported ? (
        <Empty testId="sa-rk-unsupported">
          <b>{r.message ?? `${kpiN} không tách được theo ${srcN}.`}</b>
          <br />
          Các cặp theo sản phẩm có cho mọi chỉ số × luồng; Lượt xem, CTR, CTOR không tách theo mức ưu đãi.
        </Empty>
      ) : (
        <Section
          aside={
            <span className="sa-rk-switches">
              <span className="sa-hint">Xếp theo</span>
              <span className="sa-seg">
                {XEP.map(([k, , label]) => (
                  <Link className={`sa-seg__item ${rs.xep === k ? "sa-seg__item--on" : ""}`} aria-current={rs.xep === k ? "true" : undefined} href={withState({ xep: k === "gmv" ? null : k })} key={k}>
                    {label}
                  </Link>
                ))}
              </span>
              <span className="sa-seg">
                {(additive ? [["xuong", "Kéo xuống"], ["len", "Kéo lên"]] : [["xuong", "Thấp → cao"], ["len", "Cao → thấp"]]).map(([k, label]) => (
                  <Link className={`sa-seg__item ${autoDir === k ? "sa-seg__item--on" : ""}`} aria-current={autoDir === k ? "true" : undefined} href={withState({ huong: k })} key={k}>
                    {label}
                  </Link>
                ))}
              </span>
            </span>
          }
          testId="sa-rk-table"
          title={`${listRows.length} ${nounInfo.noun} ${additive ? (autoDir === "xuong" ? `kéo ${kpiN} xuống` : `kéo ${kpiN} lên`) : `· sắp theo ${r.xep_theo.label}`}`}
        >
          <div className="sa-rrow sa-rrow--head">
            <span>{nounInfo.head}</span>
            <span>{r.xep_theo.label} · trước → nay</span>
            <span>Đơn · trước → nay</span>
            <span>{additive ? `${r.xep_theo.label} · thay đổi` : "Thay đổi"}</span>
            <span>Chi</span>
            <span>Tin cậy</span>
            <span />
          </div>

          {listRows.map((row) => {
            const focus = !!rs.focus && (row.id === rs.focus || row.product_id === rs.focus);
            const open = !!openRows[row.id];
            const delta = row.delta;
            const bar = Math.round((Math.abs(delta ?? 0) / maxAbs) * 100);
            const productId = row.product_id ?? (kind === "keywords" ? row.id.split("|")[0] : null);
            const openHref = productId
              ? links.product(
                  productId,
                  { tab: kind === "keywords" ? "kw" : "ng", kpi: rs.kpi, src: rs.src, sub: rs.sub, row: row.id, from: "ranking" },
                  w,
                )
              : links.overview(w);
            const hlOn = focus && hl;
            return (
              <div
                className={`sa-rcard ${hlOn ? "sa-rcard--focus" : open ? "sa-rcard--open" : ""}`}
                data-testid={`sa-rk-row-${row.id}`}
                key={row.id}
                ref={focus ? focusRef : undefined}
              >
                <div className="sa-rrow">
                  <button aria-expanded={open} className="sa-mname" onClick={() => setOpenRows({ ...openRows, [row.id]: !open })} type="button">
                    <span className="sa-hint sa-caret-s">{open ? "▾" : "▸"}</span>
                    <Ini text={kind === "products" ? initialsOf(row.label) : ROW_INI[kind]} />
                    <span>
                      <span className="sa-mname__t">{row.label}</span>
                      {hlOn ? <span className="sa-tag">Vừa xem ở thẻ</span> : null}
                      <span className="sa-hint sa-block">{productId ?? row.id}</span>
                    </span>
                  </button>
                  <span>
                    {row.before_missing ? `mới → ${valueText(rs.xep, row.now)}` : `${valueText(rs.xep, row.before)} → ${valueText(rs.xep, row.now)}`}
                  </span>
                  <span className="sa-hint2">
                    {fmt(row.quantity.orders_before)} → {fmt(row.quantity.orders_now)} đơn
                  </span>
                  <span className="sa-rbar">
                    <span aria-hidden="true" className="sa-bar">
                      <span className={`sa-bar__fill ${(delta ?? 0) < 0 ? "sa-bar__fill--red" : "sa-bar__fill--green"}`} style={{ width: `${bar}%` }} />
                    </span>
                    <b className={(delta ?? 0) < 0 ? "sa-tone--down" : "sa-tone--up"}>
                      {delta === null ? DASH : isMoney(rs.xep) ? `${sv(delta)}/ngày` : deltaText(rs.xep, delta)}
                    </b>
                  </span>
                  <span className="sa-hint2">{row.spend ? vnd(row.spend) : DASH}</span>
                  <span className={`sa-conf ${row.confidence === "Rõ" ? "sa-conf--ok" : "sa-conf--warn"}`}>{row.confidence}</span>
                  <span className="sa-mrec">
                    {row.card ? (
                      <Link className="sa-rec" href={links.card(row.card.id, "xep-hang", row.id)}>
                        → {row.card.at_stake_per_month != null ? `${vnd(row.card.at_stake_per_month)}/tháng` : "đề xuất"}
                        <br />
                        <span className="sa-hint">{row.card.title ?? ""}</span>
                      </Link>
                    ) : (
                      <span className="sa-hint">Chưa có đề xuất</span>
                    )}
                  </span>
                </div>
                {open ? (
                  <div className="sa-facts">
                    <div className="sa-fact">
                      <span className="sa-hint">Kỳ này</span>
                      <b>{valueText(rs.xep, row.now)}</b>
                    </div>
                    <div className="sa-fact">
                      <span className="sa-hint">Kỳ trước</span>
                      <b>{row.before_missing ? "chưa có" : valueText(rs.xep, row.before)}</b>
                    </div>
                    <div className="sa-fact">
                      <span className="sa-hint">Đơn trong kỳ</span>
                      <b>{fmt(row.quantity.orders_now)}</b>
                    </div>
                    <Link className="sa-fact sa-fact--link" href={openHref}>
                      <span className="sa-hint">
                        {productId ? `KPI ${kpiN} và nguồn ${srcN} đã chọn sẵn` : "Chiến dịch / voucher không gắn sản phẩm"}
                      </span>
                      <b>{productId ? (kind === "keywords" ? "Mở tab Từ khoá" : "Mở sản phẩm") : "Mở trong Tổng quan"} ›</b>
                    </Link>
                  </div>
                ) : null}
              </div>
            );
          })}
          {listRows.length === 0 ? (
            <Empty testId="sa-rk-empty">Không có dòng nào theo hướng này. Đổi hướng để xem các dòng còn lại.</Empty>
          ) : null}

          {additive && side ? (
            <>
              <button
                aria-expanded={restOpen}
                className="sa-rest"
                data-testid="sa-rk-rest"
                onClick={() => setRestOpen(!restOpen)}
                type="button"
              >
                <span>{restOpen ? "▾" : "▸"}</span>
                <span>Còn lại · {side.closing.length} dòng</span>
                <b>{sv(side.closing.reduce((t, c) => t + (c.delta ?? 0), 0))}/ngày</b>
              </button>
              {restOpen ? (
                <div className="sa-rest__list" data-testid="sa-rk-closing">
                  {side.closing.map((c) => (
                    <div className="sa-rest__line" key={c.label}>
                      <span>{c.label}</span>
                      <b>{sv(c.delta)}/ngày</b>
                    </div>
                  ))}
                </div>
              ) : null}
              <div className="sa-rk-total" data-testid="sa-rk-total">
                <span className="sa-hint">
                  Tổng · bằng số của ô {kpiN} · {srcN}
                </span>
                <b>{sv(side.cell_delta)}/ngày</b>
              </div>
              <p className="sa-hint" data-testid="sa-rk-check">
                Σ các dòng + các dòng còn lại = {sv(side.sum)}/ngày {r.adds_up ? "✓ cộng đúng" : "(chưa khớp)"}
              </p>
            </>
          ) : null}
          {r.adds_up_note ? <p className="sa-hint" data-testid="sa-rk-nonadd">{r.adds_up_note}</p> : null}
        </Section>
      )}
    </>
  );
}

function cellChip(xep: string, before: N, now: N): Chip {
  if (xep === "bien" || xep === "disc") {
    if (before === null || now === null) return { text: DASH, up: null, r: 0 };
    const d = now - before;
    return Math.abs(d) < 0.05
      ? { text: "0,0 điểm", up: null, r: d }
      : { text: `${d > 0 ? "▲" : "▼"} ${fmt(Math.abs(d), 1)} điểm`, up: d > 0, r: d };
  }
  return chipOf(before, now);
}

function deltaText(xep: string, d: number): string {
  const sign = d >= 0 ? "+" : "−";
  if (xep === "bien" || xep === "disc") return `${sign}${fmt(Math.abs(d), 1)} điểm`;
  if (xep === "orders") return `${sign}${fmt(Math.abs(d), 1)} đơn/ngày`;
  if (xep === "aov") return sv(d);
  return `${sign}${fmt(Math.abs(d), 2)}`;
}

function backOf(rs: RankingState, links: ReturnType<typeof useShopee>["links"], w: ReturnType<typeof readWindow>): { href: string; label: string } {
  switch (rs.from) {
    case "phan-tich":
      return { href: links.critical(w), label: BACK["phan-tich"] ?? "Phân tích" };
    case "card":
      return { href: links.card(rs.card ?? "", "xep-hang"), label: BACK.card ?? "Thẻ đề xuất" };
    case "san-pham":
      return rs.focus
        ? { href: links.product(rs.focus, { tab: "ng" }, w), label: BACK["san-pham"] ?? "Sản phẩm" }
        : { href: links.products(w), label: "Sản phẩm" };
    default:
      return { href: links.overview(w), label: BACK["tong-quan"] ?? "Tổng quan" };
  }
}

