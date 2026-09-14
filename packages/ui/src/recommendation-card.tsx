"use client";

import { forwardRef, useId, useState } from "react";

import { Badge } from "./badge";
import { Button } from "./button";

/**
 * One line of the card's preview block (issue #1916, v3 draft): the field
 * being changed and the change in miniature, so approving is an informed
 * click rather than a navigation. `kind: "keep"` rows state explicitly
 * what Juli will NOT touch — rendered muted, never omitted.
 */
export interface RecommendationCardPreviewRow {
  label: string;
  change: string;
  kind: "change" | "keep";
}

export interface RecommendationCardProps {
  approveDisabledReason?: string;
  /**
   * Right-hand header label naming the workflow category (issue #1916,
   * v3 draft: subject on the left, workflow category on the right).
   */
  categoryLabel?: string;
  detailHref?: string;
  eligibility: string;
  evidence: string;
  isHighlighted?: boolean;
  isPriority?: boolean;
  knownLimits: string;
  onApprove?: () => void;
  onReject: () => void;
  /**
   * When provided, the card renders "Xem thêm" instead of its legacy
   * in-card "Mở rộng" accordion: the caller opens the detail beside the
   * list (issue #1916 — never an overlay or a modal).
   */
  onSeeMore?: () => void;
  previewRows?: readonly RecommendationCardPreviewRow[];
  reasoning: string;
  rejectLabel?: string;
  risks: string;
  /**
   * True while this card's beside-the-list detail is open: "Xem thêm"
   * hides itself; Phê duyệt and Từ chối stay on the card (issue #1916).
   */
  seeMoreOpen?: boolean;
  sellerReason?: string;
  signal: string;
  title: string;
  workflowKey: string;
}

export const RecommendationCard = forwardRef<
  HTMLElement,
  RecommendationCardProps
>(function RecommendationCard(
  {
    approveDisabledReason,
    categoryLabel,
    detailHref,
    eligibility,
    evidence,
    isHighlighted = false,
    isPriority = false,
    knownLimits,
    onApprove,
    onReject,
    onSeeMore,
    previewRows,
    reasoning,
    rejectLabel = "Từ chối",
    risks,
    seeMoreOpen = false,
    sellerReason,
    signal,
    title,
    workflowKey,
  },
  ref,
) {
  const [expanded, setExpanded] = useState(false);
  const reactId = useId();
  const titleId = `${reactId}-title`;
  const panelId = `${reactId}-panel`;
  const approveNoteId = `${reactId}-approve-note`;
  const approveEnabled = Boolean(onApprove);
  const cardReason = sellerReason ?? reasoning;
  const hasPreview = Boolean(previewRows?.length);

  const classNames = [
    "juli-recommendation-card",
    isPriority ? "juli-recommendation-card--priority" : null,
    isHighlighted ? "juli-recommendation-card--highlighted" : null,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <article
      ref={ref}
      aria-labelledby={titleId}
      className={classNames}
      data-workflow-key={workflowKey}
      tabIndex={-1}
    >
      {isHighlighted ? (
        <p className="juli-recommendation-card__highlight-flag">
          <span aria-hidden="true">🔍</span> Đang xem
        </p>
      ) : null}

      <header className="juli-recommendation-card__header">
        <div className="juli-recommendation-card__heading">
          {isPriority ? <Badge variant="priority">★ Ưu tiên</Badge> : null}
          <h3 className="juli-recommendation-card__title" id={titleId}>
            {detailHref ? (
              <a className="juli-recommendation-card__title-link" href={detailHref}>
                {title}
              </a>
            ) : (
              title
            )}
          </h3>
        </div>
        {categoryLabel ? (
          <p className="juli-recommendation-card__category">{categoryLabel}</p>
        ) : null}
      </header>

      {hasPreview ? (
        <dl
          className="juli-recommendation-card__preview"
          data-testid="recommendation-preview"
        >
          {previewRows!.map((row) => (
            <div
              className="juli-recommendation-card__preview-row"
              data-kind={row.kind}
              key={row.label}
            >
              <dt className="juli-recommendation-card__preview-label">
                {row.label}
              </dt>
              <dd className="juli-recommendation-card__preview-change">
                {row.change}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="juli-recommendation-card__signal">{signal}</p>
      )}
      <p className="juli-recommendation-card__reasoning">{cardReason}</p>

      <div className="juli-recommendation-card__actions">
        <Button
          aria-describedby={approveEnabled ? undefined : approveNoteId}
          disabled={!approveEnabled}
          onClick={onApprove}
          variant="primary"
        >
          Phê duyệt
        </Button>
        <Button onClick={onReject} variant="secondary">
          {rejectLabel}
        </Button>
        {onSeeMore ? (
          seeMoreOpen ? null : (
            <Button onClick={onSeeMore} variant="ghost">
              Xem thêm
            </Button>
          )
        ) : (
          <Button
            aria-controls={panelId}
            aria-expanded={expanded}
            onClick={() => setExpanded((current) => !current)}
            variant="ghost"
          >
            {expanded ? "Thu gọn" : "Mở rộng"}
          </Button>
        )}
      </div>

      {!approveEnabled && approveDisabledReason ? (
        <p className="juli-recommendation-card__approve-note" id={approveNoteId}>
          {approveDisabledReason}
        </p>
      ) : null}

      {!onSeeMore && expanded ? (
        <div className="juli-recommendation-card__panel" id={panelId}>
          <dl>
            <div>
              <dt>Lý do đề xuất</dt>
              <dd>{reasoning}</dd>
            </div>
            <div>
              <dt>Bằng chứng</dt>
              <dd>{evidence}</dd>
            </div>
            <div>
              <dt>Điều kiện áp dụng</dt>
              <dd>{eligibility}</dd>
            </div>
            <div>
              <dt>Giới hạn hiện tại</dt>
              <dd>{knownLimits}</dd>
            </div>
            <div>
              <dt>Rủi ro</dt>
              <dd>{risks}</dd>
            </div>
          </dl>
        </div>
      ) : null}
    </article>
  );
});
