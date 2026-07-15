import { Suspense } from "react";

import { RecommendationsView } from "../../components/recommendations-view";

export default function DecisionsPage() {
  return (
    <Suspense fallback={<p className="demo-kicker">Đang tải…</p>}>
      <RecommendationsView />
    </Suspense>
  );
}
