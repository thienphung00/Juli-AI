"use client";

import { useId } from "react";

import { ACTION_ROW_LABEL, cardStatusLabel, EXECUTOR_COPY, REJECTED_NOTICE, type CardView } from "../../lib/quyet-dinh/card-model";
import type { CardStatus, LeverExecutor } from "../../lib/quyet-dinh/p10-types";
import { REJECT_REASONS, reasonOption } from "../../lib/quyet-dinh/reasons";
import { useSandboxReviewer } from "../../lib/reviewer/mode";
import { useApproveControl, useSellerHref, useWriteControl } from "../seller-view-context";
import { ReasonDone } from "./reason-dialog";

/**
 * The recommendation card (ADR-109 Amendment 1 d.1–3): `Main.dc.html` from
 * 768 px, `Mobile.dc.html` below. Collapsed by default; "Xem thêm" expands
 * in place (Lý do đầy đủ, before → after per field, how GMV dự kiến is
 * computed). Duyệt → the blue notice + "Xem tiến độ ›"; Từ chối opens
 * the reason dialog (the caller owns it). Promotion / photo cards carry the
 * executor chip and what happens after Duyệt (`Levers.dc.html`).
 */

export const STATUS_TONE: Readonly<Record<CardStatus, string>> = {
  pending: "wait",
  running: "info",
  applied: "ok",
  simulated: "muted",
  rejected: "muted",
  expired: "expired",
};

/** P64 (D73.4): on the reviewer's live sandbox shop a sandbox write is the real change. */
function CardStatusChip({ status }: { readonly status: CardStatus }) {
  const sandboxShop = useSandboxReviewer();
  const tone = status === "simulated" && sandboxShop ? "ok" : STATUS_TONE[status];
  return (
    <span className={`qv-chip qv-status qv-tone--${tone}`} data-testid="card-status">
      {cardStatusLabel(status, sandboxShop)}
    </span>
  );
}

const WHO_TONE: Readonly<Record<LeverExecutor, string>> = {
  juli: "ok",
  juli_with_photo: "info",
  seller_center: "wait",
  juli_drafts: "drafts",
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
  /** The reason code the seller gave when rejecting it in this visit (the completion message). */
  readonly rejectReason?: string | null;
}

function AnalysisLink({ href }: { readonly href: string | null | undefined }) {
  const sellerHref = useSellerHref();
  if (!href) return null;
  return (
    <a className="qv-analysis-link" href={sellerHref(href)}>
      Xem phân tích ›
    </a>
  );
}

/** P17 (D26): a quick-scan card says so — "Đề xuất nhanh · dựa trên 14 ngày". */
function QuickScanChip({ card }: { readonly card: CardView }) {
  if (!card.quickScan) return null;
  return (
    <span className="qv-quick-chip" data-testid="quick-scan-chip" title={card.quickScan.basis ?? undefined}>
      {card.quickScan.label}
    </span>
  );
}

/** P23 (D29.6): "Độ tin cậy: Cao / Vừa / Thấp" — green / amber / grey. */
function ConfidencePill({ card }: { readonly card: CardView }) {
  if (!card.confidence) return null;
  return (
    <span className={`qv-confidence qv-tone--${card.confidence.tone}`} data-testid="confidence-pill">
      Độ tin cậy: {card.confidence.label}
    </span>
  );
}

/** P23 (D29.1) + D32: the KPI's window and channel, "· 30 ngày · đo trên kênh Thẻ sản phẩm". */
function KpiWindow({ card }: { readonly card: CardView }) {
  if (!card.kpiWindow) return null;
  return (
    <span className="qv-kpi__window" data-testid="kpi-window">
      · {card.kpiWindow}
    </span>
  );
}

/** P17: the quick card's confidence ("Độ tin cậy: Tham khảo"), next to its expected GMV. */
function QuickScanConfidence({ card }: { readonly card: CardView }) {
  // P23: the pill under the title already says it.
  if (!card.quickScan || card.confidence) return null;
  return (
    <div className="qv-quick-confidence" data-testid="quick-scan-confidence">
      Độ tin cậy: {card.quickScan.confidence}
    </div>
  );
}

/** `ContentCards.dc.html`: the action row = the action chip + the purple "Juli soạn · bạn làm" chip. */
function ContentAction({ card }: { readonly card: CardView }) {
  if (!card.content) return null;
  return (
    <>
      <span className="qv-field-chip">{card.content.actionLabel}</span>
      <span className="qv-drafts-chip" data-testid="drafts-chip">
        {card.content.chip}
      </span>
    </>
  );
}

