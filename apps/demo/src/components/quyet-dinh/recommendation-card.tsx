"use client";

import { useId } from "react";

import { CARD_STATUS_LABELS, EXECUTOR_COPY, REJECTED_NOTICE, type CardView } from "../../lib/quyet-dinh/card-model";
import type { CardStatus, LeverExecutor } from "../../lib/quyet-dinh/p10-types";

/**
 * The recommendation card (ADR-109 Amendment 1 d.1–3): `Main.dc.html` from
 * 768 px, `Mobile.dc.html` below. Collapsed by default; "Xem thêm" expands
 * in place (Lý do đầy đủ, before → after per field, how GMV dự kiến is
 * computed). Phê duyệt → the blue notice + "Xem tiến độ ›"; Từ chối opens
 * the reason dialog (the caller owns it). Promotion / photo cards carry the
 * executor chip and what happens after Phê duyệt (`Levers.dc.html`).
 */

export const STATUS_TONE: Readonly<Record<CardStatus, string>> = {
  pending: "wait",
  running: "info",
  applied: "ok",
  rejected: "muted",
  expired: "expired",
};

const WHO_TONE: Readonly<Record<LeverExecutor, string>> = {
  juli: "ok",
  juli_with_photo: "info",
  seller_center: "wait",
};

export interface RecommendationCardProps {
  readonly card: CardView;
  /** Effective status (local approve / reject override the payload's). */
  readonly status: CardStatus;
  readonly expanded: boolean;
  readonly narrow: boolean;
  /** Approve is blocked (bands not set, a batch running…): the reason, shown under the buttons. */
  readonly blockedReason?: string | null;
  readonly busy?: boolean;
  readonly error?: string | null;
  /** Where "Xem tiến độ ›" goes once approved. */
  readonly progressHref: string | null;
  readonly onToggle: () => void;
  readonly onApprove: () => void;
  readonly onReject: () => void;
  readonly onOpenProgress?: (event: React.MouseEvent<HTMLAnchorElement>) => void;
  /** "Xem phân tích ›" (ADR-109 Amendment 2 d.4, PtFlow): Phân tích on the card's stream, metric and row. */
  readonly analysisHref?: string | null;
  /** Arrived from Phân tích's "Xem đề xuất ›": outlined pink for 3 s. */
  readonly focused?: boolean;
}

function AnalysisLink({ href }: { readonly href: string | null | undefined }) {
  if (!href) return null;
  return (
    <a className="qv-analysis-link" href={href}>
      Xem phân tích ›
    </a>
  );
}

function MoreSection({ card }: { readonly card: CardView }) {
  return (
    <section aria-label="Chi tiết đề xuất" className="qv-more">
      {card.reasonFull ? (
        <div className="qv-more__block">
          <div className="qv-more__label">Lý do đầy đủ</div>
          <div>{card.reasonFull}</div>
        </div>
      ) : null}
      {card.beforeAfter.map((row) => (
        <div className="qv-more__block" key={row.field}>
          <div className="qv-more__label">{row.label}</div>
          {row.style === "strike" ? (
            <>
              <div className="qv-before qv-before--strike">
                <span className="qv-sr">Trước: </span>
                {row.before}
              </div>
              <div className="qv-after--strong">
                <span className="qv-sr">Sau: </span>
                {row.after}
              </div>
            </>
          ) : (
            <>
              <div className="qv-before">Hiện tại: {withStop(row.before)}</div>
              <div>Đề xuất: {withStop(row.after)}</div>
            </>
          )}
        </div>
      ))}
      {card.gmvMethod ? (
        <div className="qv-more__method">GMV dự kiến tính theo cách của TikTok: {withStop(card.gmvMethod)}</div>
      ) : null}
    </section>
  );
}

function withStop(text: string): string {
  return /[.!?…]$/.test(text) ? text : `${text}.`;
}

function ExecutorLines({ executor, show }: { readonly executor: LeverExecutor; readonly show: boolean }) {
  if (!show) return null;
  return (
    <span className={`qv-who qv-tone--${WHO_TONE[executor]}`} data-testid="executor-chip">
      {EXECUTOR_COPY[executor].chip}
    </span>
  );
}

