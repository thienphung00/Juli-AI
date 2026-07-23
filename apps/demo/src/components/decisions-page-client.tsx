"use client";

import { useSearchParams } from "next/navigation";

import { RecommendationsView } from "./recommendations-view";

export function DecisionsPageClient() {
  const searchParams = useSearchParams();
  const load = searchParams.get("load");
  const initialLoadState = load === "error" ? "error" : "ready";

  return <RecommendationsView initialLoadState={initialLoadState} />;
}
