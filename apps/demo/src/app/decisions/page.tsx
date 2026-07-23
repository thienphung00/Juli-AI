import { Suspense } from "react";

import { DecisionsPageClient } from "../../components/decisions-page-client";

export default function DecisionsPage() {
  return (
    <Suspense fallback={<p className="demo-kicker">Đang tải…</p>}>
      <DecisionsPageClient />
    </Suspense>
  );
}
