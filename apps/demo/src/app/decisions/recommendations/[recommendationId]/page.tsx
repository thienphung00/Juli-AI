import { Suspense } from "react";

import { RecommendationReview } from "../../../../components/recommendation-review";

interface RecommendationReviewPageProps {
  params: Promise<{ recommendationId: string }>;
}

export default async function RecommendationReviewPage({
  params,
}: RecommendationReviewPageProps) {
  const { recommendationId } = await params;

  return (
    <Suspense fallback={<p className="demo-kicker">Đang tải…</p>}>
      <RecommendationReview workflowKey={recommendationId} />
    </Suspense>
  );
}
