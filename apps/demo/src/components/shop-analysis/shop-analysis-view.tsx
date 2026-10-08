"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import {
  CHANNEL_LABELS,
  CHANNEL_SUBTITLES,
  FIVE_CHANNELS,
  isChannelMissing,
  NO_DATA,
  RANKING_LABELS,
} from "../../lib/shop-analysis/derive";
import type {
  ChannelKey,
  ChannelRow,
  FunnelComparison,
  HeroRanking,
  ShopAnalysisEnvelope,
  ShopDiagnosisReport,
} from "../../lib/shop-analysis/types";
import { money, num, pct, shortDate, signedMoney, slashDate } from "../../lib/vn-format";
import { FunnelBoxes } from "./funnel";
import { HeroProfileCard } from "./hero-profile";
import { BandsTable, FlashSection, VoucherSection } from "./promotions";
import { ChangeChip, ConfidenceBadge, ContributionLine, KpiTable, Note, TableWrap, Verdict } from "./shared";
import { TimelineSection } from "./timeline";

/**
 * Phân tích (AC-7.7, D21): the ADR-108 shop diagnosis report, rendered from
 * its JSON. Wording mirrors the owner-approved HTML page
 * (`shop_diagnosis/render.py`); the order follows the app: GMV theo 5 kênh →
 * phễu từng kênh → sản phẩm chủ lực → dòng thời gian → khuyến mãi → toàn
 * shop → cách tính. Vietnamese only, dd/mm/yyyy dates, no backend names.
 */

function Section({
  id,
  eyebrow,
  title,
  lede,
  children,
}: {
  readonly id: string;
  readonly eyebrow: string;
  readonly title: string;
  readonly lede?: ReactNode;
  readonly children: ReactNode;
}) {
  return (
    <section className="card analysis-section" id={id} aria-labelledby={`${id}-title`}>
      <p className="analysis-eyebrow">{eyebrow}</p>
      <h2 className="analysis-section__title" id={`${id}-title`}>
        {title}
      </h2>
      {lede && <p className="analysis-lede">{lede}</p>}
      {children}
    </section>
  );
}

const STACK_CLASSES = [
  "stack-0",
  "stack-1",
  "stack-2",
  "stack-3",
  "stack-4",
] as const;

/** Backend `render._stacked_bars`: the additive channels, prior vs last. */
function StackedBars({ report }: { readonly report: ShopDiagnosisReport }) {
  const rows = report.channels.filter((r) => r.additive);
  const scale = Math.max(report.total.prior.gmv, report.total.last.gmv) || 1;
  return (
    <div className="stacked-bars">
      <div className="band-legend">
        {rows.map((r, i) => (
          <span key={r.channel}>
            <i className={`band-legend__swatch ${STACK_CLASSES[i % STACK_CLASSES.length]}`} />
            {CHANNEL_LABELS[r.channel]}
          </span>
        ))}
      </div>
      {(
        [
          ["30 ngày trước", "prior"],
          ["30 ngày gần đây", "last"],
        ] as const
      ).map(([label, side]) => (
        <div className="stacked-bars__row" key={side}>
          <span className="stacked-bars__label">{label}</span>
          <span
            className="stacked-bars__track"
            role="img"
            aria-label={`GMV mỗi ngày theo kênh, ${label}: ${rows
              .map((r) => `${CHANNEL_LABELS[r.channel]} ${money(r.comparison[side].gmv)}`)
              .join(", ")}`}
          >
            {rows.map((r, i) => (
              <span
                key={r.channel}
                className={`stacked-bars__seg ${STACK_CLASSES[i % STACK_CLASSES.length]}`}
                style={{ width: `${(Math.max(r.comparison[side].gmv, 0) / scale) * 100}%` }}
                title={`${CHANNEL_LABELS[r.channel]}: ${money(r.comparison[side].gmv)}`}
              />
            ))}
          </span>
        </div>
      ))}
    </div>
  );
}

