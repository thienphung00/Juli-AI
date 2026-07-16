"use client";

import { forwardRef, useId, useState } from "react";

import { Badge } from "./badge";
import { Button } from "./button";

export type RecommendationConfidenceLevel = "high" | "medium" | "low";

export interface RecommendationCardProps {
  approveDisabledReason?: string;
  capabilityLabel: string;
  confidenceLabel: string;
  confidenceLevel: RecommendationConfidenceLevel;
  eligibility: string;
  evidence: string;
  expectedImpactLabel: string;
  isHighlighted?: boolean;
  isPriority?: boolean;
  knownLimits: string;
  onApprove?: () => void;
  onReject: () => void;
  reasoning: string;
  rejectLabel?: string;
  risks: string;
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
    capabilityLabel,
    confidenceLabel,
    confidenceLevel,
    eligibility,
    evidence,
    expectedImpactLabel,
    isHighlighted = false,
    isPriority = false,
    knownLimits,
    onApprove,
    onReject,
    reasoning,
    rejectLabel = "Từ chối",
    risks,
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
            {title}
          </h3>
        </div>
        <Badge variant={`confidence-${confidenceLevel}`}>
          {confidenceLabel}
        </Badge>
      </header>

      <p className="juli-recommendation-card__signal">{signal}</p>
      <p className="juli-recommendation-card__reasoning">{reasoning}</p>

      <div className="juli-recommendation-card__impact-line">
        <span className="juli-recommendation-card__impact">
          Tác động dự kiến: {expectedImpactLabel}
        </span>
        <Badge variant="capability">{capabilityLabel}</Badge>
      </div>

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
        <Button
          aria-controls={panelId}
          aria-expanded={expanded}
          onClick={() => setExpanded((current) => !current)}
          variant="ghost"
        >
          {expanded ? "Thu gọn" : "Mở rộng"}
        </Button>
      </div>

      {!approveEnabled && approveDisabledReason ? (
        <p className="juli-recommendation-card__approve-note" id={approveNoteId}>
          {approveDisabledReason}
        </p>
      ) : null}

      {expanded ? (
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
