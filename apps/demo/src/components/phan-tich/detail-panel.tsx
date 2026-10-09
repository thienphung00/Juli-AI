import { aov, CHANNEL_LABELS, ctor, ctr, FIVE_CHANNELS, isChannelMissing, NO_DATA } from "../../lib/shop-analysis/derive";
import type { HeroProfile } from "../../lib/shop-analysis/types";
import { formatMetric, METRIC_NAMES } from "../../lib/phan-tich/model";
import type { RankingPayload, RankingRow } from "../../lib/phan-tich/types";
import { money, num, pct, signedMoney, slashDate } from "../../lib/vn-format";
import { ConfidenceBadge } from "../shop-analysis/shared";

/**
 * The "Ví dụ · <mã>" panel to the right of the ranking (ADR-109 d.2, video
 * 0:57): one row of the table. A hero product shows its 5-channel profile from
 * the report (Kết luận + phễu by channel); any other row shows the numbers the
 * ranking carries for it — never more than the backend gave.
 */

const QUANTITY: Record<string, string> = {
  impressions: "Lượt hiển thị sản phẩm",
  ctr: "Lượt bấm",
};

function quantityLabel(metric: string): string {
  return QUANTITY[metric] ?? "Đơn hàng SKU";
}

function ProfileChannels({ profile }: { readonly profile: HeroProfile }) {
  const byChannel = new Map(profile.channels.map((r) => [r.channel, r]));
  return (
    <div className="pt-table-wrap" role="region" aria-label={`Hồ sơ 5 kênh · ${profile.title}`} tabIndex={0}>
      <table className="pt-table pt-table--compact">
        <thead>
          <tr>
            <th scope="col">Kênh</th>
            <th scope="col">CTR</th>
            <th scope="col">CTOR</th>
            <th scope="col">AOV</th>
            <th scope="col">GMV/ngày</th>
          </tr>
        </thead>
        <tbody>
          {FIVE_CHANNELS.map((channel) => {
            const row = byChannel.get(channel);
            if (!row || isChannelMissing(row)) {
              return (
                <tr key={channel}>
                  <th scope="row">{CHANNEL_LABELS[channel]}</th>
                  <td colSpan={4}>{NO_DATA}</td>
                </tr>
              );
            }
            const p = row.comparison.prior;
            const q = row.comparison.last;
            return (
              <tr key={channel}>
                <th scope="row">{CHANNEL_LABELS[channel]}</th>
                <td className="num">
                  {pct(ctr(p))} → {pct(ctr(q))}
                </td>
                <td className="num">
                  {pct(ctor(p))} → {pct(ctor(q))}
                </td>
                <td className="num">
                  {money(aov(p))} → {money(aov(q))}
                </td>
                <td className="num">
                  {money(p.gmv)} → {money(q.gmv)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export interface DetailPanelProps {
  readonly payload: RankingPayload;
  readonly row: RankingRow;
  readonly profile: HeroProfile | undefined;
}

export function DetailPanel({ payload, row, profile }: DetailPanelProps) {
  const metric = payload.metric;
  const isProduct = payload.row_kind === "product";
  const code = isProduct ? row.id : row.date ? slashDate(row.date) : row.id;
  return (
    <aside aria-labelledby="pt-detail-title" className="card pt-detail" data-testid="detail-panel">
      <p className="eyebrow">Ví dụ · {code}</p>
      <h3 className="pt-detail__title" id="pt-detail-title">
        {row.name}
      </h3>
      <dl className="pt-detail__facts">
        <div>
          <dt>{METRIC_NAMES[metric]}{isProduct ? "" : " (so với luồng 30 ngày trước)"}</dt>
          <dd className="num">
            {formatMetric(metric, row.prior)} → <b>{formatMetric(metric, row.last)}</b>
          </dd>
        </div>
        <div>
          <dt>GMV/ngày do thay đổi này</dt>
          <dd className="num">
            <b>{signedMoney(row.gmv_per_day)}</b> <ConfidenceBadge label={row.confidence} />
          </dd>
        </div>
        <div>
          <dt>{quantityLabel(metric)} (30 ngày)</dt>
          <dd className="num">
            {row.quantity_prior === null ? "" : `${num(row.quantity_prior, 0)} → `}
            {num(row.quantity_last, 0)}
          </dd>
        </div>
        {row.steps ? (
          <div>
            <dt>Chia theo hai bước của CTOR</dt>
            <dd className="num">
              Thêm giỏ/bấm {signedMoney(row.steps.add_to_cart_rate)} · Đơn/thêm giỏ{" "}
              {signedMoney(row.steps.orders_per_cart)}
            </dd>
          </div>
        ) : null}
      </dl>
      {profile ? (
        <div className="pt-detail__profile">
          <p className="pt-detail__verdict">{profile.conclusion.headline}</p>
          <p className="pt-detail__next">
            <b>Cần xem tiếp:</b> {profile.conclusion.look_next}
          </p>
          <ProfileChannels profile={profile} />
          <a className="link-secondary" href={`#pt-hero-${profile.product_id}`}>
            Xem hồ sơ đầy đủ trong danh sách sản phẩm chủ lực
          </a>
        </div>
      ) : isProduct ? (
        <p className="pt-detail__note">
          Sản phẩm này không thuộc năm sản phẩm chủ lực, nên Juli chỉ có số liệu của luồng này.
        </p>
      ) : null}
    </aside>
  );
}