function GmvRow({
  label,
  comparison,
  share,
  variant,
}: {
  readonly label: string;
  readonly comparison: FunnelComparison;
  readonly share: number | null;
  readonly variant?: "group" | "sub" | "total";
}) {
  const p = comparison.prior.gmv;
  const q = comparison.last.gmv;
  return (
    <tr className={variant ? `analysis-table__${variant}` : undefined}>
      <th scope="row">{label}</th>
      <td>{money(p)}</td>
      <td>{money(q)}</td>
      <td>
        {signedMoney(q - p)} <ChangeChip prior={p} last={q} />
      </td>
      <td>{pct(share, 0)}</td>
      <td>
        <ConfidenceBadge label={comparison.gmv_confidence} />
      </td>
    </tr>
  );
}

function MissingRow({ label }: { readonly label: string }) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td colSpan={5} className="analysis-table__text">
        {NO_DATA}
      </td>
    </tr>
  );
}

function channelLabel(row: ChannelRow | undefined, channel: ChannelKey): string {
  return CHANNEL_LABELS[channel] + (row && !row.additive ? " *" : "");
}

function ChannelSplit({ report }: { readonly report: ShopDiagnosisReport }) {
  const byChannel = new Map(report.channels.map((r) => [r.channel, r]));
  const groups = report.groups ?? [];
  return (
    <>
      <StackedBars report={report} />
      <TableWrap label="GMV trung bình mỗi ngày theo kênh">
        <table className="analysis-table">
          <thead>
            <tr>
              <th scope="col">Kênh</th>
              <th scope="col">GMV/ngày · 30 ngày trước</th>
              <th scope="col">GMV/ngày · 30 ngày gần đây</th>
              <th scope="col">Thay đổi</th>
              <th scope="col">Góp vào thay đổi GMV shop</th>
              <th scope="col">Mức tin cậy</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => [
              <GmvRow
                key={group.label}
                label={group.label}
                comparison={group.comparison}
                share={group.share_of_change}
                variant="group"
              />,
              ...group.channels.flatMap((channel) => {
                const row = byChannel.get(channel);
                const main = isChannelMissing(row) ? (
                  <MissingRow key={channel} label={CHANNEL_LABELS[channel]} />
                ) : (
                  <GmvRow
                    key={channel}
                    label={channelLabel(row, channel)}
                    comparison={(row as ChannelRow).comparison}
                    share={(row as ChannelRow).share_of_change}
                  />
                );
                const subs =
                  channel === "affiliate"
                    ? (report.affiliate_rows ?? []).map((sub) => (
                        <GmvRow
                          key={sub.channel}
                          label={CHANNEL_LABELS[sub.channel]}
                          comparison={sub.comparison}
                          share={null}
                          variant="sub"
                        />
                      ))
                    : [];
                return [main, ...subs];
              }),
            ])}
            <GmvRow label="Tất cả kênh (toàn shop)" comparison={report.total} share={1} variant="total" />
          </tbody>
        </table>
      </TableWrap>
      <Note>
        * Tab Cửa hàng được TikTok báo riêng và trùng một phần với các kênh khác, nên không cộng vào
        tổng shop; cột &quot;góp vào thay đổi&quot; của bốn kênh còn lại cộng lại đúng bằng thay đổi
        của shop. Dòng Nhóm khách tự tìm đến cộng cả Tab Cửa hàng.
      </Note>
    </>
  );
}

function FunnelCard({
  channel,
  comparison,
  missing,
}: {
  readonly channel: ChannelKey;
  readonly comparison?: FunnelComparison;
  readonly missing: boolean;
}) {
  const label = channel === "total" ? "Tất cả kênh" : CHANNEL_LABELS[channel];
  return (
    <article className="funnel-card" aria-label={`Phễu: ${label}`}>
      <div className="funnel-card__head">
        <h3 className="funnel-card__title">{label}</h3>
        <p className="funnel-card__subtitle">{CHANNEL_SUBTITLES[channel]}</p>
      </div>
      {missing || !comparison ? (
        <p className="funnel-card__missing">{NO_DATA}</p>
      ) : (
        <>
          <FunnelBoxes channel={channel} comparison={comparison} />
          <ContributionLine comparison={comparison} />
        </>
      )}
    </article>
  );
}

