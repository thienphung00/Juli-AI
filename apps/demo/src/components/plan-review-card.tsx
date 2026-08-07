"use client";

import {
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  CardTitle,
  ConfirmDialog,
} from "@juli/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";

import {
  PLAN_REASONING_DISCLOSURE_QUESTION,
  type PlanReviewContent,
} from "../lib/plan-reviews";
import {
  SELLER_APPROVE_GATE,
  sanitizeSellerReviewText,
} from "../lib/review-seller-copy";
import { buildDecisionsHighlightHref } from "../lib/recommendations";
import { useDemoState } from "./demo-state";
import { PlanImpactBlock } from "./impact-block";

interface PlanReviewCardProps {
  plan: PlanReviewContent;
}

/**
 * Situation → Decision → Details plan review card (ADR-055 items 1, 8, 13).
 *
 * - Situation is a header, not a section: its known fields collapse into one
 *   summary row with a count and a question-phrased disclosure. Expansion
 *   adds detail below the row and keeps the summary line visible.
 * - The impact block sits directly under the header, above the proposal: the
 *   tied Main KPI's real value, trend and directional goal (ADR-055 items
 *   15–17). It is the card's centre of gravity, and it has one state.
 * - Decision rests folded on the proposed outcome — one sentence.
 * - Details renders as nothing when the plan carries no branch-gated detail.
 * - The Decision section carries the reasoning disclosure (ADR-055 items 3,
 *   11): a question-labelled expansion revealing the workflow's pre-authored
 *   reasoning — always present, never a conversation. Opening adds the
 *   reasoning below the proposal; closing returns the card to resting height.
 * - A seller who agrees approves in one tap, without expanding anything.
 */
export function PlanReviewCard({ plan }: PlanReviewCardProps) {
  const router = useRouter();
  const { startExecution } = useDemoState();
  const [situationOpen, setSituationOpen] = useState(false);
  const [reasoningOpen, setReasoningOpen] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [approveGateOpen, setApproveGateOpen] = useState(false);
  const titleId = useId();
  const situationDetailId = useId();
  const reasoningDetailId = useId();
  const decisionOptionsId = useId();
  const recommendedOptions = plan.decision.recommendedOptions;

  const handleApproveConfirm = () => {
    const executionId = startExecution(plan.workflowKey);
    router.push(`/decisions/in-progress/${executionId}`);
  };

  return (
    <section className="demo-plan">
      <p className="demo-review__back">
        <Link href={buildDecisionsHighlightHref(plan.workflowKey)}>
          Về danh sách đề xuất
        </Link>
      </p>

      <Card aria-labelledby={titleId} data-testid="plan-review-card">
        <CardHeader className="demo-plan__header">
          <CardTitle id={titleId}>{plan.title}</CardTitle>
          <button
            aria-controls={situationDetailId}
            aria-expanded={situationOpen}
            className="demo-plan__summary-row"
            onClick={() => setSituationOpen((open) => !open)}
            type="button"
          >
            <span className="demo-plan__summary-line">
              {plan.situation.summary}
            </span>
            <span aria-hidden="true" className="demo-plan__summary-chevron">
              ›
            </span>
            <span className="demo-plan__summary-question">
              {plan.situation.disclosureQuestion}
            </span>
          </button>
          {situationOpen ? (
            <div className="demo-plan__situation-detail" id={situationDetailId}>
              {plan.situation.detailLines.map((line) => (
                <p key={line.slice(0, 48)}>{line}</p>
              ))}
              <p>
                <Link href={plan.situation.analyticsMetricHref}>
                  Xem trên Phân tích
                </Link>
              </p>
            </div>
          ) : null}
        </CardHeader>
        <PlanImpactBlock impact={plan.impact} />
        <CardBody className="demo-plan__decision" data-testid="plan-decision">
          <p>{plan.decision.proposal}</p>
          <button
            aria-controls={reasoningDetailId}
            aria-expanded={reasoningOpen}
            className="demo-plan__summary-row"
            onClick={() => setReasoningOpen((open) => !open)}
            type="button"
          >
            <span className="demo-plan__summary-question">
              {PLAN_REASONING_DISCLOSURE_QUESTION}
            </span>
            <span aria-hidden="true" className="demo-plan__summary-chevron">
              ›
            </span>
          </button>
          {reasoningOpen ? (
            <div
              className="demo-plan__reasoning-detail"
              data-testid="plan-reasoning"
              id={reasoningDetailId}
            >
              <p>{sanitizeSellerReviewText(plan.decision.reasoning)}</p>
            </div>
          ) : null}
          {recommendedOptions ? (
            <>
              <button
                aria-controls={decisionOptionsId}
                aria-expanded={optionsOpen}
                className="demo-plan__summary-row"
                onClick={() => setOptionsOpen((open) => !open)}
                type="button"
              >
                <span className="demo-plan__summary-question">
                  {recommendedOptions.disclosureQuestion}
                </span>
                <span aria-hidden="true" className="demo-plan__summary-chevron">
                  ›
                </span>
              </button>
              {optionsOpen ? (
                <div
                  className="demo-plan__decision-options"
                  data-testid="plan-decision-options"
                  id={decisionOptionsId}
                >
                  {recommendedOptions.groups.map((group) => (
                    <div key={group.label}>
                      <p className="demo-plan__option-group-label">
                        {group.label}
                      </p>
                      <ul className="demo-plan__option-list">
                        {group.options.map((option) => (
                          <li key={option.value.slice(0, 48)}>
                            {option.value}
                            {option.proposed ? (
                              <span className="demo-plan__option-proposed">
                                Gợi ý bởi Juli
                              </span>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              ) : null}
            </>
          ) : null}
        </CardBody>
        {plan.details ? (
          <CardBody className="demo-plan__details" data-testid="plan-details">
            {plan.details.detailLines.map((line) => (
              <p key={line.slice(0, 48)}>{line}</p>
            ))}
          </CardBody>
        ) : null}
        <CardFooter className="demo-plan__actions">
          <Button onClick={() => setApproveGateOpen(true)} type="button">
            Phê duyệt
          </Button>
        </CardFooter>
      </Card>

      <ConfirmDialog
        cancelLabel={SELLER_APPROVE_GATE.cancelLabel}
        confirmLabel={SELLER_APPROVE_GATE.confirmLabel}
        description={SELLER_APPROVE_GATE.description}
        onConfirm={handleApproveConfirm}
        onOpenChange={setApproveGateOpen}
        open={approveGateOpen}
        title={SELLER_APPROVE_GATE.title}
      />
    </section>
  );
}