function Outcome({
  status,
  executor,
  progressHref,
  onOpenProgress,
}: {
  readonly status: CardStatus;
  readonly executor: LeverExecutor;
  readonly progressHref: string | null;
  readonly onOpenProgress?: (event: React.MouseEvent<HTMLAnchorElement>) => void;
}) {
  if (status === "running") {
    return (
      <div className="qv-notice" role="status">
        <span>{EXECUTOR_COPY[executor].notice}</span>
        {progressHref ? (
          <a className="qv-link" href={progressHref} onClick={onOpenProgress}>
            Xem tiến độ ›
          </a>
        ) : null}
      </div>
    );
  }
  if (status === "rejected") {
    return (
      <div className="qv-rejected" role="status">
        {REJECTED_NOTICE}
      </div>
    );
  }
  return null;
}

export function RecommendationCard(props: RecommendationCardProps) {
  return props.narrow ? <MobileCard {...props} /> : <DesktopCard {...props} />;
}

function DesktopCard({
  card,
  status,
  expanded,
  blockedReason,
  busy,
  error,
  progressHref,
  onToggle,
  onApprove,
  onReject,
  onOpenProgress,
  analysisHref,
  focused = false,
}: RecommendationCardProps) {
  const titleId = useId();
  const blockId = useId();
  const showWho = card.executor !== "juli";
  return (
    <article
      aria-labelledby={titleId}
      className={`qv-card${focused ? " qv-card--focus" : ""}`}
      data-decision-id={card.id}
      data-focused={focused ? "true" : undefined}
      data-status={status}
      data-testid="recommendation-card"
    >
      <div className="qv-card__top">
        <div className="qv-card__id">
          <div className="qv-card__name-row">
            {card.sku ? <span className="qv-sku">SKU · {card.sku}</span> : null}
            <h3 className="qv-card__title" id={titleId}>
              {card.title}
            </h3>
          </div>
          <div className="qv-card__meta">{card.meta}</div>
        </div>
        <span className={`qv-chip qv-status qv-tone--${STATUS_TONE[status]}`} data-testid="card-status">
          {CARD_STATUS_LABELS[status]}
        </span>
      </div>

      {card.kpiLabel || card.gmvPerMonth ? (
        <div className="qv-kpi">
          <div className="qv-kpi__main">
            {card.kpiLabel ? <div className="qv-kpi__label">{card.kpiLabel}</div> : null}
            {card.kpiCurrent ? (
              <div className="qv-kpi__values">
                <span className="qv-kpi__big">{card.kpiCurrent}</span>
                {card.kpiTarget ? (
                  <>
                    <span aria-hidden="true" className="qv-kpi__arrow">
                      →
                    </span>
                    <span className="qv-sr"> mục tiêu </span>
                    <span className="qv-kpi__big">{card.kpiTarget}</span>
                  </>
                ) : null}
                {card.kpiUplift ? <span className="qv-uplift">{card.kpiUplift}</span> : null}
              </div>
            ) : null}
          </div>
          {card.gmvPerMonth ? (
            <div className="qv-kpi__gmv">
              <div className="qv-kpi__label">GMV dự kiến</div>
              <div className="qv-kpi__money">{card.gmvPerMonth}</div>
            </div>
          ) : null}
        </div>
      ) : null}

      <dl className="qv-facts">
        <dt>Lý do</dt>
        <dd>{card.reasonShort}</dd>
        <dt>Thay đổi đề xuất</dt>
        <dd className="qv-field-chips">
          {card.changeLabels.map((label) => (
            <span className="qv-field-chip" key={label}>
              {label}
            </span>
          ))}
        </dd>
      </dl>

      {expanded ? <MoreSection card={card} /> : null}

      <ExecutorLines executor={card.executor} show={showWho} />

      <Outcome executor={card.executor} onOpenProgress={onOpenProgress} progressHref={progressHref} status={status} />

      <div className="qv-card__actions">
        {status === "pending" ? (
          <div className="qv-card__buttons">
            <button
              aria-describedby={blockedReason ? blockId : undefined}
              className="qv-btn qv-btn--primary"
              disabled={Boolean(blockedReason) || busy}
              onClick={onApprove}
              type="button"
            >
              Phê duyệt
            </button>
            <button className="qv-btn qv-btn--secondary" disabled={busy} onClick={onReject} type="button">
              Từ chối
            </button>
          </div>
        ) : null}
        <button aria-expanded={expanded} className="qv-btn qv-btn--ghost qv-card__toggle" onClick={onToggle} type="button">
          {expanded ? "Thu gọn" : "Xem thêm"}
        </button>
        <AnalysisLink href={analysisHref} />
      </div>
      {showWho && status === "pending" ? <span className="qv-after-note">{EXECUTOR_COPY[card.executor].after}</span> : null}
      {status === "pending" && blockedReason ? (
        <p className="qv-card__error" id={blockId}>
          {blockedReason}
        </p>
      ) : null}
      {error ? (
        <p className="qv-card__error" role="alert">
          {error}
        </p>
      ) : null}
    </article>
  );
}