function ChannelFunnels({ report }: { readonly report: ShopDiagnosisReport }) {
  const byChannel = new Map(report.channels.map((r) => [r.channel, r]));
  return (
    <>
      <div className="funnel-list">
        <FunnelCard channel="total" comparison={report.total} missing={false} />
        {FIVE_CHANNELS.map((channel) => {
          const row = byChannel.get(channel);
          return (
            <FunnelCard
              key={channel}
              channel={channel}
              comparison={row?.comparison}
              missing={isChannelMissing(row)}
            />
          );
        })}
      </div>
      {(report.affiliate_rows ?? []).length > 0 && (
        <TableWrap label="Liên kết chia theo Video và LIVE">
          <table className="analysis-table">
            <thead>
              <tr>
                <th scope="col">Liên kết chia theo</th>
                <th scope="col">Lượt hiển thị sản phẩm</th>
                <th scope="col">CTR (Tỷ lệ nhấp)</th>
                <th scope="col">Lượt nhấp vào sản phẩm</th>
                <th scope="col">GMV</th>
              </tr>
            </thead>
            <tbody>
              {report.affiliate_rows.map((r) => {
                const p = r.comparison.prior;
                const q = r.comparison.last;
                const ctrP = p.impressions ? p.clicks / p.impressions : null;
                const ctrQ = q.impressions ? q.clicks / q.impressions : null;
                return (
                  <tr key={r.channel} className="analysis-table__sub">
                    <th scope="row">{CHANNEL_LABELS[r.channel]}</th>
                    <td>
                      {num(p.impressions)} → {num(q.impressions)}
                    </td>
                    <td>
                      {pct(ctrP)} → {pct(ctrQ)}
                    </td>
                    <td>
                      {num(p.clicks)} → {num(q.clicks)}
                    </td>
                    <td>
                      {money(p.gmv)} → {money(q.gmv)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableWrap>
      )}
      <Note>Video và LIVE liên kết không có số đơn riêng nên không có CTOR.</Note>
    </>
  );
}

function Heroes({ report }: { readonly report: ShopDiagnosisReport }) {
  const sel = report.selection;
  const movers = sel?.movers ?? [];
  return (
    <>
      <p className="analysis-lede">
        Xếp hạng theo: <b>{RANKING_LABELS[sel?.ranking] ?? RANKING_LABELS["60d"]}</b> (GMV mọi kênh).
        Năm sản phẩm chiếm {`${pct(sel?.gmv_share, 0)} GMV`} của shop trong khoảng xếp hạng. Kết luận của
        mỗi sản phẩm dựa trên Nhóm khách tự tìm đến; chỉ yếu tố có mức tin cậy &quot;Rõ&quot; mới được
        chọn làm nguyên nhân chính.
      </p>
      {sel?.dispersed && (
        <p className="analysis-warn">
          Shop phân tán, top 5 chưa đại diện: năm sản phẩm chỉ chiếm {pct(sel.gmv_share, 0)} GMV.
        </p>
      )}
      {movers.length > 0 && (
        <>
          <p>Thay đổi trong top 5 giữa hai kỳ:</p>
          <ul className="analysis-list">
            {movers.map(([pid, move]) => (
              <li key={pid}>
                {report.titles?.[pid] || "Sản phẩm chưa có tên"}: {move}
              </li>
            ))}
          </ul>
        </>
      )}
      <div className="hero-list">
        {report.profiles.map((profile) => (
          <HeroProfileCard key={profile.product_id} profile={profile} report={report} />
        ))}
      </div>
    </>
  );
}

function ShopWide({ report }: { readonly report: ShopDiagnosisReport }) {
  const selfSearch = (report.groups ?? []).find((g) => g.label === "Nhóm khách tự tìm đến");
  return (
    <>
      <h3 className="analysis-subtitle">Chỉ số trung bình của shop · Tất cả kênh</h3>
      <KpiTable comparison={report.total} label="Chỉ số trung bình của shop" />
      {selfSearch && (
        <>
          <h3 className="analysis-subtitle">Nhóm khách tự tìm đến</h3>
          <KpiTable comparison={selfSearch.comparison} withExtras={false} label="Chỉ số của Nhóm khách tự tìm đến" />
          <ContributionLine comparison={selfSearch.comparison} />
        </>
      )}
      {report.rest_conclusion && report.rest_total && (
        <>
          <h3 className="analysis-subtitle">Phần còn lại ngoài top 5</h3>
          <Verdict headline={report.rest_conclusion.headline} lookNext={report.rest_conclusion.look_next} />
          <KpiTable comparison={report.rest_total} label="Chỉ số phần còn lại ngoài top 5" />
        </>
      )}
      <h3 className="analysis-subtitle">Sản phẩm cần theo dõi</h3>
      {report.watch?.length ? (
        <TableWrap label="Sản phẩm cần theo dõi">
          <table className="analysis-table">
            <thead>
              <tr>
                <th scope="col">Sản phẩm</th>
                <th scope="col">Lý do</th>
                <th scope="col">GMV/ngày · 30 ngày trước</th>
                <th scope="col">GMV/ngày · 30 ngày gần đây</th>
              </tr>
            </thead>
            <tbody>
              {report.watch.map((w) => (
                <tr key={w.product_id}>
                  <th scope="row">{w.title || "Sản phẩm chưa có tên"}</th>
                  <td className="analysis-table__text">{w.reason}</td>
                  <td>{money(w.gmv_prior)}</td>
                  <td>{money(w.gmv_last)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      ) : (
        <Note>Không có sản phẩm nào ngoài top 5 thay đổi đáng kể.</Note>
      )}
    </>
  );
}

/** Backend `render.NOTES`, verbatim. */
const NOTES = [
  "Mọi số trong bảng là trung bình mỗi ngày của từng khoảng 30 ngày, cộng từ số liệu từng ngày của TikTok.",
  "Tỷ lệ của một khoảng thời gian được tính từ tổng của khoảng đó (ví dụ CTR = tổng lượt nhấp chia tổng lượt hiển thị), giống cách Trung tâm người bán tính, không lấy trung bình các tỷ lệ từng ngày.",
  "CTR = lượt nhấp vào sản phẩm chia lượt hiển thị sản phẩm. Tỷ lệ thêm vào giỏ hàng = số lượt thêm vào giỏ chia lượt nhấp. CTOR = đơn hàng SKU chia lượt nhấp. AOV (SKU) = GMV chia đơn hàng SKU.",
  "GMV là GMV của TikTok, đã gồm đơn bị hủy và hoàn tiền; không trừ gì thêm.",
  "Thay đổi GMV được tách thành bốn phần theo tỷ lệ lôgarit của từng yếu tố; bốn phần cộng lại đúng bằng thay đổi GMV.",
  "Tab Cửa hàng không có số liệu thêm vào giỏ hàng; đơn hàng SKU của kênh này được ước tính bằng CTOR nhân lượt nhấp. Kênh này trùng một phần với các kênh khác nên không cộng vào tổng shop.",
  "Ở Video và LIVE của người bán, khách thường mua ngay không qua giỏ hàng, nên CTOR gồm cả khách mua thẳng.",
  'Mức tin cậy: "Rõ" khi mỗi kỳ có từ 30 đơn trở lên và khoảng tin cậy 90 % của chênh lệch không chứa 0; "Tham khảo" khi một kỳ có 10 đến 29 đơn hoặc chênh lệch nằm trong biên độ nhiễu; "Chưa đủ dữ liệu" khi một kỳ có dưới 10 đơn. Tỷ lệ dùng kiểm định hai tỷ lệ; lượt hiển thị, GMV và AOV dùng chuỗi số từng ngày.',
  "Kết luận sản phẩm: GMV đổi dưới 10 % là Ổn định; dưới 30 đơn hàng SKU trong một kỳ là Chưa đủ dữ liệu; nếu yếu tố lớn nhất là lượt hiển thị thì xét yếu tố tiếp theo; nếu là CTOR thì tách thành trước giỏ (tỷ lệ thêm vào giỏ) và sau giỏ (đơn trên lượt thêm vào giỏ).",
  "Một ngày là ngày flash sale khi flash sale chạy từ nửa ngày trở lên. Độ sâu thật so giá flash với giá đã giảm sẵn bởi chương trình giảm giá sản phẩm đang chạy, không so với giá niêm yết.",
  "Voucher được phân loại theo cấu hình (ngưỡng đơn, phạm vi, số lượt) so với giá một món phổ biến, là trung vị giá trị các đơn một món trong 30 ngày gần đây; không dựa vào tên voucher.",
  "Ngày sale nền tảng (ngày trùng tháng như 9/9, 10/10) được đánh dấu, không bị loại khỏi số liệu.",
  "Số liệu đơn hàng lấy theo ngày tạo đơn, theo giờ Việt Nam.",
];

const SECTIONS = [
  ["phan-tich-kenh", "GMV theo kênh"],
  ["phan-tich-pheu", "Phễu"],
  ["phan-tich-san-pham", "Sản phẩm chủ lực"],
  ["phan-tich-dong-thoi-gian", "Dòng thời gian"],
  ["phan-tich-khuyen-mai", "Khuyến mãi"],
  ["phan-tich-toan-shop", "Toàn shop"],
  ["phan-tich-ghi-chu", "Cách tính"],
] as const;

export interface ShopAnalysisViewProps {
  readonly envelope: ShopAnalysisEnvelope;
  /** The anonymous sample: invented shop, invented numbers — said on screen. */
  readonly sample?: boolean;
  /** Signed-in only: the hero ranking toggle (re-reads the report). */
  readonly ranking?: HeroRanking;
  readonly onRankingChange?: (ranking: HeroRanking) => void;
}

export function ShopAnalysisView({
  envelope,
  sample = false,
  ranking,
  onRankingChange,
}: ShopAnalysisViewProps) {
  const report = envelope.report;
  const w = report.windows;
  const saleDays = (report.sale_days ?? []).map(shortDate).join(", ") || "không có";
  const builtAt = envelope.built_at ? slashDate(envelope.built_at.slice(0, 10)) : null;

  return (
    <div className="analysis-page" data-testid="shop-analysis">
      <header className="analysis-header">
        <div>
          <h1 className="demo-title" id="analytics-title">
            Phân tích
          </h1>
          <p className="analysis-header__shop">
            {report.shop_name || "Shop của bạn"}
            {sample && <span className="badge badge-pink">Dữ liệu mẫu</span>}
          </p>
        </div>
        <p className="analysis-lede">
          30 ngày gần đây: {slashDate(w.last_first)}–{slashDate(w.last_last)} · 30 ngày trước:{" "}
          {slashDate(w.prior_first)}–{slashDate(w.prior_last)}. Mọi số trong bảng là trung bình mỗi
          ngày. Ngày sale nền tảng trong 60 ngày: {saleDays}.
          {builtAt && !sample ? ` Cập nhật ngày ${builtAt}.` : ""}
        </p>
        {sample && (
          <p className="juli-assist">
            Đây là báo cáo của một shop minh họa với số liệu tự tạo. Đăng nhập và kết nối TikTok Shop
            để xem báo cáo của shop bạn, cập nhật mỗi ngày.
          </p>
        )}
        <nav className="analysis-toc" aria-label="Các phần của báo cáo">
          {SECTIONS.map(([id, label]) => (
            <a key={id} href={`#${id}`}>
              {label}
            </a>
          ))}
        </nav>
      </header>

      <Section
        id="phan-tich-kenh"
        eyebrow="GMV theo kênh"
        title="GMV trung bình mỗi ngày, chia theo 5 kênh"
        lede={
          <>
            GMV trung bình mỗi ngày của từng kênh trong 30 ngày gần đây so với 30 ngày trước, và phần
            mỗi kênh góp vào thay đổi GMV của cả shop. Hai nhóm: <b>Nhóm khách tự tìm đến</b> (nơi việc
            sửa trang sản phẩm, giá và voucher tác động; CTOR là chỉ số chính) và <b>Nhóm nội dung</b>{" "}
            (lượt hiển thị sản phẩm và GMV là chỉ số chính).
          </>
        }
      >
        <ChannelSplit report={report} />
      </Section>

      <Section
        id="phan-tich-pheu"
        eyebrow="Phễu"
        title="Phễu của từng kênh: từ lượt hiển thị sản phẩm đến GMV"
        lede="Mỗi ô ghi số trung bình mỗi ngày của 30 ngày gần đây, số của 30 ngày trước và mức thay đổi. Thay đổi GMV của mỗi kênh được tách thành bốn phần: Lượt hiển thị sản phẩm, CTR, CTOR và AOV (SKU); bốn phần cộng lại đúng bằng thay đổi GMV."
      >
        <ChannelFunnels report={report} />
      </Section>

      <Section id="phan-tich-san-pham" eyebrow="Sản phẩm chủ lực" title="Năm sản phẩm chủ lực">
        {onRankingChange && (
          <div className="analysis-segmented" role="group" aria-label="Xếp hạng sản phẩm chủ lực theo">
            {(["60d", "30d"] as const).map((key) => (
              <button
                key={key}
                type="button"
                aria-pressed={(ranking ?? envelope.ranking ?? "60d") === key}
                onClick={() => onRankingChange(key)}
              >
                {RANKING_LABELS[key]}
              </button>
            ))}
          </div>
        )}
        <Heroes report={report} />
      </Section>

      <Section
        id="phan-tich-dong-thoi-gian"
        eyebrow="Dòng thời gian"
        title="Dòng thời gian sự kiện"
        lede="Đây là phần duy nhất xem theo ngày. Mỗi đường là trung bình 7 ngày liền trước của từng kênh; nền cam là ngày có flash sale, vạch dọc liền là ngày bắt đầu 30 ngày gần đây, vạch đỏ nét đứt là ngày sale nền tảng."
      >
        <TimelineSection report={report} />
      </Section>

      <Section id="phan-tich-khuyen-mai" eyebrow="Khuyến mãi" title="Flash sale, giảm giá và voucher">
        <BandsTable bands={report.shop_bands ?? []} />
        {report.shop_flash && (
          <FlashSection flash={report.shop_flash} bands={report.shop_bands ?? []} shopLevel />
        )}
        <VoucherSection summary={report.vouchers} />
      </Section>

      <Section id="phan-tich-toan-shop" eyebrow="Toàn shop" title="Chỉ số trung bình của shop">
        <ShopWide report={report} />
      </Section>

      <Section id="phan-tich-ghi-chu" eyebrow="Ghi chú" title="Cách tính">
        <ul className="analysis-notes">
          {NOTES.map((note) => (
            <li key={note}>{note}</li>
          ))}
          {report.missing_days?.length > 0 && (
            <li>
              Thiếu số liệu {report.missing_days.length} ngày:{" "}
              {report.missing_days.map(shortDate).join(", ")}; trung bình chỉ tính trên các ngày có
              số liệu.
            </li>
          )}
          {!report.orders_present && (
            <li>Chưa có dữ liệu đơn hàng: các mục voucher và giảm giá trên đơn bị bỏ trống.</li>
          )}
        </ul>
      </Section>

      <p className="analysis-footer">
        Số liệu từ TikTok Shop, đọc ở chế độ chỉ đọc. Trang này không đề xuất hành động; mỗi sản
        phẩm kết thúc bằng kết luận và chỗ cần xem tiếp.{" "}
        <Link className="link-secondary" href="/analytics/gmv-tiktok">
          Xem KPI chính của shop
        </Link>
      </p>
    </div>
  );
}
