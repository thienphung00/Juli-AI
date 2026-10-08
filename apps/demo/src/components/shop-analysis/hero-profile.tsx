"use client";

import { useState } from "react";

import {
  addToCartRate,
  aov,
  CHANNEL_LABELS,
  CTOR_DIRECT,
  ctor,
  ctr,
  ESTIMATED,
  FIVE_CHANNELS,
  isChannelMissing,
  isSellerContent,
  NO_DATA,
  NOT_PROVIDED,
} from "../../lib/shop-analysis/derive";
import type { Appearance, ChannelRow, HeroProfile, ShopDiagnosisReport } from "../../lib/shop-analysis/types";
import { money, num, pct, slashDate } from "../../lib/vn-format";
import { FlashSection, BandsTable } from "./promotions";
import { ContributionLine, KpiTable, Note, TableWrap, Verdict } from "./shared";
import { allDays, BandStrip } from "./timeline";

function cell(
  prior: number | null | undefined,
  last: number | null | undefined,
  fmt: (v: number | null) => string,
): string {
  if ((prior === null || prior === undefined) && (last === null || last === undefined)) return "—";
  return `${fmt(prior ?? null)} → ${fmt(last ?? null)}`;
}

/** Backend `render._channel_table`: every one of the five channels. */
function ChannelTable({ profile }: { readonly profile: HeroProfile }) {
  const byChannel = new Map(profile.channels.map((r) => [r.channel, r]));
  return (
    <TableWrap label="Phễu theo từng kênh">
      <table className="analysis-table">
        <thead>
          <tr>
            <th scope="col">Kênh</th>
            <th scope="col">Lượt hiển thị sản phẩm</th>
            <th scope="col">CTR (Tỷ lệ nhấp)</th>
            <th scope="col">Lượt nhấp vào sản phẩm</th>
            <th scope="col">Tỷ lệ thêm vào giỏ hàng</th>
            <th scope="col">Đơn hàng SKU</th>
            <th scope="col">CTOR</th>
            <th scope="col">AOV (SKU)</th>
            <th scope="col">GMV</th>
            <th scope="col">Nhận xét</th>
          </tr>
        </thead>
        <tbody>
          {FIVE_CHANNELS.map((channel) => {
            const row: ChannelRow | undefined = byChannel.get(channel);
            if (!row || isChannelMissing(row)) {
              return (
                <tr key={channel}>
                  <th scope="row">{CHANNEL_LABELS[channel]}</th>
                  <td colSpan={9} className="analysis-table__text">
                    {NO_DATA}
                  </td>
                </tr>
              );
            }
            const p = row.comparison.prior;
            const q = row.comparison.last;
            const subRows = channel === "affiliate" ? profile.affiliate_rows ?? [] : [];
            return [
              <tr key={channel}>
                <th scope="row">{CHANNEL_LABELS[channel]}</th>
                <td>{cell(p.impressions, q.impressions, (v) => num(v))}</td>
                <td>{cell(ctr(p), ctr(q), (v) => pct(v))}</td>
                <td>{cell(p.clicks, q.clicks, (v) => num(v))}</td>
                <td>{p.add_to_cart === null ? NOT_PROVIDED : cell(addToCartRate(p), addToCartRate(q), (v) => pct(v))}</td>
                <td>
                  {cell(p.sku_orders, q.sku_orders, (v) => num(v))}
                  {p.orders_estimated ? ` (${ESTIMATED})` : ""}
                </td>
                <td>
                  {cell(ctor(p), ctor(q), (v) => pct(v))}
                  {isSellerContent(channel) ? ` (${CTOR_DIRECT})` : ""}
                </td>
                <td>{cell(aov(p), aov(q), money)}</td>
                <td>{cell(p.gmv, q.gmv, money)}</td>
                <td className="analysis-table__text">
                  <span className="analysis-tags">
                    {(row.tags ?? []).map((tag) => (
                      <span key={tag} className="badge badge-neutral">
                        {tag}
                      </span>
                    ))}
                  </span>
                </td>
              </tr>,
              ...subRows.map((sub) => (
                <tr key={sub.channel} className="analysis-table__sub">
                  <th scope="row">{CHANNEL_LABELS[sub.channel]}</th>
                  <td>{cell(sub.comparison.prior.impressions, sub.comparison.last.impressions, (v) => num(v))}</td>
                  <td>{cell(ctr(sub.comparison.prior), ctr(sub.comparison.last), (v) => pct(v))}</td>
                  <td>{cell(sub.comparison.prior.clicks, sub.comparison.last.clicks, (v) => num(v))}</td>
                  <td />
                  <td />
                  <td />
                  <td />
                  <td>{cell(sub.comparison.prior.gmv, sub.comparison.last.gmv, money)}</td>
                  <td />
                </tr>
              )),
            ];
          })}
        </tbody>
      </table>
    </TableWrap>
  );
}