/** `ContentCards.dc.html` Xem thêm: Lý do đầy đủ · Juli sẽ soạn · Đo kết quả. */
function ContentMore({ card }: { readonly card: CardView }) {
  if (!card.content) return null;
  return (
    <section aria-label="Chi tiết đề xuất" className="qv-more qv-more--content">
      {card.reasonFull ? (
        <div>
          <div className="qv-more__label">Lý do đầy đủ</div>
          <div>{card.reasonFull}</div>
        </div>
      ) : null}
      <div>
        <div className="qv-more__label">Juli sẽ soạn</div>
        <div className="qv-pre-line">{card.content.willDraft}</div>
      </div>
      <div>
        <div className="qv-more__label">Đo kết quả</div>
        <div>{card.content.measure}</div>
      </div>
    </section>
  );
}

function MoreSection({ card }: { readonly card: CardView }) {
  if (card.content) return <ContentMore card={card} />;
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
        <div className="qv-more__method">{withStop(card.gmvMethod)}</div>
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
  rejectReason = null,
}: {
  readonly rejectReason?: string | null;
  readonly status: CardStatus;
  readonly executor: LeverExecutor;
  readonly progressHref: string | null;
  readonly onOpenProgress?: (event: React.MouseEvent<HTMLAnchorElement>) => void;
}) {
  const sellerHref = useSellerHref();
  if (status === "running") {
    return (
      <div className="qv-notice" role="status">
        <span>{EXECUTOR_COPY[executor].notice}</span>
        {progressHref ? (
          <a className="qv-link" href={sellerHref(progressHref)} onClick={onOpenProgress}>
            Xem tiến độ ›
          </a>
        ) : null}
      </div>
    );
  }
  if (status === "rejected" && rejectReason) {
    return (
      <ReasonDone
        lines={[
          "Juli không đề xuất lại cùng thay đổi cho sản phẩm này trong 7 ngày.",
          "Chỗ trống trong Đề xuất được dành cho sản phẩm có GMV tiềm năng kế tiếp.",
        ]}
        reason={reasonOption(REJECT_REASONS, rejectReason)}
        title="Hoàn thành · đã từ chối thẻ"
      />
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

/** `ContentCards.dc.html` footer: Duyệt · Từ chối · Xem phân tích › · (right) Xem thêm. */
function ContentActions({
  status,
  blockedReason,
  blockId,
  busy,
  expanded,
  analysisHref,
  onApprove,
  onReject,
  onToggle,
}: {
  readonly status: CardStatus;
  readonly blockedReason?: string | null;
  readonly blockId: string;
  readonly busy?: boolean;
  readonly expanded: boolean;
  readonly analysisHref?: string | null;
  readonly onApprove: () => void;
  readonly onReject: () => void;
  readonly onToggle: () => void;
}) {
  const write = useWriteControl();
  const approveWrite = useApproveControl();
  return (
    <div className="qv-card__actions qv-card__actions--content">
      {status === "pending" ? (
        <>
          <button
            aria-describedby={blockedReason ? blockId : undefined}
            className="qv-btn qv-btn--primary"
            onClick={onApprove}
            {...approveWrite(Boolean(blockedReason) || busy)}
            type="button"
          >
            Duyệt
          </button>
          <button className="qv-btn qv-btn--secondary" onClick={onReject} type="button" {...write(busy)}>
            Từ chối
          </button>
        </>
      ) : null}
      <AnalysisLink href={analysisHref} />
      <button aria-expanded={expanded} className="qv-btn qv-btn--ghost qv-card__toggle" onClick={onToggle} type="button">
        {expanded ? "Thu gọn" : "Xem thêm"}
      </button>
    </div>
  );
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
  rejectReason = null,
}: RecommendationCardProps) {
  const write = useWriteControl();
  const approveWrite = useApproveControl();
  const titleId = useId();
  const blockId = useId();
  const showWho = card.executor !== "juli" && card.content === null;
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
            <h3 className="qv-card__title" id={titleId} title={card.fullTitle ?? undefined}>
              {card.title}
            </h3>
          </div>
          <div className="qv-card__meta">{card.meta}</div>
          <QuickScanChip card={card} />
          <ConfidencePill card={card} />
        </div>
        <CardStatusChip status={status} />
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
                <KpiWindow card={card} />
              </div>
            ) : null}
          </div>
          {card.gmvPerMonth ? (
            <div className="qv-kpi__gmv">
              <div className="qv-kpi__label">GMV dự kiến</div>
              <div className="qv-kpi__money">{card.gmvPerMonth}</div>
              <QuickScanConfidence card={card} />
            </div>
          ) : null}
        </div>
      ) : null}

      <dl className="qv-facts">
        <dt>Lý do</dt>
        <dd>{card.reasonShort}</dd>
        {card.groupResult ? (
          <>
            <dt>Kết quả nhóm</dt>
            <dd data-testid="group-result">{card.groupResult}</dd>
          </>
        ) : null}
        {card.content?.source ? (
          <>
            <dt>{card.content.sourceLabel}</dt>
            <dd data-testid="content-source">{card.content.source}</dd>
          </>
        ) : null}
        <dt>{card.content ? ACTION_ROW_LABEL : "Thay đổi đề xuất"}</dt>
        <dd className="qv-field-chips">
          {card.content ? (
            <ContentAction card={card} />
          ) : (
            card.changeLabels.map((label) => (
              <span className="qv-field-chip" key={label}>
                {label}
              </span>
            ))
          )}
        </dd>
      </dl>

      {expanded ? <MoreSection card={card} /> : null}

      <ExecutorLines executor={card.executor} show={showWho} />

      <Outcome executor={card.executor} onOpenProgress={onOpenProgress} progressHref={progressHref} rejectReason={rejectReason} status={status} />

      {card.content ? (
        <ContentActions
          blockId={blockId}
          blockedReason={blockedReason}
          busy={busy}
          expanded={expanded}
          analysisHref={analysisHref}
          onApprove={onApprove}
          onReject={onReject}
          onToggle={onToggle}
          status={status}
        />
      ) : (
      <div className="qv-card__actions">
        {status === "pending" ? (
          <div className="qv-card__buttons">
            <button
              aria-describedby={blockedReason ? blockId : undefined}
              className="qv-btn qv-btn--primary"
              onClick={onApprove}
              {...approveWrite(Boolean(blockedReason) || busy)}
              type="button"
            >
              Duyệt
            </button>
            <button className="qv-btn qv-btn--secondary" onClick={onReject} type="button" {...write(busy)}>
              Từ chối
            </button>
          </div>
        ) : null}
        <button aria-expanded={expanded} className="qv-btn qv-btn--ghost qv-card__toggle" onClick={onToggle} type="button">
          {expanded ? "Thu gọn" : "Xem thêm"}
        </button>
        <AnalysisLink href={analysisHref} />
      </div>
      )}
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
  rejectReason = null,
}: RecommendationCardProps) {
  const write = useWriteControl();
  const approveWrite = useApproveControl();
  const titleId = useId();
  const blockId = useId();
  const showWho = card.executor !== "juli" && card.content === null;
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
          <h3 className="qv-card__title" id={titleId} title={card.fullTitle ?? undefined}>
            {card.title}
          </h3>
          <div className="qv-card__meta">{card.meta}</div>
          <QuickScanChip card={card} />
          <ConfidencePill card={card} />
        </div>
        <CardStatusChip status={status} />
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
              <KpiWindow card={card} />
            </div>
          ) : null}
          {card.gmvPerMonth ? (
            <div className="qv-kpi__row">
              <span className="qv-kpi__label">GMV dự kiến</span>
              <span className="qv-kpi__money">
                {card.gmvPerMonth} <span className="qv-estimate">ước tính</span>
              </span>
              <QuickScanConfidence card={card} />
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="qv-mfact">
        <div className="qv-mfact__label">Lý do</div>
        <div>{card.reasonMobile}</div>
      </div>
      {card.groupResult ? (
        <div className="qv-mfact" data-testid="group-result-mobile">
          <div className="qv-mfact__label">Kết quả nhóm</div>
          <div>{card.groupResult}</div>
        </div>
      ) : null}

      {card.content?.source ? (
        <div className="qv-mfact" data-testid="content-source-mobile">
          <div className="qv-mfact__label">{card.content.sourceLabel}</div>
          <div>{card.content.source}</div>
        </div>
      ) : null}

      <div className="qv-mfact qv-mfact--changes">
        <div className="qv-mfact__label">{card.content ? ACTION_ROW_LABEL : "Thay đổi đề xuất"}</div>
        {card.content ? (
          <span className="qv-field-chips">
            <ContentAction card={card} />
          </span>
        ) : card.beforeAfter.length > 0
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

      <Outcome executor={card.executor} onOpenProgress={onOpenProgress} progressHref={progressHref} rejectReason={rejectReason} status={status} />

      {status === "pending" ? (
        <div className="qv-card__grid-buttons">
          <button
            aria-describedby={blockedReason ? blockId : undefined}
            className="qv-btn qv-btn--primary"
            onClick={onApprove}
            {...approveWrite(Boolean(blockedReason) || busy)}
            type="button"
          >
            Duyệt
          </button>
          <button className="qv-btn qv-btn--secondary" onClick={onReject} type="button" {...write(busy)}>
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
