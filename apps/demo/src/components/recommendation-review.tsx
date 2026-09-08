"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { getWorkflowPlanReview } from "../lib/plan-reviews";
import { OPTIMIZE_PRODUCT_WORKFLOW_KEY } from "../lib/reviews";
import { REPLAY_SCENARIO_RUN_ID } from "../lib/run-surface/replay-scenario";
import { PlanReviewCard } from "./plan-review-card";

interface RecommendationReviewProps {
  workflowKey: string;
}

/**
 * Recoverable not-found state for keys without a plan review — the
 * scaffold-only FBT intake keys (deliberately non-executable per ADR-055's
 * Consequences) and malformed keys from a bad URL. Copy is seller-facing
 * recovery copy (ADR-028); moved verbatim out of the retired five-stage
 * review by #910.
 */
function RecommendationReviewNotFound() {
  return (
    <section
      aria-label="Không tìm thấy quy trình"
      className="demo-placeholder"
      role="status"
    >
      <p className="demo-kicker">Không tìm thấy</p>
      <h1>Quy trình không được hỗ trợ</h1>
      <p>
        Đề xuất hoặc quy trình này chưa có trong Demo. Hãy quay lại Quyết định
        để chọn đề xuất khác.
      </p>
      <Link className="demo-placeholder__recovery" href="/decisions">
        Về Quyết định
      </Link>
    </section>
  );
}

export function RecommendationReview({ workflowKey }: RecommendationReviewProps) {
  const router = useRouter();

  // Route by workflow key (ADR-055 item 8): all eleven reviewable workflows
  // carry a plan review and render the Situation → Decision → Details spine.
  // The superseded five-stage review was removed by #910; a key without a
  // plan renders the recoverable not-found state.
  const plan = getWorkflowPlanReview(workflowKey);

  if (plan) {
    // Optimize Product is the one workflow whose approval does not create a
    // mock `ExecutionRecord` (#1320 part 2, ADR-094): it reaches the staged
    // run view directly, via the well-known replay run id
    // (`lib/run-surface/replay-scenario.ts`). The other ten workflows pass
    // no override and keep `PlanReviewCard`'s original mock-execution
    // default, unchanged. This is the one place that knows which workflow
    // is which — `PlanReviewCard` itself stays workflow-agnostic.
    const onApproveConfirm =
      workflowKey === OPTIMIZE_PRODUCT_WORKFLOW_KEY
        ? () => router.push(`/decisions/in-progress/${REPLAY_SCENARIO_RUN_ID}`)
        : undefined;

    return <PlanReviewCard onApproveConfirm={onApproveConfirm} plan={plan} />;
  }

  return <RecommendationReviewNotFound />;
}