function ShareTable({ profile }: { readonly profile: HeroProfile }) {
  return (
    <TableWrap label="Tỷ trọng GMV theo kênh">
      <table className="analysis-table">
        <thead>
          <tr>
            <th scope="col">Tỷ trọng GMV theo kênh</th>
            <th scope="col">30 ngày trước</th>
            <th scope="col">30 ngày gần đây</th>
          </tr>
        </thead>
        <tbody>
          {FIVE_CHANNELS.map((channel) => {
            const share = profile.gmv_share?.[channel];
            return (
              <tr key={channel}>
                <th scope="row">
                  {CHANNEL_LABELS[channel]}
                  {channel === "shop_tab" ? " *" : ""}
                </th>
                {share ? (
                  <>
                    <td>{pct(share[0], 0)}</td>
                    <td>{pct(share[1], 0)}</td>
                  </>
                ) : (
                  <td colSpan={2}>{NO_DATA}</td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </TableWrap>
  );
}

function AppearanceList({
  title,
  items,
  noneCount,
  unit,
}: {
  readonly title: string;
  readonly items: Appearance[];
  readonly noneCount: number;
  readonly unit: string;
}) {
  return (
    <>
      {items.length > 0 ? (
        <TableWrap label={title}>
          <table className="analysis-table">
            <thead>
              <tr>
                <th scope="col">{title}</th>
                <th scope="col">Ngày</th>
                <th scope="col">{unit}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((a, i) => (
                <tr key={`${a.title}-${a.day}-${i}`}>
                  <th scope="row">{a.title || "(không tên)"}</th>
                  <td>{slashDate(a.day)}</td>
                  <td>{a.orders ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      ) : (
        <Note>Không có {title.toLowerCase()} nào có đơn của sản phẩm này.</Note>
      )}
      <Note>
        {noneCount} {title.toLowerCase()} có sản phẩm nhưng không có đơn.
      </Note>
    </>
  );
}

export function HeroProfileCard({
  profile,
  report,
}: {
  readonly profile: HeroProfile;
  readonly report: ShopDiagnosisReport;
}) {
  const [expanded, setExpanded] = useState(false);
  const title = profile.title || `Sản phẩm ${profile.rank}`;
  const detailsId = `hero-${profile.rank}-details`;
  const appearances = profile.appearances;

  return (
    <article className="card hero-card" aria-labelledby={`hero-${profile.rank}-title`}>
      <p className="analysis-eyebrow">Sản phẩm chủ lực {profile.rank}</p>
      <h3 className="hero-card__title" id={`hero-${profile.rank}-title`}>
        {title}
      </h3>
      <Verdict headline={profile.conclusion.headline} lookNext={profile.conclusion.look_next} />
      <Note>{profile.content_note}</Note>
      <button
        type="button"
        className="btn-secondary hero-card__toggle"
        aria-expanded={expanded}
        aria-controls={detailsId}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? "Thu gọn" : "Mở rộng"}
      </button>
      <div id={detailsId} hidden={!expanded} className="hero-card__details">
        <h4>Chỉ số 30 ngày gần đây so với 30 ngày trước (mọi kênh)</h4>
        <KpiTable comparison={profile.total} label={`Chỉ số của ${title}`} />
        <ShareTable profile={profile} />
        <h4>Phễu theo từng kênh</h4>
        <p>
          <b>Cách đọc:</b> {profile.reading}
        </p>
        <ChannelTable profile={profile} />
        <Note>
          Nhóm khách tự tìm đến (Thẻ sản phẩm của người bán và Tab Cửa hàng), phần góp vào thay đổi
          GMV:
        </Note>
        <ContributionLine comparison={profile.self_search} />
        <h4>Khuyến mãi trên sản phẩm này</h4>
        <BandStrip days={allDays(report)} bands={profile.bands ?? []} coverage={profile.flash?.coverage ?? {}} />
        <BandsTable bands={profile.bands ?? []} />
        {profile.flash && <FlashSection flash={profile.flash} bands={profile.bands ?? []} shopLevel={false} />}
        {profile.discounts_prior && profile.discounts_last && (
          <>
            <h4>Giảm giá trên đơn</h4>
            <TableWrap label="Giảm giá trên đơn">
              <table className="analysis-table">
                <thead>
                  <tr>
                    <th scope="col">Giảm giá trên đơn</th>
                    <th scope="col">30 ngày trước</th>
                    <th scope="col">30 ngày gần đây</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <th scope="row">Số món đã bán (theo đơn)</th>
                    <td>{profile.discounts_prior.items}</td>
                    <td>{profile.discounts_last.items}</td>
                  </tr>
                  <tr>
                    <th scope="row">Món có giảm giá từ TikTok</th>
                    <td>{pct(profile.discounts_prior.platform_share, 0)}</td>
                    <td>{pct(profile.discounts_last.platform_share, 0)}</td>
                  </tr>
                  <tr>
                    <th scope="row">Món có giảm giá từ người bán</th>
                    <td>{pct(profile.discounts_prior.seller_share, 0)}</td>
                    <td>{pct(profile.discounts_last.seller_share, 0)}</td>
                  </tr>
                </tbody>
              </table>
            </TableWrap>
          </>
        )}
        {appearances && (
          <>
            <h4>LIVE và video có nhiều đơn nhất</h4>
            <AppearanceList
              title="Phiên LIVE"
              items={appearances.top_live}
              noneCount={appearances.live_without_orders}
              unit="Đơn hàng SKU"
            />
            <AppearanceList
              title="Video"
              items={appearances.top_videos}
              noneCount={appearances.videos_without_orders}
              unit="Số món bán (từ khi đăng)"
            />
          </>
        )}
      </div>
    </article>
  );
}