function MobileCard({
  card,
  status,
  expanded,
  blockedReason,
  busy,
  error,
  progressHref,
  onToggle,
  onApprove,
  onReject,
  onOpenProgress,
  analysisHref,
  focused = false,
}: RecommendationCardProps) {
  const titleId = useId();
  const blockId = useId();
  const showWho = card.executor !== "juli";
  return (
    <article
      aria-labelledby={titleId}
      className={`qv-card qv-card--mobile${focused ? " qv-card--focus" : ""}`}
      data-decision-id={card.id}
      data-focused={focused ? "true" : undefined}
      data-status={status}
      data-testid="recommendation-card"
    >
      <div className="qv-card__top">
        <div className="qv-card__id">
          {card.sku ? <span className="qv-sku">SKU · {card.sku}</span> : null}
          <h3 className="qv-card__title" id={titleId}>
            {card.title}
          </h3>
          <div className="qv-card__meta">{card.meta}</div>
        </div>
        <span className={`qv-chip qv-status qv-tone--${STATUS_TONE[status]}`} data-testid="card-status">
          {CARD_STATUS_LABELS[status]}
        </span>
      </div>

      {card.kpiLabel || card.gmvPerMonth ? (
        <div className="qv-kpi qv-kpi--mobile">
          {card.kpiLabel ? (
            <div className="qv-kpi__label">Chỉ số chính · {card.kpiLabel.replace(/ - /g, " ")}</div>
          ) : null}
          {card.kpiPairText ? (
            <div className="qv-kpi__values">
              <span className="qv-kpi__big">{card.kpiPairText}</span>
              {card.kpiUplift ? <span className="qv-uplift">{card.kpiUplift}</span> : null}
            </div>
          ) : null}
          {card.gmvPerMonth ? (
            <div className="qv-kpi__row">
              <span className="qv-kpi__label">GMV dự kiến</span>
              <span className="qv-kpi__money">
                {card.gmvPerMonth} <span className="qv-estimate">ước tính</span>
              </span>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="qv-mfact">
        <div className="qv-mfact__label">Lý do</div>
        <div>{card.reasonMobile}</div>
      </div>

      <div className="qv-mfact qv-mfact--changes">
        <div className="qv-mfact__label">Thay đổi đề xuất</div>
        {card.beforeAfter.length > 0
          ? card.beforeAfter.map((row) => (
              <span key={row.field}>
                <strong>{row.label}:</strong> {row.inline}
              </span>
            ))
          : card.changeLabels.map((label) => (
              <span key={label}>
                <strong>{label}</strong>
              </span>
            ))}
      </div>

      {expanded ? <MoreSection card={card} /> : null}

      <ExecutorLines executor={card.executor} show={showWho} />

      <Outcome executor={card.executor} onOpenProgress={onOpenProgress} progressHref={progressHref} status={status} />

      {status === "pending" ? (
        <div className="qv-card__grid-buttons">
          <button
            aria-describedby={blockedReason ? blockId : undefined}
            className="qv-btn qv-btn--primary"
            disabled={Boolean(blockedReason) || busy}
            onClick={onApprove}
            type="button"
          >
            Phê duyệt
          </button>
          <button className="qv-btn qv-btn--secondary" disabled={busy} onClick={onReject} type="button">
            Từ chối
          </button>
        </div>
      ) : null}
      {status === "pending" && blockedReason ? (
        <p className="qv-card__error" id={blockId}>
          {blockedReason}
        </p>
      ) : null}
      {error ? (
        <p className="qv-card__error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="qv-card__links">
        <button aria-expanded={expanded} className="qv-card__more-link" onClick={onToggle} type="button">
          {expanded ? "Thu gọn ‹" : "Xem thêm ›"}
        </button>
        <AnalysisLink href={analysisHref} />
      </div>
    </article>
  );
}
